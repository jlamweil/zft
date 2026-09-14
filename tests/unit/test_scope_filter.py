"""Phase C — cross-lineage clause ownership: optional `applies_to` scope field.

A clause may declare `applies_to: ["<workspace>", ...]` (list of package/
workspace names). Scope semantics (plan RECONCILE-2026-09-12 §4 option 1):

- `applies_to` absent or empty  ->  in scope everywhere (back-compat default).
- `applies_to` present          ->  in scope only for the named workspaces.
- Out-of-scope clauses are skipped by the coverage gate: they are neither due
  nor reported as uncovered — skipping must never weaken an in-scope clause.
"""

import json
from pathlib import Path

from traceagent.gates.l2 import _workspace_name, run_l2


def _node(alias: str, domain: str, applies_to=None, kind="manual") -> dict:
    node = {
        "node_id": f"018f3a2b-0000-7000-8000-{abs(hash(alias)) % 10**12:012d}",
        "alias": alias, "domain": domain, "title": alias.lower(),
        "status": "VALIDATED", "version": 1, "content_hash": "0" * 64,
        "invariants": [{"id": alias,
                        "statement": f"WHEN probed THE SYSTEM SHALL {alias.lower()}",
                        "property": "True", "check": {"kind": kind}}],
        "external_links": [],
    }
    if applies_to is not None:
        node["applies_to"] = applies_to
    return node


def _seed(tmp_path: Path, nodes: list[dict], project_name="traceagent") -> Path:
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    for i, node in enumerate(nodes):
        node["content_hash"] = f"{i}" * 64
        (spec / f"{node['alias'].lower()}.json").write_text(json.dumps(node))
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "{project_name}"\n')
    return tmp_path


def test_workspace_name_from_pyproject(tmp_path):
    root = _seed(tmp_path, [])
    assert _workspace_name(root) == "traceagent"


def test_workspace_name_absent_is_none(tmp_path):
    assert _workspace_name(tmp_path) is None


def test_out_of_scope_clause_is_not_due(tmp_path):
    root = _seed(tmp_path, [
        _node("SCOPE-EXCL", "g", applies_to=["other-workspace"]),
    ])
    verdict = run_l2(root, tier="fast")
    assert verdict.ok, verdict.failures
    # the excluded clause must not appear in the coverage universe at all
    assert "SCOPE-EXCL" not in json.dumps(verdict.coverage)


def test_out_of_scope_clause_is_skipped_not_uncovered(tmp_path):
    root = _seed(tmp_path, [
        _node("SCOPE-EXCL", "g", applies_to=["other-workspace"], kind="manual"),
    ])
    verdict = run_l2(root, tier="fast")
    assert verdict.ok, verdict.failures
    assert not any("SCOPE-EXCL" in f for f in verdict.failures)


def test_in_scope_named_workspace_stays_due(tmp_path):
    root = _seed(tmp_path, [
        _node("SCOPE-ZFT", "g", applies_to=["zft", "traceagent"]),
    ])
    verdict = run_l2(root, tier="fast")
    assert not verdict.ok, "in-scope clause with no binding must stay due"
    assert any("SCOPE-ZFT" in f for f in verdict.failures), \
        "in-scope clause with no binding must stay red (no weakening)"


def test_scope_never_rescues_an_unbound_in_scope_clause(tmp_path):
    root = _seed(tmp_path, [
        _node("SCOPE-HERE", "g", kind="manual"),
    ])
    verdict = run_l2(root, tier="fast")
    assert not verdict.ok, "missing binding for in-scope clause must stay red"
