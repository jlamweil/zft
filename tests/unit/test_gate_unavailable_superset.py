"""C4 record-superset contract: EVERY gate_unavailable record, from every
writer (codex gates hook L0+stop, zft-gates gates hook L0, zft-gates
stop gate) carries the same keys — in particular `blocked` (true iff
enforce mode), so readers can rely on one schema. A gate that cannot run
is never green and, in enforce, blocks — the record must say so.

The JS writers (opencode-zft, pi-zft) are covered by their own suites;
this file is the Python half of the parity pin.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODEX_HOOK = REPO / "plugins" / "codex" / "hooks" / "gates_hook.py"
GATES_HOOK = REPO / "plugins" / "zft-gates" / "hooks" / "gates_hook.py"
STOP_GATE = REPO / "plugins" / "zft-gates" / "hooks" / "stop_gate.py"
CLAUSE_PATH = ".zft/specs/x/x-one.json"
NODE_ID = "018f3a2b-9e41-7100-8000-000000000001"


def _seed_store(root: Path) -> None:
    from zft.spec.canon import canonical_hash

    spec_dir = root / ".zft" / "specs" / "x"
    spec_dir.mkdir(parents=True)
    node = {"node_id": NODE_ID, "alias": "X-ONE", "domain": "x", "title": "t",
            "status": "PROPOSED", "version": 1,
            "invariants": [{"id": "X-INV-01",
                            "statement": "WHEN a THE SYSTEM SHALL b",
                            "property": "forall x: ok(x)",
                            "check": {"kind": "test"}}],
            "external_links": []}
    node["content_hash"] = canonical_hash(node)
    (spec_dir / "x-one.json").write_text(json.dumps(node))


def _edit_event(root: Path, session: str) -> dict:
    return {"session_id": session, "hook_event_name": "PostToolUse",
            "tool_name": "Write", "cwd": str(root),
            "tool_input": {"file_path": str(root / CLAUSE_PATH)}}


def _stop_event(root: Path, session: str) -> dict:
    return {"session_id": session, "hook_event_name": "Stop", "cwd": str(root)}


def _exit2_gate(root: Path) -> Path:
    """A gate binary that ran but exits 2 — the bad-exit (broken gate) path."""
    p = root / "badgate"
    p.write_text("#!/bin/sh\nexit 2\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def _fire(script: Path, event: dict, root: Path, *, mode: str | None = None,
          extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("ZFT_HOOK_MODE", None)
    env.pop("ZFT_STOP_MODE", None)
    env.pop("ZFT_BIN", None)
    if mode:
        env["ZFT_HOOK_MODE"] = mode
        env["ZFT_STOP_MODE"] = mode
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(script)],
                          input=json.dumps(event), capture_output=True,
                          text=True, env=env, cwd=root, timeout=120)


def _last_log_record(root: Path) -> dict:
    log = root / ".zft" / "gates-hook" / "log.jsonl"
    lines = log.read_text().strip().splitlines()
    assert lines, "hook wrote no log records"
    return json.loads(lines[-1])


def _assert_unavailable(record: dict, enforce: bool) -> None:
    assert record["decision"] == "gate_unavailable", record
    assert "blocked" in record, f"superset key `blocked` missing: {record}"
    assert record["blocked"] is enforce, record


# --- codex gates hook: L0 (no argv) ------------------------------------------

def test_codex_l0_no_argv_superset_observe(tmp_path):
    _seed_store(tmp_path)
    _fire(CODEX_HOOK, _edit_event(tmp_path, "s1"), tmp_path,
          extra_env={"ZFT_BIN": "/nonexistent/zft"})
    _assert_unavailable(_last_log_record(tmp_path), enforce=False)


def test_codex_l0_no_argv_superset_enforce(tmp_path):
    _seed_store(tmp_path)
    proc = _fire(CODEX_HOOK, _edit_event(tmp_path, "s1"), tmp_path,
                 mode="enforce", extra_env={"ZFT_BIN": "/nonexistent/zft"})
    assert proc.returncode == 2
    _assert_unavailable(_last_log_record(tmp_path), enforce=True)


def test_codex_l0_bad_exit_superset(tmp_path):
    _seed_store(tmp_path)
    _fire(CODEX_HOOK, _edit_event(tmp_path, "s1"), tmp_path,
          extra_env={"ZFT_BIN": str(_exit2_gate(tmp_path))})
    _assert_unavailable(_last_log_record(tmp_path), enforce=False)
    assert _last_log_record(tmp_path)["gate"]["status"] == "unavailable"


# --- codex gates hook: stop (no argv / bad exit) -----------------------------

# (codex stop-gate superset: private-only — the public codex hook has no
# stop path; the pin lives in zft-private's copy of this test.)

def test_zcode_l0_no_argv_superset_observe(tmp_path):
    _seed_store(tmp_path)
    _fire(GATES_HOOK, _edit_event(tmp_path, "s3"), tmp_path,
          extra_env={"ZFT_BIN": "/nonexistent/zft"})
    _assert_unavailable(_last_log_record(tmp_path), enforce=False)


def test_zcode_l0_no_argv_superset_enforce(tmp_path):
    _seed_store(tmp_path)
    proc = _fire(GATES_HOOK, _edit_event(tmp_path, "s3"), tmp_path,
                 mode="enforce", extra_env={"ZFT_BIN": "/nonexistent/zft"})
    assert proc.returncode == 2
    _assert_unavailable(_last_log_record(tmp_path), enforce=True)


def test_zcode_l0_bad_exit_superset(tmp_path):
    _seed_store(tmp_path)
    _fire(GATES_HOOK, _edit_event(tmp_path, "s3"), tmp_path,
          extra_env={"ZFT_BIN": str(_exit2_gate(tmp_path))})
    _assert_unavailable(_last_log_record(tmp_path), enforce=False)
    assert _last_log_record(tmp_path)["gate"]["status"] == "unavailable"


# --- zft-gates stop gate (no argv / bad exit) ---------------------------------

def test_zcode_stop_no_argv_superset_observe(tmp_path):
    _seed_store(tmp_path)
    _fire(STOP_GATE, _stop_event(tmp_path, "s4"), tmp_path,
          extra_env={"ZFT_BIN": "/nonexistent/zft"})
    _assert_unavailable(_last_log_record(tmp_path), enforce=False)


def test_zcode_stop_no_argv_superset_enforce(tmp_path):
    _seed_store(tmp_path)
    proc = _fire(STOP_GATE, _stop_event(tmp_path, "s4"), tmp_path,
                 mode="enforce", extra_env={"ZFT_BIN": "/nonexistent/zft"})
    assert proc.returncode == 2
    _assert_unavailable(_last_log_record(tmp_path), enforce=True)


def test_zcode_stop_bad_exit_superset(tmp_path):
    _seed_store(tmp_path)
    _fire(STOP_GATE, _stop_event(tmp_path, "s4"), tmp_path,
          extra_env={"ZFT_BIN": str(_exit2_gate(tmp_path))})
    _assert_unavailable(_last_log_record(tmp_path), enforce=False)
