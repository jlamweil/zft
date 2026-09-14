"""C-38: check pipeline completeness — gherkin stage, L1 summary, gate_log, reverse coverage."""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("TRACEAGENT_REPO") or os.environ.get("ZFT_REPO")
      or Path(__file__).resolve().parents[2])

def _live_counts() -> tuple[int, int]:
    """(node count, milestone-scoped due count) derived from the live store + contract."""
    from traceagent.gates.l2 import _current_milestone
    from traceagent.spec.store import Store, load_contract

    nodes = Store.load(REPO).nodes
    deferred = load_contract(REPO).get("meta", {}).get("target_milestone", {})
    milestone = _current_milestone(REPO)
    due = len({a for a in nodes if deferred.get(a, milestone) <= milestone})
    return len(nodes), due


def _check():
    return subprocess.run([sys.executable, "-m", "traceagent.cli.main", "check", str(REPO)],
                          capture_output=True, text=True)


def test_check_green_and_complete():
    r = _check()
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    n_nodes, n_due = _live_counts()
    expected_keys = [
        f'"gherkin_scenarios": {n_nodes}',
        '"gherkin_ok": true',
        '"l1"',
        '"gate_log"',
        '"out_of_contract"',
        f'"due": {n_due}',
        '"deferred"',
    ]
    for key in expected_keys:
        assert key in out, f"missing {key} in check output"


def test_check_gherkin_stage_runs_scenarios():
    """The gherkin fallback stage must actually execute scenarios, not just render."""
    r = _check()
    n_nodes, _ = _live_counts()
    assert f'"gherkin_scenarios": {n_nodes}' in r.stdout


def test_gate_log_projection_attached():
    """Identity is caller-supplied, never invented: with no flags/config envs
    the models stay null and the claim fails closed model-dependent."""
    r = _check()
    assert r.returncode == 0, r.stdout + r.stderr
    assert '"producer": null' in r.stdout and '"gate": null' in r.stdout, \
        "unsupplied identity must stay null, not a default name"
    assert '"model_dependent": true' in r.stdout, \
        "no proven model difference -> no independence claim"
    assert "producer-dev" not in r.stdout


def test_check_reverse_coverage_nonvacuous():
    """NEXT_STEPS #4 done-when: the declared element slice runs live —
    nonzero justified elements, no vacuous-direction warning."""
    import json
    r = _check()
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["l2_warnings"] == [], out["l2_warnings"]
    assert out["coverage"]["elements_total"] > 0
    assert out["coverage"]["elements_justified"] > 0
