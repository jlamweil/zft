"""C-18: symbol anchors — refactor resilience (the V4 lesson, mechanized).

Line anchors go stale after inserts; symbol anchors must keep resolving.
"""
import textwrap

from zft.lineage.extract import extract_bindings

SAMPLE = '''
# @trace("TR-FORWARD-COVERAGE")
def check_forward_coverage(rows):
    return all(r.clause_id for r in rows)
'''


def test_symbol_anchor_resolves_after_insert(tmp_path):
    p = tmp_path / "m.py"
    p.write_text(textwrap.dedent(SAMPLE))
    before = extract_bindings(tmp_path)[0]
    assert before["line"] == 2

    p.write_text("import os\nimport re\n\n" + textwrap.dedent(SAMPLE))
    after = extract_bindings(tmp_path)[0]
    inserted_lines = 3  # "import os\nimport re\n\n"
    assert after["line"] == before["line"] + inserted_lines, "must track moved def"
    assert after["symbol"] == "check_forward_coverage"


# @trace("TR-IMPACT-QUERY")
def test_symbol_anchor_tracks_rename(tmp_path):
    p = tmp_path / "m.py"
    p.write_text(textwrap.dedent(SAMPLE))
    p.write_text(textwrap.dedent(SAMPLE).replace("check_forward_coverage",
                                                 "check_forward_coverage_v2"))
    binding = extract_bindings(tmp_path)[0]
    assert binding["symbol"] == "check_forward_coverage_v2"


# @trace("TR-UNRESOLVED-BINDINGS-FAIL")
def test_unresolvable_alias_reported(tmp_path):
    """TR-UNRESOLVED-BINDINGS-FAIL: a binding whose alias is not in the store is flagged."""
    from zft.lineage.matrix import coverage_report

    p = tmp_path / "m.py"
    p.write_text(textwrap.dedent(SAMPLE))
    aliases_in_store = {"TR-OTHER-CLAUSE"}
    report = coverage_report(extract_bindings(tmp_path), aliases_in_store)
    assert "TR-FORWARD-COVERAGE" in report["unresolved"]
    assert report["unresolved"] == ["TR-FORWARD-COVERAGE"]


# @trace("TR-REVERSE-COVERAGE")
def test_reverse_coverage_flags_unbound_elements(tmp_path):
    """TR-REVERSE-COVERAGE: elements without bindings are flagged out-of-contract."""
    from zft.lineage.extract import extract_bindings
    from zft.lineage.matrix import coverage_report

    (tmp_path / "bound.py").write_text('# @trace("TR-FORWARD-COVERAGE")\ndef a():\n    return 1\n')
    (tmp_path / "unbound.py").write_text("def b():\n    return 2\n")
    bindings = extract_bindings(tmp_path)
    report = coverage_report(
        bindings, {"TR-FORWARD-COVERAGE"},
        elements=["bound.py", "unbound.py"],
    )
    assert "unbound.py" in report["out_of_contract"]
    assert report["elements_justified"] == 1


def test_coverage_ratio_is_the_bound_fraction():
    # GATE-MUTATION-KILL: coverage_ratio key + covered/total value are the
    # report's contract (key renames and */divergence must not pass)
    from zft.lineage.matrix import coverage_report

    bindings = [{"alias": "A-ONE", "file": "a.py"},
                {"alias": "A-TWO", "file": "b.py"}]
    report = coverage_report(bindings, {"A-ONE", "B-TWO"})
    assert report["coverage"] == "1/2"
    assert report["coverage_ratio"] == 0.5


def test_coverage_ratio_empty_store_is_one():
    # GATE-MUTATION-KILL: no clauses in the store means nothing unbound — 1.0
    from zft.lineage.matrix import coverage_report

    report = coverage_report([], set())
    assert report["coverage_ratio"] == 1.0
