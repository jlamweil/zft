"""C-03: run ledger — every gate/negotiation run is crash-safe and reproducible.

Seams (plan §1): RunLedger.start() creates the run dir + manifest; append()
writes JSONL with periodic fsync; RunLedger.load() reads back runs, ignoring a
trailing partial line written by a crash (plan C-03).
"""
import json
import subprocess
from pathlib import Path

import pytest

from traceagent.debug.ledger import RunLedger


@pytest.fixture()
def runs_root(tmp_path):
    return tmp_path / "runs"


def _git_commit(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@l", "-c", "user.name=t", "commit",
                    "--allow-empty", "-qm", "base"], cwd=tmp_path, check=True)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def test_start_creates_manifest_and_events(runs_root, tmp_path):
    commit = _git_commit(tmp_path)
    led = RunLedger.start(runs_root, manifest={"tool": "zft", "stage": "L0"},
                          repo=tmp_path)
    assert (Path(led.dir) / "manifest.json").exists()
    manifest = json.loads((Path(led.dir) / "manifest.json").read_text())
    assert manifest["tool"] == "zft"
    assert manifest["git_commit"] == commit
    assert manifest["dirty"] is False
    assert led.run_id in Path(led.dir).as_posix()


def test_append_and_load_round_trip(runs_root):
    led = RunLedger.start(runs_root, manifest={})
    led.append({"event": "clause_ok", "alias": "TR-FORWARD-COVERAGE"})
    led.append({"event": "verdict", "ok": True})
    record = RunLedger.load(runs_root, led.run_id)
    assert record.manifest["run_id"] == led.run_id
    assert record.events == [
        {"event": "clause_ok", "alias": "TR-FORWARD-COVERAGE"},
        {"event": "verdict", "ok": True},
    ]


def test_load_ignores_trailing_partial_line(runs_root):
    """Crash-consistency (plan C-03): a torn final write must not poison the run."""
    led = RunLedger.start(runs_root, manifest={})
    led.append({"event": "ok"})
    with open(Path(led.dir) / "events.jsonl", "ab") as fh:
        fh.write(b'{"event": "to')  # torn write, no newline
    record = RunLedger.load(runs_root, led.run_id)
    assert record.events == [{"event": "ok"}]


def test_load_manifest_lost_mid_run_degrades_not_crashes(runs_root):
    """Round-trip proof of the 2026-09-07 check-pipeline incident: an external
    state tidy deleted a live run's manifest between start() and the gate
    pipeline's reload, crashing `check` on a bare FileNotFoundError. Events
    are the evidence and must read back intact; the manifest degrades to {}."""
    led = RunLedger.start(runs_root, manifest={"stage": "check", "tier": "fast"})
    led.append({"event": "l0", "ok": True})
    led.append({"event": "l1", "ok": True, "executed": 1})
    (Path(led.dir) / "manifest.json").unlink()
    record = RunLedger.load(runs_root, led.run_id)
    assert record.manifest == {}
    assert record.events == [{"event": "l0", "ok": True},
                             {"event": "l1", "ok": True, "executed": 1}]
    # the .events property (the seam gates actually call) survives the same way
    assert led.events == record.events


def test_load_corrupt_manifest_degrades_not_crashes(runs_root):
    led = RunLedger.start(runs_root, manifest={"stage": "L0"})
    led.append({"event": "l0", "ok": False})
    (Path(led.dir) / "manifest.json").write_text('{"stage": "L0"')  # torn JSON
    record = RunLedger.load(runs_root, led.run_id)
    assert record.manifest == {}
    assert record.events == [{"event": "l0", "ok": False}]


def test_load_vanished_run_still_raises(runs_root):
    """The events file decides existence: repro maps FileNotFoundError to
    no_such_run, so a vanished/never-started run must keep raising."""
    with pytest.raises(FileNotFoundError):
        RunLedger.load(runs_root, "no-such-run")


def test_fsync_every_n_events(runs_root):
    syncs = []
    led = RunLedger.start(runs_root, manifest={}, sync_every=2,
                          syncer=lambda fh: syncs.append(1))
    for i in range(5):
        led.append({"i": i})
    assert len(syncs) == 2, "fsync fires every 2nd event (and not on empty close)"
