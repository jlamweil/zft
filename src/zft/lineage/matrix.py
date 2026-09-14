"""Bi-directional coverage builder (plan C-20): clause→elements + element→clauses.

Element enumeration (plan WP-D1): ``list_all_elements`` lists the deliverable
elements a contract is traced against — Python function/class definitions and
Markdown headings.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from .extract import IGNORE_DIRS

_ELEMENT_SUFFIXES = {".py", ".md"}

_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")
_SLUG_DROP_RE = re.compile(r"[^\w\s-]")
_SLUG_WS_RE = re.compile(r"\s+")
_HEADING_TAIL_RE = re.compile(r"\s+#+\s*$")


def list_all_elements(root) -> list[str]:
    """Enumerate deliverable elements under *root*, in deterministic order.

    Python files contribute function and class definitions (nested included,
    qualified names dot-joined) as ``relpath::qualified.name``. Markdown files
    contribute ATX headings as ``relpath#slug`` using GitHub-style slugs;
    headings inside fenced code blocks are not elements. Traversal skips
    ``IGNORE_DIRS`` (consistent with ``lineage/extract.py``). Order: files
    sorted by path, elements in order of appearance within each file.
    """
    root = Path(root)
    elements: list[str] = []
    for path in _iter_element_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.suffix == ".py":
            elements.extend(_py_elements(rel, text))
        else:
            elements.extend(_md_elements(rel, text))
    return elements


def _iter_element_files(root: Path) -> list[Path]:
    """Files under *root* with an element suffix, skipping ``IGNORE_DIRS``.

    Mirrors ``lineage/extract.py::_iter_source_files``: ``os.walk`` with
    in-place dir pruning plus an any-component check, sorted once for
    deterministic order.
    """
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fname in filenames:
            path = Path(dirpath) / fname
            if path.suffix not in _ELEMENT_SUFFIXES:
                continue
            if set(path.relative_to(root).parts) & IGNORE_DIRS:
                continue
            files.append(path)
    files.sort()
    return files


def _py_elements(rel: str, text: str) -> list[str]:
    """Function/class definitions of a Python file as ``rel::qualname``."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out: list[str] = []

    def walk(node, prefix: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                child_prefix = prefix + (child.name,)
                out.append(f"{rel}::" + ".".join(child_prefix))
                walk(child, child_prefix)

    walk(tree, ())
    return out


def _md_elements(rel: str, text: str) -> list[str]:
    """ATX headings of a Markdown file as ``rel#slug`` (fence-aware)."""
    out: list[str] = []
    used: set[str] = set()
    fence: tuple[str, int] | None = None  # (fence char, min closing length)
    for line in text.splitlines():
        m = _FENCE_RE.match(line)
        if m:
            marker, rest = m.group(1), m.group(2)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1] and not rest.strip():
                fence = None
            continue
        if fence is not None:
            continue
        h = _HEADING_RE.match(line)
        if not h:
            continue
        title = _HEADING_TAIL_RE.sub("", h.group(2)).strip()
        if not title:
            continue
        slug = _SLUG_WS_RE.sub("-", _SLUG_DROP_RE.sub("", title.lower()))
        base, n = slug, 1
        while slug in used:
            slug = f"{base}-{n}"
            n += 1
        used.add(slug)
        out.append(f"{rel}#{slug}")
    return out


# @trace("TR-REVERSE-COVERAGE")
def new_unbound_elements(elements: list[str], bindings: list[dict],
                         baseline: set[str]) -> list[str]:
    """Deliverable elements that are new since *baseline* and bind to no clause.

    Reverse-coverage scope (WP-D2): public, top-level, non-test elements under
    ``src/``. Test directories/files, private names (``_*``), and nested
    symbols/methods are excluded. The returned list is deterministic (sorted).
    """
    baseline_set = set(baseline)
    bound = _bound_element_ids(bindings)
    return sorted(
        element
        for element in set(elements)
        if element not in baseline_set
        and _is_reverse_coverage_element(element)
        and element not in bound
    )


def _bound_element_ids(bindings: list[dict]) -> set[str]:
    """Element ids that carry a binding, matched by file + symbol when present."""
    bound: set[str] = set()
    for binding in bindings:
        file = binding.get("file")
        symbol = binding.get("symbol")
        if not file:
            continue
        if symbol:
            bound.add(f"{file}::{symbol}")
    return bound


def _is_reverse_coverage_element(element: str) -> bool:
    """True for public top-level non-test ``src/`` elements."""
    if not element.startswith("src/"):
        return False
    rel = element.split("::", 1)[0].split("#", 1)[0]
    parts = Path(rel).parts[1:]
    if not parts:
        return False
    if any(part in {"tests", "test"} for part in parts):
        return False
    if any(part.startswith("test_") or part.endswith(("_test.py", "_tests.py"))
           for part in parts):
        return False
    if "::" in element:
        _, qualname = element.split("::", 1)
        if "." in qualname or qualname.startswith("_"):
            return False
    return True


def coverage_report(bindings: list[dict], aliases_in_store: set[str],
                    elements: list[str] | None = None) -> dict:
    """Coverage report over bindings vs the validated clause store.

    elements: optional list of all deliverable elements (e.g. test files);
    those without any binding are reported as out-of-contract (reverse coverage).
    """
    unresolved = sorted({b["alias"] for b in bindings if b["alias"] not in aliases_in_store})
    bound = sorted({b["alias"] for b in bindings if b["alias"] in aliases_in_store})
    covered = len(bound)
    total = len(aliases_in_store)
    bound_elements = {b["file"] for b in bindings}
    out_of_contract = sorted(set(elements or []) - bound_elements)
    return {
        "unresolved": unresolved,
        "covered_aliases": bound,
        "coverage": f"{covered}/{total}",
        "coverage_ratio": (covered / total) if total else 1.0,
        "elements_total": len(elements or []),
        "elements_justified": len(set(elements or []) & bound_elements),
        "out_of_contract": out_of_contract,
    }
