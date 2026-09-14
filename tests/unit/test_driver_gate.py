"""Driver gate (batch-driver contract): EARS + fast read-only L0-L3 subset.

Pins the driver contract: exit-code verdicts, read-only workspace (no ledger,
no verdict cache, no bytecode, no hypothesis DB inside {folder}), bounded
payload for the ~2000-char sink, and the shell entrypoint's behavior.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from traceagent.gates.driver_gate import BUDGET_CHARS, main, run_driver_gate
from traceagent.gates.l1 import run_l1
from traceagent.spec.canon import canonical_hash

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "gates" / "driver-gate.sh"

EARS_STATEMENT = "WHEN a work order is expired, THE SYSTEM SHALL reject it."


def _node(alias: str, inv_id: str, statement: str, title: str = "expired -> err") -> dict:
    inv = {
        "id": inv_id,
        "statement": statement,
        "property": "forall t: expired(t) => validate(t) == err('Unauthorized')",
        "check": {"kind": "property"},
    }
    content = {"domain": "g", "title": title, "invariants": [inv]}
    return {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": alias, "domain": "g", "title": title,
        "status": "VALIDATED", "version": 1,
        "content_hash": canonical_hash(content),
        "invariants": [inv], "external_links": [],
    }


def _seed_repo(tmp_path: Path, test_body: str | None = None) -> Path:
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    (spec / "gate-inv-01.json").write_text(
        json.dumps(_node("GATE-INV-01", "GATE-INV-01", EARS_STATEMENT)))
    (tmp_path / "impl.py").write_text("def expired(t):\n    return t > 100\n")
    (tmp_path / "oracle_GATE-INV-01.py").write_text("def expired(t):\n    return t > 100\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    body = test_body or (
        "from impl import expired\n\n\n"
        "def test_bound():\n    assert expired(150) is True\n"
    )
    (tests / "test_bound.py").write_text('# @trace("GATE-INV-01")\n' + body)
    return tmp_path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# @trace("DRIVER-GATE-GREEN")
def test_driver_gate_green_on_seeded_workspace(tmp_path):
    verdict = run_driver_gate(_seed_repo(tmp_path))
    assert verdict.ok, verdict.failures
    assert verdict.stages == {"ears": True, "l0": True, "l1": True, "l2_fast": True}
    assert verdict.l1 == {"executed": 1, "ok": True}
    doc = json.loads(verdict.payload)
    assert doc["ok"] is True and doc["ears_checked"] == 1
    assert doc["coverage"]["deterministic"] == "1/1"


def test_driver_gate_workspace_is_byte_identical(tmp_path):
    """READ-ONLY: green run leaves zero writes — no ledger, cache, bytecode,
    pytest cache, or hypothesis DB inside the governed folder."""
    root = _seed_repo(tmp_path, test_body=(
        "from hypothesis import given, strategies as st\n"
        "from impl import expired\n\n\n"
        "@given(st.integers(min_value=0, max_value=200))\n"
        "def test_bound(t):\n    assert expired(t) == (t > 100)\n"
    ))
    before = _snapshot(root)
    verdict = run_driver_gate(root)
    assert verdict.ok, verdict.failures
    assert _snapshot(root) == before, "the gate must not write into {folder}"
    after = _snapshot(root)
    for stateful in (".traceagent", ".hypothesis", ".pytest_cache", "__pycache__"):
        assert not any(name.startswith(stateful) for name in after), stateful


def test_driver_gate_non_ears_statement_is_typed_deny(tmp_path):
    root = _seed_repo(tmp_path)
    spec = root / ".zft" / "specs" / "g" / "gate-inv-01.json"
    spec.write_text(json.dumps(
        _node("GATE-INV-01", "GATE-INV-01", "The system should reject expired orders.")))
    verdict = run_driver_gate(root)
    assert verdict.ok is False
    assert verdict.stages["ears"] is False
    assert any("GATE-INV-01" in f and "not an EARS statement" in f
               for f in verdict.failures)


def test_driver_gate_unseeded_folder_fails_closed(tmp_path):
    verdict = run_driver_gate(tmp_path)
    assert verdict.ok is False
    # render_finding carries the message, not the rule code
    assert any("no clause store found" in f for f in verdict.failures)


def test_driver_gate_red_suite_names_clause_and_fits_budget(tmp_path):
    root = _seed_repo(tmp_path, test_body="def test_bound():\n    assert False\n")
    verdict = run_driver_gate(root)
    assert verdict.ok is False
    assert any("GATE-INV-01: bound suite failed" in f for f in verdict.failures)
    assert "GATE-INV-01" in verdict.payload
    assert len(verdict.payload) <= BUDGET_CHARS <= 2000, "driver sink is ~2000 chars"


def test_driver_gate_payload_fits_budget_under_many_failures(tmp_path):
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    for i in range(10):
        alias = f"GATE-INV-{i:02d}"
        (spec / f"{alias.lower()}.json").write_text(json.dumps(
            _node(alias, alias, EARS_STATEMENT, title=f"clause {i}")))
    verdict = run_driver_gate(tmp_path)  # property clauses, none bound
    assert verdict.ok is False
    assert len(verdict.failures) > 10
    assert len(verdict.payload) <= BUDGET_CHARS
    json.loads(verdict.payload)  # stays valid JSON after shrinking


def test_driver_gate_corrupt_store_degrades_to_typed_red(tmp_path):
    root = _seed_repo(tmp_path)
    (root / ".zft" / "specs" / "g" / "gate-inv-01.json").write_text("{broken")
    verdict = run_driver_gate(root)
    assert verdict.ok is False
    assert any("STORE_NODE_JSON" in f or "evidence collection failed" in f
               for f in verdict.failures)


def test_driver_gate_module_main_exit_codes(tmp_path, capsys):
    green = _seed_repo(tmp_path)
    assert main([str(green)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["stage"] == "DRIVER-GATE" and doc["ok"] is True

    (green / "tests" / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\ndef test_bound():\n    assert False\n')
    assert main([str(green)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


_DRIVER_IDENTITY_ENVS = ("TRACEAGENT_PRODUCER_MODEL", "TRACEAGENT_GATE_MODEL")


def test_driver_gate_identity_env_config_flows(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACEAGENT_PRODUCER_MODEL", "env-prod")
    monkeypatch.setenv("TRACEAGENT_GATE_MODEL", "env-gate")
    verdict = run_driver_gate(_seed_repo(tmp_path))
    assert verdict.ok, verdict.failures
    assert verdict.models == {"producer": "env-prod", "gate": "env-gate",
                              "model_dependent": False}


def test_driver_gate_identity_unsupplied_is_null_not_dev_name(tmp_path, monkeypatch):
    for k in _DRIVER_IDENTITY_ENVS:
        monkeypatch.delenv(k, raising=False)
    verdict = run_driver_gate(_seed_repo(tmp_path))
    assert verdict.ok, verdict.failures
    assert verdict.models == {"producer": None, "gate": None,
                              "model_dependent": True}, (
        "fail-closed: no proven model difference -> the claim stays "
        "model-dependent, and no default name may stand in")
    assert "producer-dev" not in verdict.payload


def test_driver_gate_cli_identity_flag_beats_env(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TRACEAGENT_PRODUCER_MODEL", "env-prod")
    monkeypatch.setenv("TRACEAGENT_GATE_MODEL", "env-gate")
    from traceagent.cli.main import main as cli_main

    assert cli_main(["driver-gate", str(_seed_repo(tmp_path)),
                     "--producer-model", "flag-prod",
                     "--gate-model", "flag-gate"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["models"] == {"producer": "flag-prod", "gate": "flag-gate",
                             "model_dependent": False}


def test_l1_write_cache_false_leaves_no_trace(tmp_path):
    root = _seed_repo(tmp_path)
    assert run_l1(root, write_cache=False).ok is True
    assert not (root / ".traceagent").exists(), "read-only runs never persist verdicts"
    assert run_l1(root, write_cache=False).executed == 1, "no cache write => no cache hit"
    assert run_l1(root).executed == 1, "default run executes (nothing was persisted)"
    assert run_l1(root).executed == 0, "default behavior still caches its own greens"


def _run_script(*args: str, folder: Path | str | None = None,
                env_extra: dict | None = None):
    env = os.environ | {"TRACEAGENT_PYTHON": sys.executable}
    if env_extra:
        env |= env_extra
    argv = ["bash", str(SCRIPT)]
    if folder is not None:
        argv.append(str(folder))
    return subprocess.run([*argv, *args], capture_output=True, text=True,
                          env=env, timeout=115)


@pytest.mark.skipif(not SCRIPT.exists() or sys.platform == "win32",
                    reason="driver-gate.sh is a bash artifact")
class TestDriverGateScript:
    def test_green_exits_zero_with_bounded_output(self, tmp_path):
        root = _seed_repo(tmp_path)
        before = _snapshot(root)
        r = _run_script(folder=root)
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.startswith('{"stage":"DRIVER-GATE"')
        assert '"ok":true' in r.stdout
        assert len(r.stdout) + len(r.stderr) <= 2000
        assert _snapshot(root) == before, "script must not write into {folder}"

    def test_red_exits_nonzero(self, tmp_path):
        root = _seed_repo(tmp_path, test_body="def test_bound():\n    assert False\n")
        r = _run_script(folder=root)
        assert r.returncode == 1
        assert "GATE-INV-01" in r.stdout

    def test_usage_and_missing_folder(self, tmp_path):
        assert _run_script().returncode == 2  # no folder argument
        assert _run_script(folder=tmp_path / "nope").returncode == 1

    def test_budget_overrun_rejects_instead_of_hanging(self, tmp_path):
        slow_body = "import time\n\n\ndef test_bound():\n    time.sleep(30)\n"
        slow = _seed_repo(tmp_path, test_body=slow_body)
        r = _run_script(folder=slow, env_extra={"DRIVER_GATE_BUDGET_S": "2"})
        assert r.returncode == 1
        assert "budget" in r.stdout
