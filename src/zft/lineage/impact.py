"""Impact query utilities for tracing changes to @trace bindings.

Provides two public functions:
- impact(bindings, changes) -> dict
- impact_from_root(root, changes) -> dict
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Set


def _norm_path(p: str) -> str:
    """Normalize a path string to POSIX form without a leading './' prefix.

    Do not use str.lstrip('./'): it strips any combination of leading '.' and
    '/' characters, corrupting hidden paths ('.zft/...' -> 'zft/...') and
    absolute paths ('/a/b' -> 'a/b').
    """
    s = Path(p).as_posix()
    while s.startswith("./"):
        s = s[2:]
    return s


def impact(bindings: List[Mapping[str, object]], changes: Iterable[str]) -> Dict:
    """Compute impact of changes on extracted @trace bindings.

    Args:
        bindings: List of dicts with keys ``alias``, ``file``, ``line``, ``symbol``.
        changes: Iterable of strings ``path`` or ``path::symbol``. Paths are
            repository-relative and are matched if either path is a suffix of the
            other after normalisation.
    Returns:
        Dict with two keys:
            ``aliases`` - sorted list of affected alias strings.
            ``affected`` - mapping alias -> list of reference dicts (file, line,
            symbol) for each matching binding, de-duplicated.
    """
    parsed: List[tuple[str, str | None]] = []
    for ch in changes:
        if "::" in ch:
            path, symbol = ch.split("::", 1)
            parsed.append((_norm_path(path), symbol))
        else:
            parsed.append((_norm_path(ch), None))

    affected: Dict[str, Set[tuple[str, int, str | None]]] = {}
    for binding in bindings:
        alias = binding.get("alias")
        b_file = _norm_path(str(binding.get("file", "")))
        b_sym = binding.get("symbol")
        for c_path, c_sym in parsed:
            if b_file == c_path or b_file.endswith(c_path) or c_path.endswith(b_file):
                if c_sym is not None and b_sym != c_sym:
                    continue
                affected.setdefault(alias, set()).add(
                    (b_file, int(binding.get("line", 0)), b_sym)
                )
                break

    aliases = sorted(affected.keys())
    affected_dict: Dict[str, List[Dict[str, object]]] = {}
    for alias, refs in affected.items():
        sorted_refs = sorted(refs, key=lambda t: (t[0], t[1], t[2] or ""))
        affected_dict[alias] = [
            {"file": f, "line": line, "symbol": sym}
            for (f, line, sym) in sorted_refs
        ]
    return {"aliases": aliases, "affected": affected_dict}


def impact_from_root(root: Path, changes: Iterable[str]) -> Dict:
    """Convenience wrapper that extracts bindings from *root* and runs ``impact``."""
    from zft.lineage.extract import extract_bindings

    bindings = extract_bindings(root)
    return impact(bindings, changes)
