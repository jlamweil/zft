"""C-31/C-32/C-33/C-34: negotiation state machine + a2a adapter + CLI flow.

V7 ground truth: gate rejection -> INPUT_REQUIRED (re-open), pre-commitment
refusal -> REJECTED; cfp/counters/verdicts ride Messages; artifacts carry
contract + deliverable.

The full transition matrix is golden-pinned (tests/golden/
negotiation_transitions.json): every (state, action) pair appears exactly
once as legal (end state + appended history entry) or illegal (verbatim
typed message), plus the budget-exhaustion precedence variants. The gate
rejection loop — IMPLEMENTED -> REJECTED -> REVISED, budget-bounded — is
the transition this machine exists for.
"""
import json
from pathlib import Path

import pytest

from traceagent.negotiate.sm import (
    _TRANSITIONS,
    DEFAULT_RETRY_BUDGET,
    IllegalTransition,
    NegotiationSM,
)


def test_happy_path_full_cycle():
    sm = NegotiationSM.start()
    assert sm.state == "DRAFT"
    sm.counter("producer wants examples=50")          # COUNTERED
    sm.accept_counter()                               # REVISED
    sm.validate()                                     # VALIDATED
    sm.implement()                                    # IMPLEMENTED
    assert sm.state == "IMPLEMENTED"


def test_rejection_reopens_to_revision():
    sm = NegotiationSM.start()
    sm.validate()                                     # direct validation allowed
    sm.implement()
    sm.reject_gate(["GATE-INV-01"], fault="contract")  # -> REJECTED
    assert sm.state == "REJECTED"
    sm.reopen()                                       # -> REVISED (bounded loop)
    assert sm.state == "REVISED"


# @trace("PRT-TYPED-REFUSAL")
def test_pre_commitment_refusal():
    sm = NegotiationSM.start()
    sm.refuse("missing capability: jsonschema")
    assert sm.state == "REFUSED"
    with pytest.raises(IllegalTransition):
        sm.validate()  # no coming back from refusal


# @trace("CON-VALIDATED-OR-NO-START")
def test_illegal_transitions_blocked():
    sm = NegotiationSM.start()
    with pytest.raises(IllegalTransition):
        sm.implement()  # cannot implement from DRAFT (CON-VALIDATED-OR-NO-START)
    with pytest.raises(IllegalTransition):
        sm.reject_gate(["X"], fault="implementation")  # nothing to reject yet


def test_retry_budget_enforced():
    sm = NegotiationSM.start()
    sm.validate()
    sm.implement()
    for _ in range(3):
        sm.reject_gate(["GATE-INV-01"], fault="implementation")
        sm.reopen()
        sm.validate()      # revised contract re-validated
        sm.implement()
    with pytest.raises(IllegalTransition, match="retry budget"):
        sm.reopen()


# --- golden transition matrix (tests/golden/negotiation_transitions.json) ----

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "golden"
     / "negotiation_transitions.json").read_text())
STATES = GOLDEN["shape"]["states"]
ACTIONS = GOLDEN["shape"]["actions"]


def _steps(path):
    """Flatten a golden path, expanding {"repeat": n, "steps": [...]} blocks."""
    for step in path:
        if "repeat" in step:
            for _ in range(step["repeat"]):
                yield from step["steps"]
        else:
            yield step


def _walk(sm, path):
    """Replay a legal path; every step's end state is itself golden-checked."""
    for step in _steps(path):
        getattr(sm, step["action"])(**step.get("args", {}))
        assert sm.state == step["to"], f"setup path broke at {step}: {sm.state}"


def _at(case):
    """A fresh SM walked to the case's start state (explicit path wins)."""
    sm = NegotiationSM.start()
    _walk(sm, case["path"] if "path" in case else GOLDEN["paths"][case["state"]])
    return sm


@pytest.mark.parametrize("case", GOLDEN["legal"], ids=lambda c: c["name"])
def test_golden_legal_transition(case):
    """Every legal transition lands on its golden end state and appends its
    golden history entry — the ledger projection consumes exactly this shape."""
    sm = _at(case)
    getattr(sm, case["action"])(**case["args"])
    assert sm.state == case["to"]
    assert sm.history[-1] == case["history_entry"]
    assert len(sm.history) == sum(1 for _ in _steps(
        GOLDEN["paths"][case["state"]])) + 1


@pytest.mark.parametrize("case", GOLDEN["illegal"], ids=lambda c: c["name"])
def test_golden_illegal_transition_is_typed_and_inert(case):
    """Every illegal pair raises IllegalTransition with the golden message and
    leaves the machine untouched — a refused step must not mutate anything."""
    sm = _at(case)
    before = list(sm.history)
    with pytest.raises(IllegalTransition) as excinfo:
        getattr(sm, case["action"])(**case["args"])
    assert str(excinfo.value) == case["error"]
    assert sm.state == case["state"]
    assert sm.history == before
    assert sm.retries == 0


@pytest.mark.parametrize("case", GOLDEN["budget"], ids=lambda c: c["name"])
def test_golden_budget_exhaustion(case):
    """The bounded gate-retry loop: once `retries` hits the budget, reopen is
    typed as exhausted — including at REVISED, reopen's own target, proving
    the budget check wins the precedence race over the self-loop check."""
    sm = _at(case)
    assert sm.state == case["state_after_path"]
    with pytest.raises(IllegalTransition) as excinfo:
        getattr(sm, case["action"])(**case["args"])
    assert str(excinfo.value) == case["error"]
    assert sm.state == case["state_after_path"]


def test_golden_transition_matrix_is_complete():
    """The golden IS the transition matrix: every (state, action) pair appears
    exactly once — as a legal case or an illegal one — with no gaps, no
    duplicates, and a self-loop witness for every action at its own target."""
    pairs = [(c["state"], c["action"]) for c in GOLDEN["legal"]]
    pairs += [(c["state"], c["action"]) for c in GOLDEN["illegal"]]
    full = {(s, a) for s in STATES for a in ACTIONS}
    assert len(pairs) == len(set(pairs)), "duplicate (state, action) witnesses"
    assert set(pairs) == full, (
        f"uncovered pairs: {sorted(full - set(pairs))}, "
        f"unknown pairs: {sorted(set(pairs) - full)}")
    for action, target in ACTIONS.items():
        loops = [c for c in GOLDEN["illegal"]
                 if c["action"] == action and c["state"] == target]
        assert len(loops) == 1, f"{action}: missing self-loop witness at {target}"
        assert loops[0]["error"] == f"self-loop {action} in {target}"
    assert not [c for c in GOLDEN["legal"] if c["state"] == "REFUSED"], \
        "REFUSED is terminal — no legal transition may leave it"


def test_golden_legal_set_matches_source_table():
    """Source drift guard: the SM's own transition table and the golden legal
    set must coincide — a new/removed transition forces a golden update (and
    then a witness for its history entry or typed rejection)."""
    source_legal = {(state, action) for state, allowed in _TRANSITIONS.items()
                    for action in allowed}
    golden_legal = {(c["state"], c["action"]) for c in GOLDEN["legal"]}
    assert source_legal == golden_legal
    assert set(_TRANSITIONS) | set(ACTIONS.values()) == set(STATES)
    assert GOLDEN["shape"]["default_retry_budget"] == DEFAULT_RETRY_BUDGET
