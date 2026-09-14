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

import pytest

from traceagent.debug.ledger import RunLedger
from traceagent.negotiate.resume import (
    CANNED_COUNTER_TERMS,
    advance_to_validated,
    find_resumable,
    resume,
)
from traceagent.negotiate.sm import DEFAULT_RETRY_BUDGET, IllegalTransition, NegotiationSM


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
    with pytest.raises(IllegalTransition, match="history mismatch"):
        NegotiationSM.replay(history, retry_budget=1)


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
