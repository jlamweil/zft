"""Negotiation crash resumption: replay integrity, resumable-run scan, driver.

The kill-9 proof itself is e2e (tests/e2e/test_negotiate_resumption.py);
these unit pins cover the pieces it composes:
- NegotiationSM.replay rebuilds state, details, and retry budget from ledger
  history — and fails typed on a forged or torn chain (resumption never
  trusts a log it did not earn);
- find_resumable picks the latest unfinished negotiate run and skips
  terminal, foreign-stage, and unidentifiable runs;
- RunLedger.resume reopens a run append-only and records torn-tail recovery;
- advance_to_validated continues from every mid-state the canned protocol
  can be killed in.
"""
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from zft.debug.ledger import RunLedger
from zft.negotiate.resume import (
    CANNED_COUNTER_TERMS,
    advance_to_validated,
    find_resumable,
    resume,
)
from zft.negotiate.sm import DEFAULT_RETRY_BUDGET, IllegalTransition, NegotiationSM
from zft.negotiate.terms import CounterTerms


def _history(sm: NegotiationSM) -> list[dict]:
    """Ledger-shaped events for a machine's history (the CLI's projection)."""
    return [{"event": h["action"], **h} for h in sm.history]


def _billed_rejection_history() -> list[dict]:
    """A history that spends the retry budget: one full reject→reopen loop."""
    sm = NegotiationSM.start(retry_budget=1)
    sm.validate()
    sm.implement()
    sm.reject_gate(["GATE-INV-01"], fault="contract")
    sm.reopen()
    sm.validate()
    sm.implement()
    sm.reject_gate(["GATE-INV-01"], fault="implementation")
    return _history(sm)


# --- NegotiationSM.replay ----------------------------------------------------

def test_replay_rebuilds_state_details_and_budget():
    history = _billed_rejection_history()
    sm = NegotiationSM.replay(history, retry_budget=1)
    assert sm.state == "REJECTED"
    assert sm.retries == 1, "reopen re-spends the budget on replay"
    assert sm.history == [{k: v for k, v in e.items() if k != "event"}
                          for e in history], "replayed history is the recorded chain"
    assert sm.history[-1]["clause_ids"] == ["GATE-INV-01"]
    assert sm.history[-1]["fault"] == "implementation"


def test_replay_preserves_counter_terms():
    sm = NegotiationSM.start()
    sm.counter("producer wants examples=50")
    sm.accept_counter()
    replayed = NegotiationSM.replay(_history(sm))
    assert replayed.state == "REVISED"
    assert replayed.history[0]["terms"] == "producer wants examples=50"


def test_replay_empty_is_fresh():
    sm = NegotiationSM.replay([])
    assert sm.state == "DRAFT"
    assert sm.retries == 0
    assert sm.retry_budget == DEFAULT_RETRY_BUDGET


def test_replay_rejects_forged_to():
    history = _billed_rejection_history()
    history[0]["to"] = "IMPLEMENTED"  # validate never lands there
    with pytest.raises(IllegalTransition, match="history mismatch"):
        NegotiationSM.replay(history, retry_budget=1)


def test_replay_rejects_forged_from():
    history = _billed_rejection_history()
    history[2]["from"] = "DRAFT"  # reject_gate never starts there
    with pytest.raises(
        IllegalTransition,
        match=(r"^history mismatch at reject_gate: recorded DRAFT->REJECTED, "
               r"replayed IMPLEMENTED->REJECTED$"),
    ):
        NegotiationSM.replay(history, retry_budget=1)


def test_replay_event_entry_promotes_when_event_is_an_action():
    """A raw event entry whose event name is itself an action name replays as
    that step; every other raw event (cfp, validated, resumed) stays a
    non-step — the ACTIONS membership test is the whole discriminator."""
    sm = NegotiationSM.replay([{"event": "counter", "from": "DRAFT",
                                "to": "COUNTERED", "terms": "examples=50"}])
    assert sm.state == "COUNTERED"
    assert sm.history == [{"action": "counter", "from": "DRAFT",
                           "to": "COUNTERED", "terms": "examples=50"}]


def test_replay_rejects_unknown_kwarg_message_is_exact():
    """counter takes only `terms`; an unknown kwarg on an action with real
    parameters is forgery residue — typed refusal naming it, never a
    TypeError mid-replay."""
    with pytest.raises(
        IllegalTransition,
        match=r"^torn history at counter: missing \[\], unknown \['bogus'\]$",
    ):
        NegotiationSM.replay([{"action": "counter", "from": "DRAFT",
                               "to": "COUNTERED", "terms": "x", "bogus": 1}])


def test_replay_rejects_unknown_action():
    with pytest.raises(IllegalTransition, match="unknown action"):
        NegotiationSM.replay([{"action": "mint_money", "from": "DRAFT",
                               "to": "VALIDATED"}])


def test_replay_rejects_torn_counter_missing_terms():
    """A counter event whose terms were lost (corruption, truncation) must fail
    typed, not TypeError mid-replay — torn history is never replayed blind."""
    with pytest.raises(IllegalTransition, match="torn history at counter"):
        NegotiationSM.replay([{"event": "counter", "action": "counter",
                               "from": "DRAFT", "to": "COUNTERED"}])


def test_replay_rejects_forged_extra_keys():
    """Keys no action accepts are forgery residue — typed refusal, not crash."""
    with pytest.raises(IllegalTransition, match="torn history at validate"):
        NegotiationSM.replay([{"event": "validate", "action": "validate",
                               "from": "REVISED", "to": "VALIDATED",
                               "attacker_key": "x"}])


def test_resume_of_torn_ledger_fails_typed(tmp_path):
    """End to end through the ledger: a durable prefix with a stripped counter
    is a typed refusal on resume, never a raw traceback in the CLI."""
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "negotiate"},
                          repo=tmp_path)
    led.append({"event": "cfp", "contract": "x", "clauses": 1})
    led.append({"event": "counter", "action": "counter",
                "from": "DRAFT", "to": "COUNTERED"})
    led.close()
    with pytest.raises(IllegalTransition, match="torn history"):
        resume(tmp_path / "runs")


def test_replay_ignores_non_action_events():
    """cfp/validated/resumed ride the same ledger but are not SM actions —
    the CLI passes raw events; replay filters instead of choking."""
    sm = NegotiationSM.replay([
        {"event": "cfp", "contract": "x", "clauses": 26},
        {"event": "counter", "action": "counter", "from": "DRAFT",
         "to": "COUNTERED", "terms": "t"},
        {"event": "validated", "version": 2},
    ])
    assert sm.state == "COUNTERED"


# --- find_resumable ----------------------------------------------------------

def _negotiate_run(runs_root, events, stage="negotiate", mtime=None):
    led = RunLedger.start(runs_root, manifest={"stage": stage})
    for e in events:
        led.append(e)
    led.close()
    if mtime is not None:
        os.utime(led.dir, (mtime, mtime))
    return led.run_id


def test_find_resumable_empty_root(tmp_path):
    assert find_resumable(tmp_path) is None
    assert find_resumable(tmp_path / "nope") is None


def test_find_resumable_skips_terminal_and_foreign(tmp_path):
    _negotiate_run(tmp_path, [{"event": "cfp"},
                              {"event": "counter", "action": "counter",
                               "from": "DRAFT", "to": "COUNTERED", "terms": "t"},
                              {"event": "validated", "version": 2}])
    _negotiate_run(tmp_path, [{"event": "cfp"}], stage="check")
    assert find_resumable(tmp_path) is None


def test_find_resumable_picks_latest_unfinished(tmp_path):
    old = _negotiate_run(tmp_path, [{"event": "cfp"}], mtime=1_000)
    new = _negotiate_run(tmp_path, [{"event": "cfp"},
                                    {"event": "counter", "action": "counter",
                                     "from": "DRAFT", "to": "COUNTERED", "terms": "t"}],
                         mtime=2_000)
    _negotiate_run(tmp_path, [{"event": "cfp"},
                              {"event": "validated", "version": 2}], mtime=3_000)
    assert find_resumable(tmp_path) == new
    assert find_resumable(tmp_path) != old


def test_find_resumable_skips_unidentifiable_manifest(tmp_path):
    run = tmp_path / "deadbeef"
    run.mkdir()
    (run / "manifest.json").write_text("{torn")
    assert find_resumable(tmp_path) is None


def test_find_resumable_skips_eventsless_run(tmp_path):
    run = tmp_path / "deadbeef"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"stage": "negotiate"}))
    assert find_resumable(tmp_path) is None


# --- resume ------------------------------------------------------------------

def test_resume_replays_and_reopens_ledger(tmp_path):
    _negotiate_run(tmp_path, [{"event": "cfp"},
                              {"event": "counter", "action": "counter",
                               "from": "DRAFT", "to": "COUNTERED",
                               "terms": "examples=50"}])
    out = resume(tmp_path)
    assert out is not None
    led, sm = out
    assert sm.state == "COUNTERED"
    assert sm.history[0]["terms"] == "examples=50"
    led.append({"event": "accept_counter", "action": "accept_counter",
                "from": "COUNTERED", "to": "REVISED"})
    led.close()
    record = RunLedger.load(tmp_path, led.run_id)
    assert [e["event"] for e in record.events] == \
        ["cfp", "counter", "resumed", "accept_counter"]


def test_resume_none_when_all_finished(tmp_path):
    _negotiate_run(tmp_path, [{"event": "cfp"},
                              {"event": "validated", "version": 2}])
    assert resume(tmp_path) is None


def test_resume_truncates_torn_tail_and_records_it(tmp_path):
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    led.append({"event": "cfp"})
    with open(led.dir / "events.jsonl", "ab") as fh:
        fh.write(b'{"event": "counter", "act')  # torn mid-write, no newline
    led.close()

    out = resume(tmp_path)
    assert out is not None
    resumed_led, sm = out
    assert sm.state == "DRAFT", "torn event never happened — replay skips it"
    assert resumed_led._torn_tail_bytes > 0
    resumed_led.append({"event": "counter", "action": "counter",
                        "from": "DRAFT", "to": "COUNTERED", "terms": "t"})
    resumed_led.close()
    record = RunLedger.load(tmp_path, resumed_led.run_id)
    events = [e["event"] for e in record.events]
    assert events[0] == "cfp"
    assert "resumed_torn_tail" in events, "recovery is ledgered, not silent"
    assert events[-1] == "counter", "post-recovery events must be readable"


# --- advance_to_validated ----------------------------------------------------

@pytest.mark.parametrize("prefix", [
    [],
    # a canned run's counter always carries the canned sheet — an external
    # term sheet here would make the canned continuation a typed refusal
    [{"event": "counter", "action": "counter", "from": "DRAFT",
      "to": "COUNTERED", "terms": CANNED_COUNTER_TERMS}],
    [{"event": "counter", "action": "counter", "from": "DRAFT",
      "to": "COUNTERED", "terms": CANNED_COUNTER_TERMS},
     {"event": "accept_counter", "action": "accept_counter",
      "from": "COUNTERED", "to": "REVISED"}],
], ids=["killed-in-DRAFT", "killed-in-COUNTERED", "killed-in-REVISED"])
def test_advance_from_every_killable_state(tmp_path, prefix):
    sm = NegotiationSM.replay(prefix)
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    advance_to_validated(sm, led)
    led.close()
    assert sm.state == "VALIDATED"
    record = RunLedger.load(tmp_path, led.run_id)
    assert record.events[-1]["event"] == "validate"


def test_advance_refuses_states_without_canned_continuation(tmp_path):
    sm = NegotiationSM.replay(
        [{"event": "refuse", "action": "refuse", "from": "DRAFT",
          "to": "REFUSED", "reason": "missing capability"}])
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(IllegalTransition, match="no canned continuation"):
        advance_to_validated(sm, led)
    led.close()


# --- kill-shard pins: scan order, manifest budget, recovery payload ----------

def test_find_resumable_scans_past_every_skip_class(tmp_path, monkeypatch):
    """Every skip class sits AHEAD of the good run in a controlled order —
    a skip that turned into a scan-stopping break would resume nothing."""
    dead_file = tmp_path / "zzz-not-a-run"
    dead_file.write_text("not a run dir at all")
    torn = tmp_path / "run-torn"
    torn.mkdir()
    (torn / "manifest.json").write_text("{torn")
    foreign = RunLedger.start(tmp_path, manifest={"stage": "check"})
    foreign.append({"event": "cfp"})
    foreign.close()
    hollow = tmp_path / "run-hollow"  # manifest without an events file
    hollow.mkdir()
    (hollow / "manifest.json").write_text(json.dumps({"stage": "negotiate"}))
    good = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    good.append({"event": "cfp"})
    good.close()
    order = [dead_file, torn, foreign.dir, hollow, good.dir]
    monkeypatch.setattr(type(good.dir), "iterdir", lambda self: iter(order))
    assert find_resumable(tmp_path) == good.run_id


def _cfp_run(tmp_path, manifest=None):
    led = RunLedger.start(tmp_path, manifest=manifest or {"stage": "negotiate"})
    led.append({"event": "cfp"})
    led.close()
    return led.run_id


def test_resume_honors_recorded_retry_budget(tmp_path):
    """A run's recorded budget survives the crash: the manifest's retry_budget
    replays into the machine — not the module default."""
    _cfp_run(tmp_path, manifest={"stage": "negotiate", "retry_budget": 1})
    led, sm = resume(tmp_path)
    assert sm.retry_budget == 1
    assert sm.state == "DRAFT"
    led.close()


def test_resume_defaults_budget_when_manifest_carries_none(tmp_path):
    """No retry_budget key in the manifest → the module default — the
    fallback is load-bearing, and a manifest that fails to parse or read
    degrades to an empty one, never None."""
    _cfp_run(tmp_path)  # manifest has no retry_budget key
    led, sm = resume(tmp_path)
    assert sm.retry_budget == DEFAULT_RETRY_BUDGET
    led.close()


def test_resume_unreadable_manifest_degrades_to_empty(tmp_path, monkeypatch):
    """A manifest readable during the scan but gone before the replay (a race,
    not a forgery) degrades to an empty manifest — the machine still resumes
    on the default budget, never a crash and never a None manifest."""
    _cfp_run(tmp_path)
    real_read = Path.read_text
    reads = {"n": 0}

    def flaky_read(self, *args, **kwargs):
        reads["n"] += 1
        if self.name == "manifest.json" and reads["n"] >= 2:
            raise OSError("manifest vanished mid-resume")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read)
    led, sm = resume(tmp_path)
    assert sm.retry_budget == DEFAULT_RETRY_BUDGET
    led.close()


def test_resume_ledgers_recovery_payload_exact(tmp_path):
    """resumed_torn_tail carries the truncated byte count; the resumed event
    names what was replayed and the state it landed in — the recovery trail
    is ledger contract, not free-form."""
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    led.append({"event": "cfp", "contract": "x"})
    torn = b'{"event": "counter", "act'
    with open(led.dir / "events.jsonl", "ab") as fh:
        fh.write(torn)  # torn mid-write, no newline
    led.close()

    resumed_led, sm = resume(tmp_path)
    resumed_led.close()
    record = RunLedger.load(tmp_path, resumed_led.run_id)
    torn_ev = next(e for e in record.events if e["event"] == "resumed_torn_tail")
    assert torn_ev["bytes"] == len(torn)
    resumed_ev = next(e for e in record.events if e["event"] == "resumed")
    assert resumed_ev["replayed"] == 0 and resumed_ev["state"] == "DRAFT"


# --- kill-shard pins: typed-refusal wording is exact --------------------------

_EXTERNAL_TERMS_MSG = ("run countered with external terms; finishing it canned "
                       "would invent the counter-party's decision — resume "
                       "with the --counter-terms document")


def _countered_sm(terms=CANNED_COUNTER_TERMS):
    return NegotiationSM.replay(
        [{"event": "counter", "action": "counter", "from": "DRAFT",
          "to": "COUNTERED", "terms": terms}])


def test_advance_external_terms_refusal_message_is_exact(tmp_path):
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(IllegalTransition) as excinfo:
        advance_to_validated(_countered_sm("producer wants examples=50"), led)
    assert str(excinfo.value) == _EXTERNAL_TERMS_MSG
    led.close()


def test_advance_mismatched_counter_terms_message_is_exact(tmp_path):
    recorded = "producer wants examples=50"
    sheet = CounterTerms(terms="a different bargain", decision="accept", reason=None)
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(IllegalTransition) as excinfo:
        advance_to_validated(_countered_sm(recorded), led, terms=sheet)
    assert str(excinfo.value) == ("counter-terms document does not match the "
                                  f"recorded counter-proposal {recorded!r}")
    led.close()


def test_advance_refused_entry_message_is_exact(tmp_path):
    sm = NegotiationSM.replay(
        [{"event": "refuse", "action": "refuse", "from": "DRAFT",
          "to": "REFUSED", "reason": "missing capability"}])
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(IllegalTransition) as excinfo:
        advance_to_validated(sm, led)
    assert str(excinfo.value) == "no canned continuation from REFUSED"
    led.close()


def test_advance_implemented_entry_message_is_exact(tmp_path):
    """A run that already validated and implemented has no continuation the
    driver may invent — the else-branch refusal, named with the state."""
    sm = NegotiationSM.start()
    sm.counter(CANNED_COUNTER_TERMS)
    sm.accept_counter()
    sm.validate()
    sm.implement()
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(IllegalTransition) as excinfo:
        advance_to_validated(NegotiationSM.replay(_history(sm)), led)
    assert str(excinfo.value) == "no canned continuation from IMPLEMENTED"
    led.close()


# --- kill-shard pins: the demo seam SIGKILLs only on the named action --------

_KILL_CHILD = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from zft.debug.ledger import RunLedger
from zft.negotiate.resume import advance_to_validated
from zft.negotiate.sm import NegotiationSM
from zft.negotiate.terms import CounterTerms
spec = json.loads(sys.argv[1])
sm = NegotiationSM.replay(spec["prefix"])
led = RunLedger.start(Path(sys.argv[2]), manifest={"stage": "negotiate"})
terms = None if spec.get("sheet") is None else CounterTerms(**spec["sheet"])
advance_to_validated(sm, led, kill_after=spec["kill_after"], terms=terms)
led.close()
print("survived:" + sm.state)
"""

_REFUSE_SHEET = {"terms": CANNED_COUNTER_TERMS, "decision": "refuse",
                 "reason": "no deal"}
_COUNTERED_PREFIX = [{"event": "counter", "action": "counter", "from": "DRAFT",
                      "to": "COUNTERED", "terms": CANNED_COUNTER_TERMS}]
_REVISED_PREFIX = _COUNTERED_PREFIX + [
    {"event": "accept_counter", "action": "accept_counter",
     "from": "COUNTERED", "to": "REVISED"}]


def _mutants_src():
    """The mutants/src tree the current process imported from, when present
    (inside a mutmut workspace the child must import the mutated tree).
    Walks up from the imported package — under mutmut the package sits at
    <workspace>/mutants/src/zft, one level deeper than a plain
    src/ checkout, so a fixed parent count guesses wrong in one of the two."""
    pkg = Path(__import__("zft").__file__).resolve()
    for base in pkg.parents:
        if (base / "mutants" / "src" / "zft").is_dir():
            return str(base / "mutants" / "src")
    return ""


def _active_mutant() -> str:
    """The mutant under test, forwarded to children: mutmut sets it as a
    process-local trampoline global, which subprocesses do not inherit —
    without this, a child would happily run the original code."""
    try:
        from mutmut.mutation.trampoline import get_mutant_under_test
        return get_mutant_under_test()
    except ImportError:
        return os.environ.get("MUTANT_UNDER_TEST", "")


def _child(spec: dict, runs_root) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=_mutants_src() + os.pathsep
               + os.environ.get("PYTHONPATH", ""),
               MUTANT_UNDER_TEST=_active_mutant())
    return subprocess.run(
        [sys.executable, "-c", _KILL_CHILD, json.dumps(spec), str(runs_root),
         _mutants_src()],
        capture_output=True, text=True, timeout=120, env=env)


def test_kill_seam_fires_on_each_branch_and_only_there(tmp_path):
    """The kill-9 demo seam is contract: with kill_after naming the action
    about to run, the process dies by SIGKILL the moment that transition is
    durable — from every branch — and a named action that never happens
    leaves the process alive to finish. (The e2e drives this through the
    CLI subprocess; these children import the module directly so the seam
    itself stays pinned at the unit tier.)"""
    # coverage mapping: touch the driver in-process once (no kill)
    sm = NegotiationSM.replay([])
    led = RunLedger.start(tmp_path / "map", manifest={"stage": "negotiate"})
    advance_to_validated(sm, led)
    assert sm.state == "VALIDATED"
    led.close()

    kills = {
        "counter-from-DRAFT": {"prefix": [], "kill_after": "counter"},
        "accept_counter-from-COUNTERED": {"prefix": _COUNTERED_PREFIX,
                                          "kill_after": "accept_counter"},
        "refuse-from-COUNTERED": {"prefix": _COUNTERED_PREFIX,
                                  "kill_after": "refuse",
                                  "sheet": _REFUSE_SHEET},
        "validate-from-REVISED": {"prefix": _REVISED_PREFIX,
                                  "kill_after": "validate"},
        "refuse-from-REVISED": {"prefix": _REVISED_PREFIX,
                                "kill_after": "refuse",
                                "sheet": _REFUSE_SHEET},
    }
    for name, spec in kills.items():
        runs = tmp_path / name
        proc = _child(spec, runs)
        assert proc.returncode == -9, \
            f"{name}: seam must die by SIGKILL, rc={proc.returncode} " \
            f"stderr={proc.stderr[-300:]}"
    # a named action that never happens must NOT fire the seam
    proc = _child({"prefix": [], "kill_after": "refuse"}, tmp_path / "calm")
    assert proc.returncode == 0, \
        f"mismatched kill_after must leave the process alive: {proc.stderr[-300:]}"
    assert "survived:VALIDATED" in proc.stdout


class _SeamKill(Exception):
    """The faked seam fired: os.kill was reached."""
def _seam_kill_call(monkeypatch):
    calls = []

    def fake_kill(pid, sig):
        calls.append((pid, sig))
        raise _SeamKill((pid, sig))

    monkeypatch.setattr(os, "kill", fake_kill)
    return calls
def _counter_event(terms):
    return {"event": "counter", "action": "counter", "from": "DRAFT",
            "to": "COUNTERED", "terms": terms}
def _accept_event():
    return {"event": "accept_counter", "action": "accept_counter",
            "from": "COUNTERED", "to": "REVISED"}
def _refuse_sheet():
    return CounterTerms(terms=CANNED_COUNTER_TERMS, decision="refuse",
                        reason="no deal")
def test_kill_seam_fires_at_counter_from_draft(tmp_path, monkeypatch):
    calls = _seam_kill_call(monkeypatch)
    sm = NegotiationSM.replay([])
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(_SeamKill):
        advance_to_validated(sm, led, kill_after="counter")
    assert calls == [(os.getpid(), signal.SIGKILL)]
def test_kill_seam_fires_at_accept_counter_from_countered(tmp_path, monkeypatch):
    calls = _seam_kill_call(monkeypatch)
    sm = NegotiationSM.replay([_counter_event(CANNED_COUNTER_TERMS)])
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(_SeamKill):
        advance_to_validated(sm, led, kill_after="accept_counter")
    assert calls == [(os.getpid(), signal.SIGKILL)]
def test_kill_seam_fires_at_refuse_from_countered(tmp_path, monkeypatch):
    calls = _seam_kill_call(monkeypatch)
    sm = NegotiationSM.replay([_counter_event(CANNED_COUNTER_TERMS)])
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(_SeamKill):
        advance_to_validated(sm, led, kill_after="refuse", terms=_refuse_sheet())
    assert calls == [(os.getpid(), signal.SIGKILL)]
def test_kill_seam_fires_at_validate_from_revised(tmp_path, monkeypatch):
    calls = _seam_kill_call(monkeypatch)
    sm = NegotiationSM.replay([_counter_event(CANNED_COUNTER_TERMS),
                               _accept_event()])
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(_SeamKill):
        advance_to_validated(sm, led, kill_after="validate")
    assert calls == [(os.getpid(), signal.SIGKILL)]
def test_kill_seam_fires_at_refuse_from_revised(tmp_path, monkeypatch):
    calls = _seam_kill_call(monkeypatch)
    sm = NegotiationSM.replay([_counter_event(CANNED_COUNTER_TERMS),
                               _accept_event()])
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(_SeamKill):
        advance_to_validated(sm, led, kill_after="refuse", terms=_refuse_sheet())
    assert calls == [(os.getpid(), signal.SIGKILL)]
def test_non_matching_kill_after_never_fires(tmp_path, monkeypatch):
    """A kill_after no walked action matches completes the protocol — the
    or/!= inversions at the seam would SIGKILL on the very first step."""
    calls = _seam_kill_call(monkeypatch)
    sm = NegotiationSM.replay([])
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    advance_to_validated(sm, led, kill_after="refuse")
    assert sm.state == "VALIDATED"
    assert calls == []
def test_external_terms_canned_refusal_message_is_exact(tmp_path):
    """A run that countered with external terms refuses the canned finish;
    the refusal names the way out — contract text, anchored byte-exact."""
    sm = NegotiationSM.replay([_counter_event("examples=50")])
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(IllegalTransition) as ei:
        advance_to_validated(sm, led)
    assert str(ei.value) == ("run countered with external terms; finishing it "
                             "canned would invent the counter-party's decision "
                             "— resume with the --counter-terms document")
def test_counter_terms_mismatch_message_is_exact(tmp_path):
    """Swapping the sheet mid-bargain is a different bargain; the typed
    refusal quotes the recorded counter-proposal — anchored byte-exact."""
    sm = NegotiationSM.replay([_counter_event("terms A")])
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(IllegalTransition) as ei:
        advance_to_validated(
            sm, led, terms=CounterTerms(terms="terms B", decision="accept",
                                        reason=None))
    assert str(ei.value) == ("counter-terms document does not match the "
                             "recorded counter-proposal 'terms A'")
def test_advance_refuses_implemented_midstate(tmp_path):
    """IMPLEMENTED is nobody's continuation: the walk's else branch refuses
    typed (the REFUSED-entry guard above it is a different exit)."""
    sm = NegotiationSM.start()
    sm.counter(CANNED_COUNTER_TERMS)
    sm.accept_counter()
    sm.validate()
    sm.implement()
    resumed = NegotiationSM.replay(_history(sm))
    assert resumed.state == "IMPLEMENTED"
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    with pytest.raises(IllegalTransition) as ei:
        advance_to_validated(resumed, led)
    assert str(ei.value) == "no canned continuation from IMPLEMENTED"
def test_resume_replays_with_the_recorded_retry_budget(tmp_path):
    """The manifest's retry_budget rides the replay: a resumed machine is
    budget-faithful to the run it continues."""
    led = RunLedger.start(tmp_path,
                          manifest={"stage": "negotiate", "retry_budget": 2})
    led.append({"event": "cfp"})
    led.close()
    out = resume(tmp_path)
    assert out is not None
    resumed_led, sm = out
    assert sm.retry_budget == 2
def test_resume_defaults_budget_when_manifest_omits_it(tmp_path):
    """No budget in the manifest means the protocol default — not None."""
    _negotiate_run(tmp_path, [{"event": "cfp"}])
    out = resume(tmp_path)
    assert out is not None
    resumed_led, sm = out
    assert sm.retry_budget == DEFAULT_RETRY_BUDGET
def test_resume_ledger_records_are_exact(tmp_path):
    """Resume's own ledger lines carry their contract keys and values:
    torn-tail recovery records the dropped byte count; the resumed event
    records the replayed step count and the rebuilt state."""
    led = RunLedger.start(tmp_path, manifest={"stage": "negotiate"})
    led.append({"event": "cfp"})
    with open(led.dir / "events.jsonl", "ab") as fh:
        fh.write(b'{"event": "counter", "act')  # torn mid-write, no newline
    led.close()

    out = resume(tmp_path)
    assert out is not None
    resumed_led, sm = out
    torn_bytes = resumed_led._torn_tail_bytes
    resumed_led.close()
    events = RunLedger.load(tmp_path, resumed_led.run_id).events
    assert events[-2] == {"event": "resumed_torn_tail", "bytes": torn_bytes}
    assert events[-1] == {"event": "resumed", "replayed": len(sm.history),
                          "state": sm.state}
