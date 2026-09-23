"""C-17: ast-grep binding extraction — 3 languages, V4 fixtures as goldens."""

from zft.lineage.extract import extract_bindings

SAMPLES = {
    "sample.py": '''
# @trace("TR-FORWARD-COVERAGE")
def check_forward_coverage(rows):
    return all(r.clause_id for r in rows)
''',
    "sample.ts": '''
// @trace("TR-UNRESOLVED-BINDINGS-FAIL")
export function reportUnresolved(bindings: Binding[]): number {
    return bindings.filter((b) => !b.resolved).length;
}
''',
    "sample.rs": '''
// @trace("TR-DETERMINISTIC-EXTRACTION")
pub fn manifest_hash(rows: Vec<Row>) -> u64 {
    rows.iter().map(|r| r.hash).fold(0, |a, b| a ^ b)
}
''',
}


def _write_samples(tmp_path):
    for name, src in SAMPLES.items():
        p = tmp_path / name
        p.write_text(src)
    return tmp_path


def test_extracts_bindings_across_three_languages(tmp_path):
    root = _write_samples(tmp_path)
    bindings = extract_bindings(root)
    aliases = {b["alias"] for b in bindings}
    assert {"TR-FORWARD-COVERAGE", "TR-UNRESOLVED-BINDINGS-FAIL",
            "TR-DETERMINISTIC-EXTRACTION"} <= aliases


def test_binding_records_have_file_line_symbol(tmp_path):
    root = _write_samples(tmp_path)
    bindings = extract_bindings(root)
    py = next(b for b in bindings if b["file"] == "sample.py")
    assert py["line"] == 2
    assert py["symbol"] == "check_forward_coverage"


# @trace("TR-DETERMINISTIC-EXTRACTION")
def test_extraction_is_deterministic(tmp_path):
    root = _write_samples(tmp_path)
    assert extract_bindings(root) == extract_bindings(root)


def test_hidden_dirs_and_mutmut_workspace_are_not_evidence(tmp_path):
    """EVID-1 (ATTACK_MATRIX): mirror copies bind as basename twins →
    pytest 'import file mismatch' in L1; worse, a stale mirror would launder
    old coverage into the attestation."""
    root = _write_samples(tmp_path)
    for mirror in ("mutants/tests", ".venv/lib", ".zft/sandbox"):
        d = root / mirror
        d.mkdir(parents=True)
        (d / "sample.py").write_text(SAMPLES["sample.py"])
    assert {b["file"] for b in extract_bindings(root)} == {
        "sample.py", "sample.ts", "sample.rs"}


def test_renamed_campaign_and_scratch_copies_are_not_evidence(tmp_path):
    """EVID-1 (ATTACK_MATRIX) — regression (2026-09-06 check red): stale tree
    snapshots under shifted
    names — a renamed mutants archive and a batch copy under scratch/ — came
    back as bindings for ID-CONTENT-CHANGE / TR-DETERMINISTIC-EXTRACTION and
    died on 'import file mismatch' against their tests/ twins."""
    root = _write_samples(tmp_path)
    for mirror in ("mutants-prev-l0l3/tests/unit",
                   "scratch/mutmut-mut-dsl-codegen/copy/tests/unit"):
        d = root / mirror
        d.mkdir(parents=True)
        (d / "sample.py").write_text(SAMPLES["sample.py"])
    assert {b["file"] for b in extract_bindings(root)} == {
        "sample.py", "sample.ts", "sample.rs"}


# --- hygiene sitting 2026-09-22 (loop continuation): lineage front pins ---

from zft.lineage.extract import _md_slug, skipped_dir  # noqa: E402


def test_skipped_dir_scratch_is_the_exact_literal():
    assert skipped_dir("scratch") is True
    assert skipped_dir("SCRATCH") is False
    assert skipped_dir("XXscratchXX") is False


def test_md_slug_normalization_is_byte_exact():
    assert _md_slug("My Head ###") == "my-head"
    assert _md_slug("Foo: Bar's?") == "foo-bars"
    assert _md_slug("   ###  ") == ""


def test_write_cache_atomic_write_is_pinned(tmp_path, monkeypatch):
    import json as jsonlib
    import tempfile as tempfilelib

    import zft.lineage.extract as ex

    cache_file = tmp_path / ".zft" / "cache" / "extract.json"
    captured = {}
    real_mkstemp = tempfilelib.mkstemp

    def spy_mkstemp(*args, **kwargs):
        captured.update(kwargs)
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(tempfilelib, "mkstemp", spy_mkstemp)
    data = {"files": {"z.py": {"bindings": [], "mtime_ns": 1, "size": 2},
                      "a.py": {"bindings": [], "mtime_ns": 3, "size": 4}},
            "version": ex.CACHE_VERSION}
    ex._write_cache(cache_file, data)
    assert captured == {"dir": cache_file.parent, "prefix": ".extract-",
                        "suffix": ".tmp"}
    content = cache_file.read_text()
    assert content == jsonlib.dumps(data, sort_keys=True), \
        "cache payload must be written sort_keys=True (byte-stable)"
    assert list(tmp_path.rglob("*.tmp")) == [], "the tmp file must be replaced away"


def test_enclosing_symbol_walks_past_non_targets(tmp_path):
    p = tmp_path / "s.py"
    p.write_text(
        '# @trace("TR-WALK")\n'
        'x = 1\n'
        'def walked_fn():\n'
        '    return 1\n'
    )
    bindings = extract_bindings(tmp_path)
    assert [b["symbol"] for b in bindings] == ["walked_fn"]


def test_enclosing_symbol_descends_decorated_wrapper(tmp_path):
    p = tmp_path / "s.py"
    p.write_text(
        '# @trace("TR-DEC")\n'
        '@functools.lru_cache\n'
        'def cached_fn():\n'
        '    return 1\n'
    )
    bindings = extract_bindings(tmp_path)
    assert [b["symbol"] for b in bindings] == ["cached_fn"]


def test_decoy_comments_do_not_stop_the_scan(tmp_path):
    p = tmp_path / "s.py"
    p.write_text(
        '# plain prose, not a trace\n'
        '# @trace("TR-DECOY")\n'
        'def seen():\n'
        '    return 1\n'
    )
    bindings = extract_bindings(tmp_path)
    assert [b["symbol"] for b in bindings] == ["seen"]


def test_hidden_dot_dirs_are_pruned_by_the_walk(tmp_path):
    (tmp_path / "visible.py").write_text(
        '# @trace("TR-VIS")\ndef visible():\n    return 1\n')
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.py").write_text(
        '# @trace("TR-SECRET")\ndef secret():\n    return 1\n')
    bindings = extract_bindings(tmp_path)
    assert {b["file"] for b in bindings} == {"visible.py"}


def test_extract_md_fences_and_anchors(tmp_path):
    (tmp_path / "doc.md").write_text(
        '<!-- @trace("TR-OPEN") -->\n'
        '## Open Head\n'
        '```rust\n'
        '<!-- @trace("TR-IN") -->\n'
        '## Inside Head\n'
        '~~~\n'
        '<!-- @trace("TR-NEST") -->\n'
        '## Nest Head\n'
        '```\n'
        '<!-- @trace("TR-AFTER") -->\n'
        '## After Head\n'
    )
    bindings = extract_bindings(tmp_path)
    assert [(b["alias"], b["line"], b["symbol"]) for b in bindings] == [
        ("TR-OPEN", 1, "open-head"),
        ("TR-AFTER", 10, "after-head"),
    ]


def test_extract_md_invalid_bytes_replace_still_binds(tmp_path):
    (tmp_path / "bad.md").write_bytes(
        b'<!-- @trace("TR-BAD") -->\n## Caf\xe9 Head\n')
    bindings = extract_bindings(tmp_path)
    assert [(b["alias"], b["symbol"]) for b in bindings] == [
        ("TR-BAD", "caf-head")]


def test_extract_md_pending_sentinels_are_not_truthy(tmp_path):
    (tmp_path / "orphan.md").write_text(
        '```python\n'
        'x = 1\n'
        '```\n'
        '## Orphan Head\n'
    )
    (tmp_path / "plain.md").write_text(
        '<!-- @trace("TR-FIRST") -->\n'
        '## First Head\n'
        '## Bare Head\n'
        'plain text line\n'
        '## Orphan Head\n'
    )
    bindings = extract_bindings(tmp_path)
    assert [(b["alias"], b["file"], b["symbol"]) for b in bindings] == [
        ("TR-FIRST", "plain.md", "first-head")]
