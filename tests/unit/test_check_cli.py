"""CI-gate exit-code contract (NEXT_STEPS #2): check speaks 0/1/2 with typed
JSON on stdout — 0 green, 1 typed clause-IDed rejection, 2 usage."""
import json
import subprocess
import sys
from pathlib import Path

from zft.cli.main import main

REPO = Path(__file__).resolve().parents[2]


def _check(root):
    return subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "check", str(root)],
        capture_output=True, text=True)


def test_check_exit_0_typed_json_green():
    r = _check(REPO)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)  # stdout must parse as typed JSON
    assert out["stage"] == "L2-FAST"
    assert out["ok"] is True
    assert out["failures"] == []


def test_check_exit_1_red_clause_typed_rejection(tmp_path):
    seed = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "create",
         "--alias", "X-RED", "--domain", "x", "--title", "Red clause",
         "--statement", "WHEN red, THE SYSTEM SHALL fail visibly",
         "--property", "forall x: ok(x)", "--kind", "test",
         str(tmp_path)], capture_output=True, text=True)
    assert seed.returncode == 0, seed.stdout + seed.stderr
    node_path = tmp_path / ".zft" / "specs" / "x" / "x-red.json"
    node = json.loads(node_path.read_text())
    node["content_hash"] = "0" * 64  # tamper — L0 must name the clause
    node_path.write_text(json.dumps(node))
    r = _check(tmp_path)
    assert r.returncode == 1
    out = json.loads(r.stdout)  # typed rejection, not a traceback
    assert out["code"] == "L0_STORE_INTEGRITY"
    assert "x-red" in json.dumps(out).lower(), "rejection must name the clause node"
    assert "Traceback" not in r.stderr


def test_check_exit_2_usage_paths(capsys):
    assert main(["check", "--kind"]) == 2  # dangling flag value
    assert main([]) == 2  # no command
    assert main(["nope"]) == 2  # unknown command
    out = capsys.readouterr().out
    assert "missing value for --kind" in out
    assert "usage:" in out
    assert "unknown command: nope" in out


def test_val_refuses_flag_shaped_values():
    from zft.cli.main import _val

    argv = ["attest", "--key-out", "--alias", "K"]
    assert _val(argv, "--key-out") is None, "--key-out must not swallow --alias"
    assert _val(argv, "--alias") == "K"
    assert _val(["attest", "--key-expires"], "--key-expires") is None


_IDENTITY_ENVS = ("ZFT_PRODUCER_MODEL", "ZFT_GATE_MODEL")


def test_check_identity_caller_supplied_flags(capsys, monkeypatch):
    for k in _IDENTITY_ENVS:
        monkeypatch.delenv(k, raising=False)
    assert main(["check", str(REPO), "--producer-model", "prod-x",
                 "--gate-model", "gate-y"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["gate_log"]["models"] == {"producer": "prod-x", "gate": "gate-y"}
    assert out["gate_log"]["model_dependent"] is False


def test_check_identity_unsupplied_is_null_not_dev_name(capsys, monkeypatch):
    for k in _IDENTITY_ENVS:
        monkeypatch.delenv(k, raising=False)
    assert main(["check", str(REPO)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["gate_log"]["models"] == {"producer": None, "gate": None}
    # fail-closed: no proven model difference -> the claim stays model-dependent
    assert out["gate_log"]["model_dependent"] is True
    assert "producer-dev" not in json.dumps(out)


def test_check_identity_env_config_fallback(capsys, monkeypatch):
    monkeypatch.setenv("ZFT_PRODUCER_MODEL", "env-prod")
    monkeypatch.setenv("ZFT_GATE_MODEL", "env-gate")
    assert main(["check", str(REPO)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["gate_log"]["models"] == {"producer": "env-prod", "gate": "env-gate"}


def test_check_identity_flag_beats_env(capsys, monkeypatch):
    monkeypatch.setenv("ZFT_PRODUCER_MODEL", "env-prod")
    monkeypatch.delenv("ZFT_GATE_MODEL", raising=False)
    assert main(["check", str(REPO), "--producer-model", "flag-prod",
                 "--gate-model", "env-prod"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["gate_log"]["models"] == {"producer": "flag-prod", "gate": "env-prod"}
