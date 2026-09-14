"""B2 (P-006a): execute consumer oracle in L1.

Validate that property clauses require an oracle to be present and executed.
Four scenarios are covered:
1. Correct implementation + correct oracle → L1 ok.
2. Wrong implementation (value 41) + correct oracle → L1_ORACLE_FAIL.
3. Correct implementation + mutated oracle (expects 41) → L1_ORACLE_FAIL.
4. No oracle file present → L1_ORACLE_REQUIRED.
"""

import json
from pathlib import Path

from traceagent.gates.l1 import run_l1

ALIAS = "ORACLE-EXEC-01"


def _node(alias: str) -> dict:
    return {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": alias,
        "domain": "g",
        "title": "oracle exec test",
        "status": "VALIDATED",
        "version": 1,
        "content_hash": "0" * 64,
        "invariants": [
            {
                "id": alias,
                "statement": "when ... then ...",
                "property": "some property",
                "check": {"kind": "property"},
            }
        ],
        "external_links": [],
        # no oracle_file / oracle_sha256 – legacy path using default naming
    }


def _seed_repo(tmp_path: Path, *, impl_correct: bool = True,
                oracle_mutated: bool = False, missing_oracle: bool = False) -> Path:
    # spec directory and node
    spec_dir = tmp_path / ".zft" / "specs" / "g"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / f"{ALIAS}.json").write_text(json.dumps(_node(ALIAS)))

    # target module with @trace binding and implementation
    target_path = tmp_path / "target.py"
    impl_val = 42 if impl_correct else 41
    target_path.write_text(
        f"# @trace(\"{ALIAS}\")\n"
        "def value():\n"
        f"    return {impl_val}\n"
    )

    # dummy test file bound to the clause (does nothing but satisfies binding requirement)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_dummy.py").write_text(
        f"# @trace(\"{ALIAS}\")\n"
        "def test_dummy():\n    assert True\n"
    )

    # optional oracle file
    if not missing_oracle:
        oracle_path = tmp_path / f"oracle_{ALIAS}.py"
        if oracle_mutated:
            oracle_content = (
                "def check():\n"
                "    import target\n"
                "    assert target.value() == 41\n"
            )
        else:
            oracle_content = (
                "def check():\n"
                "    import target\n"
                "    assert target.value() == 42\n"
            )
        oracle_path.write_text(oracle_content)

    return tmp_path


def test_oracle_exec_correct_impl_and_oracle(tmp_path):
    root = _seed_repo(tmp_path)
    verdict = run_l1(root)
    assert verdict.ok, verdict.rejection


def test_oracle_exec_wrong_impl(tmp_path):
    root = _seed_repo(tmp_path, impl_correct=False)
    verdict = run_l1(root)
    assert not verdict.ok
    rej = verdict.rejection
    assert rej is not None
    assert rej["code"] == "L1_ORACLE_FAIL"
    assert rej["fault"] == "producer"
    assert rej["clause_ids"] == [ALIAS]


def test_oracle_exec_mutated_oracle(tmp_path):
    root = _seed_repo(tmp_path, oracle_mutated=True)
    verdict = run_l1(root)
    assert not verdict.ok
    rej = verdict.rejection
    assert rej is not None
    assert rej["code"] == "L1_ORACLE_FAIL"
    assert rej["fault"] == "producer"
    assert rej["clause_ids"] == [ALIAS]


def test_oracle_missing(tmp_path):
    root = _seed_repo(tmp_path, missing_oracle=True)
    verdict = run_l1(root)
    assert not verdict.ok
    rej = verdict.rejection
    assert rej is not None
    assert rej["code"] == "L1_ORACLE_REQUIRED"
    assert rej["fault"] == "producer"
    assert rej["clause_ids"] == [ALIAS]
