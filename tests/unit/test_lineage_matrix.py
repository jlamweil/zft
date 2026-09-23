"""Lineage/matrix kill-shard pins (2026-09-15 cut — 62 suspects: 53 kills, 9 waivers).

lineage/matrix.py decides what counts as a deliverable element and what counts
as reverse-coverage scope: the element-id grammar (``rel::qualname`` /
``rel#slug``), the public/top-level/non-test classifier the L2 gate enforces,
fence-aware heading slugs, and the enumeration order evidence cites. Each pin
states one contract fact; the waiver sheet carries the nine reviewed waivers
(eight equivalents + the one structurally unconvertible hang) with reasons.

Subprocess-pin mechanics (load-bearing twice over): mutmut selects the tests
to run against a mutant by *parent-process coverage*, so a subprocess pin that
only exercises the mutation in a child is invisible to selection and never
fires — each subprocess pin therefore opens with a loop-free in-process call
(``_md_elements(rel, "")`` / ``list_all_elements(empty_dir)``: no lines beyond
the function entry execute, so no mutant variant can hang it) purely to
register coverage. The subprocess body itself carries a 10 s timeout: a mutant
that spins the dedup loop fails the pin fast instead of hanging the mutmut
worker into a wall-limit ⏰ suspect (30 s pins × a selected-suite slice can
outlive mutmut's ``(estimated + 1) × 15`` wall limit and re-mark the mutant
timeout; 10 s cannot). One limit remains, documented on the sheet: mutmut's
selection order is coverage-derived, not definition order, so the inverted
dedup-condition mutant (which non-terminates on loop ENTRY, i.e. on any
heading) always hangs an in-process pin before any subprocess sentinel is
reached — no pin ordering can convert it; the counter mutants (which enter
the loop only on duplicates) die here via the 3-duplicate child.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from zft.lineage import matrix
from zft.lineage.matrix import (
    _bound_element_ids,
    _is_reverse_coverage_element,
    _iter_element_files,
    _md_elements,
    list_all_elements,
)


def _run_in_subprocess(script: str, args: list[str], timeout_s: int = 10,
                       env_overrides: dict | None = None):
    """Run *script* against the tree-local src; the tree-local src must be on
    PYTHONPATH (a plain subprocess would import the installed original, not
    the tree under test). MUTANT_UNDER_TEST rides along in os.environ so the
    child imports the same variant the worker is scoring."""
    repo_src = Path(__file__).resolve().parents[2] / "src"
    env = {**os.environ, **(env_overrides or {}), "PYTHONPATH": str(repo_src)}
    return subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True, text=True, timeout=timeout_s, env=env,
    )


# ---------------------------------------------------------------------------
# Dedup sentinels — subprocess-shaped contract pins for the duplicate-heading
# disambiguators.
#
# The dedup loop is the one place in this module where a mutant can spin: the
# inverted-condition variant non-terminates on loop entry (any heading), the
# constant/decrementing counter variants on the third duplicate. A worker-side
# hang is scored by mutmut as a wall-limit timeout suspect, so these pins run
# every duplicate input in a SUBPROCESS child with a 10 s timeout: the child
# hangs, the pin fails, the suite goes red in seconds instead of hanging (and
# any future regression of the dedup loop fails CI the same way). The
# loop-free in-process coverage marker exists because mutmut selects a
# mutant's tests by parent-process coverage — without it these pins would
# never be selected and the counter mutants would survive. Selection order is
# coverage-derived, so this placement does not control which pin runs first;
# the inverted-condition mutant therefore remains a scored timeout (waived on
# the sheet — mutmut structural), while the counter mutants die here.
# ---------------------------------------------------------------------------

def test_duplicate_headings_get_ordered_disambiguators():
    """Two duplicate headings dedup to the base slug and -1, in order."""
    _md_elements("d.md", "")  # loop-free coverage marker: see module docstring
    script = textwrap.dedent("""\
        import json
        from zft.lineage.matrix import _md_elements
        print(json.dumps(_md_elements("d.md", "# Same\\n# Same\\n")))
    """)
    proc = _run_in_subprocess(script, [])
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["d.md#same", "d.md#same-1"]


def test_duplicate_dedup_terminates_and_counts_up_from_one():
    """Three duplicate headings dedup to -1/-2 and the loop terminates, so a
    mutant that spins the dedup loop (constant or decrementing counter,
    inverted condition) fails this pin at its 10 s timeout instead of hanging
    the mutmut worker into a wall-limit timeout suspect."""
    _md_elements("d.md", "")  # loop-free coverage marker: see module docstring
    script = textwrap.dedent("""\
        import json
        from zft.lineage.matrix import _md_elements
        print(json.dumps(_md_elements("d.md", "# Same\\n# Same\\n# Same\\n")))
    """)
    proc = _run_in_subprocess(script, [])
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["d.md#same", "d.md#same-1", "d.md#same-2"]


# ---------------------------------------------------------------------------
# _is_reverse_coverage_element — the reverse-coverage scope classifier.
# Contract: public, top-level, non-test src/ elements only; everything else
# is excluded, and each exclusion rule is individually load-bearing.
# ---------------------------------------------------------------------------

def test_non_src_element_is_out_of_scope():
    assert _is_reverse_coverage_element("README.md#intro") is False


def test_bare_src_prefix_with_no_path_is_out_of_scope():
    assert _is_reverse_coverage_element("src/") is False


def test_tests_directory_is_out_of_scope():
    assert _is_reverse_coverage_element("src/tests/util.py::helper") is False


def test_singular_test_directory_is_out_of_scope():
    assert _is_reverse_coverage_element("src/test/util.py::helper") is False


def test_test_prefixed_module_is_out_of_scope():
    assert _is_reverse_coverage_element("src/test_foo.py::x") is False


def test_suffix_test_module_is_out_of_scope():
    assert _is_reverse_coverage_element("src/mod_test.py::f") is False


def test_suffix_tests_module_is_out_of_scope():
    assert _is_reverse_coverage_element("src/mod_tests.py::f") is False


def test_nested_qualname_is_out_of_scope():
    assert _is_reverse_coverage_element("src/a.py::Mod.meth") is False


def test_private_top_level_is_out_of_scope():
    assert _is_reverse_coverage_element("src/a.py::_private") is False


def test_public_md_element_is_in_scope():
    assert _is_reverse_coverage_element("src/pkg.md#title") is True


def test_public_py_element_is_in_scope():
    assert _is_reverse_coverage_element("src/a.py::plain") is True


def test_multi_segment_qualname_still_in_scope_at_classifier_level():
    """The classifier excludes dot-joined (nested) qualnames, not ::-joined
    segments — 'src/a.py::A::b' passes the public/top-level checks."""
    assert _is_reverse_coverage_element("src/a.py::A::b") is True


def test_private_segment_before_a_later_separator_is_caught():
    """The private-name rule reads the FIRST ::-segment: 'src/a.py::_x::y'
    starts private, so it is out of scope even though the tail is public."""
    assert _is_reverse_coverage_element("src/a.py::_x::y") is False


def test_test_dir_marker_after_a_second_separator_is_still_caught():
    """The rel path is split at the FIRST '::': in 'src/tests::weird::f' the
    rel component is 'src/tests', so the tests-directory rule fires."""
    assert _is_reverse_coverage_element("src/tests::weird::f") is False


def test_test_file_marker_before_the_separator_is_still_caught():
    """'src/pkg/_test.py::f' is excluded by the _test.py suffix rule on the
    real rel path, not rescued by the trailing ::f segment."""
    assert _is_reverse_coverage_element("src/pkg/_test.py::f") is False


def test_fragment_separator_resolves_before_the_directory_rules():
    """'#' is stripped from the rel path before the directory rules run:
    in 'src/tests#a#b::f' the rel is 'src/tests' (first-fragment rule),
    so the tests-directory rule fires."""
    assert _is_reverse_coverage_element("src/tests#a#b::f") is False


def test_fragment_of_a_bare_src_anchor_does_not_invent_a_path():
    """'src/#x' strips to the bare prefix 'src/' — no path parts — so it is
    out of scope rather than classified by the fragment text."""
    assert _is_reverse_coverage_element("src/#x") is False


def test_first_fragment_wins_over_the_rest_of_the_line():
    """Only text before the first '#' is path: in 'src/tests#x y::f' the
    fragment ' y' never rescues the element from the tests-dir rule."""
    assert _is_reverse_coverage_element("src/tests#x y::f") is False


def test_whitespace_is_never_a_path_separator():
    """Paths may contain spaces: 'src/tests x.py::f' is one component
    'tests x.py' (public), not split into a 'tests' directory."""
    assert _is_reverse_coverage_element("src/tests x.py::f") is True


# ---------------------------------------------------------------------------
# _md_elements — fence-aware GitHub-style heading slugs.
# ---------------------------------------------------------------------------

def test_fence_lines_do_not_stop_heading_scan():
    """A fence line (open or close) is consumed and the scan continues:
    headings after a fenced block are elements."""
    assert _md_elements("d.md", "```python\nx = 1\n```\n\n# After\n") == ["d.md#after"]


def test_headings_inside_a_fence_are_not_elements():
    assert _md_elements("d.md", "```\n# Inside\n```\n# After\n") == ["d.md#after"]


def test_mismatched_fence_char_does_not_close_the_fence():
    """A ``` fence is closed only by backticks: a ~~~ line inside stays
    fenced, so '# b' between them is not an element."""
    text = "```\n# a\n~~~\n# b\n```\n# c\n"
    assert _md_elements("d.md", text) == ["d.md#c"]


def test_shorter_fence_of_same_char_does_not_close_the_fence():
    """The closing fence must be at least as long as the opener: ``` does
    not close a ```` fence."""
    text = "````\n# a\n```\n# b\n````\n# c\n"
    assert _md_elements("d.md", text) == ["d.md#c"]


def test_non_heading_lines_do_not_stop_the_scan():
    assert _md_elements("d.md", "plain prose line\n\n# After\n") == ["d.md#after"]


def test_empty_heading_is_skipped_and_does_not_stop_the_scan():
    assert _md_elements("d.md", "# \n# After\n") == ["d.md#after"]


def test_closing_hash_suffix_is_stripped_from_the_title():
    """ATX closing sequences are not part of the title: '# Title ##'
    slugs as 'title'."""
    assert _md_elements("d.md", "# Title ##\n") == ["d.md#title"]


def test_slug_joins_words_with_single_dashes():
    assert _md_elements("d.md", "# Multi Word Title\n") == ["d.md#multi-word-title"]


def test_slug_drops_punctuation_without_a_trace():
    assert _md_elements("d.md", "# Hello, World!\n") == ["d.md#hello-world"]


# ---------------------------------------------------------------------------
# _iter_element_files — deterministic traversal, skips are local.
# ---------------------------------------------------------------------------

def test_non_element_file_does_not_stop_the_directory_scan(tmp_path, monkeypatch):
    """Skipping a non-.py/.md file must not stop the scan of its directory:
    a.py after z.txt is still enumerated (order as yielded)."""
    calls = [
        (tmp_path, ["sub"], ["z.txt", "a.py"]),
        (tmp_path / "sub", [], ["b.md"]),
    ]
    monkeypatch.setattr(matrix.os, "walk", lambda root: iter(calls))
    assert _iter_element_files(tmp_path) == [tmp_path / "a.py", tmp_path / "sub" / "b.md"]


def test_iter_prunes_ignored_and_dot_directories(tmp_path):
    (tmp_path / "mod.py").write_text("def a():\n    pass\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.py").write_text("def hidden():\n    pass\n")
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "y.md").write_text("# Hidden\n")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "z.md").write_text("# Hidden\n")
    assert _iter_element_files(tmp_path) == [tmp_path / "mod.py"]


# ---------------------------------------------------------------------------
# list_all_elements — reading is robust and explicit.
# ---------------------------------------------------------------------------

def test_unreadable_element_file_is_skipped_not_fatal(tmp_path):
    """An unreadable element file (broken symlink) is skipped and the rest
    of the (sorted) enumeration continues."""
    (tmp_path / "aaa.md").symlink_to(tmp_path / "missing-target")
    (tmp_path / "bbb.md").write_text("# Real\n")
    assert list_all_elements(tmp_path) == ["bbb.md#real"]


def test_element_walk_skips_scratch_and_mutants_mirrors(tmp_path):
    """Walker parity with extract._iter_source_files (campaign-host lesson,
    2026-09-07; drifted apart by 2026-09-15): kill-shard working copies live
    under scratch/<shard>/copy{,/mutants} and campaign trees shift names
    (mutants-prev-*), and none of it is ever a deliverable element — the
    matrix walk must apply the extractor's skip policy, or every mirror
    function pollutes the reverse-coverage universe (a shard night left
    ~19k .py copies in scratch/ and each check ast-parsed them all)."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text(
        "def real_element():\n    pass\n", encoding="utf-8")
    mirror = tmp_path / "scratch" / "shard" / "copy" / "mutants" / "src"
    mirror.mkdir(parents=True)
    (mirror / "real.py").write_text(
        "def mirror_element():\n    pass\n", encoding="utf-8")
    campaign = tmp_path / "mutants-prev-l0l3" / "src"
    campaign.mkdir(parents=True)
    (campaign / "real.py").write_text(
        "def campaign_element():\n    pass\n", encoding="utf-8")
    elements = list_all_elements(tmp_path)
    assert "src/real.py::real_element" in elements
    assert not any("mirror_element" in e or "campaign_element" in e
                   for e in elements)


def test_invalid_utf8_is_replaced_not_raised(tmp_path):
    """Element extraction never dies on undecodable bytes: replacement
    chars flow into the slug (and drop out of it)."""
    (tmp_path / "bad.md").write_bytes(b"# T\xffitle\n")
    assert list_all_elements(tmp_path) == ["bad.md#title"]


def test_extraction_decodes_utf8_regardless_of_host_locale(tmp_path):
    """The explicit ``encoding="utf-8"`` is load-bearing: even on a host
    whose locale is POSIX/ASCII, extraction decodes element files as UTF-8
    (é survives into the slug) and replaces undecodable bytes (the lone
    \\xff drops out instead of raising). Run in a subprocess with the locale
    coercion escapes disabled — this venv's interpreter defaults to UTF-8
    mode, which is exactly why the kwarg drop survives an in-process pin —
    and a loop-free in-process ``list_all_elements`` call on an empty dir so
    mutmut's coverage-based selection sees this pin (module docstring)."""
    list_all_elements(tmp_path)  # empty dir: no files, no read path executed
    (tmp_path / "u.md").write_bytes(b"# Caf\xc3\xa9\n# T\xffitle\n")
    script = textwrap.dedent("""\
        import json, sys
        from pathlib import Path
        from zft.lineage.matrix import list_all_elements
        print(json.dumps(list_all_elements(Path(sys.argv[1]))))
    """)
    proc = _run_in_subprocess(
        script, [str(tmp_path)],
        env_overrides={"LC_ALL": "C", "PYTHONCOERCECLOCALE": "0",
                       "PYTHONUTF8": "0"},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["u.md#café", "u.md#title"]


# ---------------------------------------------------------------------------
# _bound_element_ids — a binding without a file is skipped, not fatal.
# ---------------------------------------------------------------------------

def test_fileless_binding_is_skipped_without_stopping_the_scan():
    bindings = [
        {"symbol": "orphan"},
        {"file": "src/a.py", "symbol": "b"},
    ]
    assert _bound_element_ids(bindings) == {"src/a.py::b"}
