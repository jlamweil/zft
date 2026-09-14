"""Counter-terms document parser — the outside-the-process bargain input.

The negotiate CLI takes a counter-party's term sheet as JSON (file or stdin):
{"terms": ..., "decision": "accept"|"refuse", "reason": <required with refuse>}.
Parsing is strict and typed: anything the schema does not admit is a
CounterTermsError naming the defect, never a guess — a bargain must be about
exactly the terms on the sheet.
"""
import pytest

from traceagent.negotiate.terms import (
    CounterTermsError,
    digest_from_recorded,
    parse_counter_terms,
    terms_digest,
    terms_string,
)


def test_accept_document_parses():
    doc = '{"terms": "raise timeout budget to 90s", "decision": "accept"}'
    parsed = parse_counter_terms(doc)
    assert parsed.terms == "raise timeout budget to 90s"
    assert parsed.decision == "accept"
    assert parsed.reason is None


def test_refuse_document_carries_reason():
    doc = ('{"terms": "drop GATE-MUTATION-ATTRIBUTION",'
           ' "decision": "refuse", "reason": "out of scope"}')
    parsed = parse_counter_terms(doc)
    assert parsed.decision == "refuse"
    assert parsed.reason == "out of scope"


def test_structured_terms_accepted():
    doc = ('{"terms": [{"clause": "GATE-L0-HASH-VERIFY",'
           ' "change": "skip on draft"}], "decision": "accept"}')
    parsed = parse_counter_terms(doc)
    assert parsed.terms == [{"clause": "GATE-L0-HASH-VERIFY", "change": "skip on draft"}]


def test_empty_terms_rejected():
    with pytest.raises(CounterTermsError, match="terms"):
        parse_counter_terms('{"decision": "accept"}')


def test_missing_decision_rejected():
    with pytest.raises(CounterTermsError, match="decision"):
        parse_counter_terms('{"terms": "x"}')


def test_unknown_decision_value_rejected():
    with pytest.raises(CounterTermsError, match="decision"):
        parse_counter_terms('{"terms": "x", "decision": "maybe"}')


def test_refuse_without_reason_rejected():
    with pytest.raises(CounterTermsError, match="reason"):
        parse_counter_terms('{"terms": "x", "decision": "refuse"}')


def test_unknown_keys_rejected_with_names():
    with pytest.raises(CounterTermsError, match="desicion"):
        parse_counter_terms('{"terms": "x", "desicion": "accept"}')


def test_non_object_document_rejected():
    for raw in ('["terms"]', '"accept"', "3", "null"):
        with pytest.raises(CounterTermsError, match="object"):
            parse_counter_terms(raw)


def test_malformed_json_rejected():
    with pytest.raises(CounterTermsError, match="JSON"):
        parse_counter_terms('{"terms": ')


def test_empty_input_rejected():
    with pytest.raises(CounterTermsError):
        parse_counter_terms("")


def test_bytes_input_accepted():
    parsed = parse_counter_terms(b'{"terms": "x", "decision": "accept"}')
    assert parsed.terms == "x"


def test_digest_is_canonical():
    """Digest binds the bargain to the terms' meaning, not their key order."""
    a = terms_digest({"b": 2, "a": 1})
    b = terms_digest({"a": 1, "b": 2})
    assert a == b
    assert a != terms_digest({"a": 2, "b": 1})


def test_digest_distinguishes_string_from_structured():
    assert terms_digest("[1, 2]") != terms_digest([1, 2])


def test_digest_reconstructs_from_recorded_string_terms():
    sheet = "raise timeout budget to 90s"
    assert digest_from_recorded(terms_string(sheet)) == terms_digest(sheet)


def test_digest_reconstructs_from_recorded_structured_terms():
    terms = {"budget": "90s", "clauses": ["GATE-L0"]}
    assert digest_from_recorded(terms_string(terms)) == terms_digest(terms)


@pytest.mark.parametrize("value", ["plain terms", ["a", 2], {"k": "v", "n": 3}, 42])
def test_digest_from_recorded_is_path_stable(value):
    """CLI and wire bind the SAME digest to the same sheet, whichever path
    validates — the recorded counter bytes are the shared truth."""
    assert digest_from_recorded(terms_string(value)) == terms_digest(value)
