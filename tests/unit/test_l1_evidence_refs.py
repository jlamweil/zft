"""L1 evidence references: executed evidence must be recorded, not dropped.

B2 follow-up: run_l1 executes the pinned/consumer oracle and the bound suites,
but the verdict's evidence_refs was hard-coded to [] — the executed evidence
was never recorded. L1Verdict must carry evidence_refs:
- a contract entry (sha256 of the contract manifest, best-effort),
- a per-clause tests entry (bound files + suite digest),
- a per-executed-oracle entry (oracle filename + oracle digest).
The typed rejection must carry the same list when the gate fails.
"""
import hashlib
import json
import re
from pathlib import Path

from traceagent.gates.l1 import run_l1
from traceagent.spec.store import load_contract

ALIAS = "EVID-REF-01"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _node(alias: str) -> dict:
    return {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": alias,
        "domain": "g",
        "title": "evidence refs test",
        "status": "VALIDATED",
        "version": 1,
        "content_hash": "0" * 64,
        "invariants": [
            {
                "id": alias,
                "statement": "when value() THE SYSTEM SHALL return 42",
                "property": "value() == 42",
                "check": {"kind": "property"},
            }
        ],
        "external_links": [],
    }


def _seed_repo(tmp_path: Path, *, oracle_fails: bool = False) -> Path:
    """Repo with one property clause, a real oracle, a bound test, and a contract."""
    spec_dir = tmp_path / ".zft" / "specs" / "g"
    spec_dir.mkdir(parents=True)
    (spec_dir / f"{ALIAS}.json").write_text(json.dumps(_node(ALIAS)))

    contracts_dir = tmp_path / ".zft" / "contracts"
    contracts_dir.mkdir(parents=True)
    (contracts_dir / "evid-ref-v0.json").write_text(json.dumps({
        "name": "evid-ref-v0",
        "clause_ids": [ALIAS],
    }))

    (tmp_path / "target.py").write_text(
        f'# @trace("{ALIAS}")\n'
        "def value():\n"
        "    return 42\n"
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_bound.py").write_text(
        f'# @trace("{ALIAS}")\n'
        "def test_bound():\n    assert True\n"
    )

    expected = 41 if oracle_fails else 42
    (tmp_path / f"oracle_{ALIAS}.py").write_text(
        "def check():\n"
        "    import target\n"
        f"    assert target.value() == {expected}\n"
    )
    return tmp_path


def _refs_by_kind(refs: list[dict]) -> dict[str, dict]:
    return {r["kind"]: r for r in refs}


def test_evidence_refs_recorded_on_green(tmp_path):
    root = _seed_repo(tmp_path)
    verdict = run_l1(root)
    assert verdict.ok, verdict.rejection
    refs = verdict.evidence_refs
    assert refs, "evidence_refs must be non-empty"
    by_kind = _refs_by_kind(refs)

    # contract entry: 64-hex sha256 matching the canonical manifest digest
    contract = by_kind["contract"]
    assert HEX64.match(contract["sha256"])
    expected_contract = hashlib.sha256(
        json.dumps(load_contract(root), sort_keys=True).encode()
    ).hexdigest()
    assert contract["sha256"] == expected_contract

    # tests entry: the bound test file(s) and the suite digest
    tests = by_kind["tests"]
    assert tests["alias"] == ALIAS
    assert "tests/test_bound.py" in tests["files"]
    assert HEX64.match(tests["sha256"])

    # oracle entry: the oracle filename and its actual digest
    oracle = by_kind["oracle"]
    assert oracle["alias"] == ALIAS
    assert oracle["file"] == f"oracle_{ALIAS}.py"
    assert oracle["sha256"] == hashlib.sha256(
        (root / f"oracle_{ALIAS}.py").read_bytes()
    ).hexdigest()


def test_rejection_carries_same_evidence_refs_on_oracle_fail(tmp_path):
    root = _seed_repo(tmp_path, oracle_fails=True)
    verdict = run_l1(root)
    assert not verdict.ok
    assert verdict.rejection is not None
    assert verdict.rejection["code"] == "L1_ORACLE_FAIL"
    assert verdict.rejection["evidence_refs"] == verdict.evidence_refs
    assert {"contract", "tests", "oracle"} <= set(_refs_by_kind(verdict.evidence_refs))
