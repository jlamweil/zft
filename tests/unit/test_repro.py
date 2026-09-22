"""C-26: repro — re-execute only failed units from a ledger record.

2026-09-15 night kill shard: the module had no test file at all; these pins
hold the replay matcher (event/alias/ok keys, byte-exact), the recovered /
still_failing reporting, and the spawned L1 run's manifest shape.
"""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from zft.debug.ledger import RunLedger
from zft.debug.repro import repro


def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@l", "-c", "user.name=t", "commit",
         "--allow-empty", "-qm", "base"], cwd=tmp_path, check=True)
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _record(runs_root, events):
    led = RunLedger.start(runs_root, manifest={})
    for e in events:
        led.append(e)
    led.close()
    return led.run_id


def test_repro_replays_failures_and_recovers(tmp_path, monkeypatch):
    runs_root = tmp_path / "runs"
    root = tmp_path / "store"
    root.mkdir()
    commit = _git_repo(root)
    run_id = _record(runs_root, [
        {"event": "l0", "ok": False},
        {"event": "l0", "ok": True},
        {"event": "l1_clause", "alias": "X", "ok": False},
        {"event": "l1_clause", "alias": "Y", "ok": True},
    ])

    calls = {}

    def fake_l0(r):
        calls["l0"] = r
        return SimpleNamespace(ok=True)

    def fake_l1(r, ledger=None):
        calls["l1_root"] = r
        calls["l1_ledger"] = ledger
        return SimpleNamespace(ok=True, failures=[])

    monkeypatch.setattr("zft.gates.l0.run_l0", fake_l0)
    monkeypatch.setattr("zft.gates.l1.run_l1", fake_l1)

    result = repro(root, runs_root, run_id)

    # only the failed l0 replays; the ok:True l0 event is not re-run
    assert result.re_executed == ["l0", "l1:X"]
    assert result.recovered is True
    assert result.still_failing == []
    assert result.run_id == run_id
    assert calls["l0"] == root
    assert calls["l1_root"] == root
    # the spawned L1 replay run is a real ledger run with the repro lineage
    spawned = calls["l1_ledger"]
    assert spawned is not None
    manifest = json.loads((Path(spawned.dir) / "manifest.json").read_text())
    assert manifest == {"git_commit": commit, "dirty": False, "stage": "L1",
                        "repro_of": run_id}


def test_repro_l0_failure_not_masked_by_passing_l1_replay(tmp_path, monkeypatch):
    runs_root = tmp_path / "runs"
    root = tmp_path / "store"
    root.mkdir()
    run_id = _record(runs_root, [
        {"event": "l0", "ok": False},
        {"event": "l1_clause", "alias": "Y", "ok": False},
    ])

    monkeypatch.setattr("zft.gates.l0.run_l0",
                        lambda r: SimpleNamespace(ok=False))
    monkeypatch.setattr("zft.gates.l1.run_l1",
                        lambda r, ledger=None: SimpleNamespace(ok=True, failures=[]))

    result = repro(root, runs_root, run_id)

    # the L0 replay's failure verdict is False (never None/True), and a green
    # L1 replay neither flips it nor fabricates still_failing entries
    assert result.re_executed == ["l0", "l1:Y"]
    assert result.recovered is False
    assert result.still_failing == []


def test_repro_reports_still_failing(tmp_path, monkeypatch):
    runs_root = tmp_path / "runs"
    root = tmp_path / "store"
    root.mkdir()
    run_id = _record(runs_root, [
        {"event": "l0", "ok": False},
        {"event": "l1_clause", "alias": "Z", "ok": False},
    ])

    monkeypatch.setattr("zft.gates.l0.run_l0",
                        lambda r: SimpleNamespace(ok=False))
    monkeypatch.setattr("zft.gates.l1.run_l1",
                        lambda r, ledger=None: SimpleNamespace(
                            ok=False, failures=["clause Z still red"]))

    result = repro(root, runs_root, run_id)

    assert result.re_executed == ["l0", "l1:Z"]
    assert result.recovered is False
    assert result.still_failing == ["clause Z still red"]


def test_repro_with_no_failures_reexecutes_nothing(tmp_path, monkeypatch):
    runs_root = tmp_path / "runs"
    root = tmp_path / "store"
    root.mkdir()
    run_id = _record(runs_root, [
        {"event": "l0", "ok": True},
        {"event": "l1_clause", "alias": "Y", "ok": True},
    ])

    def bomb(*a, **k):
        raise AssertionError("no failed unit must be re-executed")

    monkeypatch.setattr("zft.gates.l0.run_l0", bomb)
    monkeypatch.setattr("zft.gates.l1.run_l1", bomb)

    result = repro(root, runs_root, run_id)
    assert result.re_executed == []
    assert result.recovered is True
