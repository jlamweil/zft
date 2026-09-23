"""v0.1 TR-IMPACT-QUERY: changed deliverable element(s) -> affected clause aliases."""
from __future__ import annotations

from pathlib import Path

from zft.lineage import impact, impact_from_root

BINDINGS = [
    {"alias": "A-ONE", "file": "src/a.py", "line": 1, "symbol": "foo"},
    {"alias": "B-TWO", "file": "src/b.py", "line": 2, "symbol": "bar"},
    {"alias": "A-ONE", "file": "src/a.py", "line": 8, "symbol": "baz"},
]


# @trace("TR-IMPACT-QUERY")
def test_file_level_match():
    result = impact(BINDINGS, ["src/a.py"])
    assert result["aliases"] == ["A-ONE"]
    assert len(result["affected"]["A-ONE"]) == 2
    assert {r["file"] for r in result["affected"]["A-ONE"]} == {"src/a.py"}


# @trace("TR-IMPACT-QUERY")
def test_symbol_narrowing():
    result = impact(BINDINGS, ["src/a.py::baz"])
    assert result["aliases"] == ["A-ONE"]
    assert result["affected"]["A-ONE"] == [
        {"file": "src/a.py", "line": 8, "symbol": "baz"}
    ]


# @trace("TR-IMPACT-QUERY")
def test_suffix_match():
    result = impact(BINDINGS, ["a.py"])
    assert result["aliases"] == ["A-ONE"]


# @trace("TR-IMPACT-QUERY")
def test_impact_from_root(tmp_path: Path):
    (tmp_path / "x.py").write_text('# @trace("Z-CLAUSE")\ndef foo():\n    return 1\n')
    result = impact_from_root(tmp_path, ["x.py::foo"])
    assert result["aliases"] == ["Z-CLAUSE"]
    assert result["affected"]["Z-CLAUSE"][0]["file"] == "x.py"
    assert result["affected"]["Z-CLAUSE"][0]["symbol"] == "foo"


# --- hygiene sitting 2026-09-22 (loop continuation): impact pin battery ---

def test_change_symbols_may_themselves_contain_separators():
    bindings = [{"alias": "S", "file": "src/a.py", "line": 1, "symbol": "na::me"}]
    result = impact(bindings, ["src/a.py::na::me"])
    assert result["aliases"] == ["S"]
    assert result["affected"]["S"] == [
        {"file": "src/a.py", "line": 1, "symbol": "na::me"}]


def test_binding_without_file_matches_the_empty_path():
    result = impact([{"alias": "N", "line": 3}], [""])
    assert result["aliases"] == ["N"]
    assert result["affected"]["N"] == [{"file": ".", "line": 3, "symbol": None}]


def test_symbol_mismatch_skips_without_stopping_the_scan():
    bindings = [{"alias": "S", "file": "a.py", "line": 1, "symbol": "foo"}]
    result = impact(bindings, ["a.py::bar", "a.py"])
    assert result["aliases"] == ["S"]
    assert result["affected"]["S"] == [
        {"file": "a.py", "line": 1, "symbol": "foo"}]


def test_binding_without_line_defaults_to_zero():
    result = impact([{"alias": "L", "file": "a.py", "symbol": "s"}], ["a.py"])
    assert result["affected"]["L"] == [
        {"file": "a.py", "line": 0, "symbol": "s"}]


def test_affected_refs_sort_by_file_line_then_symbol_with_none_last():
    bindings = [
        {"alias": "K", "file": "b.py", "line": 2, "symbol": None},
        {"alias": "K", "file": "b.py", "line": 2, "symbol": "X"},
        {"alias": "K", "file": "a.py", "line": 9, "symbol": "y"},
        {"alias": "K", "file": "b.py", "line": 1, "symbol": "w"},
    ]
    result = impact(bindings, ["a.py", "b.py"])
    assert result["affected"]["K"] == [
        {"file": "a.py", "line": 9, "symbol": "y"},
        {"file": "b.py", "line": 1, "symbol": "w"},
        {"file": "b.py", "line": 2, "symbol": None},
        {"file": "b.py", "line": 2, "symbol": "X"},
    ]


def test_norm_path_strips_the_leading_dot_slash_only():
    from zft.lineage.impact import _norm_path

    assert _norm_path("./ab.py") == "ab.py"
    assert _norm_path("./.zft/x.py") == ".zft/x.py"
    assert _norm_path("/abs/x.py") == "/abs/x.py"
