def check():
    """Oracle for TR-DETERMINISTIC-EXTRACTION property clause.

    Asserts that binding extraction is deterministic: two runs over the same
    source tree produce identical sorted results.
    """
    import tempfile
    from pathlib import Path
    from traceagent.lineage.extract import extract_bindings

    # Samples mirroring tests/unit/test_lineage_extract.py:SAMPLES
    samples = {
        "sample.py": '# @trace("TR-DETERMINISTIC-EXTRACTION")\n' 'def func():\n    pass\n',
        "sample.ts": '// @trace("TR-DETERMINISTIC-EXTRACTION")\n' 'export function func(): void {}\n',
        "sample.rs": '// @trace("TR-DETERMINISTIC-EXTRACTION")\n' 'pub fn func() {}\n',
    }

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for name, src in samples.items():
            (root / name).write_text(src)
        first = extract_bindings(root)
        second = extract_bindings(root)
        assert first == second, "extraction must be deterministic"
