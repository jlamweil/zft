"""The mechanical kill-rate bar: verdict semantics, mutation-diff
classification, waiver accounting, shard loading, and the CLI exit-code
contract."""
from __future__ import annotations

import json

import pytest

from zft.cli.main import main
from zft.gates.mutation_bar import (
    COSMETIC,
    STATUS_BY_EXIT,
    FileVerdicts,
    ShardInput,
    _orig_fn_key,
    classify,
    evaluate,
    load_shard,
    load_waivers,
    write_mutation_records,
)

# --- verdict semantics (mutmut 3.7 status_by_exit_code, pinned byte-exact) --

def test_mutmut_exit_code_semantics_pinned():
    # Verified against the installed mutmut/__main__.py status_by_exit_code:
    # a cpu-limit death (-24) and pytest internal errors (3) are kills,
    # 33 means the stats phase bound no test to the mutant (not a pass).
    assert STATUS_BY_EXIT[0] == "survived"
    assert STATUS_BY_EXIT[1] == "killed"
    assert STATUS_BY_EXIT[3] == "killed"
    assert STATUS_BY_EXIT[-24] == "killed"
    assert STATUS_BY_EXIT[33] == "no_tests"
    assert STATUS_BY_EXIT[5] == "no_tests"
    assert STATUS_BY_EXIT[36] == "timeout"
    assert STATUS_BY_EXIT[None] == "not_checked"
    assert STATUS_BY_EXIT.get(99) is None  # unknown -> SUSPICIOUS at evaluate


# --- classification (from the mutation record: orig fn source + changed
#     lines, as written to .mutdiff.json by jobs/mut-src.sh) -----------------

ORIG_FN = '''def alpha(x):
    """Alpha docstring: + - here."""
    return x + 1
'''


def _entry(changed=None, line=2, last_line=None):
    """A .mutdiff.json diffs entry mutating the function body line (default:
    the ``return x + 1`` line, 0-based line 2 of ORIG_FN)."""
    return {"line": line,
            "last_line": last_line,
            "orig": "    return x + 1\n",
            "mutant": changed if changed is not None else "    return x + 1\n"}


def test_docstring_mutation_is_the_only_cosmetic_class():
    entry = {"line": 1,
             "orig": '    """Alpha docstring: + - here."""\n',
             "mutant": '    """Alpha docstring: + - HERE."""\n'}
    assert classify(entry, ORIG_FN) == "docstring"
    assert COSMETIC == frozenset({"docstring"})  # nothing else auto-passes


def test_logic_mutation_is_a_suspect():
    assert classify(_entry(changed="    return x - 1\n"), ORIG_FN) == "logic"
    # message text is contractual in this project: a changed string literal
    # outside a docstring is never cosmetic
    str_orig = 'def beta(x):\n    """Beta."""\n    return "reason: " + x\n'
    entry = _entry(changed='    return "other: " + x\n')
    assert classify(entry, str_orig) == "logic"


def test_classification_fails_closed_on_missing_or_unusable_records():
    assert classify(None, ORIG_FN) == "unattributed"
    assert classify(_entry(changed="    return x - 1\n"), None) == "unattributed"
    assert classify({"orig": "", "mutant": ""}, ORIG_FN) == "unattributed"
    assert classify(_entry(changed="    return x - 1\n"), "def broken(:\n") == \
        "unattributed"
    assert classify({"line": 0, "orig": "x", "mutant": "y"}, ORIG_FN) == "logic"


def test_multiline_change_spanning_out_of_docstring_is_logic():
    # change starts on the docstring line but extends past it: not provably
    # contained, so not cosmetic
    entry = {"line": 1, "last_line": 2,
             "orig": '    """Alpha docstring: + - here."""\n    return x + 1\n',
             "mutant": '    """Alpha."""\n    return x - 1\n'}
    assert classify(entry, ORIG_FN) == "logic"


# --- classifier kill pins (post-batch review 2026-09-12: each test here
#     kills a specific surviving mutant of the classifier itself; verified
#     against the mutmut variants, see scratch/killproof-mutation-bar) -------

def test_classify_numeric_first_statement_is_logic():
    # a numeric first statement is not a docstring: its mutation is logic,
    # never cosmetic (numbers are contractual in this project)
    orig = "def f():\n    123\n"
    assert classify({"line": 1, "orig": "123\n", "mutant": "124\n"},
                    orig) == "logic"


def test_classify_call_statement_first_is_logic():
    # a call expression as first statement is not a docstring either
    orig = "def f():\n    cleanup(1)\n"
    assert classify({"line": 1, "orig": "cleanup(1)\n",
                     "mutant": "cleanup(2)\n"}, orig) == "logic"


def test_classify_pass_statement_first_is_logic():
    orig = "def f():\n    pass\n"
    assert classify({"line": 1, "orig": "pass\n", "mutant": "pass2\n"},
                    orig) == "logic"


def test_classify_malformed_record_never_classes():
    # a record missing any of its three fields is malformed: unattributed,
    # even when a plausible line number would land inside a docstring
    orig = 'def f():\n    """Doc."""\n'
    assert classify({"line": 1}, orig) == "unattributed"
    assert classify({"line": 1, "mutant": "1\n"}, orig) == "unattributed"
    assert classify({"line": 1, "orig": "1\n"}, orig) == "unattributed"


def test_classify_first_docstring_line_is_cosmetic():
    # the docstring class includes the docstring's own first line; a boundary
    # off-by-one there would turn every genuine docstring mutant into a
    # suspect — needs a multi-line docstring so the two bounds differ
    orig = 'def f():\n    """Doc: value 1.\n\n    More prose here."""\n'
    assert classify({"line": 1, "orig": '    """Doc: value 2.\n',
                     "mutant": '    """Doc: value 1.\n'}, orig) == \
        "docstring"


def test_orig_fn_key_splits_only_on_last_scaffolding_marker():
    # a source function whose own name embeds the scaffolding marker: only
    # the final __mutmut_ segment is the variant suffix
    assert _orig_fn_key("pkg.x_f__mutmut_3__mutmut_12") == \
        "pkg.x_f__mutmut_3__mutmut_orig"
    assert _orig_fn_key("pkg.x_run_l1__mutmut_60") == \
        "pkg.x_run_l1__mutmut_orig"


# --- record writer (scratch mutated tree -> .mutdiff.json) ------------------

def _scratch_tree(tmp_path):
    """A minimal mutants/ tree as mutmut 3.7 writes it: per-file .spans
    (1-based inclusive line ranges into the mutated module), .meta verdicts,
    and the mutated module itself. Every generated function is padded with
    two leading blank lines and carries the mangled variant name on its def
    line — the scaffolding the writer must not report as a change."""
    orig = ['\n', '\n',
            'def x_f__mutmut_orig(x):\n',
            '    """Doc: value 1."""\n',
            '    return x + 1\n']
    variants = {
        # docstring-only mutation
        'x_f__mutmut_1': ['\n', '\n',
                          'def x_f__mutmut_1(x):\n',
                          '    """Doc: value 2."""\n',
                          '    return x + 1\n'],
        # body mutation
        'x_f__mutmut_2': ['\n', '\n',
                          'def x_f__mutmut_2(x):\n',
                          '    """Doc: value 1."""\n',
                          '    return x - 1\n'],
        # real def-line mutation (gained a default): must survive the
        # scaffolding normalization and be recorded on the def line
        'x_f__mutmut_3': ['\n', '\n',
                          'def x_f__mutmut_3(x=1):\n',
                          '    """Doc: value 1."""\n',
                          '    return x + 1\n'],
    }
    lines, spans = list(orig), {}
    for name, body in variants.items():
        start = len(lines) + 1
        lines.extend(body)
        spans[name] = [start, len(lines)]
    spans = {"x_f__mutmut_orig": [1, len(orig)], **spans}

    mod = tmp_path / "mutants" / "src" / "pkg"
    mod.mkdir(parents=True)
    (mod / "mod.py").write_text("".join(lines))
    (mod / "mod.py.spans").write_text(json.dumps(
        {"version": 1, "spans": spans}))
    (mod / "mod.py.meta").write_text(json.dumps(
        {"exit_code_by_key": {f"pkg.mod.{n}": 0 for n in variants}}))
    return mod


def test_writer_records_def_line_rename_and_classes_docstring(tmp_path):
    mod = _scratch_tree(tmp_path)
    assert write_mutation_records(tmp_path) == 1
    data = json.loads((mod / "mod.py.mutdiff.json").read_text())
    assert set(data["diffs"]) == {f"pkg.mod.x_f__mutmut_{i}" for i in (1, 2, 3)}

    # the scaffolding def-line rename is NOT reported: the docstring-only
    # mutant's changed range sits inside the docstring, so it classes
    # cosmetic end-to-end (line 0-based; docstring is line 3 of the fn)
    d1 = data["diffs"]["pkg.mod.x_f__mutmut_1"]
    assert (d1["line"], d1["last_line"]) == (3, 3)
    assert classify(d1, data["functions"]["pkg.mod.x_f__mutmut_orig"]) == \
        "docstring"

    # a body mutation records only the body line
    d2 = data["diffs"]["pkg.mod.x_f__mutmut_2"]
    assert (d2["line"], d2["last_line"]) == (4, 4)
    assert d2["orig"] == "    return x + 1\n"
    assert d2["mutant"] == "    return x - 1\n"


def test_writer_keeps_real_def_line_mutations(tmp_path):
    mod = _scratch_tree(tmp_path)
    write_mutation_records(tmp_path)
    data = json.loads((mod / "mod.py.mutdiff.json").read_text())
    d3 = data["diffs"]["pkg.mod.x_f__mutmut_3"]
    # the gained argument default is on the def line: normalization may not
    # swallow it, and a def-line change is never inside the docstring
    assert d3["line"] == 2
    assert 'x=1' in d3["mutant"] and 'x=1' not in d3["orig"]
    assert classify(d3, data["functions"]["pkg.mod.x_f__mutmut_orig"]) == \
        "logic"


def test_written_records_drive_the_bar_end_to_end(tmp_path):
    _scratch_tree(tmp_path)
    write_mutation_records(tmp_path)
    shard = load_shard(tmp_path, tmp_path)  # no manifest: digest None
    rep = evaluate([shard])
    assert rep["ok"] is False
    assert rep["survivor_classes"] == {"docstring": 1, "logic": 2}
    # the docstring survivor is cosmetic and never listed; the two logic
    # suspects are, sorted by (file, mutant)
    assert [(s["mutant"], s["class"]) for s in rep["suspects"]] == [
        ("pkg.mod.x_f__mutmut_2", "logic"),
        ("pkg.mod.x_f__mutmut_3", "logic"),
    ]


# --- residue cut pins (2026-09-21 night sitting: the fresh-generation
#     survivor block; baseline scratch/killproof-mutation-bar-base) ---------

def _residue_tree(tmp_path):
    """A mutants/ tree exercising every walk edge the writer must survive:
    a .zft sandbox mirror pair sorting first, a wrong-version spans index
    with verdicts, an orphan .spans with no .meta, one rich module whose
    index carries a scaffolding-only variant (identical to orig), a
    same-length two-line change with trailing body lines, variants two lines
    longer and two lines shorter than their original, and a variant with no
    __mutmut_orig entry, then a second real module for the count."""
    lines: list[str] = []
    spans: dict[str, list[int]] = {}

    def add(name, body):
        start = len(lines) + 1
        lines.extend(body)
        spans[name] = [start, len(lines)]

    add("x_f__mutmut_orig", [
        "\n", "\n", "def x_f__mutmut_orig(x):\n", '    """Doc: value 1."""\n',
        "    if x > 0:\n", "        return x + 1\n", "    return 0\n"])
    add("x_f__mutmut_1", [  # docstring-only mutation
        "\n", "\n", "def x_f__mutmut_1(x):\n", '    """Doc: value 2."""\n',
        "    if x > 0:\n", "        return x + 1\n", "    return 0\n"])
    add("x_f__mutmut_2", [  # scaffolding-only: identical except the def name
        "\n", "\n", "def x_f__mutmut_2(x):\n", '    """Doc: value 1."""\n',
        "    if x > 0:\n", "        return x + 1\n", "    return 0\n"])
    add("x_f__mutmut_3", [  # same-length change: two adjacent lines, and the
        # body continues after them so over-extended ranges are observable
        "\n", "\n", "def x_f__mutmut_3(x):\n", '    """Doc: value 1."""\n',
        "    if x >= 0:\n", "        return x + 2\n", "    return 0\n"])
    add("x_f__mutmut_4", [  # two lines longer than its original
        "\n", "\n", "def x_f__mutmut_4(x):\n", '    """Doc: value 1."""\n',
        "    if x > 0:\n", "        y = x + 1\n", "        y += 2\n",
        "        return y\n", "    return 0\n"])
    add("x_f__mutmut_5", [  # two lines shorter than its original
        "\n", "\n", "def x_f__mutmut_5(x):\n", '    """Doc: value 1."""\n',
        "    return x - 1\n"])
    add("x_g__mutmut_1", [  # no x_g__mutmut_orig entry exists at all
        "\n", "\n", "def x_g__mutmut_1(x):\n", "    return x\n"])
    add("x_h__mutmut_orig", [
        "\n", "\n", "def x_h__mutmut_orig():\n", "    return 1\n"])
    add("x_h__mutmut_1", [
        "\n", "\n", "def x_h__mutmut_1():\n", "    return 2\n"])

    root = tmp_path / "mutants"
    mod = root / "src" / "pkg"
    mod.mkdir(parents=True)
    (mod / "mod.py").write_text("".join(lines))
    (mod / "mod.py.spans").write_text(
        json.dumps({"version": 1, "spans": spans}))
    (mod / "mod.py.meta").write_text(json.dumps(
        {"exit_code_by_key": {f"pkg.mod.{n}": 0 for n in spans}}))

    # a second real module: the count pin needs more than one record
    (mod / "other.py").write_text(
        "\n\ndef x_o__mutmut_orig():\n    return 1\n"
        "\n\ndef x_o__mutmut_1():\n    return 2\n")
    (mod / "other.py.spans").write_text(json.dumps(
        {"version": 1, "spans": {"x_o__mutmut_orig": [1, 4],
                                 "x_o__mutmut_1": [5, 8]}}))
    (mod / "other.py.meta").write_text(json.dumps(
        {"exit_code_by_key": {"pkg.other.x_o__mutmut_1": 0}}))

    # wrong-version index with verdicts, sorts before everything under src/
    (root / "aaa.py.meta").write_text(json.dumps({"exit_code_by_key": {}}))
    (root / "aaa.py.spans").write_text(
        json.dumps({"version": 2, "spans": {}}))
    # a .zft sandbox mirror pair, sorts before both
    mirror = root / ".zft" / "sb"
    mirror.mkdir(parents=True)
    (mirror / "m.py").write_text("x = 1\n")
    (mirror / "m.py.meta").write_text(json.dumps({"exit_code_by_key": {}}))
    (mirror / "m.py.spans").write_text(
        json.dumps({"version": 1, "spans": {}}))
    # an orphan .spans (no verdicts) sorting before the real modules
    (mod / "aaa.py.spans").write_text(
        json.dumps({"version": 1, "spans": {}}))
    return mod


def test_writer_walk_skips_non_records_and_counts_only_real_files(tmp_path):
    # skip-and-continue at every non-record: the walk must reach both real
    # modules (the two break mutants would strand them) and count exactly
    # two written records
    mod = _residue_tree(tmp_path)
    assert write_mutation_records(tmp_path) == 2
    assert not (tmp_path / "mutants" / ".zft" / "sb" / "m.py.mutdiff.json"
                ).exists()  # the mirror pair never gets a record
    assert (mod / "mod.py.mutdiff.json").exists()
    assert (mod / "other.py.mutdiff.json").exists()
    data = json.loads((mod / "mod.py.mutdiff.json").read_text())
    # the orig-less x_g variant is skipped, and the walk still diffs x_h
    assert "pkg.mod.x_g__mutmut_1" not in data["diffs"]
    assert "pkg.mod.x_h__mutmut_1" in data["diffs"]


def test_writer_records_exact_multi_line_change_bounds(tmp_path):
    # the changed-range texts are byte-exact: no join separator, no
    # over-extended last line, and a scaffolding-only variant never blocks
    # the variants recorded after it
    mod = _residue_tree(tmp_path)
    write_mutation_records(tmp_path)
    data = json.loads((mod / "mod.py.mutdiff.json").read_text())
    assert set(data["diffs"]) == {
        f"pkg.mod.x_f__mutmut_{i}" for i in (1, 3, 4, 5)} | {
        "pkg.mod.x_h__mutmut_1"}  # _2 is scaffolding-only: no diff
    d3 = data["diffs"]["pkg.mod.x_f__mutmut_3"]
    assert (d3["line"], d3["last_line"]) == (4, 5)
    assert d3["orig"] == "    if x > 0:\n        return x + 1\n"
    assert d3["mutant"] == "    if x >= 0:\n        return x + 2\n"
    # length-mismatching variants still record (the comparison uses a None
    # sentinel past the shorter list, never an index error)
    assert (data["diffs"]["pkg.mod.x_f__mutmut_4"]["line"],
            data["diffs"]["pkg.mod.x_f__mutmut_4"]["last_line"]) == (5, 8)
    assert (data["diffs"]["pkg.mod.x_f__mutmut_5"]["line"],
            data["diffs"]["pkg.mod.x_f__mutmut_5"]["last_line"]) == (4, 6)
    assert data["diffs"]["pkg.mod.x_h__mutmut_1"]["mutant"] == "    return 2\n"


def test_written_mutdiff_format_pins_version_key(tmp_path):
    # the .mutdiff.json envelope is part of the shard format the bar joins
    # on: version key spelled and valued exactly
    mod = _residue_tree(tmp_path)
    write_mutation_records(tmp_path)
    data = json.loads((mod / "mod.py.mutdiff.json").read_text())
    assert list(data) == ["version", "functions", "diffs"]
    assert data["version"] == 1


# --- evaluate ---------------------------------------------------------------

def _shard(verdicts, diffs=None, functions=None, digest_ok=None):
    return ShardInput(name="mut-fixture", files=[FileVerdicts(
        relpath="src/x.py", verdicts=verdicts,
        diffs=diffs or {}, functions=functions or {},
        source_digest_ok=digest_ok)])


def _fixture_logic_mutant():
    key = "m.x_alpha__mutmut_1"
    return key, {key: _entry(changed="    return x - 1\n")}, {"m.x_alpha__mutmut_orig": ORIG_FN}


def test_bar_fails_on_logic_survivor_and_passes_on_docstring_only():
    key, diffs, functions = _fixture_logic_mutant()
    doc_entry = {"line": 1,
                 "orig": '    """Alpha docstring: + - here."""\n',
                 "mutant": '    """Alpha docstring: + - HERE."""\n'}
    verdicts = {key: 0, "m.x_alpha__mutmut_2": 0}
    diffs = {**diffs, "m.x_alpha__mutmut_2": doc_entry}
    rep = evaluate([_shard(verdicts, diffs, functions)])
    assert rep["ok"] is False
    assert [s["mutant"] for s in rep["suspects"]] == [key]
    assert rep["survivor_classes"] == {"docstring": 1, "logic": 1}


def test_suspect_report_carries_the_mutation_for_triage():
    key, diffs, functions = _fixture_logic_mutant()
    rep = evaluate([_shard({key: 0}, diffs, functions)])
    assert rep["suspects"][0]["mutation"] == "'return x + 1' -> 'return x - 1'"


def test_no_tests_and_not_checked_block_the_bar():
    rep = evaluate([_shard({"m.x_alpha__mutmut_1": 33,
                            "m.x_alpha__mutmut_2": None,
                            "m.x_beta__mutmut_1": 36})])
    assert rep["ok"] is False
    classes = sorted(s["class"] for s in rep["suspects"])
    assert classes == ["no_tests", "not_checked", "timeout"]
    assert rep["totals"]["kill_rate"] == 0.0


def test_waivers_clear_suspects_and_stale_ones_are_reported():
    key, diffs, functions = _fixture_logic_mutant()
    rep = evaluate([_shard({key: 0}, diffs, functions)],
                   waivers={key: {"reason": "verified equivalent",
                                  "killing_test": None},
                            "m.x_ghost__mutmut_9": {
                                "reason": "mutant no longer generated"}})
    assert rep["ok"] is True
    assert rep["waived_count"] == 1
    assert rep["stale_waivers"] == ["m.x_ghost__mutmut_9"]
    assert all(s["waived"] for s in rep["suspects"])


def test_unknown_exit_code_is_suspicious_not_killed():
    rep = evaluate([_shard({"m.x_alpha__mutmut_1": 99})])
    assert rep["ok"] is False
    assert rep["suspects"][0]["class"] == "suspicious"


def test_source_drift_overrides_mutation_classification():
    key, diffs, functions = _fixture_logic_mutant()
    doc_entry = {"line": 1,
                 "orig": '    """Alpha docstring: + - here."""\n',
                 "mutant": '    """Alpha docstring: + - HERE."""\n'}
    diffs = {**diffs, "m.x_alpha__mutmut_2": doc_entry}
    rep = evaluate([_shard({key: 0, "m.x_alpha__mutmut_2": 0}, diffs, functions,
                           digest_ok=False)])
    # even a docstring-class mutation must class source_drift: the record
    # describes code that no longer exists in this tree
    assert rep["survivor_classes"] == {"source_drift": 2}
    assert rep["ok"] is False


# --- report contract (post-batch review 2026-09-12: exact-dict pins of
#     every field the morning report, the waiver sheet and the paper read) --

def test_evaluate_report_contract_pinned_field_by_field():
    doc = {"line": 1, "orig": '    """D."""\n', "mutant": '    """d."""\n'}
    verdicts = {"m.x_alpha__mutmut_1": 0,   # docstring survivor (cosmetic)
                "m.x_alpha__mutmut_2": 0,   # logic survivor
                "m.x_alpha__mutmut_3": 0,   # unattributed: record w/o texts
                "m.x_alpha__mutmut_4": 1,   # killed
                "m.x_alpha__mutmut_5": 1,   # killed
                "m.x_alpha__mutmut_6": 36}  # timeout
    diffs = {"m.x_alpha__mutmut_1": doc,
             "m.x_alpha__mutmut_2": _entry(changed="    return x - 1\n"),
             "m.x_alpha__mutmut_3": {"line": 2},
             "m.x_alpha__mutmut_6": {"line": 2, "orig": "a",
                                     "mutant": "b"},
             "m.x_alpha__mutmut_7": doc}
    verdicts["m.x_alpha__mutmut_7"] = 0   # second docstring survivor
    rep = evaluate([_shard(verdicts, diffs,
                           {"m.x_alpha__mutmut_orig": ORIG_FN})])
    assert rep["ok"] is False
    assert rep["bar"] == "no unwaived suspects"
    assert rep["totals"] == {"killed": 2, "survived": 4, "no_tests": 0,
                             "skipped": 0, "suspicious": 0, "timeout": 1,
                             "not_checked": 0, "mutants": 7,
                             "kill_rate": 0.2857}
    assert rep["shards"]["mut-fixture"] == {
        "killed": 2, "survived": 4, "timeout": 1,
        "survivor_classes": {"docstring": 2, "logic": 1,
                             "unattributed": 1}}
    assert rep["survivor_classes"] == {"docstring": 2, "logic": 1,
                                       "unattributed": 1}
    assert rep["suspects"] == [
        {"shard": "mut-fixture", "mutant": "m.x_alpha__mutmut_2",
         "file": "src/x.py", "class": "logic",
         "mutation": "'return x + 1' -> 'return x - 1'",
         "waived": False, "reason": None, "killing_test": None},
        {"shard": "mut-fixture", "mutant": "m.x_alpha__mutmut_3",
         "file": "src/x.py", "class": "unattributed",
         "mutation": "'' -> ''",
         "waived": False, "reason": None, "killing_test": None},
        {"shard": "mut-fixture", "mutant": "m.x_alpha__mutmut_6",
         "file": "src/x.py", "class": "timeout",
         "mutation": "'a' -> 'b'",
         "waived": False, "reason": None, "killing_test": None}]


def test_waived_suspects_leave_the_report_counted():
    # waived entries are counted, not listed: the report's suspects are the
    # unwaived queue, and waived_count is the audit trail of what left it
    key, diffs, functions = _fixture_logic_mutant()
    rep = evaluate(
        [_shard({key: 0}, diffs, functions), _shard({"m.x_beta__mutmut_1": 36})],
        waivers={key: {"reason": "reviewed equivalent",
                       "killing_test": "tests/unit/test_x.py::test_y"},
                 "m.x_beta__mutmut_1": {"reason": "reviewed clock edge",
                                        "killing_test": None}})
    assert rep["ok"] is True
    assert rep["waived_count"] == 2
    assert rep["suspects"] == []


def test_empty_bar_report_pins_degenerate_totals():
    # no shards at all: ok with a None kill_rate, never a division by zero
    rep = evaluate([])
    assert rep["ok"] is True
    assert rep["totals"] == {"killed": 0, "survived": 0, "no_tests": 0,
                             "skipped": 0, "suspicious": 0, "timeout": 0,
                             "not_checked": 0, "mutants": 0, "kill_rate": None}
    assert rep["suspects"] == []
    assert rep["stale_waivers"] == []


def test_suspect_mutation_field_defaults_on_record_missing_texts():
    diffs = {"m.x_alpha__mutmut_1": {"line": 2}}  # orig/mutant texts missing
    rep = evaluate([_shard({"m.x_alpha__mutmut_1": 0}, diffs,
                           {"m.x_alpha__mutmut_orig": ORIG_FN})])
    s = rep["suspects"][0]
    assert s["class"] == "unattributed"
    assert s["mutation"] == "'' -> ''"


# --- load_shard -------------------------------------------------------------

def test_load_shard_reads_meta_and_mutdiff(tmp_path):
    shard_dir = tmp_path / "results-mut-demo" / "mutants" / "src" / "pkg"
    shard_dir.mkdir(parents=True)
    (shard_dir / "mod.py.meta").write_text(json.dumps(
        {"exit_code_by_key": {"pkg.mod.x_f__mutmut_1": 0, "pkg.mod.x_f__mutmut_2": 1}}))
    (shard_dir / "mod.py.mutdiff.json").write_text(json.dumps({
        "version": 1,
        "functions": {"pkg.mod.x_f__mutmut_orig": "def f(x):\n    return x\n"},
        "diffs": {"pkg.mod.x_f__mutmut_1": {
            "line": 1, "orig": "    return x\n", "mutant": "    return x - 1\n"}},
    }))
    src_root = tmp_path / "src"
    (src_root / "pkg").mkdir(parents=True)
    (src_root / "pkg" / "mod.py").write_text("def f(x):\n    return x - 1\n")

    shard = load_shard(tmp_path / "results-mut-demo", tmp_path)
    assert shard.name == "mut-demo"
    fv = shard.files[0]
    assert fv.verdicts["pkg.mod.x_f__mutmut_1"] == 0
    assert fv.diffs["pkg.mod.x_f__mutmut_1"]["mutant"] == "    return x - 1\n"
    assert fv.functions["pkg.mod.x_f__mutmut_orig"] == "def f(x):\n    return x\n"
    assert evaluate([shard])["suspects"][0]["class"] == "logic"


def test_load_shard_without_mutdiff_classes_survivors_unattributed(tmp_path):
    shard_dir = tmp_path / "results-mut-demo" / "mutants" / "src"
    shard_dir.mkdir(parents=True)
    (shard_dir / "a.py.meta").write_text(json.dumps(
        {"exit_code_by_key": {"src.a.x_f__mutmut_1": 0}}))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f(x):\n    return x\n")

    shard = load_shard(tmp_path / "results-mut-demo", tmp_path)
    rep = evaluate([shard])
    assert rep["suspects"][0]["class"] == "unattributed"
    assert rep["ok"] is False


def test_source_manifest_mismatch_forces_source_drift_class(tmp_path):
    import hashlib

    shard_dir = tmp_path / "results-mut-demo"
    meta = shard_dir / "mutants" / "src" / "a.py.meta"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"exit_code_by_key": {"src.a.x_f__mutmut_1": 0}}))
    (shard_dir / "mutants" / "src" / "a.py.mutdiff.json").write_text(json.dumps({
        "functions": {"src.a.x_f__mutmut_orig": "def f(x):\n    return x\n"},
        "diffs": {"src.a.x_f__mutmut_1": {
            "line": 1, "orig": "    return x\n", "mutant": "    return x - 1\n"}},
    }))
    src_root = tmp_path / "src"
    src_root.mkdir()
    (src_root / "a.py").write_text("def f(x):\n    return x\n")
    matching = hashlib.sha256(b"def f(x):\n    return x\n").hexdigest()
    (shard_dir / "source-manifest.txt").write_text(
        f"{matching}  ./src/a.py\n"
        f"{'0' * 64}  ./src/gone.py\n")

    shard = load_shard(shard_dir, tmp_path)
    assert shard.files[0].source_digest_ok is True
    assert evaluate([shard])["suspects"][0]["class"] == "logic"

    # now drift the live file: the mutation record describes vanished code,
    # so the survivor must class source_drift, never cosmetic
    (src_root / "a.py").write_text("def f(x):\n    return x + 2\n")
    shard = load_shard(shard_dir, tmp_path)
    assert shard.files[0].source_digest_ok is False
    rep = evaluate([shard])
    assert rep["suspects"][0]["class"] == "source_drift"
    assert rep["ok"] is False


def test_load_shard_skips_sandbox_evidence_mirrors(tmp_path):
    mirror = tmp_path / "results-mut-demo" / "mutants" / ".zft" / "sb"
    mirror.mkdir(parents=True)
    (mirror / "m.py.meta").write_text(json.dumps(
        {"exit_code_by_key": {"sb.m.x_f__mutmut_1": None}}))
    real = tmp_path / "results-mut-demo" / "mutants" / "src"
    real.mkdir(parents=True)
    (real / "a.py.meta").write_text(json.dumps(
        {"exit_code_by_key": {"src.a.x_f__mutmut_1": 0}}))

    shard = load_shard(tmp_path / "results-mut-demo", tmp_path / "empty-src-root")
    assert [f.relpath for f in shard.files] == ["src/a.py"]  # mirror excluded


def test_load_shard_sidecars_missing_keys_degrade_to_empty(tmp_path):
    # an empty .meta or a record lacking diffs/functions must degrade to
    # empty dicts, never crash, and the no-manifest digest state stays None
    shard_dir = tmp_path / "results-mut-demo" / "mutants" / "src"
    shard_dir.mkdir(parents=True)
    (shard_dir / "a.py.meta").write_text(json.dumps({}))
    (shard_dir / "a.py.mutdiff.json").write_text(json.dumps({"version": 1}))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f(x):\n    return x\n")

    fv = load_shard(tmp_path / "results-mut-demo", tmp_path).files[0]
    assert fv.verdicts == {}
    assert fv.diffs == {}
    assert fv.functions == {}
    assert fv.source_digest_ok is None


def test_load_waivers_rejects_bad_shapes_with_pinned_message(tmp_path):
    message = ("waivers file must be a JSON object of "
               "{mutant: {reason, killing_test}}")
    p = tmp_path / "waivers.json"
    p.write_text(json.dumps({"m.x__mutmut_1": "not a dict"}))
    with pytest.raises(ValueError) as ei:
        load_waivers(p)
    assert str(ei.value) == message
    p.write_text(json.dumps(["a", "b"]))
    with pytest.raises(ValueError) as ei:
        load_waivers(p)
    assert str(ei.value) == message


# --- CLI contract -----------------------------------------------------------

@pytest.fixture()
def shard_dir(tmp_path):
    base = tmp_path / "results-mut-demo" / "mutants" / "src"
    base.mkdir(parents=True)
    (base / "a.py.meta").write_text(json.dumps(
        {"exit_code_by_key": {"src.a.x_f__mutmut_1": 0}}))
    (base / "a.py.mutdiff.json").write_text(json.dumps({
        "functions": {"src.a.x_f__mutmut_orig": "def f(x):\n    return x\n"},
        "diffs": {"src.a.x_f__mutmut_1": {
            "line": 1, "orig": "    return x\n", "mutant": "    return x - 1\n"}},
    }))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f(x):\n    return x\n")
    return tmp_path / "results-mut-demo"


def test_cli_mutation_bar_exit_1_on_suspects_with_json(capsys, shard_dir, tmp_path):
    rc = main(["mutation-bar", str(shard_dir), "--source-root", str(tmp_path)])
    assert rc == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["suspects"][0]["mutant"] == "src.a.x_f__mutmut_1"


def test_cli_mutation_bar_exit_0_when_waived(capsys, shard_dir, tmp_path):
    waivers = tmp_path / "waivers.json"
    waivers.write_text(json.dumps(
        {"src.a.x_f__mutmut_1": {"reason": "pinned equivalent", "killing_test": None}}))
    rc = main(["mutation-bar", str(shard_dir), "--waivers", str(waivers),
               "--source-root", str(tmp_path)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_cli_mutation_bar_exit_2_without_shards():
    assert main(["mutation-bar"]) == 2

def test_source_manifest_split_keeps_names_with_double_spaces(tmp_path):
    # kills load_shard _22: a manifest line splits on the FIRST double-space
    # run; a filename containing one must survive intact (rpartition would
    # eat it and the digest check would silently degrade to None)
    import hashlib

    shard_dir = tmp_path / "results-mut-demo"
    meta = shard_dir / "mutants" / "src" / "a  b.py.meta"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps(
        {"exit_code_by_key": {"src.a  b.x_f__mutmut_1": 0}}))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a  b.py").write_text("def f(x):\n    return x\n")
    digest = hashlib.sha256(b"def f(x):\n    return x\n").hexdigest()
    (shard_dir / "source-manifest.txt").write_text(
        f"{digest}  ./src/a  b.py\n")

    shard = load_shard(shard_dir, tmp_path)
    assert shard.files[0].source_digest_ok is True
