"""Spec generator for the oracle campaign (C-42): seeded, deterministic.

Every accepted spec is ground-truth-verified at build time: the compiled
predicate must evaluate True over the spec's finite domains under the true
oracle, and False somewhere under the mutant oracle — a spec whose template
math does not kill its own mutant never leaves the generator, so the
campaign's green-run and mutant-kill verdicts mean something.

Families cover the DSL v1 grammar x binder vocabulary x oracle shapes:
thresholds, bands, membership, flags, rosters, prime (next-state), two-binder
relations, explicit check.generator, existentials, pure arithmetic, and
CLAUSES scans — plus typed-negative families (parse, judge routing, missing
oracle impl, unlexable literals).

`python tests/unit/oracle_spec_gen.py > specs.json` regenerates the corpus
artifact; the seed and the grids fully determine it.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from itertools import product

SEED = 20260907


@dataclass
class Spec:
    sid: str
    family: str
    alias: str
    statement: str  # EARS surface statement (parse-checked by the battery)
    predicate: str  # DSL v1 source
    oracle_terms: dict[str, str]
    producer_terms: list[str]
    check: dict
    domains: dict[str, list]
    mutant_terms: dict[str, str] = field(default_factory=dict)
    # body-only specs: explicit binder -> strategy source (no quantifier in the
    # predicate; the rendered @given draws the binders directly, so these are
    # the specs the rendered suite executes end-to-end)
    explicit_binders: dict[str, str] = field(default_factory=dict)
    # body-only mutants: the generator-proven violating binder assignment, so
    # the rendered-suite kill check is deterministic (feed it, watch it fail)
    kill_input: dict[str, object] = field(default_factory=dict)
    # "ok" | "parse_error" | "strategy_error" | "oracle_error" | "unlexable"
    expect: str = "ok"


def _all_runtime(domains: dict[str, list]):
    """Faithful `all_` runtime (same semantics as tests/unit/test_predicate.py):
    true iff the body holds for every binding of the named binders drawn from
    `domains` (empty product -> vacuously true)."""
    def all_(names, f):
        return all(f(*combo) for combo in product(*(domains[n] for n in names)))
    return all_


def _oracle_ns(spec: Spec, impls: dict[str, str]) -> dict:
    ns: dict = {"__builtins__": {"frozenset": frozenset, "set": set,
                                 "len": len, "bool": bool}}
    for name, impl in impls.items():
        exec(compile(impl, f"<{spec.sid}:{name}>", "exec"), ns)  # noqa: S102
    return ns


def _truth(spec: Spec, impls: dict[str, str], py: str | None = None) -> bool:
    """Evaluate a compiled predicate against an oracle built from `impls`.

    Quantified specs evaluate the whole expression under the faithful all_
    runtime; body-only specs are checked at every domain point (the rendered
    @given asserts each draw, so the ground truth is a universal reading).
    """
    from zft.dsl.predicate import compile_predicate

    ns = _oracle_ns(spec, impls)
    py = py or compile_predicate(spec.predicate)
    if not spec.explicit_binders:
        ns["all_"] = _all_runtime(spec.domains)
        return eval(py, ns)  # noqa: S307
    names = list(spec.explicit_binders)
    for combo in product(*(spec.domains[n] for n in names)):
        scope = dict(ns)
        scope.update(zip(names, combo))
        if not eval(py, scope):  # noqa: S307
            return False
    return True


def _first_violation(spec: Spec, impls: dict[str, str], py: str) -> dict:
    """The first domain point where the predicate fails under `impls` — the
    kill input, so the rendered-suite mutant check is deterministic."""
    from zft.dsl.predicate import compile_predicate

    ns = _oracle_ns(spec, impls)
    names = list(spec.explicit_binders)
    for combo in product(*(spec.domains[n] for n in names)):
        scope = dict(ns)
        scope.update(zip(names, combo))
        if not eval(py or compile_predicate(spec.predicate), scope):  # noqa: S307
            return dict(zip(names, combo))
    raise AssertionError(f"{spec.sid}: mutant has no violating input")


def _spec(sid, family, statement, predicate, oracle_terms, producer_terms,
          check, domains, mutant_terms=None, expect="ok",
          explicit_binders=None) -> Spec:
    return Spec(sid=sid, family=family, alias=sid, statement=statement,
                predicate=predicate, oracle_terms=oracle_terms,
                producer_terms=producer_terms, check=check, domains=domains,
                mutant_terms=mutant_terms or {}, expect=expect,
                explicit_binders=explicit_binders or {})


def _positive_specs() -> list[Spec]:
    specs: list[Spec] = []
    n = 0

    def add(**kw):
        nonlocal n
        n += 1
        specs.append(_spec(f"CAMP-INV-{n:03d}", **kw))

    # --- threshold: expired(t) := t > K; kills by broadening the antecedent
    # (DSL constants are non-negative: the v1 lexer has no unary minus)
    for i, k in enumerate([0, 1, 9, 10, 25, 50, 99, 100, 150, 200, 250, 333,
                           400, 500, 750, 1000]):
        for shape in ("implies", "not-or"):
            # parens are load-bearing: bare `not A or B` parses as not (A or B)
            body = (f"forall t: expired(t) => t > {k}" if shape == "implies"
                    else f"forall t: (not expired(t)) or (t > {k})")
            add(family="threshold",
                statement=f"WHEN a work item is expired past {k}, THE SYSTEM SHALL refuse it",
                predicate=body,
                oracle_terms={"expired": f"def expired(t):\n    return t > {k}\n"},
                producer_terms=["t"],
                check={},
                domains={"t": list(range(k - 40, k + 41))},
                mutant_terms={"expired": f"def expired(t):\n    return t > {k - 1}\n"})

    # --- band: in_band := LO <= c <= HI; mutant drops the upper bound
    # (HI lands in DSL text, so it stays non-negative; LO may be negative)
    for lo, hi in [(0, 10), (0, 50), (1, 99), (-10, 10), (-50, 5), (5, 6),
                   (10, 100), (-100, 100), (0, 1), (-1, 0), (25, 75), (7, 70),
                   (2, 3), (60, 65), (100, 200), (-7, 7)]:
        for shape in ("implies", "and-legal"):
            terms = {"in_band": f"def in_band(c):\n    return {lo} <= c <= {hi}\n"}
            if shape == "and-legal":
                terms["legal"] = "def legal(c):\n    return True\n"
            pred = (f"forall count: in_band(count) => count <= {hi}" if shape == "implies"
                    else f"forall count: in_band(count) and legal(count) => count <= {hi}")
            add(family="band",
                statement=f"WHILE a counter is in [{lo}, {hi}], THE SYSTEM SHALL accept increments",
                predicate=pred,
                oracle_terms=terms,
                producer_terms=["count"],
                check={},
                domains={"count": list(range(lo - 5, hi + 6))},
                mutant_terms={"in_band": f"def in_band(c):\n    return {lo} - 1 <= c\n"})

    # --- membership: allowed set + member_of runtime; mutant inverts it.
    # The antecedent is `listed`, a plain oracle predicate — DSL `in` compiles
    # to member_of, so a membership-on-both-sides predicate is invariant under
    # member_of inversion and no mutant could kill it.
    for i, members in enumerate([[0], [0, 1], [1, 2, 3], [-5, 5], [0, 7, 13],
                                 [2, 4, 6, 8], [11], [3, 17], [-1, 0, 1],
                                 [10, 20, 30, 40], [5], [0, 2]]):
        members_str = ", ".join(str(m) for m in members)
        extras = sorted({m + 1 for m in members} - set(members))
        universe = sorted(set(members) | set(extras) | {999})
        universe_str = ", ".join(str(m) for m in universe)
        terms = {"allowed": f"allowed = frozenset({{{members_str}}})\n",
                 "member_of": "def member_of(item, bag):\n    return item in bag\n",
                 "listed": "def listed(x):\n    return x in allowed\n"}
        for shape in ("implies", "not-or", "double-bag"):
            preds = {
                "implies": "forall x: listed(x) => member_of(x, allowed)",
                "not-or": "forall x: (not listed(x)) or (member_of(x, allowed))",
                "double-bag": ("forall x: listed(x) => member_of(x, allowed)"
                               " and member_of(x, universe)"),
            }
            shape_terms = dict(terms)
            if shape == "double-bag":
                shape_terms["universe"] = f"universe = frozenset({{{universe_str}}})\n"
            add(family="membership",
                statement=(f"WHEN a request cites allowed set {i}, "
                           "THE SYSTEM SHALL admit only its members"),
                predicate=preds[shape],
                oracle_terms=shape_terms,
                producer_terms=["x"],
                check={},
                domains={"x": sorted(set(members) | set(extras)) + [999]},
                mutant_terms={
                    "member_of": "def member_of(item, bag):\n    return item not in bag\n"})

    # --- flag: armed(b) := b is True; mutant pins it constant-true
    for i, impl in enumerate(["return b is True\n", "return b == True\n",
                              "return bool(b)\n", "return b\n"]):
        for binder in ("is_live", "is_armed"):
            add(family="flag",
                statement="WHEN the kill switch is engaged, THE SYSTEM SHALL halt the pipeline",
                predicate=f"forall {binder}: armed({binder}) => {binder}",
                oracle_terms={"armed": f"def armed(b):\n    {impl}"},
                producer_terms=[binder],
                check={},
                domains={binder: [True, False]},
                mutant_terms={"armed": "def armed(b):\n    return True\n"})

    # --- roster: text membership; mutant broadens the antecedent
    for i, people in enumerate([["alice"], ["alice", "bob"], ["bob", "carol"],
                                ["a", "b", "c", "d"], ["zoe"], ["maya", "raj"],
                                ["lin", "oz", "quinn"], ["dee"]]):
        people_str = ", ".join(f"'{p}'" for p in people)
        outsider = "carol" if "carol" not in people else "zed"
        terms = {"roster": f"roster = frozenset({{{people_str}}})\n",
                 "member_of": "def member_of(item, bag):\n    return item in bag\n",
                 "cleared": "def cleared(person):\n    return person in roster\n"}
        for shape in ("implies", "and-known", "not-or"):
            shape_terms = dict(terms)
            if shape == "and-known":
                shape_terms["known"] = "def known(person):\n    return len(person) > 0\n"
            pred = {
                "implies": "forall name: cleared(name) => member_of(name, roster)",
                "and-known": ("forall name: cleared(name) and known(name)"
                              " => member_of(name, roster)"),
                "not-or": "forall name: (not cleared(name)) or (member_of(name, roster))",
            }[shape]
            add(family="roster",
                statement=(f"WHERE a caller is cleared for roster {i}, "
                           "THE SYSTEM SHALL address them"),
                predicate=pred,
                oracle_terms=shape_terms,
                producer_terms=["name"],
                check={},
                domains={"name": sorted(set(people) | {outsider})},
                mutant_terms={
                    "cleared": (f"def cleared(person):\n"
                                f"    return person in roster or person == '{outsider}'\n")})

    # --- prime (next-state): call-position t'(t) desugars to next_t(t);
    # (bare t' desugars to a free next_t NAME — a function object compared to
    # an int — unsatisfiable by any oracle; see campaign report, finding F3)
    for i, step in enumerate([1, 2, 3, 5, 10, 25, 50, 100]):
        for shape in ("eq", "geq"):
            pred = (f"forall t: t'(t) == t + {step}" if shape == "eq"
                    else f"forall t: t'(t) >= t + {step}")
            add(family="prime",
                statement=f"WHEN the clock ticks, THE SYSTEM SHALL advance time by {step}",
                predicate=pred,
                oracle_terms={"next_t": f"def next_t(t):\n    return t + {step}\n"},
                producer_terms=["t"],
                check={},
                domains={"t": list(range(-10, 11))},
                # eq mutants upward; geq must mutate downward or it still holds
                mutant_terms={"next_t": (f"def next_t(t):\n    return t + {step + 1}\n"
                                         if shape == "eq" else
                                         f"def next_t(t):\n    return t + {step - 1}\n")})

    # --- two-binder relation; mutant drops the equality arm
    for lo, hi in [(0, 5), (-5, 5), (1, 20), (-20, -1), (0, 1), (-3, 3),
                   (10, 50), (-100, 100)]:
        for shape in ("implies", "or-not"):
            pred = ("forall t, count: ordered(t, count) => t <= count" if shape == "implies"
                    else "forall t, count: (not ordered(t, count)) or (t <= count)")
            add(family="two-binder",
                statement="IF a pair is ordered, THE SYSTEM SHALL preserve the first element first",
                predicate=pred,
                oracle_terms={"ordered": "def ordered(a, b):\n    return a <= b\n"},
                producer_terms=["t", "count"],
                check={},
                domains={"t": list(range(lo, hi + 1)), "count": list(range(lo, hi + 1))},
                mutant_terms={"ordered": "def ordered(a, b):\n    return a >= b\n"})

    # --- explicit check.generator wins over the convention band
    for limit in [10, 20, 30, 40, 45, 50, 55, 60, 75, 90]:
        add(family="explicit-generator",
            statement=(f"WHEN a version is versioned for limit {limit}, "
                       "THE SYSTEM SHALL cap it there"),
            predicate=f"forall ver: versioned(ver) => ver <= {limit}",
            oracle_terms={"versioned": f"def versioned(v):\n    return v <= {limit}\n"},
            producer_terms=["ver"],
            check={"generator": f"st.integers(0, {limit + 10})"},
            domains={"ver": list(range(0, limit + 11))},
            mutant_terms={"versioned": f"def versioned(v):\n    return v <= {limit + 10}\n"})

    # --- existential: true because the domain contains a witness
    for i, k in enumerate([0, 3, 5, 7, 12, 20, 40, 77, 100, 150]):
        add(family="exists",
            statement=f"WHEN any counter exceeds {k}, THE SYSTEM SHALL report overflow",
            predicate=f"exists count: count >= {k}",
            oracle_terms={},
            producer_terms=["count"],
            check={},
            domains={"count": list(range(k - 5, k + 6))})

    # --- pure arithmetic tautologies (no oracle terms at all)
    pure = [
        "forall t: t + 0 == t",
        "forall t: t - t == 0",
        "forall t: t * 1 == t",
        "forall t: t / 1 == t",
        "forall t: (t + 1) + 1 == t + 2",
        "forall t: t + 1 > t",
        "forall t: not t + 0 != t",
        "forall t: t * 2 - t == t",
    ]
    import re

    for i, pred in enumerate(pure):
        for binder in ("t", "x"):
            add(family="pure",
                statement="THE SYSTEM SHALL preserve elementary arithmetic",
                predicate=re.sub(r"\bt\b", binder, pred),
                oracle_terms={},
                producer_terms=[binder],
                check={},
                domains={binder: list(range(-20, 21))})
    for pred in ("exists x: x == x", "exists x: x + 0 == x",
                 "exists x: x - x == 0", "exists x: x * 1 == x",
                 "exists x: not x + 1 <= x"):
        add(family="pure-exists",
            statement="THE SYSTEM SHALL exhibit a satisfying arithmetic state",
            predicate=pred,
            oracle_terms={},
            producer_terms=["x"],
            check={},
            domains={"x": list(range(-3, 4))})

    # --- CLAUSES scan: in-domain binder over an oracle-provided clause set
    for i, approved in enumerate([[1], [1, 2], [2, 4, 6], [3], [5, 10], [7]]):
        members_str = ", ".join(str(m) for m in approved)
        extras = sorted({a + 1 for a in approved} - set(approved))
        add(family="clauses-scan",
            statement="WHEN a clause is scanned, THE SYSTEM SHALL approve only listed clauses",
            predicate="forall c in CLAUSES: approved(c)",
            oracle_terms={"CLAUSES": f"CLAUSES = {approved + extras}\n",
                          "approved": f"def approved(c):\n    return c in {{{members_str}}}\n"},
            producer_terms=["c"],
            # binder c has no convention — the explicit generator is the route
            check={"generator": f"st.sampled_from({list(approved)!r})"},
            # the compiled `forall c in CLAUSES` discards the in-clause; the
            # runtime iterates the supplied domain, which is the approved set
            domains={"c": list(approved)},
            mutant_terms={"approved": "def approved(c):\n    return c in {}\n"})

    # --- body-only: no quantifier; the rendered @given draws the binders
    # directly (sampled_from over the finite domain), so these specs execute
    # end-to-end: green under the true oracle, falsified under the mutant
    for k in (10, 50, 100, 250):
        add(family="body-only",
            statement=f"WHEN a work item is expired past {k}, THE SYSTEM SHALL refuse it",
            predicate=f"expired(t) => t > {k}",
            oracle_terms={"expired": f"def expired(t):\n    return t > {k}\n"},
            producer_terms=["t"], check={},
            domains={"t": list(range(k - 40, k + 41))},
            mutant_terms={"expired": f"def expired(t):\n    return t > {k - 1}\n"},
            explicit_binders={"t": f"st.sampled_from({list(range(k - 40, k + 41))!r})"})

    for i, people in enumerate([["alice"], ["bob"]]):
        outsider = "zed" if "zed" not in people else "yuri"
        people_str = ", ".join(f"'{p}'" for p in people)
        add(family="body-only",
            statement=f"WHERE a caller is cleared for roster {i}, THE SYSTEM SHALL address them",
            predicate="cleared(name) => member_of(name, roster)",
            oracle_terms={"roster": f"roster = frozenset({{{people_str}}})\n",
                          "member_of": "def member_of(item, bag):\n    return item in bag\n",
                          "cleared": "def cleared(person):\n    return person in roster\n"},
            producer_terms=["name"], check={},
            domains={"name": sorted(set(people) | {outsider})},
            mutant_terms={"cleared": f"def cleared(person):\n    return person in roster or person == '{outsider}'\n"},  # noqa: E501
            explicit_binders={"name": f"st.sampled_from({sorted(set(people) | {outsider})!r})"})

    for lo, hi in [(0, 5), (-5, 5)]:
        domain = list(range(lo, hi + 1))
        add(family="body-only",
            statement="IF a pair is ordered, THE SYSTEM SHALL preserve the first element first",
            predicate="ordered(t, count) => t <= count",
            oracle_terms={"ordered": "def ordered(a, b):\n    return a <= b\n"},
            producer_terms=["t", "count"], check={},
            domains={"t": domain, "count": domain},
            mutant_terms={"ordered": "def ordered(a, b):\n    return a >= b\n"},
            explicit_binders={"t": f"st.sampled_from({domain!r})",
                              "count": f"st.sampled_from({domain!r})"})

    add(family="body-only",
        statement="WHEN the kill switch is engaged, THE SYSTEM SHALL halt the pipeline",
        predicate="armed(is_live) => is_live",
        oracle_terms={"armed": "def armed(b):\n    return b is True\n"},
        producer_terms=["is_live"], check={},
        domains={"is_live": [True, False]},
        mutant_terms={"armed": "def armed(b):\n    return True\n"},
        explicit_binders={"is_live": "st.sampled_from([True, False])"})

    for step in (1, 5):
        add(family="body-only",
            statement=f"WHEN the clock ticks, THE SYSTEM SHALL advance time by {step}",
            predicate=f"t'(t) == t + {step}",
            oracle_terms={"next_t": f"def next_t(t):\n    return t + {step}\n"},
            producer_terms=["t"], check={},
            domains={"t": list(range(-10, 11))},
            mutant_terms={"next_t": f"def next_t(t):\n    return t + {step + 1}\n"},
            explicit_binders={"t": f"st.sampled_from({list(range(-10, 11))!r})"})

    return specs


def _negative_specs(start: int) -> list[Spec]:
    specs: list[Spec] = []
    n = start

    def add(**kw):
        nonlocal n
        n += 1
        specs.append(_spec(f"CAMP-NEG-{n:03d}", **kw))

    # prose predicates -> ParseError
    prose = [
        "responds(p, refuse) before commitment",
        "the system shall eventually converge",
        "forall t: eventually stable",  # 'eventually stable' is prose after the binder
        "forall t: expired(t) then archived(t)",
    ]
    for i, pred in enumerate(prose):
        add(family="neg-parse", statement="THE SYSTEM SHALL reject prose predicates",
            predicate=pred, oracle_terms={}, producer_terms=[], check={},
            domains={}, expect="parse_error")

    # unlexable surface (double quotes are not in the v1 lexer)
    add(family="neg-unlexable", statement="THE SYSTEM SHALL reject string literals",
        predicate='forall t: err(t) == "Unauthorized"', oracle_terms={},
        producer_terms=[], check={}, domains={}, expect="unlexable")

    # single-quoted prose silently compiles: the lexer skips ' as a prime
    # marker, so 'expired' parses as the bare identifier expired (campaign
    # finding F5). The typed outcome is the authoring-time OracleError on the
    # unowned free name — not a silent misparse reaching the gates.
    add(family="neg-quote-swallow", statement="THE SYSTEM SHALL not swallow quotes",
        predicate="forall t: label(t) == 'expired'", oracle_terms={},
        producer_terms=["t"], check={}, domains={}, expect="oracle_error")

    # boolean-chain prose compiles as a conjunction of free names (campaign
    # finding F4); again the typed outcome is the missing-impl OracleError
    add(family="neg-compiling-prose", statement="THE SYSTEM SHALL type boolean prose",
        predicate="approved and signed and timely", oracle_terms={},
        producer_terms=[], check={}, domains={}, expect="oracle_error")

    # empty set literal is reserved for set-builders
    add(family="neg-empty-set", statement="THE SYSTEM SHALL reject empty set literals",
        predicate="forall t: {t | ok(t)} != {}", oracle_terms={}, producer_terms=[],
        check={}, domains={}, expect="parse_error")

    # binder vocabulary gaps -> StrategyError (judge routing)
    for binder in ("frobnicator", "result", "output"):
        add(family="neg-judge-route", statement="THE SYSTEM SHALL route unknown binders to judge",
            predicate=f"forall {binder}: ok({binder})",
            oracle_terms={"ok": "def ok(v):\n    return True\n"},
            producer_terms=[binder], check={}, domains={}, expect="strategy_error")

    # keyword binder: lexes fine, dies at the codegen-compile boundary with a
    # typed ParseError ("compiled DSL generated invalid Python") — before any
    # strategy routing happens
    add(family="neg-keyword-binder", statement="THE SYSTEM SHALL reject keyword binders",
        predicate="forall import: ok(import)",
        oracle_terms={"ok": "def ok(v):\n    return True\n"},
        producer_terms=["import"], check={}, domains={}, expect="parse_error")

    # pairs binder has no per-name convention either
    add(family="neg-judge-route", statement="THE SYSTEM SHALL route pair binders to judge",
        predicate="forall pairs (a, b): a <= b", oracle_terms={}, producer_terms=["a", "b"],
        check={}, domains={}, expect="strategy_error")

    # missing oracle implementations -> OracleError (typed authoring failure)
    missing = [
        ("forall t: expired(t) and archived(t)",
         {"expired": "def expired(t):\n    return t > 100\n"},
         ["t"], ["archived"]),
        ("forall t: validate(t) == err(t)",
         {"err": "def err(c):\n    return ('Err', c)\n"},
         ["t"], ["validate"]),
        ("forall x: x in allowed", {}, ["x"], ["allowed"]),
        ("forall t: ok(t) or backup(t)",
         {"backup": "def backup(t):\n    return False\n"},
         ["t"], ["ok"]),
    ]
    for i, (pred, terms, producer, gap) in enumerate(missing):
        add(family="neg-missing-impl", statement="THE SYSTEM SHALL type missing oracle terms",
            predicate=pred, oracle_terms=terms, producer_terms=producer, check={},
            domains={}, expect="oracle_error")

    return specs


def generate_specs(seed: int = SEED) -> list[Spec]:
    """The full campaign corpus: positives first, then typed negatives.

    Positives are verified in both directions before they leave here: true
    oracle -> predicate True over the finite domains; mutant oracle -> False
    somewhere. A template whose math cannot kill its mutant is a generator
    bug, not a campaign finding.
    """
    from zft.dsl.oracle import predicate_symbols
    from zft.dsl.predicate import compile_predicate

    specs = _positive_specs() + _negative_specs(len(_positive_specs()))
    for spec in specs:
        if spec.expect != "ok":
            continue
        py = compile_predicate(spec.predicate)
        if _truth(spec, spec.oracle_terms, py) is not True:
            raise AssertionError(f"{spec.sid}: true oracle does not satisfy the predicate")
        # the binder names are producer-side (drawn values), never oracle terms
        symbols = predicate_symbols(spec.predicate)
        missing = symbols - set(spec.oracle_terms) - set(spec.producer_terms)
        if missing:
            raise AssertionError(f"{spec.sid}: generator left symbols unowned: {sorted(missing)}")
        if spec.mutant_terms:
            impls = {**spec.oracle_terms, **spec.mutant_terms}
            if _truth(spec, impls, py) is not False:
                raise AssertionError(f"{spec.sid}: mutant survives its own spec")
            if spec.explicit_binders:
                spec.kill_input = _first_violation(spec, impls, py)
    assert len([s for s in specs if s.expect == "ok"]) >= 200, \
        "campaign contract: at least 200 accepted specs"
    return specs


def specs_to_json(specs: list[Spec]) -> str:
    return json.dumps({
        "seed": SEED,
        "count": len(specs),
        "positives": sum(1 for s in specs if s.expect == "ok"),
        "families": sorted({s.family for s in specs}),
        "specs": [vars(s) for s in specs],
    }, indent=1)


if __name__ == "__main__":
    corpus = generate_specs()
    json.dump(json.loads(specs_to_json(corpus)), sys.stdout, indent=1)
    print()
