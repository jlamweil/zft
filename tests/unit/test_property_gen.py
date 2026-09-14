"""C-13: property codegen — oracle-bound Hypothesis tests from compiled predicates.

The V2 regression fixture lives here: an oracle-divergent mutant must be KILLED
(the property references the oracle, not the producer's own predicate function).
Rendered output and binder->strategy mapping are additionally pinned by the
golden fixture tests/golden/property_codegen_fixtures.json.
"""
import json
from pathlib import Path

import pytest

from traceagent.codegen.property_gen import (
    PropertyTestSpec,
    binder_strategies,
    render_property_test,
)
from traceagent.dsl.strategies import StrategyError
from traceagent.gates.runners.pytest_runner import run_pytest

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1]
     / "golden" / "property_codegen_fixtures.json").read_text())

ORACLE = '''"""Oracle: contract-side reference."""
def expired(t):
    return t > 100

def err(code):
    return ("Err", code)
'''

MODULE_CORRECT = '''def expired(t):
    return t > 100

def err(code):
    return ("Err", code)

def validate(t):
    if expired(t):
        return err("Unauthorized")
    if t < 0:
        return err("Invalid")
    return ("Ok", t)
'''

MODULE_MUTANT = MODULE_CORRECT.replace("t > 100", "t < 100")  # oracle-divergent


def _spec() -> PropertyTestSpec:
    return PropertyTestSpec(
        alias="GATE-INV-01",
        predicate_py='(not (expired(t))) or (validate(t) == err("Unauthorized"))',
        binders={"t": "st.integers()"},
        oracle_src=ORACLE,
        oracle_symbols=["expired", "err"],
        producer_imports="from module import validate",
        examples=200,
    )


def test_rendered_source_compiles():
    src = render_property_test(_spec())
    compile(src, "<gen>", "exec")


def test_rendered_source_binds_oracle_not_producer():
    src = render_property_test(_spec())
    assert "from oracle import" in src and "expired" in src.split("from oracle import")[1].splitlines()[0]  # noqa: E501
    assert "from module import validate" in src
    assert "assert" in src


def test_generated_suite_passes_on_correct_module(tmp_path):
    src = render_property_test(_spec())
    (tmp_path / "oracle.py").write_text(ORACLE)
    (tmp_path / "module.py").write_text(MODULE_CORRECT)
    (tmp_path / "test_gen.py").write_text(src)
    result = run_pytest(tmp_path)
    assert result.ok, result.tail


def test_oracle_divergent_mutant_killed(tmp_path):
    """The V2 regression: producer predicates self-reference is now impossible."""
    src = render_property_test(_spec())
    (tmp_path / "oracle.py").write_text(ORACLE)
    (tmp_path / "module.py").write_text(MODULE_MUTANT)
    (tmp_path / "test_gen.py").write_text(src)
    result = run_pytest(tmp_path)
    assert result.ok is False, "oracle divergence must be caught (V2 lesson)"


# --- golden fixture (tests/golden/property_codegen_fixtures.json) ------------

@pytest.mark.parametrize("case", GOLDEN["render_cases"], ids=lambda c: c["name"])
def test_golden_render_matches_byte_for_byte(case):
    spec = PropertyTestSpec(**case["spec"])
    assert render_property_test(spec) == case["golden_source"]


@pytest.mark.parametrize("case", GOLDEN["render_cases"], ids=lambda c: c["name"])
def test_golden_render_compiles_and_binds_oracle(case):
    src = render_property_test(PropertyTestSpec(**case["spec"]))
    compile(src, "<golden>", "exec")
    assert "from oracle import" in src, "oracle binding is mandatory (D-CG)"


@pytest.mark.parametrize("case", GOLDEN["binder_cases"], ids=lambda c: c["name"])
def test_golden_binder_strategies(case):
    if "expected" in case:
        assert binder_strategies(case["predicate_py"], case["check"]) == case["expected"]
    else:
        with pytest.raises(StrategyError, match=case["error"]):
            binder_strategies(case["predicate_py"], case["check"])


# --- GATE-MUTATION-KILL (mut-dsl-codegen shard 2026-09-07 residual triage) ---

# GATE-MUTATION-KILL: the no-quantifier routing message is contractual
# (producer-facing diagnosis); an XX-wrapped variant passes a substring pin
# (binder_strategies 10)
def test_no_binder_message_byte_exact():
    with pytest.raises(StrategyError) as ei:
        binder_strategies("(not (a)) or (b)", {})
    assert str(ei.value) == "predicate has no quantifier binders — not a property clause"


# GATE-MUTATION-KILL: quote-stripping must not eat identifier characters —
# strip("XX'\"XX") strips X edges off a binder name and re-keys the strategy
# map (binder_strategies 14)
def test_binder_name_x_edges_survive_quote_strip():
    out = binder_strategies(
        "(all_(['X1'], lambda X1: ok(X1)))", {"generator": "st.integers()"})
    assert out == {"X1": "st.integers()"}
