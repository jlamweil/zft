"""WP-D1: deliverable element enumeration — Python defs/classes + Markdown headings.

Deterministic, fence-aware, consistent with lineage/extract.py ignore set.
"""
import textwrap
from pathlib import Path

from traceagent.lineage.matrix import list_all_elements

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


def test_real_repo_smoke():
    elems = list_all_elements(REPO)
    assert len(elems) > 500
    assert any("#" in e for e in elems)    # at least one Markdown element
    assert any("::" in e for e in elems)   # at least one Python element
    assert len(elems) == len(set(elems))   # no duplicate element ids
