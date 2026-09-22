"""Codex integration prototype check: the gates hook fires L0 on a sample
contract edit.

Drives plugins/codex/hooks/gates_hook.py as a subprocess with a Codex
PostToolUse event on stdin (contract pinned from learn.chatgpt.com/codex/hooks,
fetched 2026-09-07) against a one-clause store seeded in tmp_path — no live
Codex install. Proves: the hook fires on a .zft/** edit and really runs the
L0 CLI seam; edits outside the corpus pass through un-gated; enforce mode
blocks an L0-breaking edit with the findings on stderr while observe mode
records and allows; a missing gate is a typed GATE_UNAVAILABLE, never green.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "plugins" / "codex" / "hooks" / "gates_hook.py"
SKILL = REPO / "plugins" / "codex" / "skills" / "zft-gates" / "SKILL.md"
NODE_ID = "018f3a2b-9e41-7100-8000-000000000001"
CLAUSE_PATH = ".zft/specs/x/x-one.json"


def _seed_store(tmp_path: Path) -> None:
    """One L0-green clause node (test_lint_store's fixture shape)."""
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


def _apply_patch_event(root: Path, *edits: str,
                       session: str = "sess-proto-1") -> dict:
    """A Codex PostToolUse event as the hook contract defines it: one JSON
    object on stdin, apply_patch patch text in tool_input.command."""
    patch = "*** Begin Patch\n" + "".join(
        f"*** Update File: {e}\n@@\n-x\n+y\n" for e in edits) + "*** End Patch"
    return {"session_id": session, "hook_event_name": "PostToolUse",
            "tool_name": "apply_patch", "cwd": str(root),
            "tool_input": {"command": patch}}


def _fire(event: dict, root: Path, *, mode: str | None = None,
          extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("ZFT_HOOK_MODE", None)
    env.pop("ZFT_BIN", None)
    if mode:
        env["ZFT_HOOK_MODE"] = mode
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps(event), capture_output=True,
                          text=True, env=env, cwd=root, timeout=120)


def _last_log_record(root: Path) -> dict:
    log = root / ".zft" / "gates-hook" / "log.jsonl"
    lines = log.read_text().strip().splitlines()
    assert lines, "hook wrote no log records"
    return json.loads(lines[-1])


def test_hook_fires_l0_on_sample_contract_edit(tmp_path):
    """The headline: a sample apply_patch edit to .zft/** makes the hook run
    the real L0 gate and record the outcome."""
    _seed_store(tmp_path)
    proc = _fire(_apply_patch_event(tmp_path, CLAUSE_PATH), tmp_path)
    assert proc.returncode == 0, proc.stderr
    record = _last_log_record(tmp_path)
    assert record["decision"] == "allow"
    assert record["gate"] == {"name": "L0", "status": "passed", "exit": 0}
    assert record["paths"] == [CLAUSE_PATH]
    assert record["session_id"] == "sess-proto-1"
    assert Path(record["root"]).resolve() == tmp_path.resolve()
    assert record["mode"] == "observe"  # default


def test_edit_outside_corpus_skips_gate(tmp_path):
    """Policy: only the contract corpus is gated; other edits record a
    passthrough and never run the gate."""
    _seed_store(tmp_path)
    proc = _fire(_apply_patch_event(tmp_path, "src/main.py"), tmp_path)
    assert proc.returncode == 0, proc.stderr
    record = _last_log_record(tmp_path)
    assert record["decision"] == "passthrough"
    assert "gate" not in record


def test_edit_outside_any_store_is_outside_root(tmp_path):
    """No .zft/ anywhere up the tree: nothing to gate, recorded, exit 0."""
    (tmp_path / "src").mkdir()
    proc = _fire(_apply_patch_event(tmp_path, "src/main.py"), tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert _last_log_record(tmp_path)["decision"] == "outside_root"


def _break_l0(tmp_path: Path) -> None:
    """Corrupt the seeded node the way a bad edit would (test_lint_store's
    torn hash)."""
    node_path = tmp_path / CLAUSE_PATH
    node = json.loads(node_path.read_text())
    node["content_hash"] = "1" * 64
    node_path.write_text(json.dumps(node))


def test_enforce_mode_blocks_l0_breaking_edit(tmp_path):
    """enforce: torn content_hash -> exit 2, findings on stderr, deny recorded."""
    _seed_store(tmp_path)
    _break_l0(tmp_path)
    proc = _fire(_apply_patch_event(tmp_path, CLAUSE_PATH), tmp_path, mode="enforce")
    assert proc.returncode == 2
    assert "content_hash mismatch" in proc.stderr
    assert CLAUSE_PATH in proc.stderr
    record = _last_log_record(tmp_path)
    assert record["decision"] == "deny"
    assert record["blocked"] is True
    assert record["gate"]["status"] == "failed"


def test_observe_mode_records_failure_without_blocking(tmp_path):
    """observe (default): same broken edit, exit 0, failure on the record."""
    _seed_store(tmp_path)
    _break_l0(tmp_path)
    proc = _fire(_apply_patch_event(tmp_path, CLAUSE_PATH), tmp_path)
    assert proc.returncode == 0
    record = _last_log_record(tmp_path)
    assert record["decision"] == "allow"  # observed, not blocked
    assert record["blocked"] is False
    assert record["gate"]["status"] == "failed"
    assert "content_hash mismatch" in record["detail_tail"]


def test_missing_gate_fails_closed_in_enforce(tmp_path):
    """An unusable gate is typed GATE_UNAVAILABLE and blocks — never green."""
    _seed_store(tmp_path)
    proc = _fire(_apply_patch_event(tmp_path, CLAUSE_PATH), tmp_path,
                 mode="enforce",
                 extra_env={"ZFT_BIN": "/nonexistent/zft"})
    assert proc.returncode == 2
    assert "GATE_UNAVAILABLE" in proc.stderr
    assert _last_log_record(tmp_path)["decision"] == "gate_unavailable"


def test_skill_folder_shape():
    """The artifact Codex would discover: SKILL.md parses with both required
    frontmatter fields, sitting next to the hook and a valid hooks.json."""
    text = SKILL.read_text()
    assert text.startswith("---\n")
    frontmatter = text.split("---\n", 2)[1]
    assert "name: zft-gates" in frontmatter
    description = next(line for line in frontmatter.splitlines()
                       if line.startswith("description:"))
    assert len(description) > 80  # trigger-rich, per Codex skill guidance
    hooks_json = json.loads((SKILL.parents[2] / "hooks.json").read_text())
    post = hooks_json["hooks"]["PostToolUse"]
    assert post[0]["matcher"] == "^(apply_patch|Edit|Write)$"
    assert "gates_hook.py" in post[0]["hooks"][0]["command"]
    assert HOOK.exists()
