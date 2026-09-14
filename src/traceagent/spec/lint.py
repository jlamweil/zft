"""L0 rule pack (plan §4 / C-21, C-41): findings-based lint over the clause store.

Rules ACCUMULATE: every finding is collected, never first-exit. Denies block
the gate; warns publish as advisories. `lint_store` keeps the legacy seam —
rendered DENY strings — for callers that predate structured findings; the
structured source of truth is `collect_findings`.

Contract-file JSON errors still raise (uncaught): a corrupt contract is a
crashed lint, which run_l0 reports as a typed red verdict — pinned by
test_l0_crash_degrades_to_red.
"""
from __future__ import annotations

import json
from pathlib import Path

from traceagent.spec.canon import canonical_hash
from traceagent.spec.findings import DENY, WARN, Finding, render_finding
from traceagent.spec.schema import validate_node

_STATUS_WARNS = {
    "DRAFT": ("CLAUSE_STATUS_DRAFT",
              "clause is DRAFT — evidence is advisory until VALIDATED",
              "validate the clause before its evidence is relied on (consumer authorization)"),
    "DEPRECATED": ("CLAUSE_STATUS_DEPRECATED",
                   "clause is DEPRECATED — kept for lineage only",
                   "archive the node or drop it from due contracts"),
}


def collect_findings(root: Path | str) -> list[Finding]:
    """All integrity findings ([] = clean). Deterministic order: sorted node
    files, per-file rule order, then store-wide duplicate checks, then contracts."""
    root = Path(root)
    findings: list[Finding] = []
    nodes: dict[str, dict] = {}
    by_hash: dict[str, list[str]] = {}

    spec_dir = root / ".zft" / "specs"
    if not spec_dir.exists():
        return [Finding(
            code="STORE_MISSING", severity=DENY,
            msg="no clause store found — nothing is governed (CON-VALIDATED-OR-NO-START)",
            hint="seed the store with `traceagent create --alias <ALIAS>`")]
    for path in sorted(spec_dir.rglob("*.json")):
        rel = path.relative_to(root).as_posix()
        try:
            node = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            findings.append(Finding(
                code="STORE_NODE_JSON", severity=DENY, file=rel,
                msg=f"invalid JSON ({e})",
                hint="repair the JSON syntax of the node file"))
            continue
        try:
            validate_node(node)
        except Exception as e:  # noqa: BLE001 — every schema error is a deny finding
            findings.append(Finding(
                code="STORE_NODE_SCHEMA", severity=DENY, file=rel,
                msg=str(e),
                hint="fix the node to satisfy the TraceAgentClauseNode schema"))
            continue
        expected = canonical_hash(node)
        if node["content_hash"] != expected:
            findings.append(Finding(
                code="STORE_HASH_MISMATCH", severity=DENY,
                alias=node["alias"], file=rel,
                msg=f"content_hash mismatch\n"
                f"  stored:     {node['content_hash']}\n  recomputed: {expected}",
                hint="recompute content_hash with spec.canon.canonical_hash"))
        if node["alias"] in nodes:
            findings.append(Finding(
                code="STORE_ALIAS_DUPLICATE", severity=DENY,
                alias=node["alias"], file=rel,
                msg=f"duplicate alias '{node['alias']}'",
                hint="aliases are clause identity — rename one node"))
        nodes[node["alias"]] = node
        by_hash.setdefault(node["content_hash"], []).append(node["alias"])
        if node["status"] in _STATUS_WARNS:
            code, msg, hint = _STATUS_WARNS[node["status"]]
            findings.append(Finding(code=code, severity=WARN, alias=node["alias"],
                                    file=rel, msg=msg, hint=hint))

    for h, aliases in sorted(by_hash.items()):
        if len(aliases) > 1:
            findings.append(Finding(
                code="STORE_HASH_DUPLICATE", severity=DENY, alias=aliases[0],
                msg=f"duplicate content hash {h[:12]}… for clauses {sorted(aliases)}",
                hint="two aliases claim one clause — delete or rewrite one"))

    contracts = root / ".zft" / "contracts"
    for cpath in sorted(contracts.glob("*.json")) if contracts.exists() else []:
        c = json.loads(cpath.read_text())  # uncaught: corrupt contract = crashed lint
        rel = cpath.relative_to(root).as_posix()
        for field in ("contract_id", "name", "status", "version", "clause_ids"):
            if field not in c:
                findings.append(Finding(
                    code="CONTRACT_MANIFEST_FIELD", severity=DENY, file=rel,
                    msg=f"manifest missing '{field}'",
                    hint="add the missing field to the contract manifest"))
        for cid in c.get("clause_ids", []):
            if cid not in nodes:
                findings.append(Finding(
                    code="CONTRACT_DANGLING_CLAUSE", severity=DENY,
                    alias=cid, file=rel,
                    msg=f"clause_id '{cid}' resolves to no node",
                    hint="remove the reference or create the clause node"))

    return findings


def lint_store(root: Path | str) -> list[str]:
    """Legacy seam: rendered DENY findings ([] = pass). Warns are advisory and
    never appear here — see collect_findings / run_l0 warnings."""
    return [render_finding(f) for f in collect_findings(root) if f.severity == DENY]
