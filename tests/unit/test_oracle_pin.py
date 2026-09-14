"""B1 (P-006a): contract-pinned oracle verification.

A clause may specify `oracle_file` (relative path) and `oracle_sha256`
(64‑hex string). L1 must verify the pin before any execution; missing
file or hash mismatch yields a typed rejection `L1_ORACLE_PIN_MISMATCH`
with fault "producer".
"""

import hashlib
import json
from pathlib import Path

from traceagent.gates.l1 import run_l1
from traceagent.spec.schema import validate_node

ALIAS = "PIN-TEST-01"


def _node_with_pin(oracle_path: str, sha256: str) -> dict:
    """Return a minimal clause node that includes oracle pin fields."""
    return {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": ALIAS,
        "domain": "g",
        "title": "oracle pin test",
        "status": "VALIDATED",
        "version": 1,
        "content_hash": "0" * 64,
        "invariants": [
            {
                "id": ALIAS,
                "statement": "when ... then ...",
                "property": "some property",
                "check": {"kind": "property"},
            }
        ],
        "external_links": [],
        "oracle_file": oracle_path,
        "oracle_sha256": sha256,
    }


def _seed_repo(tmp_path: Path, *, mismatch: bool = False, missing: bool = False):
    """Create a repo with a property clause that pins an oracle.

    If ``mismatch`` is True, the oracle file's content does not match the
    declared hash; ``missing`` means the oracle file is not created at all.
    """
    # spec location
    spec_dir = tmp_path / ".zft" / "specs" / "g"
    spec_dir.mkdir(parents=True)
    # oracle file and hash
    oracle_content = "def answer(): return 42\n" if not mismatch else "def answer(): return 0\n"
    oracle_rel = "oracles/pin_oracle.py"
    oracle_abs = tmp_path / oracle_rel
    if not missing:
        oracle_abs.parent.mkdir(parents=True, exist_ok=True)
        oracle_abs.write_text(oracle_content)
    sha = hashlib.sha256(oracle_content.encode()).hexdigest()
    # create node (use declared sha unless we want mismatch)
    node = _node_with_pin(oracle_rel, sha if not mismatch else "0" * 64)
    (spec_dir / f"{ALIAS}.json").write_text(json.dumps(node))
    # test file (bound via @trace)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_bound.py").write_text(
        f"# @trace(\"{ALIAS}\")\n"
        "def test_bound():\n    assert True\n"
    )
    return tmp_path


def test_schema_accepts_oracle_fields():
    # generic node with oracle pin fields – validate_schema should accept it
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": "DUMMY-ALIAS",
        "domain": "g",
        "title": "test",
        "status": "VALIDATED",
        "version": 1,
        "content_hash": "0" * 64,
        "invariants": [
            {
                "id": "DUMMY-ALIAS",
                "statement": "stmt",
                "property": "prop",
                "check": {"kind": "property"},
            }
        ],
        "external_links": [],
        "oracle_file": "path/to/oracle.py",
        "oracle_sha256": "a" * 64,
    }
    # should not raise
    validate_node(node)


def test_pin_ok(tmp_path):
    root = _seed_repo(tmp_path)
    verdict = run_l1(root)
    assert verdict.ok, verdict.rejection
    # No typed pin mismatch rejection should be present
    if verdict.rejection:
        assert verdict.rejection["code"] != "L1_ORACLE_PIN_MISMATCH"


def test_pin_hash_mismatch(tmp_path):
    root = _seed_repo(tmp_path, mismatch=True)
    verdict = run_l1(root)
    assert not verdict.ok
    rej = verdict.rejection
    assert rej is not None
    assert rej["code"] == "L1_ORACLE_PIN_MISMATCH"
    assert rej["fault"] == "producer"
    assert rej["clause_ids"] == [ALIAS]


def test_pin_file_missing(tmp_path):
    root = _seed_repo(tmp_path, missing=True)
    verdict = run_l1(root)
    assert not verdict.ok
    rej = verdict.rejection
    assert rej is not None
    assert rej["code"] == "L1_ORACLE_PIN_MISMATCH"
    assert rej["fault"] == "producer"
    assert rej["clause_ids"] == [ALIAS]
