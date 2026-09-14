"""C-11/C-12: strategy mapping, judge escape hatch, oracle-artifact generation.

V2 lesson as regression fixture: predicate terms must resolve to the ORACLE,
not the producer module — an oracle-divergent mutant (expired_gt_to_lt) must be
flagged as killed-by-design when oracle is bound.
"""
import pytest

from traceagent.dsl.oracle import OracleError, generate_oracle, predicate_symbols
from traceagent.dsl.strategies import CONVENTIONS, StrategyError, strategy_for


class TestStrategies:
    def test_convention_defaults(self):
        assert strategy_for("t", {}) == "st.integers()"
        assert strategy_for("rows", {}) == "st.lists(st.integers())"
        assert strategy_for("name", {}) == "st.text()"

    def test_explicit_generator_wins(self):
        gen = strategy_for("t", {"generator": "st.integers(min_value=95, max_value=105)"})
        assert gen == "st.integers(min_value=95, max_value=105)"

    def test_unknown_convention_is_error(self):
        with pytest.raises(StrategyError, match="no strategy convention"):
            strategy_for("frobnicator", {})


class TestNestedStrategies:
    """Complex nested DSL expressions: structural binders get structural strategies."""

    def test_matrix_binder_gets_nested_lists(self):
        assert strategy_for("matrix", {}) == "st.lists(st.lists(st.integers()))"

    def test_grid_binder_gets_nested_lists(self):
        assert strategy_for("board_grid", {}) == "st.lists(st.lists(st.integers()))"

    def test_mapping_binder_gets_dictionaries(self):
        assert strategy_for("count_map", {}) == "st.dictionaries(st.text(), st.integers())"

    def test_structural_convention_beats_broad_scalar(self):
        # 'count_map' contains 'count' (integer convention) but is structural
        assert "dictionaries" in strategy_for("count_map", {})

    def test_records_get_lists_of_dicts(self):
        assert strategy_for("records", {}) == "st.lists(st.dictionaries(st.text(), st.integers()))"

    def test_grouped_binder_gets_dict_of_lists(self):
        out = strategy_for("grouped_by_kind", {})
        assert out == "st.dictionaries(st.text(), st.lists(st.integers()))"

    def test_tag_set_binder_gets_sets(self):
        assert strategy_for("tag_set", {}) == "st.sets(st.text())"

    def test_optional_binder_gets_one_of_none(self):
        assert strategy_for("opt_ver", {}) == "st.one_of(st.none(), st.integers())"

    def test_pair_binder_gets_tuples(self):
        assert strategy_for("pair_id", {}) == "st.tuples(st.integers(), st.integers())"

    def test_nested_payload_gets_recursive_strategy(self):
        assert strategy_for("payload", {}).startswith("st.recursive(")
        assert strategy_for("doc", {}).startswith("st.recursive(")

    def test_plural_binder_gets_list_fallback(self):
        assert strategy_for("orders", {}) == "st.lists(st.text())"

    def test_invalid_generator_rejected(self):
        with pytest.raises(StrategyError, match="invalid check.generator"):
            strategy_for("t", {"generator": 42})

    def test_non_string_binder_is_type_error(self):
        with pytest.raises(TypeError, match="binder must be str"):
            strategy_for(None, {})  # type: ignore[arg-type]


class TestDeeplyNestedStrategies:
    """Expanded bounded structural conventions for complex nested binders."""

    def test_tensor_binder_gets_three_level_nested_lists(self):
        assert strategy_for("tensor", {}) == (
            "st.lists(st.lists(st.lists(st.integers(), max_size=4), max_size=4), max_size=8)"
        )

    def test_edges_get_bounded_list_of_int_pairs(self):
        assert strategy_for("edge_list", {}) == (
            "st.lists(st.tuples(st.integers(), st.integers()), max_size=32)"
        )

    def test_graph_binder_gets_bounded_adjacency_map(self):
        assert strategy_for("graph", {}) == (
            "st.dictionaries(st.integers(), st.lists(st.integers(), max_size=8), max_size=16)"
        )

    def test_plural_coords_get_point_lists_singular_pair_unchanged(self):
        assert strategy_for("coords", {}) == (
            "st.lists(st.tuples(st.integers(), st.integers()), max_size=16)"
        )
        assert strategy_for("pair_id", {}) == "st.tuples(st.integers(), st.integers())"

    def test_interval_binders_get_bounded_pair_lists(self):
        assert strategy_for("ranges", {}) == strategy_for("edge_list", {})
        assert strategy_for("time_windows", {}) == strategy_for("edge_list", {})

    def test_plural_optional_gets_list_of_optionals_singular_unchanged(self):
        assert strategy_for("nullable_opts", {}) == (
            "st.lists(st.none() | st.integers(), max_size=16)"
        )
        assert strategy_for("opt_ver", {}) == "st.one_of(st.none(), st.integers())"

    def test_config_binder_gets_heterogeneous_scalar_map(self):
        out = strategy_for("config", {})
        assert out.startswith("st.dictionaries(st.text(), ")
        assert "st.integers() | st.text() | st.booleans()" in out

    def test_head_vocabulary_wins_payload_fields_stays_recursive(self):
        # 'payload' is the head noun, 'fields' a generic suffix — recursive wins
        assert strategy_for("payload_fields", {}).startswith("st.recursive(")

    def test_boolean_binders_get_booleans(self):
        assert strategy_for("is_active", {}) == "st.booleans()"
        assert strategy_for("retry_enabled", {}) == "st.booleans()"
        assert strategy_for("audit_flag", {}) == "st.booleans()"

    def test_unknown_binder_still_routes_to_judge(self):
        with pytest.raises(StrategyError, match="no strategy convention"):
            strategy_for("frobnicator", {})


class TestScalarBandAnchoring:
    """The integer band is whole-name anchored (^t$|^x$): bare t\\b/x\\b also
    matched any t-final name via the end-of-string word boundary, so
    'text'/'stmt'/'result'/'output' silently drew integers. Falsified shapes
    are pinned in tests/golden/property_codegen_fixtures.json binder_cases."""

    def test_text_binder_gets_text_strategy(self):
        assert strategy_for("text", {}) == "st.text()"
        assert strategy_for("stmt", {}) == "st.text()"

    def test_bare_t_and_x_keep_integers(self):
        assert strategy_for("t", {}) == "st.integers()"
        assert strategy_for("x", {}) == "st.integers()"

    def test_t_final_nonword_names_route_to_judge_not_integer(self):
        # ambiguous names fail loudly to the judge escape hatch — never a
        # silently wrong integer domain
        for name in ("result", "output", "import"):
            with pytest.raises(StrategyError, match="no strategy convention"):
                strategy_for(name, {})

    def test_num_count_ver_band_unchanged(self):
        assert strategy_for("count", {}) == "st.integers()"
        assert strategy_for("attempt_num", {}) == "st.integers()"
        assert strategy_for("contract_ver", {}) == "st.integers()"


class TestStrategySourcesAreExecutable:
    """Convention sources are rendered verbatim into generated @given(...) —
    every one must compile, evaluate to a real SearchStrategy, and draw."""

    @pytest.mark.parametrize(
        "pattern,source", CONVENTIONS, ids=[p for p, _ in CONVENTIONS]
    )
    def test_source_compiles_and_draws(self, pattern: str, source: str):
        from hypothesis import find
        from hypothesis import settings as hyp_settings
        from hypothesis import strategies as st

        expr = compile(f"lambda st: {source}", f"<convention:{pattern}>", "eval")
        strategy = eval(expr)(st)  # noqa: S307 — source is a repo-pinned literal
        assert isinstance(strategy, st.SearchStrategy)
        # must draw at least one example without raising
        find(
            strategy,
            lambda _: True,
            settings=hyp_settings(max_examples=10, deadline=None, derandomize=True,
                                  database=None),
        )


class TestJudgeEscapeHatch:
    def test_non_compilable_predicate_requires_judge(self):
        from traceagent.dsl.predicate import ParseError, compile_predicate

        try:
            compile_predicate("responds(p, refuse) before commitment")
        except ParseError:
            pass  # route below
        else:
            pytest.fail("prose predicate must not compile")

    # @trace("DSL-JUDGE-ESCAPE-HATCH")
    @pytest.mark.skip(reason="judge clauses are labeled, not executed — binding kept for ledger")
    def test_judge_clause_has_no_compile_requirement(self):
        ok = {"kind": "judge", "notes": "requires taste"}
        assert ok["kind"] == "judge"


class TestOracle:
    def test_predicate_symbols_extracted(self):
        syms = predicate_symbols("forall t: expired(t) => validate(t) == err(\"Unauthorized\")")
        assert {"expired", "validate", "err"} <= syms

    def test_oracle_generation_binds_non_producer_terms(self):
        """expired and err are oracle-owned; validate is producer-side."""
        src = generate_oracle(
            alias="GATE-INV-01",
            oracle_terms={"expired": "def expired(t):\n    return t > 100\n",
                          "err": "def err(code):\n    return ('Err', code)"},
            producer_terms=["validate"],
        )
        assert "def expired(t):" in src
        assert "def err(code):" in src
        assert "PRODUCER" in src  # producer imports rendered as explicit hook

    def test_missing_implementation_raises(self):
        with pytest.raises(OracleError, match="expired"):
            generate_oracle(
                alias="GATE-INV-01",
                oracle_terms={"err": "def err(code):\n    return ('Err', code)"},
                producer_terms=["validate"],
                symbols={"expired", "validate", "err"},
            )


class TestOracleValidation:
    """Runtime validation: garbage in -> deterministic, expressive error out."""

    ARGS = {
        "alias": "GATE-INV-01",
        "oracle_terms": {"expired": "def expired(t):\n    return t > 100\n"},
        "producer_terms": ["validate"],
    }

    def test_generated_source_is_deterministic(self):
        assert generate_oracle(**self.ARGS) == generate_oracle(**self.ARGS)

    def test_rendered_source_compiles(self):
        src = generate_oracle(**self.ARGS)
        compile(src, "<oracle>", "exec")  # must not raise

    def test_blank_alias_rejected(self):
        with pytest.raises(OracleError, match="alias"):
            generate_oracle(alias="  ", oracle_terms={}, producer_terms=[])

    def test_non_string_alias_is_type_error(self):
        with pytest.raises(TypeError, match="alias must be str"):
            generate_oracle(alias=7, oracle_terms={}, producer_terms=[])

    def test_non_identifier_term_name_rejected(self):
        with pytest.raises(OracleError, match="identifier"):
            generate_oracle(alias="A", oracle_terms={"not-a-name": "x = 1"}, producer_terms=[])

    def test_keyword_term_name_rejected(self):
        with pytest.raises(OracleError, match="identifier"):
            generate_oracle(alias="A", oracle_terms={"import": "x = 1"}, producer_terms=[])

    def test_syntactically_broken_impl_diagnosed(self):
        with pytest.raises(OracleError, match="expired.*does not compile"):
            generate_oracle(
                alias="A",
                oracle_terms={"expired": "def expired(t:\n    return t"},
                producer_terms=[],
            )

    def test_bare_string_producer_terms_is_type_error(self):
        with pytest.raises(TypeError, match="producer_terms must be a list"):
            generate_oracle(alias="A", oracle_terms={}, producer_terms="validate")

    def test_bare_string_symbols_is_type_error(self):
        with pytest.raises(TypeError, match="symbols must be a list"):
            generate_oracle(alias="A", oracle_terms={}, producer_terms=[], symbols="expired")

    def test_non_string_impl_source_is_type_error(self):
        with pytest.raises(TypeError, match="oracle term"):
            generate_oracle(alias="A", oracle_terms={"expired": 42}, producer_terms=[])


# --- GATE-MUTATION-KILL (mut-dsl-codegen campaign 2026-09-06) ----------------

# GATE-MUTATION-KILL: guard `or -> and` in the oracle_terms / name-bag checks
# lets int/list payloads slip through to a later, wrong crash
# (generate_oracle 11, _require_name_bag 1)
def test_non_sequence_producer_terms_is_type_error():
    with pytest.raises(TypeError, match="producer_terms must be a list of symbol names"):
        generate_oracle(alias="A", oracle_terms={}, producer_terms=42)  # type: ignore[arg-type]


def test_non_mapping_oracle_terms_is_type_error():
    with pytest.raises(TypeError, match="oracle_terms must be a Mapping"):
        generate_oracle(alias="A", oracle_terms=["expired"], producer_terms=[])  # type: ignore[list-item]


# GATE-MUTATION-KILL: reserved-word set {"CLAUSES"} -> {"clauses"} would
# re-admit the comprehension target as an oracle symbol (predicate_symbols 13)
def test_clauses_is_a_reserved_predicate_symbol():
    assert predicate_symbols("CLAUSES > 1") == set()


# GATE-MUTATION-KILL: _require_str `what`-label mutations hide which argument
# violated the contract (predicate_symbols 2/5/6)
def test_predicate_symbols_non_str_names_the_argument():
    with pytest.raises(TypeError, match="predicate must be str"):
        predicate_symbols(42)  # type: ignore[arg-type]


# GATE-MUTATION-KILL: SyntaxError detail `-> None` drops "(line N)" from the
# impl diagnostic (_check_impl_compiles 9)
def test_uncompilable_impl_diagnostic_carries_line_detail():
    with pytest.raises(OracleError, match=r"does not compile: invalid syntax \(line 1\)"):
        generate_oracle(alias="A", oracle_terms={"bad": "return 1 >"}, producer_terms=[])


# GATE-MUTATION-KILL: byte-exact rendered module pins the docstring/impl
# joiners, blank separator lines and the producer-side comment banner
# (generate_oracle 58/62/64/66/68/72)
def test_rendered_oracle_module_byte_exact():
    impl = "\n# leading comment\ndef ok(x):\n    return True\n"
    assert generate_oracle(alias="C", oracle_terms={"ok": impl}, producer_terms=["prod"]) == (
        '"""Oracle for clause C — contract-side reference (authored with the contract)."""'
        "\n"
        "\n"
        "\n# leading comment\ndef ok(x):\n    return True"
        "\n"
        "\n# PRODUCER-side symbols (resolved at gate time, never imported here):"
        "\n#   prod"
        "\n"
    )


# GATE-MUTATION-KILL: StrategyError hints are contractual routing help
# (strategy_for 16/17/18 and 24/25)
def test_invalid_generator_hint_pins_hypothesis_example():
    # byte-exact: an XX-wrapped or re-cased hint must not pass a substring pin
    with pytest.raises(StrategyError) as ei:
        strategy_for("t", {"generator": "   "})
    assert str(ei.value) == (
        "invalid check.generator for binder 't': '   ' "
        "(expected a Hypothesis strategy expression, e.g. 'st.integers()')"
    )


def test_unknown_binder_hint_offers_generator_escape():
    with pytest.raises(StrategyError) as ei:
        strategy_for("frobnicator", {})
    assert str(ei.value) == (
        "no strategy convention for binder 'frobnicator' — route to judge "
        "(or set check.generator explicitly)"
    )


# --- GATE-MUTATION-KILL (mut-dsl-codegen shard 2026-09-07 residual triage) ---
# Validation-guard messages name WHICH argument violated the contract and
# render the ACTUAL offending type/value; substring pins survive label and
# type(None) mutants, so the residual pins below are byte-exact.

def test_predicate_symbols_type_error_byte_exact():
    with pytest.raises(TypeError) as ei:
        predicate_symbols(42)  # type: ignore[arg-type]
    assert str(ei.value) == "predicate must be str, got int: 42"


def test_producer_terms_type_error_byte_exact():
    with pytest.raises(TypeError) as ei:
        generate_oracle(alias="A", oracle_terms={}, producer_terms=42)  # type: ignore[arg-type]
    assert str(ei.value) == "producer_terms must be a list of symbol names, got int: 42"


def test_producer_term_entry_type_error_byte_exact():
    with pytest.raises(TypeError) as ei:
        generate_oracle(alias="A", oracle_terms={}, producer_terms=[42])
    assert str(ei.value) == "producer_terms entry must be str, got int: 42"


def test_producer_term_entry_identifier_error_byte_exact():
    with pytest.raises(OracleError) as ei:
        generate_oracle(alias="A", oracle_terms={}, producer_terms=["not-a-name"])
    assert str(ei.value) == (
        "producer_terms entry must be a non-keyword identifier, got 'not-a-name'"
    )


def test_blank_alias_error_byte_exact():
    with pytest.raises(OracleError) as ei:
        generate_oracle(alias="  ", oracle_terms={}, producer_terms=[])
    assert str(ei.value) == "alias must be a non-empty clause identifier, got ''"


def test_oracle_terms_type_error_byte_exact():
    with pytest.raises(TypeError) as ei:
        generate_oracle(alias="A", oracle_terms=["expired"], producer_terms=[])  # type: ignore[list-item]
    assert str(ei.value) == (
        "oracle_terms must be a Mapping of name -> source, got list: ['expired']"
    )


def test_oracle_term_name_type_error_byte_exact():
    with pytest.raises(TypeError) as ei:
        generate_oracle(alias="A", oracle_terms={42: "x = 1"}, producer_terms=[])
    assert str(ei.value) == "oracle term name must be str, got int: 42"


def test_oracle_term_name_identifier_error_byte_exact():
    with pytest.raises(OracleError) as ei:
        generate_oracle(alias="A", oracle_terms={"not-a-name": "x = 1"}, producer_terms=[])
    assert str(ei.value) == (
        "oracle term name must be a non-keyword identifier, got 'not-a-name'"
    )


def test_binder_type_error_byte_exact():
    with pytest.raises(TypeError) as ei:
        strategy_for(42, {})  # type: ignore[arg-type]
    assert str(ei.value) == "binder must be str, got int: 42"


def test_check_mapping_type_error_byte_exact():
    with pytest.raises(TypeError) as ei:
        strategy_for("t", 42)  # type: ignore[arg-type]
    assert str(ei.value) == "check must be a Mapping, got int: 42"
