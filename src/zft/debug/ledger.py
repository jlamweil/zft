"""debug: run ledger — crash-safe, reproducible run records (plan §1).

Depends on nothing above it (plan §2 dependency direction).
"""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path


def _git_info(repo: Path) -> dict:
    """Best-effort git info; a repo is optional (lab/tmp contexts)."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip() != ""
        return {"git_commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"git_commit": None, "dirty": None}


def _default_syncer(fh) -> None:
    fh.flush()
    fh.fileno() and getattr(fh, "fileno")() and None
    import os

    os.fsync(fh.fileno())


class RunRecord:
    """Read-side of a run: manifest + events."""

    def __init__(self, run_id: str, manifest: dict, events: list[dict]):
        self.run_id = run_id
        self.manifest = manifest
        self.events = events


class RunLedger:
    """Append-only JSONL ledger for one gate/negotiation run (plan §1.1)."""

    def __init__(self, dir_path: Path | str):
        self.dir = Path(dir_path)
        self.run_id = self.dir.name
        self._fh = None
        self._since_sync = 0
        self._torn_tail_bytes = 0  # nonzero only on resume() after a torn write

    @classmethod
    def start(
        cls,
        runs_root: Path | str,
        manifest: dict,
        repo: Path | str | None = None,
        sync_every: int = 50,
        syncer=None,
    ) -> "RunLedger":
        runs_root = Path(runs_root)
        runs_root.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4().hex[:12]
        led = cls(runs_root / run_id)
        repo_info = _git_info(Path(repo)) if repo else {}
        full_manifest = {**repo_info, **manifest, "run_id": run_id}
        (led.dir).mkdir(parents=True)
        (led.dir / "manifest.json").write_text(json.dumps(full_manifest, indent=2))
        led._fh = open(led.dir / "events.jsonl", "ab")
        led._sync_every = sync_every
        led._syncer = syncer or _default_syncer
        return led

    @classmethod
    def resume(cls, runs_root: Path | str, run_id: str) -> "RunLedger":
        """Reopen an existing run for appending (crash resumption).

        Events persisted before the crash stay untouched; the file is opened
        in append mode after one recovery step: a trailing partial line
        (torn mid-write) is truncated, because load() stops reading at a
        torn tail (plan C-03) and everything appended after it would be
        unreadable evidence. `torn_tail_bytes` records the truncation so the
        resumer can note it in the ledger instead of recovering silently.
        """
        run_dir = Path(runs_root) / run_id
        events = run_dir / "events.jsonl"
        if not events.exists():
            raise FileNotFoundError(f"no such run: {run_id}")
        led = cls(run_dir)
        led._sync_every = 50
        led._syncer = _default_syncer
        data = events.read_bytes()
        torn_tail_bytes = 0
        if data and not data.endswith(b"\n"):
            torn_tail_bytes = len(data) - (data.rfind(b"\n") + 1)
            with open(events, "r+b") as fh:
                fh.truncate(len(data) - torn_tail_bytes)
        led._torn_tail_bytes = torn_tail_bytes
        led._fh = open(events, "ab")
        return led

    def append(self, event: dict) -> None:
        if self._fh is None:
            raise RuntimeError("RunLedger.append before start()")
        self._fh.write((json.dumps(event, sort_keys=True) + "\n").encode())
        self._fh.flush()  # visible to readers immediately; fsync is durability
        self._since_sync += 1
        if self._since_sync >= self._sync_every:
            self.flush()

    def flush(self) -> None:
        if self._fh is None:
            return
        self._fh.flush()
        self._syncer(self._fh)
        self._since_sync = 0

    def close(self) -> None:
        if self._fh is not None:
            self.flush()
            self._fh.close()
            self._fh = None

    @property
    def events(self) -> list[dict]:
        """Events of the current run (read from disk, crash-safe)."""
        return RunLedger.load(self.dir.parent, self.run_id).events

    @classmethod
    def load(cls, runs_root: Path | str, run_id: str) -> "RunRecord":
        run_dir = Path(runs_root) / run_id
        try:
            manifest = json.loads((run_dir / "manifest.json").read_text())
        except (OSError, json.JSONDecodeError):
            # metadata, not evidence: a manifest lost or torn between start()
            # and load() (external state tidy, crash mid-write) degrades the
            # read to {} instead of crashing the gate pipeline on its reload.
            # events.jsonl stays strict — its absence still means no_such_run.
            manifest = {}
        events = []
        data = (run_dir / "events.jsonl").read_bytes()
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                break  # torn tail write — ignore (plan C-03)
        return RunRecord(run_id, manifest, events)
