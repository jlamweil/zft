"""pytest sandbox runner (plan C-15): subprocess isolation, duration, timeout."""
from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunnerResult:
    ok: bool
    duration_ms: int
    timed_out: bool = False
    tail: str = ""


def run_pytest(
    sandbox: Path, test_paths: list[str] | None = None, timeout_s: int = 300,
    fail_fast: bool = True,
    env: dict[str, str] | None = None,
    junit_xml: Path | None = None,
    confcutdir: Path | None = None,
) -> RunnerResult:
    """Run pytest inside sandbox dir; never raises — failures are RunnerResult data.

    env=None inherits the parent environment; sandboxed gate runs pass
    traceagent.gates.sandbox.gate_env() for strict isolation.

    confcutdir pins pytest's collection boundary (``--confcutdir``). When a
    collected file lives OUTSIDE the sandbox dir, pytest resolves its rootdir
    to the common ancestor of the two (e.g. ``/tmp`` for gate sandboxes under
    ``/tmp``) and the collection walk descends that ancestor tree — slow, and
    fatal on hosts whose ``/tmp`` holds unstat-able entries (collection dies
    before the target file is collected). The L1 oracle batch (l1.py) pins
    it to its own temp dir so the driver is always collected.
    """
    sandbox = Path(sandbox)
    # Build pytest command; include fail-fast flag (-x) only if requested
    opts = ["-q"]
    if fail_fast:
        opts.append("-x")
    cmd = [sys.executable, "-m", "pytest"] + opts + ["--no-header", "-p", "no:cacheprovider"]
    if junit_xml is not None:
        cmd += [f"--junitxml={junit_xml}"]
    if confcutdir is not None:
        cmd += [f"--confcutdir={confcutdir}"]
    if test_paths:
        cmd += test_paths
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, cwd=sandbox, capture_output=True, text=True,
                           timeout=timeout_s, env=env)
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b"").decode(errors="ignore") + (e.stderr or b"").decode(errors="ignore"))  # noqa: E501
        tail = "\n".join(out.strip().splitlines()[-4:])
        ms = int((time.perf_counter() - t0) * 1000)
        return RunnerResult(ok=False, duration_ms=ms, timed_out=True, tail=tail)
    ms = int((time.perf_counter() - t0) * 1000)
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-4:])
    return RunnerResult(ok=r.returncode == 0, duration_ms=ms, tail=tail)
