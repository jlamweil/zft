"""C-06: store discovery + lint gate (schema, hashes, aliases, duplicates, manifest).

Seam: `zft lint [root]` exit codes; store.Store load/read.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from traceagent.spec.lint import lint_store

REPO = Path(os.environ.get("TRACEAGENT_REPO")
            or Path(__file__).resolve().parents[2])


def test_lint_own_store_green():
    """Self-check: our real 26-clause store must pass L0."""
    failures = lint_store(REPO)
    assert failures == []


# @trace("GATE-L0-HASH-VERIFY")
def test_torn_trailing_hash_line_detected(tmp_path):
    """A store node whose content_hash is wrong fails L0 with file detail."""
    spec_dir = tmp_path / ".zft" / "specs" / "x"
    spec_dir.mkdir(parents=True)
    node = {"node_id": "018f3a2b-9e41-7100-8000-000000000001",
            "alias": "X-ONE", "domain": "x", "title": "t",
            "status": "PROPOSED", "version": 1, "content_hash": "1" * 64,
            "invariants": [{"id": "X-INV-01", "statement": "WHEN a THE SYSTEM SHALL b",
                            "property": "forall x: ok(x)", "check": {"kind": "test"}}],
            "external_links": []}
    (spec_dir / "x-one.json").write_text(json.dumps(node))
    failures = lint_store(tmp_path)
    assert any("content_hash mismatch" in f and "x-one.json" in f for f in failures)


# @trace("GATE-DUPLICATE-CLAUSES")
def test_duplicate_clause_detection(tmp_path):
    """Two clauses with same §5.2 meaning (different alias) fail L0 (V9 lesson)."""
    spec_dir = tmp_path / ".zft" / "specs" / "x"
    spec_dir.mkdir(parents=True)
    base = {"node_id": "018f3a2b-9e41-7100-8000-000000000001",
            "alias": "X-ONE", "domain": "x", "title": "same",
            "status": "PROPOSED", "version": 1,
            "invariants": [{"id": "X-INV-01", "statement": "s", "property": "p",
                            "check": {"kind": "test"}}],
            "external_links": []}
    clone = dict(base, alias="X-TWO", node_id="018f3a2b-9e41-7100-8000-000000000002")
    # compute valid canonical hashes so only duplicate-detection fires
    from traceagent.spec.canon import canonical_hash

    for n in (base, clone):
        n["content_hash"] = canonical_hash(n)
        (spec_dir / f"{n['alias'].lower()}.json").write_text(json.dumps(n))
    failures = lint_store(tmp_path)
    assert any("duplicate content hash" in f for f in failures)


def test_cli_entrypoint_lint_green():
    """Entrypoint seam: `zft lint` exits 0 on the real repo."""
    r = subprocess.run([sys.executable, "-m", "traceagent.cli.main", "lint", str(REPO)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "L0 PASSED" in r.stdout
