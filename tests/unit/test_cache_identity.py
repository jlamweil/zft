'''Tests for cache key identity binding to gate fingerprint and contract hash.

Ensures that changes to the gate source or contract invalidate cached verdicts.
'''
import json
from pathlib import Path

from traceagent.gates.l1 import _cache_key, run_l1


def test_cache_key_changes_when_gate_fingerprint_changes(monkeypatch):
    import traceagent.gates.l1 as l1_mod
    key1 = _cache_key("TR-A", "b1", "oracle1")
    monkeypatch.setattr(l1_mod, "_GATE_FINGERPRINT", "different_fingerprint")
    key2 = _cache_key("TR-A", "b1", "oracle1")
    assert key1 != key2

def _seed_repo(tmp_path: Path):
    spec_dir = tmp_path / ".zft" / "specs" / "g"
    spec_dir.mkdir(parents=True)
    alias = "CACHE-IDENT-01"
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": alias,
        "domain": "g",
        "title": "cache identity test",
        "status": "VALIDATED",
        "version": 1,
        "content_hash": "0" * 64,
        "invariants": [{
            "id": alias,
            "statement": "when check() then ok",
            "property": "True",
            "check": {"kind": "property"},
        }],
        "external_links": [],
    }
    (spec_dir / f"{alias}.json").write_text(json.dumps(node))
    contracts_dir = tmp_path / ".zft" / "contracts"
    contracts_dir.mkdir(parents=True)
    (contracts_dir / "c.json").write_text(json.dumps({"name": "c", "clause_ids": [alias]}))
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_bound.py").write_text(
        f'# @trace("{alias}")\n'
        "def test_bound():\n    assert True\n"
    )
    (tmp_path / f"oracle_{alias}.py").write_text(
        "def check():\n"
        "    from pathlib import Path\n"
        f"    Path('sentinel_{alias}').write_text('')\n"
    )
    return tmp_path, alias

def test_cache_invalidation_when_gate_fingerprint_changes(monkeypatch, tmp_path):
    root, alias = _seed_repo(tmp_path)
    sentinel = tmp_path / f"sentinel_{alias}"
    if sentinel.exists():
        sentinel.unlink()
    v1 = run_l1(root)
    assert v1.executed == 1
    assert sentinel.is_file()
    sentinel.unlink()
    import traceagent.gates.l1 as l1_mod
    monkeypatch.setattr(l1_mod, "_GATE_FINGERPRINT", "different_fingerprint_2")
    v2 = run_l1(root)
    assert v2.executed == 1
    assert sentinel.is_file()
