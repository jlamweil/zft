"""Send-gate seam (batch-driver contract): the pre-send hook a batcher calls.

Pins what the RUNBOOK's `--gate-cmd`/`--gate-hook` paragraph promises at the
send path: off is a no-op (the rollback flag), shadow logs would-blocks and
never blocks, enforce blocks only a gate red — a gate that cannot answer is
a transport error and fails OPEN, loudly logged. Log lines are single-line
JSON with the gate output bounded for the ~2000-char driver sink.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from traceagent.spec.canon import canonical_hash

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "gates" / "send-gate.sh"

EARS_STATEMENT = "WHEN a work order is expired, THE SYSTEM SHALL reject it."


def _node(alias: str, inv_id: str, statement: str) -> dict:
    inv = {
        "id": inv_id,
        "statement": statement,
        "property": "forall t: expired(t) => validate(t) == err('Unauthorized')",
        "check": {"kind": "property"},
    }
    content = {"domain": "g", "title": "expired -> err", "invariants": [inv]}
    return {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": alias, "domain": "g", "title": "expired -> err",
        "status": "VALIDATED", "version": 1,
        "content_hash": canonical_hash(content),
        "invariants": [inv], "external_links": [],
    }


def _seed_repo(tmp_path: Path) -> Path:
    """Minimal healthy workspace: one clause, executed property evidence."""
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    (spec / "gate-inv-01.json").write_text(
        json.dumps(_node("GATE-INV-01", "GATE-INV-01", EARS_STATEMENT)))
    (tmp_path / "impl.py").write_text("def expired(t):\n    return t > 100\n")
    (tmp_path / "oracle_GATE-INV-01.py").write_text("def expired(t):\n    return t > 100\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\nfrom impl import expired\n\n\n'
        "def test_bound():\n    assert expired(150) is True\n")
    return tmp_path


def _fake_gate(tmp_path: Path, body: str) -> str:
    """A stand-in gate command template; {folder} must stay substituted."""
    gate = tmp_path / "fake-gate.sh"
    gate.write_text(f"#!/usr/bin/env bash\n{body}\n")
    gate.chmod(0o755)
    return f"{gate} {{folder}}"


def _run(folder: Path, *, cmd: str | None, hook: str | None, log: Path,
         timeout: str | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "TRACEAGENT_SEND_GATE_LOG": str(log),
           # the sandboxed PATH hides .venv probes; pin the interpreter that
           # has traceagent importable (this venv's, not the repo's)
           "TRACEAGENT_PYTHON": sys.executable}
    if cmd is not None:
        env["TRACEAGENT_GATE_CMD"] = cmd
    if hook is not None:
        env["TRACEAGENT_GATE_HOOK"] = hook
    if timeout is not None:
        env["TRACEAGENT_SEND_GATE_TIMEOUT"] = timeout
    return subprocess.run(
        ["bash", str(SCRIPT), str(folder)], capture_output=True, text=True,
        env=env, cwd=cwd or REPO, timeout=60)


def _lines(log: Path) -> list[dict]:
    return [json.loads(ln) for ln in log.read_text().splitlines()]


def test_missing_folder_argument_is_usage_error():
    proc = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin"})
    assert proc.returncode == 2
    assert "usage" in proc.stdout


# ── off: the rollback flag ────────────────────────────────────────────────────

def test_off_mode_is_a_full_noop(tmp_path):
    """One flag off: no gate run, no log write, exit 0 — nothing else changes."""
    canary = tmp_path / "canary"
    folder = tmp_path / "ws"
    folder.mkdir()
    log = tmp_path / "log.jsonl"
    proc = _run(folder, cmd=f"touch {canary}; exit 1", hook="off", log=log)
    assert proc.returncode == 0
    assert not canary.exists(), "gate must not run when the hook is off"
    assert not log.exists(), "no verdict log writes when the hook is off"


def test_unset_cmd_is_a_noop(tmp_path):
    folder = tmp_path / "ws"
    folder.mkdir()
    log = tmp_path / "log.jsonl"
    proc = _run(folder, cmd=None, hook="shadow", log=log)
    assert proc.returncode == 0
    assert not log.exists()


# ── shadow: log would-block, never block ─────────────────────────────────────

def test_shadow_green_gate_allows_and_logs(tmp_path):
    folder = _seed_repo(tmp_path)
    log = tmp_path / "log.jsonl"
    proc = _run(folder, cmd=_fake_gate(tmp_path, "exit 0"), hook="shadow", log=log)
    assert proc.returncode == 0, "shadow never blocks"
    (rec,) = _lines(log)
    assert rec["decision"] == "allow"
    assert rec["mode"] == "shadow" and rec["gate_exit"] == 0
    assert rec["folder"] == str(folder)
    assert rec["reason"] == ""


def test_shadow_red_gate_logs_would_block_and_proceeds(tmp_path):
    folder = tmp_path / "ws"
    folder.mkdir()
    log = tmp_path / "log.jsonl"
    proc = _run(folder, cmd=_fake_gate(tmp_path, 'echo "L0 torn hash"; exit 1'),
                hook="shadow", log=log)
    assert proc.returncode == 0, "shadow records the would-block and lets the send through"
    (rec,) = _lines(log)
    assert rec["decision"] == "would-block"
    assert rec["gate_exit"] == 1
    assert "torn hash" in rec["output"]


def test_shadow_transport_failures_fail_open_and_are_logged(tmp_path):
    folder = tmp_path / "ws"
    folder.mkdir()
    log = tmp_path / "log.jsonl"
    # template without {folder}: the seam refuses to guess what would be judged
    proc = _run(folder, cmd="exit 0", hook="shadow", log=log)
    assert proc.returncode == 0
    # gate binary missing: transport error
    log2 = tmp_path / "log2.jsonl"
    proc2 = _run(folder, cmd="definitely-not-a-gate-binary {folder}", hook="shadow", log=log2)
    assert proc2.returncode == 0, "transport fails OPEN on the driver side"
    # budget kill: the documented 120s window, shrunk for the test
    log3 = tmp_path / "log3.jsonl"
    t0 = time.monotonic()
    proc3 = _run(folder, cmd=_fake_gate(tmp_path, "sleep 30"), hook="shadow", log=log3, timeout="1")
    elapsed = time.monotonic() - t0
    assert proc3.returncode == 0 and elapsed < 15
    a, = _lines(log)
    b, = _lines(log2)
    c, = _lines(log3)
    assert a["decision"] == "gate-unavailable" and "placeholder" in a["reason"]
    assert b["decision"] == "gate-unavailable" and "not found" in b["reason"]
    assert c["decision"] == "gate-unavailable" and "budget kill" in c["reason"]
    assert b["gate_exit"] is None and c["gate_exit"] is None


def test_shadow_log_line_is_single_json_with_bounded_output(tmp_path):
    folder = tmp_path / "ws"
    folder.mkdir()
    log = tmp_path / "log.jsonl"
    noisy = 'python3 -c "print(\'quote\\" \\\\ \'+\'x\'*5000)"; exit 1'
    proc = _run(folder, cmd=_fake_gate(tmp_path, noisy), hook="shadow", log=log)
    assert proc.returncode == 0
    (rec,) = _lines(log)  # one physical line, valid JSON
    assert len(rec["output"]) <= 1900
    assert '"' in rec["output"]  # escaping survived


# ── enforce: red blocks, transport still fails open ──────────────────────────

def test_enforce_red_blocks_and_green_passes(tmp_path):
    folder = tmp_path / "ws"
    folder.mkdir()
    log = tmp_path / "log.jsonl"
    red = _run(folder, cmd=_fake_gate(tmp_path, "exit 1"), hook="enforce", log=log)
    assert red.returncode == 1, "a gate red blocks the send"
    (rec,) = _lines(log)
    assert rec["decision"] == "would-block" and rec["mode"] == "enforce"
    green = _run(folder, cmd=_fake_gate(tmp_path, "exit 0"), hook="enforce", log=log)
    assert green.returncode == 0


def test_enforce_transport_failure_fails_open_loudly(tmp_path):
    """The documented driver contract: transport errors fail OPEN — but the
    verdict log says so, which is what triage reads before enforce goes live."""
    folder = tmp_path / "ws"
    folder.mkdir()
    log = tmp_path / "log.jsonl"
    proc = _run(folder, cmd="definitely-not-a-gate-binary {folder}", hook="enforce", log=log)
    assert proc.returncode == 0
    (rec,) = _lines(log)
    assert rec["decision"] == "gate-unavailable"


def test_unknown_mode_is_a_usage_error(tmp_path):
    folder = tmp_path / "ws"
    folder.mkdir()
    log = tmp_path / "log.jsonl"
    proc = _run(folder, cmd="exit 0", hook="yolo", log=log)
    assert proc.returncode == 2


# ── the real gate, end to end ────────────────────────────────────────────────

def test_real_driver_gate_green_send_is_logged_allow(tmp_path):
    folder = _seed_repo(tmp_path)
    log = tmp_path / "log.jsonl"
    proc = _run(folder, cmd=f"{REPO / 'gates' / 'driver-gate.sh'} {{folder}}",
                hook="shadow", log=log)
    assert proc.returncode == 0
    (rec,) = _lines(log)
    assert rec["decision"] == "allow", rec["output"]


def test_real_driver_gate_torn_store_send_would_block(tmp_path):
    folder = _seed_repo(tmp_path)
    node_path = folder / ".zft" / "specs" / "g" / "gate-inv-01.json"
    node = json.loads(node_path.read_text())
    node["content_hash"] = "0" * 64  # torn: content no longer hashes to it
    node_path.write_text(json.dumps(node))
    log = tmp_path / "log.jsonl"
    proc = _run(folder, cmd=f"{REPO / 'gates' / 'driver-gate.sh'} {{folder}}",
                hook="shadow", log=log)
    assert proc.returncode == 0, "torn store is a would-block, not a crash"
    (rec,) = _lines(log)
    assert rec["decision"] == "would-block"
    assert rec["gate_exit"] == 1
