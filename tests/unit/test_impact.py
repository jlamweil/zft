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
