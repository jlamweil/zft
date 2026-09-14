"""L2 acceptance orchestration (plan C-25): coverage both ways + L1 + scoped mutation.

State transition (all gates): collect failures -> ok computed once at the end ->
typed rejection -> one summary ledger event. Store/binding load failures degrade
to a typed red verdict instead of aborting the check pipeline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from zft.debug.ledger import RunLedger
from zft.gates.l1 import L1Verdict, run_l1
from zft.lineage.matrix import coverage_report, list_all_elements, new_unbound_elements


@dataclass
class L2Verdict:
    stage: str
    ok: bool
    coverage: dict = field(default_factory=dict)
    failures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)  # typed, never gate-red
    rejection: dict | None = None
    l1: L1Verdict | None = None  # the embedded L1 run, for callers that summarize it
    l1_ok: bool = True          # flat fields (zft lineage seam) mirror l1
    l1_executed: int = 0


def run_l2(root: Path | str, tier: str = "fast", ledger: RunLedger | None = None,
           producer_model: str | None = None, gate_model: str | None = None,
           examples_timeout_s: int = 300, write_cache: bool = True) -> L2Verdict:
    root = Path(root)
    from zft.lineage.extract import extract_bindings
    from zft.spec.store import Store

    failures: list[str] = []
    store_nodes: dict[str, dict] = {}
    bindings: list[dict] = []
    try:
        store_nodes = Store.load(root).nodes
        bindings = extract_bindings(root, write_cache=write_cache)
    except Exception as e:  # noqa: BLE001 — evidence collection must red the gate, not crash it
        failures.append(f"L2: evidence collection failed ({e!r})")

    milestone = _current_milestone(root)
    deferred = _contract_meta(root).get("target_milestone", {})
    workspace = _workspace_name(root)
    due = {
        alias: node
        for alias, node in store_nodes.items()
        if deferred.get(alias, milestone) <= milestone
        and _in_scope(node, workspace)
    }
    warnings, elements = _reverse_elements(root)
    report = coverage_report(bindings, set(due), elements=elements)

    judge_excluded = sorted(
        alias for alias, node in due.items()
        if any(inv["check"]["kind"] == "judge" for inv in node["invariants"])
    )
    coverage = {
        **report,
        "judge_excluded": judge_excluded,
        "tier": tier,
    }

    # WP-D2: reverse coverage with baseline grandfathering — only elements added
    # since the baseline are flagged; absent baseline means the direction is
    # inert, which warns (vacuous, not complete) and never poses as live.
    baseline_elements = _load_baseline_elements(root)
    if baseline_elements is None:
        warnings.append(
            "TR-REVERSE-COVERAGE baseline absent: the new-element direction "
            "is inert (an absent baseline skips, it cannot flag) — seed it "
            "with `zft baseline` (the first real extraction) to make "
            "grandfathering live")
        new_unbound = []
    else:
        new_unbound = new_unbound_elements(
            list_all_elements(root), bindings, baseline_elements)
    if new_unbound:
        coverage["new_unbound"] = new_unbound
        failures.append(f"new unbound elements since baseline: {new_unbound}")
        if ledger:
            ledger.append({"event": "l2_reverse_coverage", "ok": False,
                           "new_unbound": new_unbound})

    uncovered = sorted(set(due) - set(report["covered_aliases"]) - set(judge_excluded))
    if uncovered:
        failures.append(f"uncovered clauses (no valid binding): {uncovered}")
        if ledger:
            ledger.append({"event": "l2_coverage", "ok": False, "uncovered": uncovered})

    l1_verdict = run_l1(root, ledger=ledger, bindings=bindings,
                        examples_timeout_s=examples_timeout_s,
                        write_cache=write_cache)
    if not l1_verdict.ok:
        failures.extend(l1_verdict.failures)

    ok = not failures
    verdict = L2Verdict(
        stage=f"L2-{tier}",
        ok=ok,
        coverage=coverage,
        failures=failures,
        warnings=warnings,
        l1=l1_verdict,
        l1_ok=l1_verdict.ok,
        l1_executed=l1_verdict.executed,
        rejection=None if not failures else {
            "code": "L2_REVERSE_COVERAGE" if new_unbound and not uncovered
                    else "L2_ACCEPTANCE",
            "clause_ids": uncovered or sorted({f.split(":")[0] for f in l1_verdict.failures}),
            "fault": "implementation" if not uncovered else "contract",
            "expected": "all due clauses covered by bindings and executed evidence",
            "actual": failures,
            "evidence_refs": [],
        },
    )
    if ledger:
        ledger.append({"event": "l2", "ok": ok, "tier": tier,
                       "coverage": coverage, "failures": failures,
                       "warnings": warnings})
    return verdict


def _reverse_elements(root: Path) -> tuple[list[str], list[str]]:
    """(warnings, elements) for the reverse-coverage direction.

    The element universe is caller-declared in the contract manifest
    (meta.element_roots: repo-relative files or directories). Reverse
    coverage over an empty element set is vacuous, never complete — so an
    unconfigured or fileless universe earns a typed warning while the
    0/0 report stays honest about seeing nothing.
    """
    roots = _contract_meta(root).get("element_roots") or []
    if not roots:
        return (["TR-REVERSE-COVERAGE vacuous: contract meta.element_roots is "
                 "not configured — element set is empty, 0/0 must not read "
                 "as complete"], [])
    from zft.lineage.extract import LANG, skipped_dir

    found: set[str] = set()
    for entry in roots:
        p = root / entry
        if p.is_dir():
            for f in p.rglob("*"):
                if (f.suffix in LANG and f.is_file()
                        and not any(skipped_dir(part)
                                    for part in f.relative_to(root).parts[:-1])):
                    found.add(f.relative_to(root).as_posix())
        elif p.is_file() and p.suffix in LANG:
            found.add(p.relative_to(root).as_posix())
    if not found:
        return ([f"TR-REVERSE-COVERAGE vacuous: element_roots {sorted(roots)} "
                 "matched no deliverable files — element set is empty"], [])
    return [], sorted(found)



def _load_baseline_data(root: Path):
    """Best-effort baseline JSON; ``None`` means absent/malformed -> skip (zft WP-D2)."""
    path = root / ".zft" / "baseline" / "elements.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _load_baseline_elements(root: Path) -> set[str] | None:
    """Baseline element set; ``None`` for an absent or malformed baseline (skip)."""
    data = _load_baseline_data(root)
    if data is None:
        return None
    elements = data.get("elements")
    if not isinstance(elements, list):
        return None
    return {element for element in elements if isinstance(element, str)}


def _contract_meta(root: Path) -> dict:
    """Contract manifest meta; {} when absent or corrupt (contract gate, not crash)."""
    from zft.spec.store import load_contract

    try:
        return load_contract(root).get("meta", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _workspace_name(root: Path) -> str | None:
    """Workspace identity: the gated root's pyproject [project].name, else None.

    Cross-lineage ownership (recon 2026-09-12 Phase C): a clause may declare
    `applies_to: [...]` naming the workspaces it governs; the workspace name
    is what a clause scope is matched against.
    """
    pyproject = Path(root) / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        for line in pyproject.read_text().splitlines():
            s = line.strip()
            if s.startswith("name") and "=" in s:
                return s.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _in_scope(node: dict, workspace: str | None) -> bool:
    """Clause scope gate (Phase C option 1): default include, never weaken.

    `applies_to` absent/empty -> in scope everywhere. Present -> in scope only
    for the named workspaces; an undeterminable workspace name skips scoped
    clauses (they are neither due nor uncovered — skipping never rescues an
    in-scope clause, which stays due and stays red when unbound).
    """
    applies = node.get("applies_to")
    if not applies:
        return True
    return bool(workspace) and workspace in applies


def _current_milestone(root: Path) -> str:
    return _contract_meta(root).get("current_milestone", "v0")


# milestone semantics: a clause is due unless deferred to a later milestone
# (contract manifest meta.target_milestone — plan §3bis)
