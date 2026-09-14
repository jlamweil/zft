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
