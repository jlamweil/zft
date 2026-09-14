"""C-42: oracle campaign — the oracle pipeline property-tested on generated specs.

The corpus (tests/unit/oracle_spec_gen.py, seed 20260907) is 239 specs — 222
accepted (every one ground-truth-verified at build time: true oracle satisfies
the predicate over its finite domains; its mutant does not) and 17 typed
negatives. Each accepted spec runs the full battery:

  V1 EARS statement parses            V5 oracle symbol closure (exec'd module)
  V2 predicate compiles, stable       V6 semantic truth (faithful all_ runtime)
  V3 binder strategies resolve+draw   V7 mutant killed at the semantic layer
  V4 oracle renders, byte-stable      V8 rendered suite byte-stable
                                      V9 render-exec (see below)

Known findings are pinned with teeth (campaign 2026-09-07, see
jobs/oracle-spec-campaign/REPORT.md):

  F1 (FIXED) predicate_symbols now tracks prime desugaring (v' -> next_v).
  F2b (FIXED) render_property_test no longer emits a bare `from oracle import`
      for clauses with no oracle-owned symbols.
  F2 (CLOSED 2026-09-12) Hypothesis IS the top-level forall: render elides the
      compiled `(all_([names], lambda ...))` wrapper and quantified suites
      execute end-to-end — green under the true oracle, killed at a
      generator-proven violating draw under the mutant. The elision is
      domain-faithful: quantified @given binders draw the spec's own domains
      (st.sampled_from, V3), the exact universe the generator proved — name
      conventions like st.integers() would assert a stronger universal and
      die on out-of-domain draws. A quantifier below the top level
      (top-level exists, nesting) is typed-rejected at render: sampling
      cannot prove existence, and no runtime owns nesting.
Body-only specs (explicit binders, no quantifier) execute end-to-end: green
under the true oracle, falsified under the mutant oracle.
"""
import keyword
import re
import sys
from itertools import product
from pathlib import Path

import pytest
from oracle_spec_gen import _oracle_ns, _truth, generate_specs

from traceagent.codegen.property_gen import (
    PropertyTestSpec,
    binder_strategies,
    elide_top_level_forall,
    render_property_test,
)
from traceagent.dsl.ears import parse_statement
from traceagent.dsl.oracle import OracleError, generate_oracle, predicate_symbols
from traceagent.dsl.predicate import ParseError, compile_predicate
from traceagent.dsl.strategies import StrategyError, strategy_for

SPECS = generate_specs()
POSITIVES = [s for s in SPECS if s.expect == "ok"]
NEGATIVES = [s for s in SPECS if s.expect != "ok"]

_IDENT_RE = re.compile(r"[A-Za-z_]\w*")


def _free_symbols(py: str, binders: dict) -> set[str]:
    """Names the compiled predicate needs at runtime beyond the binders and
    the quantifier machinery — i.e. what the oracle module must provide."""
    return ({n for n in _IDENT_RE.findall(py)}
            - set(binders)
            - {"all_", "CLAUSES"}
            - set(keyword.kwlist))


@pytest.mark.parametrize("source", sorted({
    src for s in POSITIVES for src in
    (list(s.explicit_binders.values()) or ["convention"])
}), ids=lambda s: s[:40])
def test_campaign_strategy_sources_draw(source):
    """Every distinct binder strategy the campaign renders is a real,
    drawable Hypothesis strategy."""
    from hypothesis import find
    from hypothesis import settings as hyp_settings
    from hypothesis import strategies as st

    if source == "convention":
        return  # convention-resolved binders are drawn via V3 in-battery
    expr = compile(f"lambda st: {source}", "<campaign-binder>", "eval")
    strategy = eval(expr)(st)  # noqa: S307 — repo-generated strategy source
    find(strategy, lambda _: True,
         settings=hyp_settings(max_examples=5, deadline=None, derandomize=True,
                               database=None))


def _exec_rendered(spec, rendered: str, oracle_dir: Path, impls: dict) -> dict:
    """Exec the rendered suite with `impls` provisioned as the oracle module.

    Each exec gets its own directory: overwriting oracle.py in one directory
    within a mtime tick serves the stale cached module from the importer."""
    oracle_src = generate_oracle(spec.alias, impls, spec.producer_terms)
    oracle_dir.mkdir(parents=True, exist_ok=True)
    (oracle_dir / "oracle.py").write_text(oracle_src)
    sys.path.insert(0, str(oracle_dir))
    sys.modules.pop("oracle", None)
    try:
        ns: dict = {"__name__": f"campaign_{spec.sid}"}
        exec(compile(rendered, f"<{spec.sid}>", "exec"), ns)  # noqa: S102
        return ns
    finally:
        sys.path.remove(str(oracle_dir))
        sys.modules.pop("oracle", None)


def _battery(spec, tmp_path: Path) -> None:
    # V1: the EARS surface statement parses into a known form
    parts = parse_statement(spec.statement)
    assert parts["type"] in {"WHEN", "IF", "WHILE", "WHERE", "UBIQUITOUS"}

    # V2: the predicate compiles, and compiles stably
    py = compile_predicate(spec.predicate)
    assert py == compile_predicate(spec.predicate)

    # V3: every binder resolves to a strategy (explicit generator wins)
    if spec.explicit_binders:
        binders = dict(spec.explicit_binders)
        for name in binders:
            strategy_for(name, spec.check)  # typed StrategyError would fail the spec
    else:
        # Typed half: each quantified binder must resolve under the name
        # conventions (StrategyError would fail the spec). F2 close soundness
        # half: the rendered @given draws from the spec's own domains — the
        # exact universe the generator proved — because convention strategies
        # (st.integers() for scalar names) assert a stronger universal than
        # the clause states and die on out-of-domain draws (CAMP-INV-191:
        # t / 1 == t holds on [-20..20] but t / 1 is inexact at 2**53 + 1).
        binders = {name: f"st.sampled_from({spec.domains[name]!r})"
                   for name in binder_strategies(py, spec.check)}

    # V4: the oracle renders deterministically and compiles
    symbols = predicate_symbols(spec.predicate)
    src = generate_oracle(spec.alias, spec.oracle_terms, spec.producer_terms,
                          symbols=symbols)
    assert src == generate_oracle(spec.alias, spec.oracle_terms,
                                  spec.producer_terms, symbols=symbols)
    compile(src, "<oracle>", "exec")

    # V5: symbol closure — the rendered module defines everything the
    # predicate needs (prime desugaring included; F1 regression)
    free = _free_symbols(py, binders)
    oracle_ns: dict = {}
    exec(compile(src, "<oracle>", "exec"), oracle_ns)  # noqa: S102
    missing = sorted(n for n in free if n not in oracle_ns)
    assert not missing, f"oracle module does not define: {missing}"

    # V6/V7: semantic truth under the faithful all_ runtime; the mutant dies
    assert _truth(spec, spec.oracle_terms, py) is True
    if spec.mutant_terms:
        assert _truth(spec, {**spec.oracle_terms, **spec.mutant_terms}, py) is False

    # V8/V9: the rendered suite. F2 close (2026-09-12): a top-level forall
    # elides to the @given body and executes end-to-end; a quantifier below
    # the top level (top-level exists) is typed-rejected at render.
    test_name = f"test_{re.sub(r'\W', '_', spec.alias)}"
    if spec.explicit_binders:
        # V8/V9a: body-only specs — stable source; green under the true
        # oracle; under the mutant, the suite fails on the generator-proven
        # kill input (st.just pins the draw, so the kill is deterministic,
        # not stochastic)
        pts = PropertyTestSpec(alias=spec.alias, predicate_py=py, binders=binders,
                               oracle_src=src, oracle_symbols=sorted(free),
                               producer_imports="", examples=40)
        rendered = render_property_test(pts)
        assert rendered == render_property_test(pts)
        green = _exec_rendered(spec, rendered, tmp_path / "green", spec.oracle_terms)
        green[test_name]()  # must not raise
        kill_binders = {b: f"st.just({spec.kill_input[b]!r})"
                        for b in spec.explicit_binders}
        kill_spec = PropertyTestSpec(alias=spec.alias, predicate_py=py,
                                     binders=kill_binders, oracle_src=src,
                                     oracle_symbols=sorted(free),
                                     producer_imports="", examples=1)
        killed = _exec_rendered(spec, render_property_test(kill_spec),
                                tmp_path / "kill",
                                {**spec.oracle_terms, **spec.mutant_terms})
        with pytest.raises(Exception) as excinfo:
            killed[test_name]()
        assert "CONTRACT VIOLATED" in str(excinfo.value)
    else:
        try:
            body = elide_top_level_forall(py)
        except StrategyError:
            # V9b-exists: a quantifier without a suite runtime (top-level
            # exists — sampling cannot prove it — or nesting) is rejected
            # loudly at render, never a NameError on first draw (the old F2
            # failure mode). This is the designed boundary, pinned per spec.
            pts = PropertyTestSpec(alias=spec.alias, predicate_py=py,
                                   binders=binders, oracle_src=src,
                                   oracle_symbols=sorted(free),
                                   producer_imports="", examples=40)
            with pytest.raises(StrategyError, match="no runtime"):
                render_property_test(pts)
            return
        # V8: stable source for the elidable (top-level forall) spec
        pts = PropertyTestSpec(alias=spec.alias, predicate_py=py, binders=binders,
                               oracle_src=src, oracle_symbols=sorted(free),
                               producer_imports="", examples=40)
        rendered = render_property_test(pts)
        assert rendered == render_property_test(pts)
        # V9b-green: the elided suite holds under the real engine — the @given
        # binders draw exactly the spec's domains (V3), so the suite's
        # universal is the one the generator proved, not a stronger one
        green = _exec_rendered(spec, rendered, tmp_path / "green", spec.oracle_terms)
        green[test_name]()  # must not raise
        if spec.mutant_terms:
            # V9b-kill: the mutant dies at its proven violating domain point
            # (st.just pins the draw — deterministic, like V9a)
            kill_input = _first_violation_quantified(
                spec, body, binders, {**spec.oracle_terms, **spec.mutant_terms})
            kill_binders = {b: f"st.just({v!r})" for b, v in kill_input.items()}
            kill_spec = PropertyTestSpec(alias=spec.alias, predicate_py=py,
                                         binders=kill_binders, oracle_src=src,
                                         oracle_symbols=sorted(free),
                                         producer_imports="", examples=1)
            killed = _exec_rendered(spec, render_property_test(kill_spec),
                                    tmp_path / "kill",
                                    {**spec.oracle_terms, **spec.mutant_terms})
            with pytest.raises(Exception) as excinfo:
                killed[test_name]()
            assert "CONTRACT VIOLATED" in str(excinfo.value)


def _first_violation_quantified(spec, body: str, binders: dict, impls: dict) -> dict:
    """First domain combo where the elided body fails under `impls` — the
    quantified families' deterministic kill draw (the analogue of the
    generator's _first_violation for body-only specs)."""
    ns = _oracle_ns(spec, impls)
    names = list(binders)
    for combo in product(*(spec.domains[n] for n in names)):
        scope = dict(ns)
        scope.update(zip(names, combo))
        if not eval(body, scope):  # noqa: S307 — repo-generated body + oracle
            return dict(zip(names, combo))
    raise AssertionError(f"{spec.sid}: mutant has no violating domain point")


@pytest.mark.parametrize("spec", POSITIVES, ids=lambda s: s.sid)
def test_campaign_positive_spec(spec, tmp_path):
    _battery(spec, tmp_path)


@pytest.mark.parametrize("spec", NEGATIVES, ids=lambda s: s.sid)
def test_campaign_negative_spec(spec):
    """Negative specs fail at their typed boundary — never later, never
    with a stray exception."""
    if spec.expect in ("parse_error", "unlexable"):
        with pytest.raises(ParseError):
            compile_predicate(spec.predicate)
    elif spec.expect == "strategy_error":
        py = compile_predicate(spec.predicate)  # the predicate itself is fine
        with pytest.raises(StrategyError):
            binder_strategies(py, spec.check)
    elif spec.expect == "oracle_error":
        py = compile_predicate(spec.predicate)
        with pytest.raises(OracleError):
            generate_oracle(spec.alias, spec.oracle_terms, spec.producer_terms,
                            symbols=predicate_symbols(spec.predicate))
    else:  # pragma: no cover — generator contract
        pytest.fail(f"unknown negative expectation: {spec.expect}")


def test_campaign_scope_contract():
    """The campaign stays a campaign: 200+ accepted specs, every sid unique,
    positives distinguished from typed negatives."""
    assert len(POSITIVES) >= 200, "campaign contract: at least 200 accepted specs"
    assert len(POSITIVES) + len(NEGATIVES) == len(SPECS) == len({s.sid for s in SPECS})
    body_only = [s for s in POSITIVES if s.explicit_binders]
    assert body_only, "executable body-only family went missing"
    assert all(s.mutant_terms for s in body_only), "every body-only spec must kill a mutant"


# --- F1 regression: prime desugaring is visible to symbol extraction ---------
# (campaign 2026-09-07: predicate_symbols('...t\'...') missed next_t, so a
# prime clause rendered an oracle without next_t and NameError'd at runtime)

def test_f1_fixed_prime_symbols_reach_generate_oracle():
    from traceagent.dsl.oracle import OracleError as OE

    prop = "forall t: t'(t) == t + 1"
    assert "next_t" in predicate_symbols(prop)
    with pytest.raises(OE, match="next_t"):
        generate_oracle(alias="CAMP-PRIME", oracle_terms={}, producer_terms=["t"],
                        symbols=predicate_symbols(prop))
    src = generate_oracle(alias="CAMP-PRIME",
                          oracle_terms={"next_t": "def next_t(t):\n    return t + 1\n"},
                          producer_terms=["t"], symbols=predicate_symbols(prop))
    assert "def next_t(t):" in src


# --- F2b regression: no bare `from oracle import ` when nothing is owned -----

def test_f2b_fixed_empty_symbol_render_compiles():
    from traceagent.codegen.property_gen import PropertyTestSpec as PTS

    rendered = render_property_test(PTS(
        alias="CAMP-PURE", predicate_py=compile_predicate("forall x: x + 0 == x"),
        binders={"x": "st.integers()"}, oracle_src="", oracle_symbols=[],
        producer_imports="", examples=10))
    assert "from oracle import " not in rendered  # no bare import
    compile(rendered, "<rendered>", "exec")
