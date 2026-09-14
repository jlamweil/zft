"""Test the source‑file iterator used by extraction.

The iterator must return only files with a recognised language suffix and must
exclude any path containing a component from ``IGNORE_DIRS``. The order must be
stable (sorted).
"""
from pathlib import Path

import traceagent.lineage.extract as extract


def _setup_tree(tmp_path):
    # Create source files in allowed locations.
    (tmp_path / "a.py").write_text('# @trace("A")\npass')
    (tmp_path / "b.ts").write_text('// @trace("B")\nexport const x = 1;')
    # Ignored directories with source‑like files – should be omitted.
    for ignored in (".git", ".venv", "node_modules", ".zft", "__pycache__"):
        d = tmp_path / ignored
        d.mkdir(parents=True, exist_ok=True)
        (d / f"ignored{ignored}.py").write_text('# @trace("IGN")\npass')
    # Non‑source file.
    (tmp_path / "readme.txt").write_text('just a readme')
    return tmp_path


def test_iter_source_files_prunes_and_sorts(tmp_path):
    root = _setup_tree(tmp_path)
    files = extract._iter_source_files(root)
    # Convert to posix strings for easy comparison.
    rels = [p.relative_to(root).as_posix() for p in files]
    # Expected only the two top‑level source files, sorted.
    assert rels == ["a.py", "b.ts"]
    # Ensure each path is a Path object and exists.
    for p in files:
        assert isinstance(p, Path)
        assert p.exists()
