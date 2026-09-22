"""C-33/C-34: negotiate CLI flow — CFP→counter→validate→implement→gate-verdict.

Integration over the real store fixture + gate stubs (no a2a transport here).
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from zft.debug.ledger import RunLedger
from zft.negotiate.sm import IllegalTransition, NegotiationSM
from zft.spec.store import load_contract

REPO = Path(os.environ.get("ZFT_REPO")
            or Path(__file__).resolve().parents[2])


# @trace("CON-COUNTER-RECORDED")
def test_negotiate_flow_runs_on_own_contract(tmp_path):
    """Full CFP→VALIDATED run against the real contract via the real CLI.

    Runs over a copy of the live .zft tree (same bytes, hermetic root) so the
    suite never writes run artifacts into the repo's .zft/runs — that
    directory is shared evidence (nightly batch, other sessions), not the
    test's to create or clean.
    """
    import shutil

    root = tmp_path / "store"
    root.mkdir()
    shutil.copytree(
        REPO / ".zft", root / ".zft",
        ignore=shutil.ignore_patterns("runs", "sandbox*", "cache"),
    )
    r = subprocess.run([sys.executable, "-m", "zft.cli.main", "negotiate",
                        str(root)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    import re

    run_id = re.search(r"run ([0-9a-f]+)", r.stdout).group(1)
    runs_root = root / ".zft" / "runs"
    record = RunLedger.load(runs_root, run_id)
    events = [e["event"] for e in record.events]
    assert events == ["cfp", "counter", "accept_counter", "validate", "validated"]


def test_clauses_due_scopes_deferred():
    """Deferred clauses are excluded from due coverage (§3bis), included after."""
    from zft.gates.l2 import _current_milestone
    from zft.spec.store import Store

    store = Store.load(REPO)
    contract = load_contract(REPO)
    deferred = contract.get("meta", {}).get("target_milestone", {})
    assert deferred.get("ATT-EXTERNAL-IMPORT") == "v0.1"

    milestone = _current_milestone(REPO)
    due = {a for a, n in store.nodes.items() if deferred.get(a, milestone) <= milestone}
    assert "ATT-EXTERNAL-IMPORT" not in due
    assert "TR-IMPACT-QUERY" in due  # deferral lifted: implemented and due
    # due = every live clause minus the deferred-to-later-milestone ones
    assert len(due) == len(store.nodes) - len(deferred)


def test_retry_budget_blocks_forever_loop():
    """C-34: bounded retries — after budget, gate rejection escalates, not loops."""
    sm = NegotiationSM.start(retry_budget=1)
    sm.validate()
    sm.implement()
    sm.reject_gate(["GATE-INV-01"], fault="implementation")
    sm.reopen()
    sm.validate()
    sm.implement()
    sm.reject_gate(["GATE-INV-01"], fault="implementation")
    with pytest.raises(IllegalTransition, match="retry budget"):
        sm.reopen()
