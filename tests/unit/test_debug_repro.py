"""Kill pins for zft.debug.repro (debug cut, 2026-09-16 sitting).

repro() re-executes only the failed units of a ledger run. The pins drive it
over a crafted record with run_l0/run_l1 monkeypatched at their source
modules (repro imports them at call time), so the re-execution set, the
failure propagation, and the L1 repro-ledger manifest are all pinned without
touching the real gates.
"""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from zft.debug.ledger import RunLedger
from zft.debug.repro import repro


@pytest.fixture()
def runs_root(tmp_path):
    return tmp_path / "runs"


def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@l", "-c", "user.name=t", "commit",
                    "--allow-empty", "-qm", "base"], cwd=tmp_path, check=True)
    return tmp_path


def _write_run(runs_root, events):
    led = RunLedger.start(runs_root, manifest={})
    for e in events:
        led.append(e)
    led.close()
    return led.run_id


def test_repro_reexecutes_exactly_the_failed_units(tmp_path, runs_root, monkeypatch):
    root = _git_repo(tmp_path)
    run_id = _write_run(runs_root, [
        {"event": "l0", "ok": False},
        {"event": "l0", "ok": False},
        {"event": "l0", "ok": True},
        {"event": "l1_clause", "alias": "GOOD", "ok": True},
        {"event": "l1_clause", "alias": "BAD", "ok": False},
        {"event": "other", "ok": False},
    ])
    l0_calls, l1_calls = [], []

    def fake_l0(r):
        l0_calls.append(r)
        return SimpleNamespace(ok=True)

    def fake_l1(r, ledger=None):
        l1_calls.append((r, ledger))
        return SimpleNamespace(failures=[])

    monkeypatch.setattr("zft.gates.l0.run_l0", fake_l0)
    monkeypatch.setattr("zft.gates.l1.run_l1", fake_l1)

    res = repro(root, runs_root, run_id)

    assert res.run_id == run_id
    assert res.re_executed == ["l0", "l0", "l1:BAD"]
    assert res.recovered is True
    assert res.still_failing == []
    assert l0_calls == [root, root]
    assert len(l1_calls) == 1
    l1_root, l1_ledger = l1_calls[0]
    assert l1_root == root
    assert isinstance(l1_ledger, RunLedger)
    assert l1_ledger.dir.parent == Path(runs_root)
    new_dirs = [d for d in Path(runs_root).iterdir() if d.name != run_id]
    assert len(new_dirs) == 1
    m = json.loads((new_dirs[0] / "manifest.json").read_text())
    assert m["stage"] == "L1"
    assert m["repro_of"] == run_id
    assert m["git_commit"], "repro passes repo=root so the L1 ledger records git info"


def test_repro_l0_failure_sets_recovered_false(tmp_path, runs_root, monkeypatch):
    run_id = _write_run(runs_root, [{"event": "l0", "ok": False}])
    monkeypatch.setattr("zft.gates.l0.run_l0",
                        lambda r: SimpleNamespace(ok=False))
    res = repro(tmp_path, runs_root, run_id)
    assert res.re_executed == ["l0"]
    assert res.recovered is False


def test_repro_l1_failures_propagate_to_still_failing(tmp_path, runs_root, monkeypatch):
    run_id = _write_run(runs_root, [{"event": "l1_clause", "alias": "BAD", "ok": False}])
    monkeypatch.setattr("zft.gates.l1.run_l1",
                        lambda r, ledger=None: SimpleNamespace(
                            failures=[{"clause": "C-9"}]))
    res = repro(tmp_path, runs_root, run_id)
    assert res.recovered is False
    assert res.still_failing == [{"clause": "C-9"}]
