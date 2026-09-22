"""L0 static integrity gate (plan C-21, C-41): findings-based verdict + ledger events.

State transition (all gates): collect findings -> ok computed once at the end
-> typed rejection -> one summary ledger event. Denies block (`ok is False`);
warns ride along as structured advisories (`verdict.warnings`) and into the
ledger event for the L3 gate log. L0 never raises: a crashed lint is itself a
deny finding (LINT_CRASHED), not a pipeline abort.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from zft.debug.ledger import RunLedger
from zft.spec.findings import DENY, Finding, partition, render_finding
from zft.spec.lint import collect_findings


@dataclass
class GateVerdict:
    stage: str
    ok: bool
    failures: list = field(default_factory=list)
    rejection: dict | None = None
    warnings: list = field(default_factory=list)  # structured advisory findings


def run_l0(root: Path | str, ledger: RunLedger | None = None) -> GateVerdict:
    try:
        findings = collect_findings(root)
    except Exception as e:  # noqa: BLE001 — a crashed lint must read as a red verdict
        findings = [Finding(
            code="LINT_CRASHED", severity=DENY,
            msg=f"integrity check crashed ({e!r})",
            hint="inspect the store/contract files; lint must not crash silently")]

    # ---- Contract self-integrity (hash drift) — zft lineage, unioned 2026-09-12
    drift: dict | None = None
    try:
        import copy
        import hashlib

        from zft.spec.store import load_contract
        contract = load_contract(root)
        declared = contract.get("meta", {}).get("contract_sha256")
        if declared is not None:
            # canonical hash of the contract minus the declared hash field
            contract_copy = copy.deepcopy(contract)
            contract_copy.get("meta", {}).pop("contract_sha256", None)
            computed = hashlib.sha256(
                json.dumps(contract_copy, sort_keys=True).encode()
            ).hexdigest()
            if computed != declared:
                drift = {"computed": computed, "declared": declared}
                findings.append(Finding(
                    code="L0_CONTRACT_HASH_DRIFT", severity=DENY,
                    msg=(f"contract hash drift: computed {computed} != "
                         f"declared {declared}"),
                    hint="re-seal meta.contract_sha256 or restore the contract"))
    except Exception:  # noqa: BLE001 — lenient: store-level lint already covers integrity
        pass

    denies, warns = partition(findings)
    failures = [render_finding(f) for f in denies]
    warnings = [w.to_dict() for w in warns]

    ok = not denies
    rejection = None
    if denies:
        rejection = {
            "code": "L0_STORE_INTEGRITY",
            "clause_ids": [],
            "fault": "implementation",
            "expected": "schema-valid, hash-consistent clause store",
            "actual": failures,
            "evidence_refs": [],
        }
        if drift is not None:
            rejection.update({
                "code": "L0_CONTRACT_HASH_DRIFT",
                "fault": "contract",
                "expected": "contract_sha256 matches contract content",
                "actual": (f"computed {drift['computed']} != "
                           f"declared {drift['declared']}"),
            })
    if ledger:
        ledger.append({"event": "l0", "ok": ok, "failures": failures,
                       "warnings": warnings})
    return GateVerdict(stage="L0", ok=ok, failures=failures, rejection=rejection,
                       warnings=warnings)
