"""E2E: the kill-9 negotiation resumption proof.

A negotiate process is SIGKILLed mid-protocol (deterministically, via the
ZFT_NEGOTIATE_KILL_AFTER demo seam — the kill itself is a real
SIGKILL, exit -9, no unwinding). The next plain invocation must find the
unfinished run, replay its durable prefix through the state machine, and
finish the SAME run — the ledger ends up holding one gapless protocol.

Runs against a copy of the repo's .zft tree, never the repo itself.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from zft.debug.ledger import RunLedger

REPO = Path(os.environ.get("ZFT_REPO")
            or Path(__file__).resolve().parents[2])
PY = sys.executable

FULL_PROTOCOL = ["cfp", "counter", "accept_counter", "validate", "validated"]


def _store_copy(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    shutil.copytree(
        REPO / ".zft", root / ".zft",
        ignore=shutil.ignore_patterns("runs", "sandbox*", "cache"),
    )
    return root


def _negotiate(root: Path, kill_after: str | None = None):
    env = os.environ | ({"ZFT_NEGOTIATE_KILL_AFTER": kill_after}
                        if kill_after else {})
    return subprocess.run(
        [PY, "-m", "zft.cli.main", "negotiate", str(root)],
        capture_output=True, text=True, env=env)


def _sole_negotiate_run(root: Path) -> tuple[str, list[dict]]:
    runs = sorted((root / ".zft" / "runs").iterdir())
    assert len(runs) == 1, f"expected one run, found {[r.name for r in runs]}"
    record = RunLedger.load(runs[0].parent, runs[0].name)
    return runs[0].name, record.events


# @trace("CON-CRASH-RESUME")
def test_kill9_mid_protocol_resumes_same_run(tmp_path):
    root = _store_copy(tmp_path)

    # phase 1: killed the moment the counter transition is durable
    killed = _negotiate(root, kill_after="counter")
    assert killed.returncode == -9, \
        f"the seam must die by SIGKILL, got rc={killed.returncode}"
    run_id, events = _sole_negotiate_run(root)
    assert [e["event"] for e in events] == ["cfp", "counter"], \
        "durable prefix only — nothing after the kill may exist"
    assert events[-1]["terms"] == "producer counter-terms (default none)"

    # phase 2: plain invocation resumes the SAME run and finishes it
    resumed = _negotiate(root)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert f"resuming negotiation run {run_id} from COUNTERED" in resumed.stdout
    assert "negotiation complete: VALIDATED" in resumed.stdout
    same_id, events = _sole_negotiate_run(root)
    assert same_id == run_id, "resumption continues the killed run, not a new one"
    assert [e["event"] for e in events] == \
        ["cfp", "counter", "resumed", "accept_counter", "validate", "validated"], \
        "one gapless protocol: durable prefix + ledgered resume + the finish"
    resumed_event = next(e for e in events if e["event"] == "resumed")
    assert resumed_event["replayed"] == 1 and resumed_event["state"] == "COUNTERED"


def test_kill9_twice_still_converges(tmp_path):
    root = _store_copy(tmp_path)

    killed = _negotiate(root, kill_after="counter")
    assert killed.returncode == -9
    killed_again = _negotiate(root, kill_after="accept_counter")
    assert killed_again.returncode == -9, "resumed runs stay killable"
    run_id, events = _sole_negotiate_run(root)
    assert [e["event"] for e in events] == \
        ["cfp", "counter", "resumed", "accept_counter"]

    final = _negotiate(root)
    assert final.returncode == 0, final.stdout + final.stderr
    assert "from REVISED" in final.stdout, "second resume replays past the first"
    same_id, events = _sole_negotiate_run(root)
    assert same_id == run_id
    assert [e["event"] for e in events] == \
        ["cfp", "counter", "resumed", "accept_counter", "resumed",
         "validate", "validated"]
    # the counter terms survived two kills and two replays
    assert events[1]["terms"] == "producer counter-terms (default none)"


def test_fresh_run_after_completed_one_is_not_a_resume(tmp_path):
    """Terminal state must not be re-resumed: a finished run stays history."""
    root = _store_copy(tmp_path)
    first = _negotiate(root)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "resuming" not in first.stdout
    second = _negotiate(root)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "resuming" not in second.stdout, "terminal runs are never resumed"
    runs = sorted((root / ".zft" / "runs").iterdir())
    assert len(runs) == 2, "each completed invocation is its own run"
    for run_dir in runs:
        record = RunLedger.load(runs[0].parent, run_dir.name)
        assert [e["event"] for e in record.events] == FULL_PROTOCOL
