"""WP-D1: deliverable element enumeration — Python defs/classes + Markdown headings.

Deterministic, fence-aware, consistent with lineage/extract.py ignore set.
"""
import textwrap
from pathlib import Path

from zft.lineage.matrix import list_all_elements

REPO = Path(__file__).resolve().parents[2]

PY_SRC = textwrap.dedent('''\
    def alpha():
        return 1


    def beta():
        return 2


    class Gamma:
        pass
''')

MD_SRC = """# First

Body text.

## Second

```text
# Third
```
"""


def test_enumerates_expected_elements(tmp_path):
    (tmp_path / "mod.py").write_text(PY_SRC)
    (tmp_path / "doc.md").write_text(MD_SRC)
    elems = list_all_elements(tmp_path)
    assert set(elems) == {
        "mod.py::alpha",
        "mod.py::beta",
        "mod.py::Gamma",
        "doc.md#first",
        "doc.md#second",
    }


def test_deterministic_across_calls(tmp_path):
    (tmp_path / "mod.py").write_text(PY_SRC)
    (tmp_path / "doc.md").write_text(MD_SRC)
    assert list_all_elements(tmp_path) == list_all_elements(tmp_path)


def test_fenced_heading_not_enumerated(tmp_path):
    (tmp_path / "doc.md").write_text(MD_SRC)
    elems = list_all_elements(tmp_path)
    assert "doc.md#third" not in elems
    # tilde fences are honored too
    (tmp_path / "tilde.md").write_text("~~~\n# Hidden\n~~~\n# Visible\n")
    assert set(list_all_elements(tmp_path)) - {"doc.md#first", "doc.md#second"} == \
        {"tilde.md#visible"}


def test_recursive_qualified_names(tmp_path):
    (tmp_path / "mod.py").write_text(textwrap.dedent('''\
        def outer():
            def inner():
                return 1


        class Point:
            def x(self):
                return 0
    '''))
    elems = list_all_elements(tmp_path)
    assert set(elems) == {
        "mod.py::outer",
        "mod.py::outer.inner",
        "mod.py::Point",
        "mod.py::Point.x",
    }


def test_ignores_excluded_dirs(tmp_path):
    (tmp_path / "mod.py").write_text(PY_SRC)
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "skip.py").write_text("def hidden():\n    pass\n")
    (tmp_path / "node_modules" / "sub").mkdir(parents=True)
    (tmp_path / "node_modules" / "sub" / "deep.md").write_text("# Deep\n")
    elems = list_all_elements(tmp_path)
    assert all("hidden" not in e for e in elems)
    assert all("deep" not in e for e in elems)
    assert set(elems) == {"mod.py::alpha", "mod.py::beta", "mod.py::Gamma"}


def test_ignores_any_dot_prefixed_dir_even_outside_ignore_dirs(tmp_path):
    """The walker skips every dot-prefixed directory, not just the IGNORE_DIRS
    set — the 61833bf regression pin: a hidden virtualenv like .venv-check
    (not an IGNORE_DIRS member) must not be descended into, while a
    non-dot directory with a similar name keeps being walked."""
    (tmp_path / "mod.py").write_text(PY_SRC)
    (tmp_path / ".venv-check" / "lib").mkdir(parents=True)
    (tmp_path / ".venv-check" / "lib" / "hidden.py").write_text(
        "def hidden():\n    pass\n")
    (tmp_path / ".secrets").mkdir()
    (tmp_path / ".secrets" / "quiet.md").write_text("# Quiet\n")
    (tmp_path / "venv-check").mkdir()
    (tmp_path / "venv-check" / "seen.py").write_text("def seen():\n    pass\n")
    elems = list_all_elements(tmp_path)
    assert all("hidden" not in e for e in elems)
    assert all("quiet" not in e for e in elems)
    assert "venv-check/seen.py::seen" in elems


def test_skip_class_file_does_not_stop_directory_scan(tmp_path):
    """A skipped file (non-element suffix) must not truncate its directory's
    scan — the per-file loop continues past skip classes, it does not break
    (sorted order puts the skip-class file first, so a break loses the
    element that follows it)."""
    (tmp_path / "a-notes.txt").write_text("not an element")
    (tmp_path / "b-mod.py").write_text(PY_SRC)
    (tmp_path / "c-readme.md").write_text(MD_SRC)
    elems = list_all_elements(tmp_path)
    assert {"b-mod.py::alpha", "b-mod.py::beta", "b-mod.py::Gamma",
            "c-readme.md#first", "c-readme.md#second"} <= set(elems)


def test_real_repo_smoke():
    elems = list_all_elements(REPO)
    assert len(elems) > 500
    assert any("#" in e for e in elems)    # at least one Markdown element
    assert any("::" in e for e in elems)   # at least one Python element
    assert len(elems) == len(set(elems))   # no duplicate element ids
