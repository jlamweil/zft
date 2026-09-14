"""A1 (P-006a): binding extraction is source-scoped.

Bindings under ignored directories (.git, .venv, node_modules, .zft,
__pycache__) are out of contract scope: they must not be extracted, and no
returned file path may contain an ignored path component.
"""

from traceagent.lineage.extract import extract_bindings

IGNORED = {".git", ".venv", "node_modules", ".zft", "__pycache__"}

PY_COPY = '# @trace("BETA-Y")\ndef beta():\n    return 2\n'
TS_COPY = '// @trace("BETA-Y")\nexport function beta(): number {\n  return 2;\n}\n'


def _build_tree(tmp_path):
    # Real source binding.
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text('# @trace("ALPHA-X")\ndef alpha():\n    return 1\n')
    # Copies of a binding under ignored directories.
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text(PY_COPY)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.ts").write_text(TS_COPY)
    (tmp_path / ".zft" / "sandbox").mkdir(parents=True)
    (tmp_path / ".zft" / "sandbox" / "copy.py").write_text(PY_COPY)
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    (tmp_path / ".git" / "hooks" / "q.py").write_text(PY_COPY)
    return tmp_path


def test_ignored_dirs_produce_no_bindings(tmp_path):
    root = _build_tree(tmp_path)
    bindings = extract_bindings(root)
    aliases = {b["alias"] for b in bindings}
    assert "ALPHA-X" in aliases
    assert "BETA-Y" not in aliases
    for b in bindings:
        assert not set(b["file"].split("/")) & IGNORED, f"ignored component in {b['file']!r}"
