"""Negotiation crash resumption: find, replay, and finish an interrupted run.

The negotiate CLI persists every state-machine transition to its run ledger
as it happens — one flushed JSON line per transition (`ledger.append` flushes
before returning, so a SIGKILL cannot unwrite an appended event). A process
killed mid-negotiation therefore leaves a durable prefix of the protocol on
disk; this module is the read/continue side:

  find_resumable(runs_root) -> run id of the latest unfinished negotiate run
  resume(runs_root)         -> (ledger, machine) replayed from that prefix
  advance_to_validated(...) -> drive the machine to a terminal state

Resumption is event-sourced: the machine is rebuilt by replaying the
recorded transitions through `NegotiationSM.replay`, which verifies each
recorded from/to against the transition actually taken — a forged or torn
history fails typed instead of resuming into a state the log never earned.

A run is *unfinished* when its ledger carries no terminal event
("validated" or "refuse"). Runs whose manifest is missing or torn are
skipped, not guessed: an unidentifiable run is never resumed.
"""
from __future__ import annotations

import json
import os
import signal
from pathlib import Path

from traceagent.debug.ledger import RunLedger
from traceagent.negotiate.sm import (
    DEFAULT_RETRY_BUDGET,
    IllegalTransition,
    NegotiationSM,
)
from traceagent.negotiate.terms import CounterTerms, terms_string

_TERMINAL_EVENTS = {"validated", "refuse"}

# the term sheet the canned demo counters with when no document is supplied
CANNED_COUNTER_TERMS = "producer counter-terms (default none)"


def find_resumable(runs_root: Path | str) -> str | None:
    """Latest negotiate run without a terminal event, newest mtime wins."""
    runs_root = Path(runs_root)
    if not runs_root.is_dir():
        return None
    unfinished: list[tuple[float, str]] = []
    for run_dir in runs_root.iterdir():
        if not run_dir.is_dir():
            continue
        try:
            manifest = json.loads((run_dir / "manifest.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue  # not identifiable as a negotiate run — skip, never guess
        if manifest.get("stage") != "negotiate":
            continue
        try:
            record = RunLedger.load(runs_root, run_dir.name)
        except FileNotFoundError:
            continue  # no events file: nothing to replay from
        events = [e.get("event") for e in record.events]
        if not events or _TERMINAL_EVENTS.isdisjoint(events):
            unfinished.append((run_dir.stat().st_mtime, run_dir.name))
    if not unfinished:
        return None
    return max(unfinished)[1]


def resume(runs_root: Path | str) -> tuple[RunLedger, NegotiationSM] | None:
    """Resume the latest unfinished negotiate run, or None if there is none.

    Rebuilds the machine from the run's recorded transitions and reopens the
    ledger for appending — the resumed process continues the same run, so
    the ledger ends up holding the whole protocol in one place.
    """
    run_id = find_resumable(runs_root)
    if run_id is None:
        return None
    runs_root = Path(runs_root)
    record = RunLedger.load(runs_root, run_id)
    try:
        manifest = json.loads((runs_root / run_id / "manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        manifest = {}
    sm = NegotiationSM.replay(record.events,
                              retry_budget=manifest.get("retry_budget",
                                                        DEFAULT_RETRY_BUDGET))
    led = RunLedger.resume(runs_root, run_id)
    if led._torn_tail_bytes:
        led.append({"event": "resumed_torn_tail", "bytes": led._torn_tail_bytes})
    led.append({"event": "resumed", "replayed": len(sm.history), "state": sm.state})
    return led, sm


def _step(sm: NegotiationSM, led: RunLedger, action: str,
          kill_after: str | None = None, **kwargs) -> None:
    """One transition, persisted the moment it happens (crash-honest order).

    With `kill_after` matching this action, the process then SIGKILLs itself:
    the demo seam. The kill is real — no unwinding, no atexit — and every
    event appended before it is already flushed to the OS, so the durable
    prefix is exactly what a killed negotiation would leave behind.
    """
    getattr(sm, action)(**kwargs)
    led.append({"event": action, **sm.history[-1]})
    if kill_after and action == kill_after:
        os.kill(os.getpid(), signal.SIGKILL)


def recorded_counter_terms(sm: NegotiationSM) -> list[str]:
    """The counter-proposals in the machine's history, ledger form in order."""
    return [e["terms"] for e in sm.history if e.get("action") == "counter"]


def advance_to_validated(sm: NegotiationSM, led: RunLedger,
                         kill_after: str | None = None,
                         terms: CounterTerms | None = None) -> None:
    """Drive the protocol from any mid-state to a terminal state.

    With a counter-terms document this is a real bargain: the counter
    carries the sheet's terms and the sheet's decision picks the terminal
    state — accept runs on to VALIDATED, refuse ends REFUSED with its
    reason, from COUNTERED or REVISED alike. Without one, the canned demo
    continues (counter→accept→validate).

    A bargain may only be continued by its own sheet. A run whose counter
    recorded external terms cannot be finished by the canned continuation
    (that would invent the counter-party's decision), and a document whose
    terms differ from the recorded counter-proposal is a different bargain,
    not a continuation — both are typed refusals.
    """
    want_terms = None if terms is None else terms_string(terms.terms)
    for recorded in recorded_counter_terms(sm):
        if terms is None and recorded != CANNED_COUNTER_TERMS:
            raise IllegalTransition(
                "run countered with external terms; finishing it canned would "
                "invent the counter-party's decision — resume with the "
                "--counter-terms document")
        if want_terms is not None and recorded != want_terms:
            raise IllegalTransition(
                "counter-terms document does not match the recorded "
                f"counter-proposal {recorded!r}")
    if sm.state == "REFUSED":  # refused on entry: no continuation to invent
        raise IllegalTransition(f"no canned continuation from {sm.state}")
    refuse_now = terms is not None and terms.decision == "refuse"
    while sm.state not in ("VALIDATED", "REFUSED"):
        if sm.state == "DRAFT":
            _step(sm, led, "counter", kill_after,
                  terms=want_terms or CANNED_COUNTER_TERMS)
        elif sm.state == "COUNTERED":
            if refuse_now:
                _step(sm, led, "refuse", kill_after, reason=terms.reason)
            else:
                _step(sm, led, "accept_counter", kill_after)
        elif sm.state == "REVISED":
            if refuse_now:  # REVISED->REFUSED is legal: the decision binds
                _step(sm, led, "refuse", kill_after, reason=terms.reason)
            else:
                _step(sm, led, "validate", kill_after)
        else:
            raise IllegalTransition(f"no canned continuation from {sm.state}")
