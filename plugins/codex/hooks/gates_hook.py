#!/usr/bin/env python3
"""Codex PostToolUse hook: run the zft L0 gate when an edit lands in the
contract corpus.

Contract (Codex hooks — learn.chatgpt.com/codex/hooks, fetched 2026-09-07):
- one JSON event on stdin: {hook_event_name, tool_name, tool_input, cwd, ...};
  apply_patch carries the patch text in tool_input.command, Edit/Write carry
  tool_input.file_path;
- exit 0 = success; exit 2 + reason on stderr = blocking feedback Codex swaps
  into the tool result. PostToolUse cannot undo the edit, so "enforce" here is
  a mandatory feedback loop, not prevention — a PreToolUse deny would have to
  predict L0 on a store state that does not exist yet.

Policy mirrors .pre-commit-hooks.yaml: the gate acts only on the contract
corpus (`<root>/.zft/**`). The gate itself is the CLI seam, `zft lint
<root>` — the same L0 CI runs, earlier in the loop. Every fired event is
appended to `<root>/.zft/gates-hook/log.jsonl`, the audit trail this
prototype's repo-local test asserts against.

ZFT_HOOK_MODE: `observe` (default) records and allows; `enforce` exits
2 with the L0 findings on stderr. A missing or broken gate never passes green:
it is recorded as GATE_UNAVAILABLE and, in enforce mode, blocks.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CORPUS_DIR = ".zft"
LOG_REL = Path(".zft") / "gates-hook" / "log.jsonl"
EDIT_TOOL_RE = re.compile(r"^(apply_patch|Edit|Write)$")
PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$", re.MULTILINE)
PATCH_MOVE_RE = re.compile(r"^\*\*\* Move to: (.+?)\s*$", re.MULTILINE)
BIN_ENV = "ZFT_BIN"
ROOT_ENV = "ZFT_ROOT"
MODE_ENV = "ZFT_HOOK_MODE"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm(path: str) -> str:
    path = path.strip().strip('"').strip("'")
    while path.startswith("./"):
        path = path[2:]
    return path


def read_event(raw: str) -> dict | None:
    """The event must be a JSON object; anything else is unclassifiable."""
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def edited_paths(event: dict) -> list[str]:
    tool_input = event.get("tool_input") or {}
    tool = str(event.get("tool_name", ""))
    if tool == "apply_patch":
        patch = str(tool_input.get("command", ""))
        found = PATCH_FILE_RE.findall(patch) + PATCH_MOVE_RE.findall(patch)
        return [p for p in dict.fromkeys(_norm(f) for f in found) if p]
    paths = []
    for key in ("file_path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(_norm(value))
    return list(dict.fromkeys(paths))


def find_root(edits: list[str], event: dict) -> Path | None:
    """ZFT_ROOT > event cwd (if it holds a store) > nearest ancestor of
    any edited path that holds a store."""
    env_root = os.environ.get(ROOT_ENV)
    if env_root and (Path(env_root) / CORPUS_DIR).is_dir():
        return Path(env_root)
    cwd_raw = event.get("cwd")
    cwd = Path(cwd_raw) if cwd_raw else Path.cwd()
    if (cwd / CORPUS_DIR).is_dir():
        return cwd
    for edit in edits:
        path = Path(edit)
        if not path.is_absolute():
            path = cwd / path
        current = path.resolve().parent
        while True:
            if (current / CORPUS_DIR).is_dir():
                return current
            if current == current.parent:
                break
            current = current.parent
    return None


def in_corpus(edit: str, root: Path) -> bool:
    path = Path(_norm(edit))
    if not path.is_absolute():
        path = root / path
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] == CORPUS_DIR


def resolve_gate() -> tuple[list[str] | None, str | None]:
    """(gate argv without `lint <root>`, unavailable-reason). An explicit
    ZFT_BIN that cannot run is authoritative — it fails rather than
    silently falling back to another interpreter."""
    override = os.environ.get(BIN_ENV)
    if override:
        argv = shlex.split(override)
        if not argv:
            return None, f"{BIN_ENV}={override!r}: empty command"
        exe = shutil.which(argv[0])
        if exe is None:
            return None, f"{BIN_ENV}={override!r}: executable not found"
        return [exe, *argv[1:]], None
    zft = shutil.which("zft")
    if zft:
        return [zft], None
    return [sys.executable, "-m", "zft.cli.main"], None


def run_l0(root: Path, gate_argv: list[str]) -> tuple[str, int | None, str]:
    """(status, exit, detail) with status in {passed, failed, unavailable}.

    The CLI reserves exit 0 for `L0 PASSED` and 1 for `L0 FAILED`; any other
    outcome (missing module, usage error, traceback, timeout) is a broken gate,
    never a green one.
    """
    try:
        proc = subprocess.run([*gate_argv, "lint", str(root)],
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "unavailable", None, f"{type(exc).__name__}: {exc}"
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode == 0:
        return "passed", 0, out
    if proc.returncode == 1 and "L0 FAILED" in out:
        return "failed", 1, out
    return "unavailable", proc.returncode, out[-400:]


def append_log(root: Path, record: dict) -> None:
    try:
        log = root / LOG_REL
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass  # the log is an audit trail, never a reason to crash the hook


def main() -> int:
    mode = os.environ.get(MODE_ENV, "observe")
    enforce = mode == "enforce"
    event = read_event(sys.stdin.read())
    if event is None:
        append_log(Path.cwd(), {"ts": _now(), "mode": mode,
                                "decision": "unclassified",
                                "reason": "stdin was not a JSON object"})
        return 0

    tool = str(event.get("tool_name", ""))
    base = {"ts": _now(), "event": event.get("hook_event_name"), "tool": tool,
            "mode": mode, "session_id": event.get("session_id")}
    if not EDIT_TOOL_RE.match(tool):
        return 0  # registered matcher drifted; not our policy, stay silent
    edits = edited_paths(event)
    if not edits:
        append_log(Path.cwd(), {**base, "decision": "unclassified",
                                "reason": "no edited paths in tool_input"})
        return 0
    root = find_root(edits, event)
    if root is None:
        append_log(Path.cwd(), {**base, "decision": "outside_root", "paths": edits})
        return 0
    protected = [e for e in edits if in_corpus(e, root)]
    if not protected:
        append_log(root, {**base, "root": str(root), "paths": edits,
                          "decision": "passthrough"})
        return 0

    record = {**base, "root": str(root), "paths": protected}
    gate_argv, reason = resolve_gate()
    if gate_argv is None:
        append_log(root, {**record, "decision": "gate_unavailable",
                          "detail_tail": reason})
        print(f"GATE_UNAVAILABLE: {reason}", file=sys.stderr)
        return 2 if enforce else 0

    status, gate_exit, detail = run_l0(root, gate_argv)
    if status == "passed":
        append_log(root, {**record, "decision": "allow",
                          "gate": {"name": "L0", "status": status, "exit": gate_exit}})
        return 0
    if status == "failed":
        append_log(root, {**record, "decision": "deny" if enforce else "allow",
                          "blocked": enforce,
                          "gate": {"name": "L0", "status": status, "exit": gate_exit},
                          "detail_tail": detail[-2000:]})
        print(f"zft L0 FAILED after edit to {', '.join(protected)}\n{detail}",
              file=sys.stderr)
        return 2 if enforce else 0
    append_log(root, {**record, "decision": "gate_unavailable",
                      "gate": {"name": "L0", "status": status, "exit": gate_exit},
                      "detail_tail": detail})
    print(f"GATE_UNAVAILABLE: gate exited {gate_exit}; tail: {detail}", file=sys.stderr)
    return 2 if enforce else 0


if __name__ == "__main__":
    sys.exit(main())
