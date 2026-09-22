"""C-09: DSL v1 predicate grammar — every form class from the V1b taxonomy.

Golden fixtures: tests/golden/dsl_predicate_fixtures.json — the 26 corpus
properties as they look AFTER patch P1; all must compile. Independent truth:
VERIFIED-DESIGNS.md D-DSL grammar (recursive quantifiers, =>, primes,
set-builders, membership binders, reserved-word renames).
"""
import json
from pathlib import Path

import pytest

from zft.dsl.predicate import ParseError, compile_predicate

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "golden" / "dsl_predicate_fixtures.json").read_text()
)


def test_implication_desugars():
    assert compile_predicate("a(x) => b(x)") == "(not (a(x))) or (b(x))"


def test_nested_quantifier():
    out = compile_predicate("forall o: implemented(o) => exists c: contains(c, o) and status(c) == VALIDATED")  # noqa: E501
    # inner exists is a negated forall, never a bare forall (the old compiler
    # emitted all_ for both — silently inverting every existential clause)
    assert "(not (all_(['c'], lambda c: (not (" in out
    assert out.startswith("(all_(['o']")  # outer forall unchanged


def test_tuple_binder():
    out = compile_predicate("forall a, b: eq(a, b) => same(a, b)")
    assert "'a', 'b'" in out


def test_membership_binder_and_member_of():
    out = compile_predicate("forall clauses c in g: member_of(c, g) => recomputed(c) == stored(c)")
    assert out  # parses and compiles


def test_in_operator_desugars_to_member_of():
    out = compile_predicate("kind(x) in {A, B}")
    assert "member_of(kind(x)" in out


def test_prime_desugars_to_next():
    # v' -> next_v: the prime binds to the identifier it marks. The args form
    # v'(a, b) exercises both suffix_name loops (lp entry, comma continuation).
    assert compile_predicate("p'") == "next_p"
    out = compile_predicate("content_changed(n) => p'(x, y)")
    assert out == "(not (content_changed(n))) or (next_p(x, y))"
    with pytest.raises(ParseError, match="trailing input"):
        compile_predicate("p' q")  # the prime consumes no following identifier


def test_set_builder_desugars_to_comprehension():
    out = compile_predicate("impact(ch) == {c | bound(c, element(ch))}")
    assert "{ c for c in CLAUSES if" in out


def test_unary_not():
    out = compile_predicate("not expressible(c) => kind(c)==judge")
    assert "not" in out


def test_free_prose_rejected():
    with pytest.raises(ParseError):
        compile_predicate("responds(p, refuse) before commitment")


def _all_runtime(domains):
    """Faithful `all_` runtime: true iff the body holds for every binding of
    the named binders drawn from `domains` (empty domain -> vacuously true)."""
    from itertools import product

    def all_(names, f):
        return all(f(*combo) for combo in product(*(domains[n] for n in names)))
    return all_


class TestQuantifierSemantics:
    """Behavioral gold: compiled predicates must preserve meaning under
    evaluation, not merely compile. Regression for the exists-as-forall
    miscompilation, which evaluated False on ground-truth-True inputs."""

    def _eval(self, dsl, domains, **env):
        py = compile_predicate(dsl)
        # single namespace as globals: the compiled lambdas resolve their free
        # names (oracle terms, constants) through __globals__, not eval-locals
        glb = {"__builtins__": {}, "all_": _all_runtime(domains), **env}
        return eval(py, glb)  # noqa: S307

    def test_exists_is_not_forall_on_the_same_domain(self):
        domains = {"x": [0, 1, 2]}
        assert self._eval("exists x: x == 1", domains) is True
        assert self._eval("forall x: x == 1", domains) is False

    def test_exists_is_false_when_no_element_satisfies(self):
        assert self._eval("exists x: x > 5", {"x": [0, 1, 2]}) is False

    def test_exists_empty_domain_is_false_where_forall_is_vacuously_true(self):
        # the distinguishing edge: exists-as-forall compiled True here
        assert self._eval("exists x: x == x", {"x": []}) is False
        assert self._eval("forall x: x == x", {"x": []}) is True

    def test_corpus_nested_predicate_ground_truth(self):
        """con-validated-or-no-start: o1 is implemented with exactly one
        VALIDATED clause; o2 is never implemented (the vacuous 'no start'
        arm) — ground truth True. With o1 stripped of validated clauses the
        exists arm fails and the predicate is False. The old compiler
        (exists as bare forall) returned False on the True model."""
        dsl = "forall o: implemented(o) => exists c: contains(c, o) and status(c) == VALIDATED"  # noqa: E501
        domains = {"o": ["o1", "o2"], "c": ["c1", "c2"]}

        def implemented(o):
            return o == "o1"

        def contains(c, o):
            return o == "o1"  # both clauses belong to o1

        def status(c):
            return "VALIDATED" if c == "c1" else "DRAFT"

        result = self._eval(dsl, domains, implemented=implemented,
                            contains=contains, status=status,
                            VALIDATED="VALIDATED")
        assert result is True, "o1's single validated clause must satisfy exists"
        # and the same model with o1 stripped of validated clauses must fail
        def status_none(c):
            return "DRAFT"
        assert self._eval(dsl, domains, implemented=implemented,
                          contains=contains, status=status_none,
                          VALIDATED="VALIDATED") is False

    def test_multi_binder_exists_needs_every_binding(self):
        # exists a, b: over a 2x2 grid where only one pair qualifies
        domains = {"a": [0, 1], "b": [0, 1]}
        assert self._eval("exists a, b: a == 1 and b == 1", domains) is True
        assert self._eval("exists a, b: a == 1 and b == 7", domains) is False


class TestEdgeCaseDiagnostics:
    """Malformed input fails with position-aware ParseError, never None or
    a bare token dump."""

    def test_empty_input_diagnosed(self):
        with pytest.raises(ParseError, match="empty or incomplete"):
            compile_predicate("")

    def test_unbalanced_open_paren_reports_end_of_input(self):
        with pytest.raises(ParseError, match=r"expected '\)' but found end of input"):
            compile_predicate("forall t: expired(t")

    def test_unbalanced_close_reports_trailing_input(self):
        with pytest.raises(ParseError, match="trailing input"):
            compile_predicate("expired(x))")

    def test_unlexable_reports_position(self):
        with pytest.raises(ParseError, match=r"unlexable input at position 2: '@'"):
            compile_predicate("a @ b")

    def test_empty_set_literal_diagnosed(self):
        with pytest.raises(ParseError, match="empty set literal"):
            compile_predicate("x in {}")

    def test_missing_colon_after_binder(self):
        with pytest.raises(ParseError, match=r"expected ':'"):
            compile_predicate("forall t expired(t)")

    def test_unlexable_operator_reports_position(self):
        # '=' alone has never been lexable DSL (only '==' and '!=')
        with pytest.raises(ParseError, match=r"unlexable input at position \d+: '='"):
            compile_predicate("a = b")

    def test_codegen_failure_raises_with_generated_source(self, monkeypatch):
        # Defensive invariant: parsing should only ever emit valid Python, but
        # if it ever doesn't, the failure must name the generated code — this
        # path used to return None silently.
        import zft.dsl.predicate as pred

        def boom(*args, **kwargs):
            raise SyntaxError("invalid syntax", ("<dsl>", 1, 1, "bogus"))

        monkeypatch.setattr(pred, "compile", boom, raising=False)
        with pytest.raises(ParseError, match="generated invalid Python") as ei:
            pred.compile_predicate("a(x)")
        assert "generated: a(x)" in str(ei.value)

    def test_deeply_nested_expression_is_parse_error_not_crash(self):
        with pytest.raises(ParseError, match="nests too deeply"):
            compile_predicate("(" * 2000 + "x" + ")" * 2000)

    def test_non_string_input_is_type_error(self):
        with pytest.raises(TypeError, match="predicate must be str"):
            compile_predicate(None)  # type: ignore[arg-type]

    def test_diagnostic_carries_caret_excerpt(self):
        with pytest.raises(ParseError) as ei:
            compile_predicate("forall t: expired(t")
        assert "at:" in str(ei.value)  # caret-marked excerpt


# @trace("DSL-COMPILE-GENERATORS")
# @trace("DSL-TRIGGER-PREDICATE-ENFORCEMENT")
def test_golden_all_26_compile():
    """Golden: every corpus property (post-P1) compiles — V1b pass criterion."""
    assert len(GOLDEN) == 26
    for alias, prop in sorted(GOLDEN.items()):
        assert compile_predicate(prop), f"{alias} failed to compile"


# GATE-MUTATION-KILL: predicate.py _display `== -> !=` and _point window/caret
# mutants survived prior campaigns: the unexpected-token diagnostic with its
# caret-marked excerpt is contractual — pinned byte-exact
def test_unexpected_token_diagnostic_pinned_byte_exact():
    with pytest.raises(ParseError) as excinfo:
        compile_predicate(")")
    assert str(excinfo.value) == (
        "unexpected ')' (rp) at position 0\n"
        "  at: ')'\n"
        "    ^"
    )


# GATE-MUTATION-KILL: _point caret-offset `pos - lo -> pos + lo` is invisible
# at position 0 (lo=0) — pin an excerpt with the error beyond the 20-char
# window so the caret offset (pos - lo == 20) is exact
def test_caret_excerpt_offset_pinned_deep_in_source():
    src = "forall x: " + "a" * 25 + "@"
    with pytest.raises(ParseError) as excinfo:
        compile_predicate(src)
    assert str(excinfo.value) == (
        "unlexable input at position 35: '@'\n"
        "  at: '" + "a" * 20 + "@'\n"
        "    " + " " * 20 + "^"
    )


# --- GATE-MUTATION-KILL (mut-dsl-codegen campaign 2026-09-06) ----------------
# Logic-bearing survivors from the full-src mutmut campaign; each pin flips
# its mutant to killed.

# GATE-MUTATION-KILL: P.sum / P.mul loop conditions `and -> or` let the
# arithmetic levels consume comparison ops and re-nest the tail under them.
# Precedence decision 2026-09-07: conventional — * / bind tighter than + -;
# comparisons looser than both. Supersedes the pre-fix pin
# `a * b + c == "(a * (b + c))"` (that pin killed the mutant by pinning the
# bug; the case below kills it by pinning the contract).
def test_arith_precedence_conventional_mul_binds_tighter():
    assert compile_predicate("a * b + c") == "((a * b) + c)"
    assert compile_predicate("a + b * c") == "(a + (b * c))"
    # kills sum's `and -> or`: a comparison RHS must stay a whole sum, not
    # `(x < a) + b`
    assert compile_predicate("x < a + b") == "(x < (a + b))"
    # kills mul's `and -> or`: a comparison must never be consumed at product
    # level with its +-tail re-nested under it
    assert compile_predicate("x * a < b + c") == "((x * a) < (b + c))"
    # left-assoc at each level, byte-exact
    assert compile_predicate("a - b + c + d") == "(((a - b) + c) + d)"
    assert compile_predicate("a * b / c * d") == "(((a * b) / c) * d)"
    # arithmetic tighter than comparison, comparison tighter than and/or
    # (and_ parenthesizes each operand, hence the doubled parens)
    assert compile_predicate("a < b * c and d > e + f") == \
        "((a < (b * c))) and ((d > (e + f)))"


# GATE-MUTATION-KILL: the quantifier lambda-arg join `', ' -> 'XX, XX' still
# compiles (aXX/XXb are valid identifiers) — only a byte-exact pin sees it
# (quant 22)
def test_multi_binder_lambda_args_render_byte_exact():
    assert compile_predicate("forall a, b: eq(a, b)") == \
        "(all_(['a', 'b'], lambda a, b: eq(a, b)))"


# GATE-MUTATION-KILL: set-literal join `', ' -> 'XX, XX' renders {AXX, XXB}
# — valid Python, so only the exact source string catches it (atom 52)
def test_set_literal_items_render_byte_exact():
    assert compile_predicate("x in {A, B}") == "member_of(x, {A, B})"


# GATE-MUTATION-KILL: `take(kind) -> take(None)` in bracket-closing positions
# swallows the wrong token and silently ACCEPTS unclosed brackets
# (atom 10/26/48, suffix_name 10, binder_group 40)
def test_unclosed_brackets_stay_rejected():
    for bad in ("(x", "{x | P(x)", "{A, B", "p'(x", "forall pairs (a, b:"):
        with pytest.raises(ParseError, match=r"expected '\)'|expected '}'"):
            compile_predicate(bad)


# GATE-MUTATION-KILL: take's found-token display `== -> !=` reports "end of
# input" for a perfectly visible token; take(None)/_display(None) crash
# instead of diagnosing (take 12/15, binder_group 2)
def test_expected_identifier_diagnostic_names_the_found_token():
    with pytest.raises(ParseError, match=r"expected identifier but found ':' \(colon\)"):
        compile_predicate("forall: b")


# --- GATE-MUTATION-KILL (mut-dsl-codegen shard 2026-09-07 residual triage) ---
# 54 mutants survived the morning pins; each pin below flips one or more of
# them to killed. The 16 that remain unpinned are recorded equivalents in
# SURVIVORS_TRIAGE.md (redundant guards, dead defaults, undocumented forms).

# GATE-MUTATION-KILL: _display's end-token branch (kind check + "end of
# input" text) is only observable through the trailing-input diagnostic —
# the substring pin let XX/case mutants through (_display 2/3/4/5)
def test_trailing_input_diagnostic_pinned_byte_exact():
    with pytest.raises(ParseError) as excinfo:
        compile_predicate("expired(x))")
    assert str(excinfo.value) == (
        "unexpected trailing input after the expression: ')' (rp) at position 10\n"
        "  at: 'expired(x))'\n"
        "              ^"
    )


# GATE-MUTATION-KILL: _point window `pos + 20 -> pos + 21` is invisible when
# the error sits at/near end of input (hi is capped by len) — pin an error
# with 25 trailing chars so the 20-char forward window is exact (_point 14)
def test_caret_excerpt_forward_window_pinned():
    with pytest.raises(ParseError) as excinfo:
        compile_predicate("a@" + "b" * 25)
    assert str(excinfo.value) == (
        "unlexable input at position 1: '@'\n"
        "  at: 'a@bbbbbbbbbbbbbbbbbbb'\n"
        "     ^"
    )


# GATE-MUTATION-KILL: _point's newline rendering — dropping or XX-wrapping
# the replace() shows a raw newline (single-escaped by repr) where the
# contract renders the two-character `\\n` (_point 20/21)
def test_caret_excerpt_newline_escape_pinned():
    with pytest.raises(ParseError) as excinfo:
        compile_predicate("a" * 30 + "\n" + "b" * 5 + "@")
    assert str(excinfo.value) == (
        "unlexable input at position 36: '@'\n"
        "  at: 'aaaaaaaaaaaaaa\\\\nbbbbb@'\n"
        "                        ^"
    )


# GATE-MUTATION-KILL: the end token's value is part of the public tokenize
# contract; nothing else observes it (tokenize 33/40)
def test_tokenize_token_list_golden():
    import zft.dsl.predicate as pred

    assert pred.tokenize("x 1") == (
        [pred.Tok("name", "x", 0), pred.Tok("num", "1", 2), pred.Tok("end", "", 3)],
        None,
    )


# GATE-MUTATION-KILL: the TypeError renders the *actual* offending type —
# the None input renders NoneType under the type(None) mutant too, so pin
# an int (compile_predicate 3, ears parse_statement 3 via golden fixture)
def test_predicate_type_error_names_the_type():
    with pytest.raises(TypeError) as excinfo:
        compile_predicate(42)  # type: ignore[arg-type]
    assert str(excinfo.value) == "predicate must be str, got int: 42"


# GATE-MUTATION-KILL: empty-set-literal diagnostic is contractual; substring
# pins survive XX-wrap and case mutants (atom 36/37)
def test_empty_set_literal_message_byte_exact():
    with pytest.raises(ParseError) as excinfo:
        compile_predicate("x in {}")
    assert str(excinfo.value) == (
        "empty set literal '{}' is not valid DSL — use a set-builder "
        "'{x | P(x)}' instead at position 5\n"
        "  at: 'x in {}'\n"
        "         ^"
    )


# GATE-MUTATION-KILL: the documented pairs binder `forall pairs (a, b):` was
# accepted but never pinned — the whole tuple branch (lp entry, comma loop)
# was free to drift (binder_group 34/35 and friends)
def test_pairs_binder_form_byte_exact():
    assert compile_predicate("forall pairs (a, b): f(a, b)") == \
        "(all_(['a', 'b'], lambda a, b: f(a, b)))"


# GATE-MUTATION-KILL: tuple-group slots demand identifiers — take(None)
# swallows ')' and renders `lambda )` into a codegen error instead of
# diagnosing the position (binder_group 30/37)
def test_tuple_group_slots_reject_non_names():
    for bad in ("forall p ():", "forall pairs (a, ):"):
        with pytest.raises(ParseError, match=r"expected identifier but found '\)' \(rp\)"):
            compile_predicate(bad)


# GATE-MUTATION-KILL: the membership domain must be an identifier —
# take(None) accepts `forall c in 9:` and silently drops the domain
# (binder_group 46)
def test_membership_binder_domain_must_be_identifier():
    with pytest.raises(ParseError) as excinfo:
        compile_predicate("forall c in 9: f(c)")
    assert str(excinfo.value) == (
        "expected identifier but found '9' (num) at position 12\n"
        "  at: 'forall c in 9: f(c)'\n"
        "                ^"
    )


# GATE-MUTATION-KILL: a dangling dot must diagnose the missing attribute
# name; take(None) turns it into `a.` + "" and a codegen error instead
# (call_chain 22)
def test_trailing_dot_rejected_with_identifier_diagnostic():
    with pytest.raises(ParseError) as excinfo:
        compile_predicate("a.")
    assert str(excinfo.value) == (
        "expected identifier but found end of input at position 2\n"
        "  at: 'a.'\n"
        "      ^"
    )


# GATE-MUTATION-KILL: binder_group's multi-name loop binds the LAST name —
# the lookahead kind-set's "name" member (binder_group 20/21) and the
# appended-name value (binder_group 22, names.append(None)) survived the
# fresh batch: space-separated multi-name binders were never pinned
def test_multi_name_binder_binds_last_name_byte_exact():
    assert compile_predicate("forall a b c: a == 1") == "(all_(['c'], lambda c: (a == 1)))"


# GATE-MUTATION-KILL: the binder loop's lookahead reads toks[i + 1]
# (binder_group 9, -> toks[i - 1]): with the follower outside the kind-set
# the loop must stop at the last real name, so the missing-colon error
# reports THAT name — the backward lookahead consumes it instead and
# reports the operator further along
def test_multi_name_binder_missing_colon_reports_last_name():
    with pytest.raises(ParseError) as excinfo:
        compile_predicate("forall x y == 1")
    assert str(excinfo.value) == (
        "expected ':' but found 'y' (name) at position 9\n"
        "  at: 'forall x y == 1'\n"
        "             ^"
    )


# GATE-MUTATION-KILL: the lookahead kind-set's "lp" member (binder_group
# 16/17): a name directly before a tuple group must be consumed by the
# multi-name loop so the lp branch is reached with the group in view;
# breaking the member strands the loop on the name and mis-reports the
# missing colon instead of binding the pair
def test_name_before_tuple_group_binds_the_pair_byte_exact():
    assert compile_predicate("forall x y (a, b): a == 1") == \
        "(all_(['a', 'b'], lambda a, b: (a == 1)))"
