"""C-35: `zft check .` — the repo gate-keeps itself (self-dogfood).

Runs L0 → coverage (milestone-scoped) → L1 as CI would. Contract assertions
independent of implementation state: deferred clauses must not be due, and a
full due set must be coverage-complete.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("TRACEAGENT_REPO")
            or Path(__file__).resolve().parents[2])


def test_check_green_on_repo():
    r = subprocess.run([sys.executable, "-m", "traceagent.cli.main", "check", str(REPO)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "L2-FAST" in r.stdout


def test_check_counts_due_and_deferred():
    from traceagent.gates.l2 import _current_milestone
    from traceagent.spec.store import Store, load_contract

    # live-derived due count, mirroring gates.l2 milestone scoping
    store = Store.load(REPO)
    contract = load_contract(REPO)
    deferred = contract.get("meta", {}).get("target_milestone", {})
    milestone = _current_milestone(REPO)
    due = len({a for a in store.nodes if deferred.get(a, milestone) <= milestone})

    r = subprocess.run([sys.executable, "-m", "traceagent.cli.main", "check", str(REPO)],
                       capture_output=True, text=True)
    stdout = r.stdout
    assert f'"due": {due}' in stdout
    assert '"deferred"' in stdout
    for alias in deferred:  # every live-deferred clause must be listed
        assert alias in stdout, f"deferred clause {alias} missing from check output"
