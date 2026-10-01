#!/usr/bin/env python3
"""ZCode Stop hook: run the zft fast check tier before a session may stop.

Contract (ZCode hooks — the documented event set includes Stop; verified
live against the zcode-remote-driver driver repo, 2026-09-28):
- one JSON event on stdin: {hook_event_name: "Stop", session_id, cwd, ...};
- exit 0 = stop allowed; exit 2 + reason on stderr = the stop is blocked and
  the reason is fed back to the session, which must resolve it and try to
  stop again. The event fires for every session running in the workspace —
  main or subagent — so a red store holds a subagent completion exactly like
  a main-session one. This is the hard half of "subagents are enforced to
  use zft": the PostToolUse gates hook feeds L0 findings back per edit, and
  this gate holds the completion itself.

Policy mirrors the gates hook: the gate acts only where a contract store
exists (nearest `<root>/.zft/` at or above the event cwd; no store, nothing
to enforce, silent exit 0 — Stop fires for every session, stores or not).
The seam is the CLI, `zft check <root>` — the same fast tier CI runs. Every
fired event over a store is appended to `<root>/.zft/gates-hook/log.jsonl`.

ZFT_STOP_MODE: `observe` (default) records and allows; `enforce` blocks a
red or unavailable check with the failure JSON on stderr. A missing or
broken gate never passes green: it is recorded as GATE_UNAVAILABLE and, in
enforce mode, blocks.

The gate never edits anything under `.zft/` — the run journal `zft check`
writes under `.zft/runs/` is the evidence the session must cite.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CORPUS_DIR = ".zft"
LOG_REL = Path(".zft") / "gates-hook" / "log.jsonl"
BIN_ENV = "ZFT_BIN"
ROOT_ENV = "ZFT_ROOT"
MODE_ENV = "ZFT_STOP_MODE"
CHECK_TIMEOUT = 120


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_event(raw: str) -> dict | None:
    """The event must be a JSON object; anything else is unclassifiable."""
    if not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def find_root(event: dict) -> Path | None:
    """ZFT_ROOT > event cwd (if it holds a store) > nearest ancestor that
    does. No store: None — Stop fires for every session and most workspaces
    have no contract corpus at all."""
    env_root = os.environ.get(ROOT_ENV)
    if env_root and (Path(env_root) / CORPUS_DIR).is_dir():
        return Path(env_root)
    current = Path(event.get("cwd") or Path.cwd()).resolve()
    while True:
        if (current / CORPUS_DIR).is_dir():
            return current
        if current == current.parent:
            return None
        current = current.parent


def resolve_gate() -> tuple[list[str] | None, str | None]:
    """Same seam resolution as the gates hook: ZFT_BIN is authoritative,
    then `zft` on PATH, then the importing interpreter."""
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


def run_check(root: Path, gate_argv: list[str]) -> tuple[str, int | None, str, dict | None]:
    """(status, exit, detail, report) with status in {passed, failed,
    unavailable}.

    The CLI reserves exit 0 for an ok report and 1 for a red one; any other
    outcome (missing module, usage error, traceback, timeout) is a broken
    gate, never a green one.
    """
    try:
        proc = subprocess.run([*gate_argv, "check", str(root)],
                              capture_output=True, text=True, timeout=CHECK_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "unavailable", None, f"{type(exc).__name__}: {exc}", None
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    report = None
    try:
        parsed = json.loads(proc.stdout)
        if isinstance(parsed, dict):
            report = parsed
    except json.JSONDecodeError:
        pass
    if proc.returncode == 0 and report is not None and report.get("ok") is not False:
        return "passed", 0, out, report
    if proc.returncode == 1 and report is not None and report.get("ok") is False:
        return "failed", 1, out, report
    return "unavailable", proc.returncode, out[-400:], None


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

    root = find_root(event)
    if root is None:
        return 0  # no contract corpus anywhere above the session cwd

    record = {"ts": _now(), "event": event.get("hook_event_name"),
              "mode": mode, "session_id": event.get("session_id"),
              "root": str(root)}
    gate_argv, reason = resolve_gate()
    if gate_argv is None:
        append_log(root, {**record, "decision": "gate_unavailable",
                          "detail_tail": reason})
        print(f"GATE_UNAVAILABLE: {reason}", file=sys.stderr)
        return 2 if enforce else 0

    status, gate_exit, detail, report = run_check(root, gate_argv)
    gate_rec = {"name": "CHECK", "status": status, "exit": gate_exit}
    if status == "passed":
        append_log(root, {**record, "decision": "allow", "gate": gate_rec})
        return 0
    if status == "failed":
        n_failures = len((report or {}).get("failures") or [])
        append_log(root, {**record,
                          "decision": "deny" if enforce else "allow",
                          "blocked": enforce, "gate": gate_rec,
                          "failures": n_failures,
                          "detail_tail": detail[-2000:]})
        print(f"zft check FAILED before stop ({n_failures} failures); "
              f"the failures list is the work list — fix and re-run, never "
              f"weaken a clause to pass:\n{detail[-4000:]}",
              file=sys.stderr)
        return 2 if enforce else 0
    append_log(root, {**record, "decision": "gate_unavailable",
                      "gate": gate_rec, "detail_tail": detail})
    print(f"GATE_UNAVAILABLE: check exited {gate_exit}; tail: {detail}",
          file=sys.stderr)
    return 2 if enforce else 0


if __name__ == "__main__":
    sys.exit(main())
