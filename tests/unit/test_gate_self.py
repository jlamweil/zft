'''WP-E1 — Gap-001 self-test (permanent regression).'''

import json

from traceagent.gates.l1 import run_l1


def _seed_repo(tmp_path, impl_return_42: bool, with_oracle: bool):
    spec = tmp_path / ".zft" / "specs" / "gap"
    spec.mkdir(parents=True)
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": "GAP-001",
        "domain": "gap",
        "title": "gap-001 property",
        "status": "VALIDATED",
        "version": 1,
        "content_hash": "0" * 64,
        "invariants": [{
            "id": "GAP-001",
            "statement": "property answer() == 42",
            "property": "answer() == 42",
            "check": {"kind": "property"}
        }],
        "external_links": []
    }
    (spec / "gap-001.json").write_text(json.dumps(node))

    impl = tmp_path / "impl.py"
    impl.write_text(
        f"def answer():\n    return {42 if impl_return_42 else 41}"
    )

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_gap.py").write_text(
        '# @trace("GAP-001")\n'
        'def test_dummy():\n    assert True\n'
    )

    if with_oracle:
        oracle = tmp_path / "oracle_GAP-001.py"
        oracle.write_text(
            'def check():\n    from impl import answer\n    assert answer() == 42\n'
        )
    return tmp_path

def test_gap_oracle_missing(tmp_path):
    root = _seed_repo(tmp_path, impl_return_42=False, with_oracle=False)
    verdict = run_l1(root)
    assert not verdict.ok
    assert verdict.rejection is not None
    assert verdict.rejection["code"] == "L1_ORACLE_REQUIRED"
    assert "GAP-001" in verdict.rejection["clause_ids"]

def test_gap_correct_impl_and_oracle(tmp_path):
    root = _seed_repo(tmp_path, impl_return_42=True, with_oracle=True)
    verdict = run_l1(root)
    assert verdict.ok, verdict.rejection
    assert verdict.rejection is None
