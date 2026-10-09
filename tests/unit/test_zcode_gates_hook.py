"""ZCode integration prototype check: the gates hook fires L0 on a sample
contract edit and the stop gate holds a red store before a session stops.

Drives plugins/zft-gates/hooks/{gates_hook.py,stop_gate.py} as subprocesses
with ZCode events on stdin (event set documented by the zcode-guide
configuration reference: PostToolUse Edit/Write with tool_input.file_path;
Stop with session_id + cwd), against a one-clause store seeded in tmp_path —
no live ZCode install. The gates hook is byte-for-byte the codex twin
(modulo its docstring), so the same events prove both files stay in lockstep
where the contracts overlap.

Proves: the hook fires on a .zft/** edit and really runs the L0 CLI seam;
edits outside the corpus pass through un-gated; enforce mode blocks an
L0-breaking edit with the findings on stderr while observe mode records and
allows; a missing gate is a typed GATE_UNAVAILABLE, never green; the stop
gate runs the fast check tier, allows green, records red in observe, blocks
red in enforce, and silently exits where no store exists. Also proves the
plugin artifact shape: manifest, hooks.json with ${CLAUDE_PLUGIN_ROOT} paths,
skill frontmatter, marketplace entry.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ZCODE_DIR = REPO / "plugins" / "zft-gates"
GATES_HOOK = ZCODE_DIR / "hooks" / "gates_hook.py"
STOP_GATE = ZCODE_DIR / "hooks" / "stop_gate.py"
CODEX_HOOK = REPO / "plugins" / "codex" / "hooks" / "gates_hook.py"
SKILL = ZCODE_DIR / "skills" / "zft-gates" / "SKILL.md"
NODE_ID = "018f3a2b-9e41-7100-8000-000000000001"
CLAUSE_PATH = ".zft/specs/x/x-one.json"


def _seed_store(tmp_path: Path) -> None:
    """One L0-green (but unbound, hence check-red) clause node — the same
    fixture shape test_codex_gates_hook.py seeds."""
    from zft.spec.canon import canonical_hash

    spec_dir = tmp_path / ".zft" / "specs" / "x"
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


def _edit_event(root: Path, *edits: str, tool: str = "Write",
                session: str = "sess-zcode-1") -> dict:
    """A ZCode PostToolUse event as the hook contract defines it: Edit/Write
    carry the touched path in tool_input.file_path."""
    return {"session_id": session, "hook_event_name": "PostToolUse",
            "tool_name": tool, "cwd": str(root),
            "tool_input": {"file_path": str(root / edits[0]) if len(edits) == 1
                           else [str(root / e) for e in edits]}}


def _stop_event(root: Path, session: str = "sess-zcode-1") -> dict:
    """A ZCode Stop event: no tool, just the session and its cwd."""
    return {"session_id": session, "hook_event_name": "Stop",
            "cwd": str(root)}


def _fire(script: Path, event: dict, root: Path, *, mode_env: str,
          mode: str | None = None,
          extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("ZFT_HOOK_MODE", None)
    env.pop("ZFT_STOP_MODE", None)
    env.pop("ZFT_BIN", None)
    if mode:
        env[mode_env] = mode
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(script)],
                          input=json.dumps(event), capture_output=True,
                          text=True, env=env, cwd=root, timeout=180)


def _last_log_record(root: Path) -> dict:
    log = root / ".zft" / "gates-hook" / "log.jsonl"
    lines = log.read_text().strip().splitlines()
    assert lines, "hook wrote no log records"
    return json.loads(lines[-1])


# --- gates hook (PostToolUse) ------------------------------------------------

def test_gates_hook_fires_l0_on_sample_contract_edit(tmp_path):
    """The headline: a Write into .zft/** makes the hook run the real L0 gate
    and record the outcome; the codex twin behaves identically."""
    _seed_store(tmp_path)
    for hook in (GATES_HOOK, CODEX_HOOK):
        proc = _fire(hook, _edit_event(tmp_path, CLAUSE_PATH), tmp_path,
                     mode_env="ZFT_HOOK_MODE")
        assert proc.returncode == 0, proc.stderr
        record = _last_log_record(tmp_path)
        assert record["decision"] == "allow"
        assert record["gate"] == {"name": "L0", "status": "passed", "exit": 0}
        assert Path(record["paths"][0]).name == "x-one.json"
        assert record["session_id"] == "sess-zcode-1"
        assert Path(record["root"]).resolve() == tmp_path.resolve()
        assert record["mode"] == "observe"  # default


def test_gates_hook_edit_outside_corpus_skips_gate(tmp_path):
    """Policy: only the contract corpus is gated; other edits record a
    passthrough and never run the gate."""
    _seed_store(tmp_path)
    proc = _fire(GATES_HOOK, _edit_event(tmp_path, "src/main.py"), tmp_path,
                 mode_env="ZFT_HOOK_MODE")
    assert proc.returncode == 0, proc.stderr
    record = _last_log_record(tmp_path)
    assert record["decision"] == "passthrough"
    assert "gate" not in record


def test_gates_hook_edit_outside_any_store_is_outside_root(tmp_path):
    """No .zft/ anywhere up the tree: nothing to gate, recorded, exit 0."""
    (tmp_path / "src").mkdir()
    proc = _fire(GATES_HOOK, _edit_event(tmp_path, "src/main.py"), tmp_path,
                 mode_env="ZFT_HOOK_MODE")
    assert proc.returncode == 0, proc.stderr
    assert _last_log_record(tmp_path)["decision"] == "outside_root"


def _break_l0(tmp_path: Path) -> None:
    """Corrupt the seeded node the way a bad edit would (torn hash)."""
    node_path = tmp_path / CLAUSE_PATH
    node = json.loads(node_path.read_text())
    node["content_hash"] = "1" * 64
    node_path.write_text(json.dumps(node))


def test_gates_hook_enforce_blocks_l0_breaking_edit(tmp_path):
    """enforce: torn content_hash -> exit 2, findings on stderr, deny recorded."""
    _seed_store(tmp_path)
    _break_l0(tmp_path)
    proc = _fire(GATES_HOOK, _edit_event(tmp_path, CLAUSE_PATH), tmp_path,
                 mode_env="ZFT_HOOK_MODE", mode="enforce")
    assert proc.returncode == 2
    assert "content_hash mismatch" in proc.stderr
    assert CLAUSE_PATH in proc.stderr
    record = _last_log_record(tmp_path)
    assert record["decision"] == "deny"
    assert record["blocked"] is True
    assert record["gate"]["status"] == "failed"


def test_gates_hook_observe_records_failure_without_blocking(tmp_path):
    """observe (default): same broken edit, exit 0, failure on the record."""
    _seed_store(tmp_path)
    _break_l0(tmp_path)
    proc = _fire(GATES_HOOK, _edit_event(tmp_path, CLAUSE_PATH), tmp_path,
                 mode_env="ZFT_HOOK_MODE")
    assert proc.returncode == 0
    record = _last_log_record(tmp_path)
    assert record["decision"] == "allow"  # observed, not blocked
    assert record["blocked"] is False
    assert record["gate"]["status"] == "failed"
    assert "content_hash mismatch" in record["detail_tail"]


def test_gates_hook_missing_gate_fails_closed_in_enforce(tmp_path):
    """An unusable gate is typed GATE_UNAVAILABLE and blocks — never green."""
    _seed_store(tmp_path)
    proc = _fire(GATES_HOOK, _edit_event(tmp_path, CLAUSE_PATH), tmp_path,
                 mode_env="ZFT_HOOK_MODE", mode="enforce",
                 extra_env={"ZFT_BIN": "/nonexistent/zft"})
    assert proc.returncode == 2
    assert "GATE_UNAVAILABLE" in proc.stderr
    assert _last_log_record(tmp_path)["decision"] == "gate_unavailable"


# --- stop gate (Stop) --------------------------------------------------------

def test_stop_gate_allows_and_records_a_red_store_in_observe(tmp_path):
    """observe (default): the seeded store is unbound, so the fast tier is
    red — recorded with the failure count, but the stop is allowed."""
    _seed_store(tmp_path)
    proc = _fire(STOP_GATE, _stop_event(tmp_path), tmp_path,
                 mode_env="ZFT_STOP_MODE")
    assert proc.returncode == 0
    record = _last_log_record(tmp_path)
    assert record["decision"] == "allow"
    assert record["blocked"] is False
    assert record["gate"]["name"] == "CHECK"
    assert record["gate"]["status"] == "failed"
    assert record["gate"]["exit"] == 1
    assert record["failures"] >= 1
    assert record["session_id"] == "sess-zcode-1"


def test_stop_gate_blocks_a_red_store_in_enforce(tmp_path):
    """enforce: red check -> exit 2, failures tail on stderr, deny recorded."""
    _seed_store(tmp_path)
    proc = _fire(STOP_GATE, _stop_event(tmp_path), tmp_path,
                 mode_env="ZFT_STOP_MODE", mode="enforce")
    assert proc.returncode == 2
    assert "zft check FAILED" in proc.stderr
    assert "failures" in proc.stderr
    record = _last_log_record(tmp_path)
    assert record["decision"] == "deny"
    assert record["blocked"] is True
    assert record["gate"]["status"] == "failed"


def test_stop_gate_missing_gate_fails_closed_in_enforce(tmp_path):
    """An unusable gate is typed GATE_UNAVAILABLE and blocks — never green."""
    _seed_store(tmp_path)
    proc = _fire(STOP_GATE, _stop_event(tmp_path), tmp_path,
                 mode_env="ZFT_STOP_MODE", mode="enforce",
                 extra_env={"ZFT_BIN": "/nonexistent/zft"})
    assert proc.returncode == 2
    assert "GATE_UNAVAILABLE" in proc.stderr
    assert _last_log_record(tmp_path)["decision"] == "gate_unavailable"


def test_stop_gate_silent_where_no_store_exists(tmp_path):
    """No .zft/ at or above the session cwd: exit 0, nothing logged — Stop
    fires for every session and most workspaces have no contract corpus."""
    (tmp_path / "src").mkdir()
    proc = _fire(STOP_GATE, _stop_event(tmp_path), tmp_path,
                 mode_env="ZFT_STOP_MODE")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""
    assert not (tmp_path / ".zft").exists()


def test_stop_gate_event_without_store_finds_nearest_ancestor(tmp_path):
    """A session whose cwd is below the store root is gated on that store."""
    _seed_store(tmp_path)
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    event = _stop_event(nested)
    proc = _fire(STOP_GATE, event, tmp_path, mode_env="ZFT_STOP_MODE")
    assert proc.returncode == 0, proc.stderr
    record = _last_log_record(tmp_path)
    assert Path(record["root"]).resolve() == tmp_path.resolve()


# --- plugin artifact shape ---------------------------------------------------

def test_plugin_manifest_and_hooks_shape():
    """The artifact ZCode would load: manifest name matches the directory,
    hooks.json wires both events through ${CLAUDE_PLUGIN_ROOT}, the skill
    parses, and the dev marketplace entry agrees."""
    manifest = json.loads((ZCODE_DIR / ".zcode-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "zft-gates"
    assert ZCODE_DIR.name == manifest["name"]
    assert manifest["skills"] == "./skills"
    assert manifest["hooks"] == "./hooks/hooks.json"

    hooks_json = json.loads((ZCODE_DIR / "hooks" / "hooks.json").read_text())
    post = hooks_json["hooks"]["PostToolUse"][0]
    assert post["matcher"] == "^(Edit|Write)$"
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/gates_hook.py" in post["hooks"][0]["command"]
    stop = hooks_json["hooks"]["Stop"][0]
    assert "${CLAUDE_PLUGIN_ROOT}/hooks/stop_gate.py" in stop["hooks"][0]["command"]
    assert GATES_HOOK.exists() and STOP_GATE.exists()

    text = SKILL.read_text()
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    assert "name: zft-gates" in frontmatter
    description = next(line for line in frontmatter.splitlines()
                       if line.startswith("description:"))
    assert len(description) > 80  # trigger-rich, per skill guidance

    market = json.loads((REPO / "plugins" / "marketplace.json").read_text())
    entry = next(p for p in market["plugins"] if p["name"] == "zft-gates")
    assert entry["source"] == "./zft-gates"
    assert entry["version"] == manifest["version"]
