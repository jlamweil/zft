"""Fuzzed parser/oracle/strategies properties (DSL surface).

Companion to tests/unit/test_attest_fuzz.py (same convention): the golden
tables pin hand-picked accepts/rejects; these properties assert the same
contracts hold for *arbitrary* inputs. Row ids are stable (DSL-FUZZ-n) so a
campaign run can be triaged against this file.

    DSL-FUZZ-1  constructed-grammar EARS statements always parse; fields match
                construction; canonical reassembly is a parse fixed point
    DSL-FUZZ-2  arbitrary text: parse to dict-or-EarsError, layered diagnostic,
                pure (same input twice -> same result)
    DSL-FUZZ-3  non-str statement -> TypeError, never anything else
    DSL-FUZZ-4  arbitrary DSL source: accept => output compiles as an eval
                expression and invents no identifiers beyond input ∪ reserved
    DSL-FUZZ-5  arbitrary text: ParseError-or-result, never an untyped crash
                (deep nesting included)
    DSL-FUZZ-6  scalar subset: compiled DSL evaluates identically to the same
                source evaluated as Python (precedence/associativity oracle)
    DSL-FUZZ-7  generate_oracle: deterministic bytes, executable module, exact
                missing-symbols message, typed (TypeError/OracleError) garbage
    DSL-FUZZ-8  cross-module: a predicate that compiles always has an oracle
                renderable over predicate_symbols(producers=[])
    DSL-FUZZ-9  strategy_for: total/deterministic over arbitrary binder names,
                every hit compiles, evaluates to a SearchStrategy and draws;
                explicit check.generator always wins; non-str/Mapping -> TypeError
    DSL-FUZZ-10 cross-surface: binder_strategies extracts exactly the bound
                variables and the rendered property module compiles
"""

import keyword
import re

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from traceagent.dsl.ears import EarsError, parse_statement
from traceagent.dsl.oracle import OracleError, generate_oracle, predicate_symbols
from traceagent.dsl.predicate import ParseError, compile_predicate
from traceagent.dsl.strategies import StrategyError, strategy_for

_HYP = settings(
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
        HealthCheck.data_too_large,
    ],
)

# --- shared generators -------------------------------------------------------

_WORDS = st.characters(codec="utf-8", categories=("L", "N"))
_CLAUSE_CHARS = st.characters(
    codec="utf-8", categories=("L", "N", "Z", "P", "S"), exclude_characters=",.\""
)
# structural separators of the EARS surface: ',' ends the trigger, '.' ends
# the statement, '"' would break nothing but is excluded to keep excerpts tame.


@st.composite
def _ears_statements(draw):
    """Well-formed EARS statements plus the fields they must parse back to."""
    use_trigger = draw(st.booleans())
    trigger_word = draw(st.sampled_from(["WHEN", "IF", "WHILE", "WHERE"]))
    modal = draw(st.sampled_from(["SHALL", "MUST"]))

    def clause_text(min_size):
        head = draw(_WORDS)
        tail = draw(st.text(_CLAUSE_CHARS, min_size=max(min_size - 1, 0), max_size=30))
        return head + tail

    if use_trigger:
        trigger = clause_text(1)  # first char is a word char => has alnum
        head = f"{trigger_word} {trigger}, THE SYSTEM {modal} "
        kind, trig = trigger_word, trigger
    else:
        head = f"THE SYSTEM {modal} "
        kind, trig = "UBIQUITOUS", None
    response = clause_text(1)
    statement = head + response + draw(st.sampled_from(["", "."]))
    return statement, {
        "type": kind,
        "trigger": trig,
        "modal": modal,
        "response": response.strip().rstrip(".") or response,
    }


# A DSL fragment generator over a fixed identifier pool: rich enough to reach
# every parser branch (quantifiers in all binder forms, implication, membership,
# primes, set-builder/literal, arithmetic, call chains), shallow enough to stay fast.
_DSL_NAMES = ["t", "x", "v", "rows", "name", "flag", "expired", "err", "CLAUSES"]


@st.composite
def _dsl_exprs(draw, depth=3):
    roll = draw(st.integers(0, 12)) if depth > 0 else draw(st.integers(0, 4))
    if roll <= 1:
        return draw(st.sampled_from(_DSL_NAMES))
    if roll == 2:
        return draw(st.sampled_from(_DSL_NAMES)) + "'"
    if roll == 3:
        return str(draw(st.integers(0, 99)))
    if roll == 4:
        return draw(st.sampled_from(_DSL_NAMES))
    # calls/attribute chains only attach to names/primes: the grammar routes
    # them through suffix_name/call_chain, not arbitrary sub-expressions
    # (parenthesized groups take no call chain; primes take calls, not dots).
    n = draw(st.sampled_from(_DSL_NAMES))
    if roll == 5:  # call on a name or prime, 1-2 args
        args = draw(st.lists(_dsl_exprs(depth - 1), min_size=1, max_size=2))
        head = n + ("'" if draw(st.booleans()) else "")
        return f"{head}({', '.join(args)})"
    if roll == 6:  # attribute access on a plain name
        return f"{n}.{draw(st.sampled_from(_DSL_NAMES))}"
    a = draw(_dsl_exprs(depth - 1))
    if roll == 7:
        return f"not ({a})"
    if roll == 8:
        return f"({a}) {draw(st.sampled_from(['and', 'or']))} ({draw(_dsl_exprs(depth - 1))})"
    if roll == 9:
        op = draw(st.sampled_from(["<", ">", "<=", ">=", "==", "!="]))
        return f"{a} {op} {draw(_dsl_exprs(depth - 1))}"
    if roll == 10:
        op = draw(st.sampled_from(["+", "-", "*", "/"]))
        return f"({a} {op} {draw(_dsl_exprs(depth - 1))})"
    if roll == 11:  # quantifier, all binder forms (pair binders: distinct vars —
        # duplicate binders are a degenerate rejection class, not an accept case)
        q = draw(st.sampled_from(["forall", "exists"]))
        a, b = draw(st.lists(st.sampled_from(_DSL_NAMES[:6]), min_size=2,
                             max_size=2, unique=True))
        binder = draw(
            st.sampled_from(
                [
                    a,
                    f"{a} in rows",
                    f"pairs ({a}, {b})",
                ]
            )
        )
        return f"{q} {binder}: {draw(_dsl_exprs(depth - 1))}"
    # roll == 12: set-builder or set literal
    var = draw(st.sampled_from(_DSL_NAMES[:6]))
    if draw(st.booleans()):
        return f"{{{var} | {draw(_dsl_exprs(depth - 1))}}}"
    # set-literal elements parse at sum() precedence (corpus shape: bare names)
    items = ", ".join(draw(st.lists(st.sampled_from(_DSL_NAMES + ["0", "1"]),
                                    min_size=2, max_size=4, unique=True)))
    return f"{{{items}}}"


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_COMPILER_RESERVED = {
    "all_", "member_of", "lambda", "not", "and", "or", "CLAUSES",
    # set-builder emission shape: "{ c for c in CLAUSES if P(c) }"
    "for", "in", "if",
}


# --- EARS parser -------------------------------------------------------------

@settings(_HYP)
@given(_ears_statements())
def test_fuzz_ears_constructed_statements_round_trip(pick):
    """DSL-FUZZ-1: every well-formed statement parses to exactly the fields it
    was built from (modulo the documented dot/whitespace normalization), and
    the canonical reassembly of the parsed fields is itself a fixed point."""
    statement, expected = pick
    result = parse_statement(statement)
    assert result == expected
    assert parse_statement(statement) == result  # purity
    canonical = statement.rstrip(".") + "."
    assert parse_statement(canonical) == expected


@settings(_HYP)
@given(st.text(max_size=200))
def test_fuzz_ears_arbitrary_text_is_dict_or_typed_diagnosed_error(stmt):
    """DSL-FUZZ-2: arbitrary text either parses or raises exactly EarsError
    carrying the layered diagnostic (problem + expected grammar + hint)."""
    try:
        result = parse_statement(stmt)
    except EarsError as e:
        msg = str(e)
        assert "not an EARS statement" in msg
        assert "expected:" in msg and "hint:" in msg
    else:
        assert set(result) == {"type", "trigger", "modal", "response"}
        assert result["modal"] in ("SHALL", "MUST")
        assert result["type"] in ("WHEN", "IF", "WHILE", "WHERE", "UBIQUITOUS")
        assert isinstance(result["response"], str) and result["response"]
        assert parse_statement(stmt) == result


@settings(_HYP)
@given(st.one_of(st.integers(), st.binary(max_size=32), st.none(), st.booleans(),
                 st.lists(st.integers(), max_size=3)))
def test_fuzz_ears_non_string_statement_is_type_error(bad):
    """DSL-FUZZ-3: non-str input is a TypeError naming the argument."""
    with pytest.raises(TypeError, match="statement must be str"):
        parse_statement(bad)  # type: ignore[arg-type]


# --- predicate compiler ------------------------------------------------------

_ALLOWED_IDENTS = set(_DSL_NAMES) | _COMPILER_RESERVED


@settings(_HYP)
@given(_dsl_exprs())
def test_fuzz_predicate_accept_compiles_and_invents_no_identifiers(src):
    """DSL-FUZZ-4: every accepted predicate compiles to an eval-expression
    whose identifiers all come from the source (or the documented emitted
    vocabulary: all_/member_of/lambda/not/and/or/CLAUSES, next_<v> for primes).
    The compiler may never invent a name it was not given."""
    py = compile_predicate(src)
    compile(py, "<fuzz>", "eval")  # external pin of the compile guarantee
    invented = set(_IDENT_RE.findall(py)) - _ALLOWED_IDENTS - {
        "next_" + n for n in _DSL_NAMES
    }
    assert not invented, f"compiler invented {invented} for {src!r} -> {py!r}"


@settings(_HYP)
@given(st.one_of(st.text(max_size=120), _dsl_exprs()))
def test_fuzz_predicate_arbitrary_input_is_typed_parseerror_or_result(src):
    """DSL-FUZZ-5: any input yields a result or exactly ParseError — never an
    IndexError/RecursionError/etc. leak; deep nesting degrades to ParseError."""
    deep = "(" * 400 + "x" + ")" * 400
    for probe in (src, deep):
        try:
            py = compile_predicate(probe)
        except ParseError:
            continue
        assert isinstance(py, str)
        compile_predicate(probe) == py  # purity (no exception)


@st.composite
def _scalar_exprs(draw):
    """Python-interpretable DSL subset over nonneg ints: arith chains (+ - * /),
    one comparison, boolean combination — valid Python verbatim, so the plain
    interpreter is an independent reference for the compiled output."""
    def arith():
        left = str(draw(st.integers(0, 9)))
        for _ in range(draw(st.integers(0, 3))):
            op = draw(st.sampled_from(["+", "-", "*", "/"]))
            right = draw(st.integers(1, 9)) if op == "/" else draw(st.integers(0, 9))
            left = f"({left} {op} {right})"
        return left

    def boolean(depth):
        if depth > 0 and draw(st.booleans()):
            op = draw(st.sampled_from(["and", "or"]))
            return f"({boolean(depth - 1)}) {op} ({boolean(depth - 1)})"
        if draw(st.booleans()):
            return f"not ({boolean(depth - 1) if depth > 0 else arith()})"
        op = draw(st.sampled_from(["<", "<=", ">", ">=", "==", "!="]))
        return f"{arith()} {op} {arith()}"

    return boolean(2)


@settings(_HYP)
@given(_scalar_exprs())
def test_fuzz_scalar_predicates_match_python_semantics(src):
    """DSL-FUZZ-6 (precedence oracle): on the scalar subset the DSL source is
    also valid Python; the compiled output must evaluate to the same value.
    Catches precedence, associativity, and emission bugs — except chained
    comparisons, which the generator does not produce (DSL is left-assoc by
    convention, Python chains)."""
    py = compile_predicate(src)
    assert eval(py, {"__builtins__": {}}, {}) == eval(src, {"__builtins__": {}}, {})  # noqa: S307


# --- oracle ------------------------------------------------------------------

_ORACLE_IMPLS = [
    "def {n}(x):\n    return x\n",
    "def {n}():\n    return True\n",
    "{n}_limit = 10\ndef {n}(v):\n    return v < {n}_limit\n",
    "def {n}(a, b=0):\n    return (a or b)\n",
]


@settings(_HYP)
@given(
    st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=0x2FFF,
                                   exclude_characters="\x00"),
            min_size=1, max_size=24),
    st.dictionaries(
        st.from_regex(r"[a-z][a-z_0-9]{0,11}", fullmatch=True),
        st.sampled_from(_ORACLE_IMPLS),
        min_size=1,
        max_size=4,
    ),
    st.lists(st.from_regex(r"[a-z][a-z_0-9]{0,11}", fullmatch=True),
             max_size=3, unique=True),
    st.data(),
)
def test_fuzz_oracle_render_deterministic_executable_exact_message(alias, terms, producers, data):
    """DSL-FUZZ-7: deterministic bytes; a rendered oracle execs as a module and
    defines every term; missing-symbol errors name exactly the sorted missing
    set; validation failures stay typed (TypeError/OracleError)."""
    symbols = data.draw(st.sets(st.from_regex(r"[a-z][a-z_0-9]{0,11}", fullmatch=True),
                                max_size=3)) if data.conjecture_data.draw_boolean(0.5) else None
    impls = {n: impl.format(n=n) for n, impl in terms.items()}
    kwargs = dict(alias=alias, oracle_terms=impls, producer_terms=producers)
    if symbols is not None:
        kwargs["symbols"] = symbols
    try:
        first = generate_oracle(**kwargs)
    except (TypeError, OracleError) as e:
        second_exc = None
        try:
            generate_oracle(**kwargs)
        except (TypeError, OracleError) as e2:
            second_exc = e2
        assert second_exc is not None and str(second_exc) == str(e)
        return
    second = generate_oracle(**kwargs)
    assert first == second  # determinism: byte-identical rendered module
    exec(first, {})  # must load as a module — noqa: S102
    assert f'Oracle for clause {alias}' in first
    for name in impls:
        assert re.search(rf"^def {name}\(|^{name}_limit", first, re.M)
    if symbols is not None:
        producer_set = set(producers)
        missing = sorted(set(symbols) - producer_set - set(impls))
        if missing:
            with pytest.raises(OracleError) as ei:
                generate_oracle(**{**kwargs, "oracle_terms": {
                    k: v for k, v in impls.items() if k not in missing}})
            assert str(ei.value) == f"oracle missing implementations for symbols: {missing}"


@settings(_HYP)
@given(_dsl_exprs())
def test_fuzz_compiled_predicate_has_renderable_oracle(src):
    """DSL-FUZZ-8 (cross-module): whatever compiles as DSL can always get its
    oracle rendered from predicate_symbols alone — symbol extraction and oracle
    validation can never disagree on the pipeline path."""
    try:
        compile_predicate(src)
    except ParseError:
        pytest.skip("not a compiling predicate")
    syms = predicate_symbols(src)
    assert all(not keyword.iskeyword(s) for s in syms), \
        f"predicate_symbols leaked a keyword for {src!r}: {syms}"
    src_rendered = generate_oracle(
        "FUZZ", {s: f"def {s}(*a):\n    return True\n" for s in syms}, [],
    )
    exec(src_rendered, {})
    for s in syms:
        assert re.search(rf"^def {s}\(", src_rendered, re.M)


# --- strategies --------------------------------------------------------------

_MORPHEMES = [
    "t", "x", "num", "count", "ver", "name", "title", "text", "stmt", "is_", "has_",
    "flag", "enabled", "rows", "names", "matrix", "grid", "tensor", "cube", "edge",
    "edges", "arc", "graph", "adjacency", "points", "vectors", "coords", "records",
    "entries", "map", "mapping", "dict", "table", "grouped", "by_", "intervals",
    "ranges", "windows", "spans", "tags", "sets", "_set", "opt", "maybe", "nullable",
    "pair", "tuple", "coord", "tree", "nested", "payload", "json", "doc", "obj",
    "config", "attrs", "props", "fields", "orders", "s", "ing", "ness",
]
_BINDER_NAMES = st.one_of(
    st.builds(str.__add__, st.builds(str.__add__, st.sampled_from(_MORPHEMES),
                                     st.sampled_from(_MORPHEMES)),
              st.sampled_from(["", "s", "_id", "9"])),
    st.from_regex(r"[a-z][a-z_0-9]{0,15}", fullmatch=True),
)


@settings(_HYP)
@given(_BINDERS := _BINDER_NAMES)
def test_fuzz_strategy_for_total_deterministic_drawable(binder):
    """DSL-FUZZ-9a: strategy_for is total (StrategyError is the only failure),
    pure, and every hit is a real drawable SearchStrategy — over arbitrary
    morpheme combinations, not just the pinned names."""
    try:
        first = strategy_for(binder, {})
    except StrategyError as e:
        assert "route to judge" in str(e) or "invalid check.generator" in str(e)
        with pytest.raises(StrategyError):
            strategy_for(binder, {})  # rejection is deterministic too
        return
    assert strategy_for(binder, {}) == first
    import hypothesis.strategies as hst

    expr = compile(f"lambda st: {first}", f"<fuzz:{binder}>", "eval")
    strategy = eval(expr)(hst)  # noqa: S307
    assert isinstance(strategy, hst.SearchStrategy)
    strategy.validate()  # well-formed and drawable (validation does a draw)


@settings(_HYP)
@given(_BINDERS, st.sampled_from(["st.just(42)", "st.none()", "st.integers(max_value=7)"]))
def test_fuzz_strategy_for_explicit_generator_always_wins(binder, generator):
    """DSL-FUZZ-9b: check.generator is returned verbatim for ANY binder name —
    conventions never shadow an explicit generator."""
    assert strategy_for(binder, {"generator": generator}) == generator


@settings(_HYP)
@given(st.one_of(st.integers(), st.binary(max_size=8), st.none(), st.lists(st.integers())),
       st.one_of(st.integers(), st.lists(st.text()), st.none()))
def test_fuzz_strategy_for_typed_errors(bad_binder, bad_check):
    """DSL-FUZZ-9c: type violations are TypeErrors naming the argument — never
    StrategyError or an AttributeError from the regex path."""
    if isinstance(bad_binder, str) or isinstance(bad_check, (dict,)):
        return  # this property only sweeps non-contract types
    with pytest.raises(TypeError):
        strategy_for(bad_binder, {})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        strategy_for("t", bad_check)  # type: ignore[arg-type]


# --- cross-surface codegen ---------------------------------------------------

_CONVENTION_BINDERS = ["t", "rows", "name", "orders", "count", "flag", "matrix", "coords"]


@st.composite
def _quantified_predicates(draw):
    n = draw(st.integers(1, 3))
    binders = draw(st.lists(st.sampled_from(_CONVENTION_BINDERS), min_size=n, max_size=n,
                            unique=True))
    body = f"{binders[0]} > {draw(st.integers(0, 9))}"
    return f"forall {', '.join(binders)}: {body}", binders


@settings(_HYP)
@given(_quantified_predicates())
def test_fuzz_binder_extraction_matches_bound_variables(pick):
    """DSL-FUZZ-10 (cross-surface): binder_strategies extracts exactly the
    quantifier's bound variables, resolves each through strategy_for, and the
    rendered property module compiles — parser × strategies × codegen agree."""
    from traceagent.codegen.property_gen import (
        PropertyTestSpec,
        binder_strategies,
        render_property_test,
    )

    src, binders = pick
    py = compile_predicate(src)
    resolved = binder_strategies(py, {})
    assert list(resolved) == binders
    spec = PropertyTestSpec(
        alias="FUZZ-X",
        predicate_py=py,
        binders=resolved,
        oracle_src="def expired(t):\n    return t > 100\n",
        oracle_symbols=["expired"],
        producer_imports="",
        examples=10,
    )
    module = render_property_test(spec)
    compile(module, "<fuzz:render>", "exec")
    for b in binders:
        assert f"{b}=" in module
