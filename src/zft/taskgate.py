"""Task gate (ENF clauses): pre-dispatch enforcement + post-task coverage verdict.

Writer lanes may only be dispatched against a contract that exists on file
(`[contract: NAME]` in the task description resolving to
.zft/contracts/NAME.json); read-only lanes are exempt. An ungated override
(`[ungated: reason]` or a truthy ZFT_ALLOW_UNGATED) allows a writer
dispatch but is flagged `gated: False` in the audit log. Every decision —
allowed, blocked, verdict, error — appends exactly one JSONL record to
<zft-root>/.zft/audit.log.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

READONLY_LANES: set[str] = {
    "explorer", "explore", "code-explorer", "librarian", "oracle",
    "analyst", "councillor", "vision", "vision-consultant", "researcher",
}

CONTRACT_RE = re.compile(r"\[contract:\s*([A-Za-z0-9._-]+)\]")
OVERRIDE_RE = re.compile(r"\[ungated:\s*([^\]]+)\]")


def classify(subagent: str) -> str:
    """Lane classification: unknown subagent types default to writer (safe side).

    Case-insensitive: harnesses capitalize agent types (zcode's `Explore`),
    opencode uses lowercase — same lane either way.
    """
    return "readonly" if subagent.strip().lower() in READONLY_LANES else "writer"


def parse_contract(description: str) -> str | None:
    """Extract the contract reference from `[contract: NAME]`, else None."""
    m = CONTRACT_RE.search(description)
    return m.group(1) if m else None


def parse_override(description: str) -> str | None:
    """Extract the ungated-override reason from `[ungated: text]`, else None."""
    m = OVERRIDE_RE.search(description)
    return m.group(1) if m else None


def append_audit(root: Path, record: dict) -> None:
    """Append one JSONL record to root/.zft/audit.log (mkdir parents)."""
    path = Path(root) / ".zft" / "audit.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_override() -> str | None:
    """ZFT_ALLOW_UNGATED with a truthy value authorizes an ungated dispatch."""
    val = os.environ.get("ZFT_ALLOW_UNGATED", "").strip().lower()
    return val if val in {"1", "true", "yes", "on"} else None


def _audit(root: Path, lane: str, subagent: str, **fields) -> None:
    append_audit(root, {"ts": _now(), "subagent": subagent, "lane": lane, **fields})


def gate_before(subagent: str, description: str, root: Path) -> tuple[int, dict]:
    """Pre-dispatch enforcement (ENF-WRITER-REQUIRES-CONTRACT, ENF-READONLY-EXEMPT,
    ENF-AUDIT-LOGGED): block writer lanes without a contract reference, exempt
    read-only lanes, always audit."""
    lane = classify(subagent)
    if lane == "readonly":
        _audit(root, lane, subagent, phase="before", gated=False, contract=None,
               override=False, reason="read-only lane")
        return 0, {"allow": True, "gated": False, "lane": "readonly",
                   "contract": None, "reason": "read-only lane", "override": False}

    contract = parse_contract(description)
    override = parse_override(description) or _env_override()
    if override:
        _audit(root, lane, subagent, phase="before", gated=False, contract=contract,
               override=True, reason=override)
        return 0, {"allow": True, "gated": False, "lane": "writer",
                   "contract": contract, "reason": override, "override": True}

    contract_path = (Path(root) / ".zft" / "contracts" / f"{contract}.json"
                     if contract else None)
    if contract_path is not None and contract_path.exists():
        _audit(root, lane, subagent, phase="before", gated=True, contract=contract,
               override=False, reason="contract on file")
        return 0, {"allow": True, "gated": True, "lane": "writer",
                   "contract": contract, "reason": "contract on file", "override": False}

    reason = (f"writer lane requires an existing [contract: ...] reference "
              f"({contract})" if contract
              else "writer lane requires a [contract: <name>] reference — none given")
    _audit(root, lane, subagent, phase="before", gated=False, contract=contract,
           override=False, reason=reason)
    return 1, {"allow": False, "gated": False, "lane": "writer", "contract": contract,
               "reason": reason, "override": False,
               "code": "ENF_WRITER_REQUIRES_CONTRACT"}


def gate_after(subagent: str, description: str, root: Path) -> tuple[int, dict]:
    """Post-task verdict (ENF-CONTRACT-VERDICT): forward coverage of the
    contract's due clauses against mechanically extracted bindings.

    due = clause_ids minus clauses deferred to a milestone after
    meta.current_milestone (mirrors gates/l2.py).
    """
    lane = classify(subagent)
    if lane == "readonly":
        _audit(root, lane, subagent, phase="after", gated=True, contract=None,
               verdict="n/a", missing=[])
        return 0, {"verdict": "n/a", "lane": "readonly", "contract": None,
                   "missing": []}

    contract = parse_contract(description)
    if not contract:
        _audit(root, lane, subagent, phase="after", gated=True, contract=None,
               verdict="error", missing=[])
        return 2, {"verdict": "error", "contract": None,
                   "reason": "no [contract: <name>] reference in description"}

    cpath = Path(root) / ".zft" / "contracts" / f"{contract}.json"
    try:
        c = json.loads(cpath.read_text())
    except (OSError, json.JSONDecodeError) as e:
        _audit(root, lane, subagent, phase="after", gated=True, contract=contract,
               verdict="error", missing=[])
        return 2, {"verdict": "error", "contract": contract,
                   "reason": f"contract unreadable: {e}"}

    meta = c.get("meta") or {}
    current = meta.get("current_milestone") or "v0"
    deferred = meta.get("target_milestone") or {}
    clause_ids = set(c.get("clause_ids") or [])
    due = clause_ids - {k for k, v in deferred.items() if v > current}

    from zft.lineage.extract import extract_bindings

    bound = {b["alias"] for b in extract_bindings(root)}
    missing = sorted(due - bound)
    covered = sorted(due & bound)
    verdict = "covered" if not missing else "missing"
    _audit(root, lane, subagent, phase="after", gated=True, contract=contract,
           verdict=verdict, missing=missing)
    return (0 if not missing else 1), {"verdict": verdict, "contract": contract,
                                       "due": sorted(due), "covered": covered,
                                       "missing": missing}
