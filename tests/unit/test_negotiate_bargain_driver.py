"""Driver-level bargain semantics: counter-terms drive the terminal state.

The canned driver (counter→accept→validate unconditionally) becomes a real
bargain when a CounterTerms document rides in: the counter carries the
sheet's terms, the sheet's decision picks the terminal state, and a run that
already recorded external terms can never be finished by the canned
continuation — no decision may be invented for a counter-party.
"""
import pytest

from traceagent.debug.ledger import RunLedger
from traceagent.negotiate.resume import (
    CANNED_COUNTER_TERMS,
    advance_to_validated,
)
from traceagent.negotiate.resume import resume as resume_run
from traceagent.negotiate.sm import IllegalTransition, NegotiationSM
from traceagent.negotiate.terms import CounterTerms, parse_counter_terms, terms_string


def _ledger(tmp_path):
    return RunLedger.start(tmp_path / "runs", manifest={"stage": "negotiate"},
                           repo=tmp_path)


def _doc(terms, decision="accept", reason=None):
    return CounterTerms(terms=terms, decision=decision, reason=reason)


def _events(led):
    led.close()
    return RunLedger.load(led.dir.parent, led.run_id).events


def test_canned_constant_matches_legacy_literal():
    """The canned term sheet is protocol history — its exact bytes are asserted
    by the e2e kill tests; the constant must not drift from them."""
    assert CANNED_COUNTER_TERMS == "producer counter-terms (default none)"


def test_accept_bargain_records_terms_and_validates(tmp_path):
    sm, led = NegotiationSM.start(), _ledger(tmp_path)
    advance_to_validated(sm, led, terms=_doc("raise timeout budget to 90s"))
    assert sm.state == "VALIDATED"
    events = _events(led)
    assert [e["event"] for e in events] == \
        ["counter", "accept_counter", "validate"]
    assert events[0]["terms"] == "raise timeout budget to 90s"


def test_structured_terms_land_as_canonical_string(tmp_path):
    sm, led = NegotiationSM.start(), _ledger(tmp_path)
    terms = _doc([{"clause": "GATE-L0-HASH-VERIFY", "change": "skip on draft"}])
    advance_to_validated(sm, led, terms=terms)
    events = _events(led)
    assert events[0]["terms"] == terms_string(terms.terms)
    assert '"clause":"GATE-L0-HASH-VERIFY"' in events[0]["terms"]


def test_refused_bargain_ends_refused_with_reason(tmp_path):
    sm, led = NegotiationSM.start(), _ledger(tmp_path)
    advance_to_validated(sm, led,
                         terms=_doc("drop the mutation gate", "refuse",
                                    reason="outside v0 scope"))
    assert sm.state == "REFUSED"
    events = _events(led)
    assert [e["event"] for e in events] == ["counter", "refuse"]
    assert events[-1]["reason"] == "outside v0 scope"


def test_canned_path_unchanged_without_document(tmp_path):
    sm, led = NegotiationSM.start(), _ledger(tmp_path)
    advance_to_validated(sm, led)
    events = _events(led)
    assert [e["event"] for e in events] == ["counter", "accept_counter", "validate"]
    assert events[0]["terms"] == CANNED_COUNTER_TERMS


def _countered_prefix(tmp_path, terms: str):
    """A durable 'killed right after counter' prefix: exactly the events a
    SIGKILL at that seam would have left (the seam itself is e2e-only —
    in-process it would kill pytest). Resumption goes through the production
    resume(), so the replayed machine is the one the CLI would drive."""
    sm, led = NegotiationSM.start(), _ledger(tmp_path)
    sm.counter(terms)
    led.append({"event": "counter", **sm.history[-1]})
    _events(led)
    resumed = resume_run(led.dir.parent)
    assert resumed is not None
    return resumed  # (ledger, machine)


def test_canned_continuation_refuses_to_invent_a_decision(tmp_path):
    """A run that countered with external terms is half a bargain: finishing it
    without the sheet would invent the counter-party's decision."""
    led2, sm2 = _countered_prefix(tmp_path, "real terms")
    with pytest.raises(IllegalTransition, match="--counter-terms"):
        advance_to_validated(sm2, led2)


def test_resumed_bargain_requires_the_same_terms(tmp_path):
    """The document resumed with must be about the recorded counter-proposal —
    swapping the sheet mid-bargain is a different bargain, not a continuation."""
    led2, sm2 = _countered_prefix(tmp_path, "terms A")
    with pytest.raises(IllegalTransition, match="does not match"):
        advance_to_validated(sm2, led2, terms=_doc("terms B"))


def test_resumed_bargain_with_matching_sheet_completes(tmp_path):
    sheet = '{"terms": "terms A", "decision": "refuse", "reason": "too costly"}'
    led2, sm2 = _countered_prefix(tmp_path, "terms A")
    advance_to_validated(sm2, led2, terms=parse_counter_terms(sheet))
    assert sm2.state == "REFUSED"
    led2.close()
    full = RunLedger.load(led2.dir.parent, led2.run_id).events
    assert [e["event"] for e in full] == \
        ["counter", "resumed", "refuse"], "same run continued, not restarted"
    assert full[0]["terms"] == "terms A"


def test_refused_bargain_via_document_decision(tmp_path):
    sm, led = NegotiationSM.start(), _ledger(tmp_path)
    doc = parse_counter_terms(
        '{"terms": "x", "decision": "refuse", "reason": "no deal"}')
    advance_to_validated(sm, led, terms=doc)
    assert sm.state == "REFUSED"


def test_refuse_decision_binds_from_revised_midstate(tmp_path):
    """A refuse sheet ends REFUSED from REVISED too: a run the canned path had
    already carried past accept_counter must not be forced to validate — the
    sheet's decision, not the midstate, picks the terminal state."""
    sm, led = NegotiationSM.start(), _ledger(tmp_path)
    sm.counter("terms A")
    led.append({"event": "counter", **sm.history[-1]})
    sm.accept_counter()
    led.append({"event": "accept_counter", **sm.history[-1]})
    _events(led)
    led2, sm2 = resume_run(led.dir.parent)
    assert sm2.state == "REVISED"
    advance_to_validated(sm2, led2,
                         terms=_doc("terms A", "refuse", reason="too costly"))
    assert sm2.state == "REFUSED"
    events = _events(led2)
    assert [e["event"] for e in events] == \
        ["counter", "accept_counter", "resumed", "refuse"]
    assert events[-1]["reason"] == "too costly"
