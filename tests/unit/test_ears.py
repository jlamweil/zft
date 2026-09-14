"""C-08: EARS statement parser — 5 forms, golden-verified on our real clause corpus.

Independent truth: EARS grammar (Mavin 2009) + our contract statements,
plus the golden fixture in tests/golden/ears_statements.json (accepted parses
and rejection diagnostics pinned verbatim).

REVERSE COVERAGE — JUSTIFIED OUT-OF-CONTRACT, per element (2026-09-12; store
run 9ed8a13c5441 ok: 32/32 due clauses bound, ratio 1.0; out-of-contract =
this file + test_pytest_runner.py only). TR-REVERSE-COVERAGE requires unbound
elements be LISTED, not that every element bind — the listing is the
compliant state; this block records why no binding is owed. None of the
store's 43 clause ids has an invariant statement that predicates EARS
statement parsing, grammar forms, or diagnostic wording. The nearest clauses
are bound where their predicates actually live: DSL-TRIGGER-PREDICATE-
ENFORCEMENT + DSL-COMPILE-GENERATORS (declarative structure, compile-to-
generators) at tests/unit/test_predicate.py:204-205; DSL-JUDGE-ESCAPE-HATCH
at tests/unit/test_strategies_oracle.py:191; store-internal integrity is L0
territory (GATE-L0-HASH-VERIFY, GATE-DUPLICATE-CLAUSES) at
tests/unit/test_lint_store.py:23,39; GATE-MUTATION-ATTRIBUTION (kill
attribution, not diagnostic text) at tests/unit/test_mutmut_runner.py:119.
Per element, every one JUSTIFIED out-of-contract:
- Grammar acceptance — test_when_form, test_if_form, test_while_form,
  test_where_form, test_ubiquitous_form, test_must_modal_accepted: pin parser
  mechanics no clause's predicate reaches.
- Rejection + diagnostics — test_non_ears_statement_rejected,
  TestEdgeCaseDiagnostics (12 methods), test_diagnose_*,
  test_response_keeps_trailing_x_before_period,
  test_punctuation_only_trigger_diagnoses_with_statement_excerpt: diagnostic
  wording is contract-author product surface pinned from the mut-dsl-codegen
  campaigns (2026-09-06/07); no clause predicates message content.
- Golden corpus vs the store — test_golden_full_corpus_parses,
  test_golden_accept_parses_exactly, test_golden_reject_diagnoses,
  test_golden_reject_messages_are_pinned_in_full,
  test_golden_fixture_covers_every_ears_pattern,
  test_golden_patterns_match_parser_keywords: reads .zft/specs as a fixture
  (corpus parseability); exercises no clause predicate — store integrity is
  L0's governed job, cited above.
A future clause whose predicate reaches the EARS grammar/diagnostics binds
this file at its negotiation; until then the store is under merge freeze
(2026-09-12, Phase C reconcile pending, owner go for any store write) and
this listing stands as recorded. Full decision record: RESEARCH_LOG 2026-09-12.
"""
import json
from pathlib import Path

import pytest

from traceagent.dsl.ears import EarsError, parse_statement

REPO = Path(__file__).resolve().parents[2]
GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "golden" / "ears_statements.json").read_text())


def test_when_form():
    parts = parse_statement("WHEN a work order is assigned, THE SYSTEM SHALL refuse implementation start")  # noqa: E501
    assert parts["type"] == "WHEN"
    assert parts["trigger"] == "a work order is assigned"
    assert parts["response"] == "refuse implementation start"


def test_if_form():
    parts = parse_statement("IF mutants are fewer than configured, THE SYSTEM SHALL attribute contract-fault")  # noqa: E501
    assert parts["type"] == "IF"
    assert parts["trigger"] == "mutants are fewer than configured"


def test_while_form():
    parts = parse_statement("WHILE campaign is running, THE SYSTEM SHALL stream verdicts")
    assert parts["type"] == "WHILE"


def test_where_form():
    parts = parse_statement("WHERE possible, THE SYSTEM SHALL evaluate with a different model")
    assert parts["type"] == "WHERE"
    assert parts["trigger"] == "possible"


def test_ubiquitous_form():
    parts = parse_statement("THE SYSTEM SHALL exchange contract as A2A artifacts")
    assert parts["type"] == "UBIQUITOUS"
    assert parts["trigger"] is None
    assert parts["response"].startswith("exchange contract")


def test_must_modal_accepted():
    parts = parse_statement("THE SYSTEM MUST refuse unvalidated contracts")
    assert parts["modal"] == "MUST"


def test_non_ears_statement_rejected():
    with pytest.raises(EarsError, match="not an EARS statement"):
        parse_statement("The system probably handles it fine.")


class TestEdgeCaseDiagnostics:
    """Parser edge cases fail gracefully, naming the problem and the fix."""

    def test_empty_statement(self):
        with pytest.raises(EarsError, match="statement is empty"):
            parse_statement("   ")

    def test_non_string_input_is_type_error(self):
        with pytest.raises(TypeError, match="statement must be str"):
            parse_statement(None)  # type: ignore[arg-type]

    def test_lowercase_the_system_hinted(self):
        with pytest.raises(EarsError, match="'THE SYSTEM' is lowercase"):
            parse_statement("the system shall log every exchange")

    def test_missing_system_clause(self):
        with pytest.raises(EarsError, match="missing 'THE SYSTEM'"):
            parse_statement("It shall log everything.")

    def test_wrong_modal_named(self):
        with pytest.raises(EarsError, match="modal after 'THE SYSTEM' is 'probably'"):
            parse_statement("THE SYSTEM probably refuses invalid contracts")

    def test_missing_response_after_modal(self):
        with pytest.raises(EarsError, match="response is missing after SHALL"):
            parse_statement("THE SYSTEM SHALL")

    def test_lowercase_trigger_keyword_hinted(self):
        with pytest.raises(EarsError, match="trigger keyword is lowercase"):
            parse_statement("when a contract arrives, THE SYSTEM SHALL validate it")

    def test_unknown_trigger_word_lists_valid_keywords(self):
        with pytest.raises(EarsError, match="not a trigger keyword"):
            parse_statement("GIVEN a signed contract, THE SYSTEM SHALL accept it")

    def test_missing_comma_between_trigger_and_system(self):
        with pytest.raises(EarsError, match="comma"):
            parse_statement("WHEN a contract arrives THE SYSTEM SHALL validate it")

    def test_empty_response_rejected(self):
        with pytest.raises(EarsError, match="response is empty"):
            parse_statement("THE SYSTEM SHALL .")

    def test_punctuation_only_trigger_rejected(self):
        with pytest.raises(EarsError, match="punctuation-only"):
            parse_statement("WHEN , THE SYSTEM SHALL accept valid contracts")

    def test_diagnostic_carries_statement_excerpt_and_grammar(self):
        with pytest.raises(EarsError) as ei:
            parse_statement("The system probably handles it fine.")
        msg = str(ei.value)
        assert "statement:" in msg  # excerpt of the offending input
        assert "expected:" in msg  # the EARS shape
        assert "hint:" in msg  # the fix


def test_golden_full_corpus_parses():
    """All real contract statements parse (V1: 100% pass criterion)."""
    from traceagent.spec.store import load_contract

    spec_dir = REPO / ".zft" / "specs"
    files = sorted(spec_dir.rglob("*.json"))
    # one spec file per contract clause: L0 enforces every clause_id resolves to
    # exactly one node, so corpus size tracks the contract manifest
    assert len(files) == len(load_contract(REPO)["clause_ids"])
    for path in files:
        import json

        node = json.loads(path.read_text())
        for inv in node["invariants"]:
            parts = parse_statement(inv["statement"])
            assert parts["response"], f"{node['alias']}: empty response"
            assert parts["type"] in {"WHEN", "IF", "WHILE", "WHERE", "UBIQUITOUS"}


# --- golden fixture (tests/golden/ears_statements.json) ----------------------

@pytest.mark.parametrize("case", GOLDEN["accept"], ids=lambda c: c["name"])
def test_golden_accept_parses_exactly(case):
    assert parse_statement(case["statement"]) == case["expected"]


@pytest.mark.parametrize("case", GOLDEN["reject"], ids=lambda c: c["name"])
def test_golden_reject_diagnoses(case):
    # GATE-MUTATION-KILL (mut-dsl-codegen shard 2026-09-07: 80 _diagnose
    # survivors): the diagnostic is the product surface for contract authors —
    # the golden pins the WHOLE layered message verbatim (problem + excerpt +
    # expected + hint), not just the problem substring, so hint/excerpt/
    # grammar drift is a test failure instead of a silent mutation.
    # "error" selects the rejection type: TypeError for the non-string guard,
    # EarsError (the default) for every grammar rejection.
    if "expected_message" not in case:
        pytest.fail("golden reject case pins only a substring — add expected_message")
    error = TypeError if case.get("error") == "TypeError" else EarsError
    with pytest.raises(error) as excinfo:
        parse_statement(case["statement"])
    assert str(excinfo.value) == case["expected_message"]
    if "diagnostic" in case:
        assert case["diagnostic"] in str(excinfo.value)


def test_golden_reject_messages_are_pinned_in_full():
    missing = [c["name"] for c in GOLDEN["reject"] if "expected_message" not in c]
    assert not missing, f"reject cases without expected_message: {missing}"
    # one golden witness per rejection branch: every _diagnose/_problem branch
    # (13 diagnostics incl. ends-at-THE-SYSTEM) + the excerpt-truncation shape
    # + the parse-level punctuation guard + the non-string type guard
    assert len(GOLDEN["reject"]) >= 16


def test_golden_fixture_covers_every_ears_pattern():
    """Full cross product: {WHEN,IF,WHILE,WHERE} x {SHALL,MUST} + UBIQUITOUS x both."""
    accepted = GOLDEN["accept"]
    patterns = GOLDEN["patterns"]
    expected = {(t, m) for t in patterns["triggers"] for m in patterns["modals"]}
    expected |= {(patterns["ubiquitous_type"], m) for m in patterns["modals"]}
    seen = {(c["expected"]["type"], c["expected"]["modal"]) for c in accepted}
    assert seen == expected, f"patterns without an accept witness: {expected - seen}"
    assert GOLDEN["reject"], "rejection corpus must stay populated"


def test_golden_patterns_match_parser_keywords():
    """The declared pattern set IS the parser's keyword set — in order.

    The hints join the keywords ('WHEN/IF/WHILE/WHERE'), so keyword order is
    product surface too; adding/removing a trigger or modal must update the
    golden declaration and earn its own accept/reject witnesses.
    """
    from traceagent.dsl.ears import _MODAL_WORDS, _TRIGGER_WORDS

    assert list(_TRIGGER_WORDS) == GOLDEN["patterns"]["triggers"]
    assert list(_MODAL_WORDS) == GOLDEN["patterns"]["modals"]
    assert GOLDEN["patterns"]["ubiquitous_type"] == "UBIQUITOUS"


# --- GATE-MUTATION-KILL (mut-dsl-codegen campaign 2026-09-06) ----------------

# GATE-MUTATION-KILL: the empty-trigger check splits `between` on ',' —
# split(None)/index [1] mutants re-admit punctuation-only triggers as long as
# ANY later segment carries an alnum (_diagnose 154/156)
def test_diagnose_empty_trigger_rejects_punctuation_first_segment():
    from traceagent.dsl.ears import _diagnose

    assert "empty or punctuation-only" in _diagnose("WHEN ,a x, THE SYSTEM SHALL x")


# GATE-MUTATION-KILL: `word != "THE" -> "the"` re-admits a lowercase leading
# article in front of an uppercase body (_diagnose 170)
def test_diagnose_lowercase_leading_word_is_not_the_keyword():
    from traceagent.dsl.ears import _diagnose

    assert "not a trigger keyword" in _diagnose("the THE SYSTEM SHALL respond")


# GATE-MUTATION-KILL: response rstrip('.') -> rstrip('XX.XX') eats trailing X
# letters out of the response text (parse_statement 19)
def test_response_keeps_trailing_x_before_period():
    assert parse_statement("WHEN x, THE SYSTEM SHALL fix X.")["response"] == "fix X"


# GATE-MUTATION-KILL: pins the punctuation-trigger diagnostic — statement
# excerpt, problem text and hint all contractual
# (parse_statement 24/25/26/27/31/32/33)
def test_punctuation_only_trigger_diagnoses_with_statement_excerpt():
    with pytest.raises(EarsError) as ei:
        parse_statement("WHEN !!!, THE SYSTEM SHALL x.")
    msg = str(ei.value)
    assert "trigger after WHEN is empty or punctuation-only" in msg
    assert "state a concrete condition, e.g. WHEN a work order is assigned," in msg
