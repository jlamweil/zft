"""Binding extraction (plan C-17): @trace("ALIAS") → {alias, file, line, symbol}.

Per-file cache (A2/P-006a): `<root>/.zft/cache/extract.json`,
`{"version": CACHE_VERSION, "files": {relpath: {"mtime_ns", "size", "bindings"}}}` —
a file whose (mtime_ns, size) is unchanged in a version-matching cache is
not re-parsed. The cache is pruned to surviving files and rewritten
atomically on every run.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

# Bump when the extraction logic changes; a mismatch invalidates the whole
# cache. Deviation from plan A2 ("contract-version change invalidates"):
# the cache is deliberately NOT coupled to the contract — source bindings
# depend only on file content, so a contract edit never changes the
# bindings of any file and must not force a re-parse; extraction-logic
# changes are covered by a CACHE_VERSION bump.
# (2: WP-D3 adds first-class Markdown `@trace` anchors — the walked file
# set changed, so pre-WP-D3 caches cold-start.)
CACHE_VERSION = 2

def skipped_dir(name: str) -> bool:
    """True for directories holding tool workspaces, never reviewable evidence.

    Kept as a public helper: l1/l2 bound-suite discovery reuses this rule so
    gate-side file walking and extraction walking can never diverge.
    """
    return (name.startswith(".")
            or name in IGNORE_DIRS
            or name == "scratch"
            or name.startswith("mutants"))


def _iter_source_files(root: Path) -> list[Path]:
    """Yield source files under *root* respecting the ignore set.

    Returns a deterministic, sorted list of ``Path`` objects whose suffix is in
    ``LANG`` and whose path does not contain any component from ``IGNORE_DIRS``.
    The traversal uses ``os.walk`` and removes ignored directories from
    ``dirnames`` in‑place, avoiding descent into large ignored trees like
    ``.git`` or ``.venv``.
    """
    files: list[Path] = []
    # ``os.walk`` yields (dirpath, dirnames, filenames). Mutate ``dirnames`` to
    # prune ignored sub‑directories before the walk recurses.
    for dirpath, dirnames, filenames in os.walk(root):
        # Remove any ignored directories from traversal. Beyond IGNORE_DIRS,
        # hidden trees hold sandboxes, never specs, and tree snapshots appear
        # under shifting names (mutmut campaign trees like mutants-prev-l0l3/,
        # the gitignored scratch/ root) — tethys-campaign lesson, 2026-09-07.
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS
                       and not d.startswith(".")
                       and d != "scratch"
                       and not d.startswith("mutants")]
        for fname in filenames:
            if Path(fname).suffix in LANG:
                path = Path(dirpath) / fname
                if set(path.relative_to(root).parts) & IGNORE_DIRS:
                    continue
                files.append(path)
    # Sort once for deterministic order.
    files.sort()
    return files

COMMENT_KIND = {"python": "comment", "typescript": "comment", "rust": "line_comment"}
LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".md": "markdown",
}
IGNORE_DIRS = {".git", ".venv", "node_modules", ".zft", "__pycache__", "private"}
TRACE_RE = re.compile(r'@trace\("([A-Z0-9-]+)"\)')
TARGET_KINDS = {
    "python": {"function_definition", "decorated_definition"},
    "typescript": {"function_declaration", "method_definition", "class_declaration",
                   "export_statement"},
    "rust": {"function_item", "function_signature_item"},
}


def extract_bindings(root: Path, write_cache: bool = True) -> list[dict]:
    """Deterministic binding extraction across the tree, sorted by (file, line).

    Unchanged files (matching mtime_ns + size in a version‑matching cache)
    reuse their cached bindings without re‑parsing. The cache is pruned to
    surviving files and rewritten atomically on every run.
    """
    root = Path(root)
    cache_path = root / ".zft" / "cache" / "extract.json"
    # Load a possibly existing cache (leniently – version mismatch or corruption → miss)
    cached_files = _load_cache(cache_path)

    bindings: list[dict] = []
    fresh: dict[str, dict] = {}
    for path in _iter_source_files(root):
        rel = path.relative_to(root).as_posix()
        st = path.stat()
        entry = cached_files.get(rel)
        if _cache_hit(entry, st):
            # Cache hit: reuse stored bindings.
            fresh[rel] = entry
            bindings.extend(entry["bindings"])
            continue
        # Cache miss: parse the file.
        parsed = _parse_file(path, rel, LANG[path.suffix])
        fresh[rel] = {
            "mtime_ns": st.st_mtime_ns,
            "size": st.st_size,
            "bindings": parsed,
        }
        bindings.extend(parsed)

    # Write (or rewrite) the cache atomically.
    if write_cache:
        _write_cache(cache_path, {"version": CACHE_VERSION, "files": fresh})
    return sorted(bindings, key=lambda b: (b["file"], b["line"], b["alias"]))


def _enclosing_symbol(node, lang: str) -> str | None:
    """Symbol anchor: nearest next-sibling chain node carrying a function name.

    V4 lesson: comments precede functions — walk next siblings, and descend one
    wrapper level (TypeScript export_statement has no `name` field itself).
    """
    targets = TARGET_KINDS[lang]
    nxt = node.next()
    while nxt is not None:
        if nxt.kind() in targets:
            name = nxt.field("name")
            if name:
                return name.text()
            for child in nxt.children():
                if child.kind() in targets:
                    name = child.field("name")
                    if name:
                        return name.text()
        nxt = nxt.next()
    return None

# WP-D3: Markdown anchor extraction.
MD_TRACE_RE = re.compile(r'^\s*<!--\s*@trace\("([A-Z0-9-]+)"\)\s*-->\s*$')
MD_HEADING_RE = re.compile(r'^\s{0,3}(#{1,6})\s+(.*)$')
MD_FENCE_RE = re.compile(r'^\s{0,3}(`{3,}|~{3,})(.*)$')
_MD_HEADING_TAIL_RE = re.compile(r'\s+#+\s*$')
_SLUG_DROP_RE = re.compile(r'[^\w\s-]')
_SLUG_WS_RE = re.compile(r'\s+')

def _md_slug(title: str) -> str:
    """GitHub-style slug of an ATX heading title (mirrors matrix._md_elements)."""
    title = _MD_HEADING_TAIL_RE.sub('', title).strip()
    if not title:
        return ''
    return _SLUG_WS_RE.sub('-', _SLUG_DROP_RE.sub('', title.lower()))


def _extract_md_file(path: Path, rel: str) -> list[dict]:
    """Extract @trace anchors from a Markdown file.

    A binding is emitted when an anchor comment sits on the line immediately
    above an ATX heading; ``line`` is the 1‑based comment line and ``symbol``
    is the heading's GitHub‑style slug. Content inside fenced code blocks
    (``` / ~~~) is ignored, so both anchor comments and headings there bind
    nothing.
    """
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []
    bindings: list[dict] = []
    fence: tuple[str, int] | None = None  # (fence char, min closing length)
    pending: tuple[str, int] | None = None  # (alias, comment line)
    for lineno, line in enumerate(lines, start=1):
        fm = MD_FENCE_RE.match(line)
        if fm:
            marker, rest = fm.group(1), fm.group(2)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1] and not rest.strip():
                fence = None
            pending = None
            continue
        if fence is not None:
            pending = None
            continue
        tm = MD_TRACE_RE.match(line)
        if tm:
            pending = (tm.group(1), lineno)
            continue
        hm = MD_HEADING_RE.match(line)
        if hm and pending is not None:
            symbol = _md_slug(hm.group(2))
            if symbol:
                bindings.append({
                    "alias": pending[0],
                    "file": rel,
                    "line": pending[1],
                    "symbol": symbol,
                })
            pending = None
        else:
            pending = None
    return bindings


def _parse_file(path: Path, rel: str, lang: str) -> list[dict]:
    """Parse a single source file into a list of binding records.

    This function is the cache seam – it is called only when a file is not
    present in a valid cache entry.
    """
    if lang == "markdown":
        return _extract_md_file(path, rel)
    from ast_grep_py import SgRoot

    kind = COMMENT_KIND[lang]
    tree = SgRoot(path.read_text(), lang).root()
    bindings: list[dict] = []
    for node in tree.find_all(kind=kind, regex=TRACE_RE.pattern):
        match = TRACE_RE.search(node.text())
        if not match:
            continue
        bindings.append({
            "alias": match.group(1),
            "file": rel,
            "line": node.range().start.line + 1,
            "symbol": _enclosing_symbol(node, lang),
        })
    return bindings


def _cache_hit(entry: object, st) -> bool:
    """Return True if a cached entry matches the file's mtime/size and contains
    a valid bindings list.
    """
    return (
        isinstance(entry, dict)
        and entry.get("mtime_ns") == st.st_mtime_ns
        and entry.get("size") == st.st_size
        and isinstance(entry.get("bindings"), list)
    )


def _load_cache(cache_file: Path) -> dict:
    """Leniently load the extract cache.

    If the file is missing, unreadable, malformed JSON, missing the expected
    top‑level version field, or the version is not equal to ``CACHE_VERSION``,
    the function returns an empty mapping, causing a full cold parse.
    """
    try:
        data = json.loads(cache_file.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return {}
    files = data.get("files")
    return files if isinstance(files, dict) else {}


def _write_cache(cache_file: Path, data: dict) -> None:
    """Write the cache atomically – write to a temporary file then replace.

    Errors are ignored because the cache is an optimisation; extraction must
    succeed even if the cache cannot be persisted.
    """
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cache_file.parent, prefix=".extract-", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, sort_keys=True)
        os.replace(tmp_path, cache_file)
    except OSError:
        # Best‑effort cache; ignore write failures.
        pass
