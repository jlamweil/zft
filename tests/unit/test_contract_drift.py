# Tests for L0 contract hash drift detection (GATE-L0-HASH-VERIFY).

import copy
import hashlib
import json
import shutil
from pathlib import Path

from traceagent.gates.l0 import run_l0


def _copy_repo_fixture(tmp_path: Path) -> Path:
    """Copy the repo's `.zft/specs` and a contract JSON into a temporary location.

    Returns the path to the copied contract file.
    """
    repo_root = Path(__file__).resolve().parents[2]
    # copy specs directory
    src_specs = repo_root / ".zft" / "specs"
    dst_specs = tmp_path / ".zft" / "specs"
    shutil.copytree(src_specs, dst_specs)
    # copy contract file (use the latest one)
    src_contract = repo_root / ".zft" / "contracts" / "traceagent-v0.json"
    dst_contract_dir = tmp_path / ".zft" / "contracts"
    dst_contract_dir.mkdir(parents=True, exist_ok=True)
    dst_contract = dst_contract_dir / "traceagent-v0.json"
    shutil.copy2(src_contract, dst_contract)
    return dst_contract


def _add_contract_hash(contract_path: Path) -> str:
    """Compute the canonical hash of *contract_path* (excluding any existing
    ``contract_sha256``) and write it back under ``meta.contract_sha256``.
    Returns the computed hash.
    """
    contract = json.loads(contract_path.read_text())
    # make a deepcopy to avoid mutating the original while computing
    contract_copy = copy.deepcopy(contract)
    contract_copy.get("meta", {}).pop("contract_sha256", None)
    canonical = json.dumps(contract_copy, sort_keys=True).encode()
    contract_hash = hashlib.sha256(canonical).hexdigest()
    # write back with the hash field
    meta = contract.setdefault("meta", {})
    meta["contract_sha256"] = contract_hash
    contract_path.write_text(json.dumps(contract, indent=2))
    return contract_hash


def test_contract_hash_drift(tmp_path: Path):
    # Prepare a repo copy with specs and contract
    contract_path = _copy_repo_fixture(tmp_path)

    # 1️⃣ Valid contract with matching hash → L0 passes
    _add_contract_hash(contract_path)
    verdict = run_l0(tmp_path)
    assert verdict.ok is True
    assert verdict.rejection is None

    # 2️⃣ Tamper the contract (change a non‑hash‑affecting field) → drift detection
    contract = json.loads(contract_path.read_text())
    contract["name"] = contract["name"] + "-tampered"
    contract_path.write_text(json.dumps(contract, indent=2))
    verdict2 = run_l0(tmp_path)
    assert verdict2.ok is False
    assert verdict2.rejection["code"] == "L0_CONTRACT_HASH_DRIFT"
    assert verdict2.rejection["fault"] == "contract"

    # 3️⃣ Remove the hash field → gate should ignore and pass
    contract = json.loads(contract_path.read_text())
    contract.get("meta", {}).pop("contract_sha256", None)
    contract_path.write_text(json.dumps(contract, indent=2))
    verdict3 = run_l0(tmp_path)
    assert verdict3.ok is True
    assert verdict3.rejection is None
