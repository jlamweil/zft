"""The mechanical kill-rate bar (roadmap #3c).

Phase-B mutmut shards (jobs/mut-src.sh) copy back per-file ``.meta`` verdict
sidecars and, since 2026-09-11, ``.mutdiff.json`` — the exact mutation of
every generated mutant (original function source + changed line range), read
out of the scratch mutated tree via mutmut's own ``MutantLineSpans`` index.
This module turns that into an enforced bar: every mutant that is **not
proven dead** must be either mechanically provably cosmetic (a mutation
inside the original function's docstring) or individually waived with a
reason and a named killing test (or an equivalence argument). Anything else
is a suspect and fails the bar.

Verdict semantics are mutmut 3.7's own ``status_by_exit_code`` (verified
against the installed package, not guessed): 1/3/-24 are killed (a cpu-limit
death counts as a kill), 0 survived, 5/33 "no tests" (the stats phase bound
no test to the mutated function — a coverage hole, not a pass), 34 skipped,
35 suspicious, 36 timeout, None not checked.

Classification is fail-closed: a survivor with no usable mutation record
(missing/malformed ``.mutdiff.json``, unparseable original source) classes
``unattributed``; a file whose live sha256 diverges from the shard's
``source-manifest.txt`` classes every survivor ``source_drift`` — the
mutation provably does not describe the code in this tree. Neither can ever
class cosmetic.
"""
from __future__ import annotations

import ast
import re
import textwrap
from dataclasses import dataclass, field

KILLED = "killed"
SURVIVED = "survived"
NO_TESTS = "no_tests"
SKIPPED = "skipped"
SUSPICIOUS = "suspicious"
TIMEOUT = "timeout"
NOT_CHECKED = "not_checked"

STATUS_BY_EXIT: dict[int | None, str] = {
    1: KILLED,
    3: KILLED,  # pytest internal error counts as a kill (mutmut)
    -24: KILLED,  # SIGXCPU: mutant hung past the cpu limit -> behavior changed
    0: SURVIVED,
    5: NO_TESTS,
    33: NO_TESTS,
    34: SKIPPED,
    35: SUSPICIOUS,
    36: TIMEOUT,
    None: NOT_CHECKED,
}

# Survivors inside this class are provably cosmetic; every other survivor
# class, and every non-survivor "not proven dead" class, blocks the bar.
# Deliberately only docstrings: message text is contractual in this project
# (pinned byte-exact), so no string mutation can be assumed unobservable.
COSMETIC = frozenset({"docstring"})

# Blocking non-survivor verdicts: the mutant dodged the suite either way.
BLOCKING_NON_KILLS = frozenset(
    {NO_TESTS, SKIPPED, SUSPICIOUS, TIMEOUT, NOT_CHECKED})

BAR = "no unwaived suspects"


@dataclass
class FileVerdicts:
    """One source file's worth of shard verdicts, plus the mutation records
    needed to classify survivors."""

    relpath: str
    verdicts: dict[str, int | None]  # mutant key -> raw exit code
    diffs: dict[str, dict]  # mutant key -> {line, last_line, orig, mutant}
    functions: dict[str, str]  # orig fn key -> original source text
    source_digest_ok: bool | None = None
    # None: the shard carries no source manifest (pre-2026-09-11 batch), so
    # byte-identity can't be proven — classification still works off the
    # mutation record itself. False: manifest present and the live file's
    # sha256 differs -> the mutations describe code that no longer exists;
    # every survivor is source_drift (fail-closed), never cosmetic.


@dataclass
class ShardInput:
    name: str
    files: list[FileVerdicts] = field(default_factory=list)


def _docstring_line_range(fn_src: str) -> tuple[int, int] | None | str:
    """(start, end) 0-based inclusive line range of the docstring of a single
    function/method source (as mutmut's ``read_function_sources`` returns it,
    possibly indented). Returns ``"unparseable"`` if the source does not
    parse, None if there is no docstring."""
    src = textwrap.dedent(fn_src)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return "unparseable"
    fn = tree.body[0] if tree.body else None
    body = getattr(fn, "body", None)
    if (not body or not isinstance(body[0], ast.Expr)
            or not isinstance(body[0].value, ast.Constant)
            or not isinstance(body[0].value.value, str)):
        return None
    doc = body[0].value
    return (doc.lineno - 1, doc.end_lineno - 1)


def _orig_fn_key(key: str) -> str:
    """The ``__mutmut_orig`` key for a mutant key (they share the function
    prefix: ``pkg.x_foo__mutmut_3`` -> ``pkg.x_foo__mutmut_orig``)."""
    return key.rsplit("__mutmut_", 1)[0] + "__mutmut_orig"


def canonical_mutation_text(text: str) -> str:
    """The whitespace-normalized, scaffolding-canonicalized form of a
    mutation text — half of a waiver's identity. ``__mutmut_(orig|N)``
    variant renames collapse to ``__mutmut_X`` (the writer's def-line rule),
    then indentation edges, trailing whitespace and blank padding are
    stripped per line: none of that is logic, so none of it is identity."""
    canon = _MUTMUT_VARIANT.sub("__mutmut_X", text)
    return "\n".join(line.strip() for line in canon.strip().splitlines())


def mutation_text_key(relpath: str, orig: str, mutant: str) -> str:
    """A waiver review's identity: sha256(module + "\\0" + canon(orig) +
    "\\0" + canon(mut)). Stable across mutmut renumberings of byte-identical
    source, and different for any drift of module or either text."""
    import hashlib

    h = hashlib.sha256()
    h.update(relpath.encode())
    h.update(b"\0")
    h.update(canonical_mutation_text(orig).encode())
    h.update(b"\0")
    h.update(canonical_mutation_text(mutant).encode())
    return h.hexdigest()


def classify(diff: dict | None, orig_src: str | None) -> str:
    """Survivor class for one mutant's mutation record, fail-closed.

    The record is one ``.mutdiff.json`` diffs entry: ``line`` (0-based first
    changed line), optional ``last_line`` (0-based, multi-line changes),
    ``orig``/``mutant`` (the changed line texts), with the original function
    source alongside in ``functions``.

    docstring      the changed line range lies inside the original
                   function's docstring — provably unobservable
    unattributed   record missing/malformed or original source unparseable —
                   suspect, never cosmetic
    logic          any other mutation — the real thing
    """
    if (not isinstance(diff, dict) or not orig_src
            or not isinstance(diff.get("orig"), str)
            or not isinstance(diff.get("mutant"), str)
            or not isinstance(diff.get("line"), int)):
        return "unattributed"
    doc = _docstring_line_range(orig_src)
    if doc == "unparseable":
        return "unattributed"  # can't locate the docstring: never cosmetic
    first = diff["line"]
    last = (diff["last_line"] if isinstance(diff.get("last_line"), int)
            else first)
    if doc and doc[0] <= first and last <= doc[1]:
        return "docstring"
    return "logic"


def _diff_texts(diff: dict | None) -> tuple[str, str] | None:
    """The (orig, mutant) texts of a diffs entry, if both are usable."""
    if (isinstance(diff, dict) and isinstance(diff.get("orig"), str)
            and isinstance(diff.get("mutant"), str)):
        return diff["orig"], diff["mutant"]
    return None


def evaluate(shards: list[ShardInput], waivers: dict[str, dict] | None = None) -> dict:
    """Typed bar report; IO-free. ok is True iff no unwaived suspects remain.

    Waiver matching is by mutation identity: an entry whose ``text_key``
    (mutation_text_key of the reviewed texts) equals a live row's waives it
    — one review covers every live row of the same text, however mutmut
    renumbered the generation. The legacy key alone still waives entries
    that carry no text_key; a key match whose entry text_key differs from
    the live row's never waives (the review proved other text — the
    mis-attachment class reads unwaived, never a false green). A waived
    text whose live row reads killed is reported under
    ``verdict_contradictions`` as a fail-loud re-verify flag; dead is dead,
    so it rides beside the bar instead of flipping ok.
    """
    waivers = waivers or {}
    by_text: dict[str, str] = {}
    for wkey, meta in waivers.items():
        tk = meta.get("text_key") if isinstance(meta, dict) else None
        if isinstance(tk, str):
            by_text.setdefault(tk, wkey)  # twins share one review: first wins

    def _has_text_key(meta: dict) -> bool:
        return isinstance(meta, dict) and isinstance(meta.get("text_key"), str)

    totals: dict[str, int] = {}
    survivor_classes: dict[str, int] = {}
    per_shard: dict[str, dict] = {}
    suspects: list[dict] = []
    contradictions: list[dict] = []
    waived_count = 0
    live_texts: set[str] = set()

    for shard in shards:
        st: dict[str, int] = {}
        classes: dict[str, int] = {}
        for fv in shard.files:
            for key, raw in fv.verdicts.items():
                status = STATUS_BY_EXIT.get(raw, SUSPICIOUS)
                st[status] = st.get(status, 0) + 1
                totals[status] = totals.get(status, 0) + 1
                texts = _diff_texts(fv.diffs.get(key))
                text_key = (mutation_text_key(fv.relpath, *texts)
                            if texts else None)
                if text_key is not None:
                    live_texts.add(text_key)
                if status == SURVIVED:
                    if fv.source_digest_ok is False:
                        cls = "source_drift"  # mutation describes vanished code
                    else:
                        cls = classify(fv.diffs.get(key),
                                       fv.functions.get(_orig_fn_key(key)))
                    classes[cls] = classes.get(cls, 0) + 1
                    survivor_classes[cls] = survivor_classes.get(cls, 0) + 1
                    if cls in COSMETIC:
                        continue
                elif status not in BLOCKING_NON_KILLS:
                    # killed: a waived text reading killed is the loud
                    # re-verify flag, never silently stale
                    if text_key is not None and text_key in by_text:
                        contradictions.append(
                            {"shard": shard.name, "mutant": key,
                             "file": fv.relpath, "text_key": text_key,
                             "waiver": by_text[text_key], "verdict": status})
                    continue
                entry = {"shard": shard.name, "mutant": key, "file": fv.relpath,
                         "class": (status if status != SURVIVED else cls),
                         "text_key": text_key}
                d = fv.diffs.get(key)
                if d is not None:
                    entry["mutation"] = f"{d.get('orig', '').strip()!r} -> " \
                                        f"{d.get('mutant', '').strip()!r}"
                w = waivers.get(key)
                if w is not None and _has_text_key(w) \
                        and w["text_key"] != text_key:
                    w = None  # the review proved other text: never honor blind
                if w is None and text_key is not None and text_key in by_text:
                    w = waivers[by_text[text_key]]
                if w is not None:
                    waived_count += 1
                    entry.update(waived=True, reason=w.get("reason"),
                                 killing_test=w.get("killing_test"))
                else:
                    entry.update(waived=False, reason=None, killing_test=None)
                suspects.append(entry)
        per_shard[shard.name] = {**st, "survivor_classes": dict(sorted(classes.items()))}

    known = {key for shard in shards for fv in shard.files for key in fv.verdicts}
    stale = sorted(
        wkey for wkey, meta in waivers.items()
        if (meta["text_key"] not in live_texts if _has_text_key(meta)
            else wkey not in known))
    unwaived = [s for s in suspects if not s["waived"]]
    killed = totals.get(KILLED, 0)
    mutants = sum(totals.values())
    return {
        "ok": not unwaived,
        "bar": BAR,
        "shards": per_shard,
        "totals": {
            **{k: totals.get(k, 0) for k in
               (KILLED, SURVIVED, NO_TESTS, SKIPPED, SUSPICIOUS, TIMEOUT, NOT_CHECKED)},
            "mutants": mutants,
            "kill_rate": round(killed / mutants, 4) if mutants else None,
        },
        "survivor_classes": dict(sorted(survivor_classes.items())),
        "suspects": sorted(unwaived, key=lambda s: (s["file"], s["mutant"])),
        "waived_count": waived_count,
        "stale_waivers": stale,
        "verdict_contradictions": sorted(
            contradictions, key=lambda c: (c["file"], c["mutant"])),
    }


# ---------------------------------------------------------------------------
# IO seam: load shard result dirs as produced by jobs/mut-src.sh copy-back.


def load_shard(shard_dir, source_root):
    """Read one ``results-mut-*`` directory into a ShardInput.

    Only ``src/**`` sidecars load: the ``.zft/sandbox`` mirrors inside
    a mutants tree are evidence copies — mutmut generates their mutants but
    nothing imports them, so every verdict there is None by construction and
    they would fail the bar spuriously. Files with no ``.meta`` sidecar (no
    mutants generated) contribute nothing.

    Mutation records come from ``.mutdiff.json`` (written by jobs/mut-src.sh
    since 2026-09-11): the original function source plus the changed line
    range per mutant. A survivor without a record classes unattributed —
    fail-closed.

    When the shard carries a ``source-manifest.txt`` (sha256 per src file),
    each file's live source is verified against it: a mismatch sets
    ``source_digest_ok = False`` and every survivor of that file classes
    ``source_drift`` — the mutations describe code that no longer exists.
    """
    import hashlib
    import json
    from pathlib import Path

    shard_dir = Path(shard_dir)
    source_root = Path(source_root)
    mutants_root = shard_dir / "mutants"
    shard = ShardInput(name=shard_dir.name.removeprefix("results-"))

    manifest: dict[str, str] = {}
    manifest_path = shard_dir / "source-manifest.txt"
    if manifest_path.exists():
        for line in manifest_path.read_text().splitlines():
            digest, _, name = line.partition("  ")
            if name.startswith("./"):
                name = name[2:]
            if name:
                manifest[name] = digest.strip()

    for meta_path in sorted(mutants_root.rglob("*.meta")):
        relpath = meta_path.relative_to(mutants_root).with_suffix("").as_posix()
        if relpath.split("/")[0] == ".zft":
            continue
        verdicts = json.loads(meta_path.read_text()).get("exit_code_by_key", {})
        diffs: dict[str, dict] = {}
        functions: dict[str, str] = {}
        mutdiff_path = meta_path.with_suffix(".mutdiff.json")
        if mutdiff_path.exists():
            data = json.loads(mutdiff_path.read_text())
            diffs = data.get("diffs", {})
            functions = data.get("functions", {})

        src_file = source_root / relpath
        digest_ok: bool | None = None
        if relpath in manifest:
            actual = (hashlib.sha256(src_file.read_bytes()).hexdigest()
                      if src_file.is_file() else "missing")
            digest_ok = actual == manifest[relpath]
        shard.files.append(FileVerdicts(relpath=relpath, verdicts=verdicts,
                                        diffs=diffs, functions=functions,
                                        source_digest_ok=digest_ok))
    return shard


def load_waivers(path):
    import json
    from pathlib import Path

    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or not all(
            isinstance(v, dict) for v in data.values()):
        raise ValueError("waivers file must be a JSON object of "
                         "{mutant: {reason, killing_test}}")
    return data


# ---------------------------------------------------------------------------
# Record writer: a scratch mutated tree -> per-file .mutdiff.json. Called by
# jobs/mut-src.sh after a completed `mutmut run`; this function is the single
# code path (no script-local copy to drift).

_MUTMUT_VARIANT = re.compile(r"__mutmut_(?:orig|\d+)\b")


def write_mutation_records(copy_dir) -> int:
    """Walk one mutmut scratch copy's ``mutants/`` tree and write one
    ``<file>.mutdiff.json`` beside every ``.spans``/``.meta`` sidecar pair:
    the original function source plus, per mutant, the exact changed line
    range and texts, keyed by fully-qualified mutant name (matching the
    ``.meta`` keys the bar joins on).

    The line comparison canonicalizes mutmut's scaffolding rename — every
    generated function is ``<name>__mutmut_orig`` or ``<name>__mutmut_N``, so
    the def line always differs and would otherwise sit inside *every*
    mutant's changed range, drowning the docstring class. A real def-line
    mutation (argument defaults, annotations) still differs after
    canonicalization and is recorded. Returns the number of files written.
    """
    import json
    from pathlib import Path

    def canonical(line: str | None) -> str | None:
        if line is None:
            return None
        return _MUTMUT_VARIANT.sub("__mutmut_X", line)

    mutants_root = Path(copy_dir) / "mutants"
    count = 0
    for spans_path in sorted(mutants_root.rglob("*.spans")):
        relpath = spans_path.relative_to(mutants_root)
        if relpath.parts[0] == ".zft":
            continue  # sandbox evidence mirrors: no live verdicts, not needed
        if not spans_path.with_suffix(".meta").exists():
            continue  # no verdicts for this file
        index = json.loads(spans_path.read_text())
        if index.get("version") != 1:
            continue
        lines = spans_path.with_suffix("").read_text().splitlines(keepends=True)

        def span_text(span):
            start, end = span
            return "".join(lines[start - 1:end])  # 1-based inclusive

        module = (relpath.with_suffix("").as_posix().removeprefix("src/")
                  .removesuffix(".py").replace("/", "."))
        span_by_name = index["spans"]
        functions = {f"{module}.{name}": span_text(span)
                     for name, span in span_by_name.items()
                     if name.endswith("__mutmut_orig")}
        diffs = {}
        for name, span in span_by_name.items():
            if name.endswith("__mutmut_orig"):
                continue
            key = f"{module}.{name}"
            orig_src = functions.get(_orig_fn_key(key))
            if orig_src is None:
                continue
            orig_lines = orig_src.splitlines(keepends=True)
            mut_lines = span_text(span).splitlines(keepends=True)
            changed = [i for i in range(max(len(orig_lines), len(mut_lines)))
                       if canonical(orig_lines[i] if i < len(orig_lines)
                                    else None)
                       != canonical(mut_lines[i] if i < len(mut_lines)
                                    else None)]
            if not changed:
                continue  # scaffolding only; mutmut never emits such a mutant
            first, last = changed[0], changed[-1]
            diffs[key] = {
                "line": first, "last_line": last,
                "orig": "".join(orig_lines[first:last + 1]),
                "mutant": "".join(mut_lines[first:last + 1]),
            }
        spans_path.with_suffix(".mutdiff.json").write_text(json.dumps(
            {"version": 1, "functions": functions, "diffs": diffs}))
        count += 1
    return count
