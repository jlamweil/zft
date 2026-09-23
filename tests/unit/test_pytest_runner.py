"""C-15: pytest sandbox runner — subprocess isolation, durations, timeouts.

Seam: run_pytest(sandbox_dir, test_relpath) -> RunnerResult{ok, duration_ms, tail}.

REVERSE COVERAGE — JUSTIFIED OUT-OF-CONTRACT, per element (2026-09-12; store
run 9ed8a13c5441 ok: 32/32 due clauses bound, ratio 1.0; out-of-contract =
this file + test_ears.py only). TR-REVERSE-COVERAGE requires unbound elements
be LISTED, not that every element bind — the listing is the compliant state;
this block records why no binding is owed. This file tests the execution
mechanism beneath the gates, not any negotiated behavior: none of the store's
43 clause ids has an invariant statement that predicates subprocess
isolation, duration measurement, timeout kills, or test-path forwarding. The
clauses the runner serves are policy-level and bound where their predicates
live: GATE-EVIDENCE-KIND (evidence only from an executed bound suite) at
tests/unit/test_l1.py:38; DRIVER-GATE-GREEN (staged gate green on a seeded
workspace, tree byte-identical) at tests/unit/test_driver_gate.py:64;
GATE-MUTATION-ATTRIBUTION (kill-fraction attribution, sibling runner) at
tests/unit/test_mutmut_runner.py:119. If the runner broke, the governed
behavior would fail in those governed tests — this file adds defense in
depth, not clause evidence. Per element, every one JUSTIFIED out-of-contract:
test_passing_suite and test_failing_suite_captures_tail (ok verdict + tail
capture), test_timeout_kills_run (timeout kill),
test_explicit_test_paths_select_the_suite (campaign path forwarding, the
mut-dsl-codegen lesson that broken test_paths must not silently collect the
whole sandbox). A future clause whose predicate reaches runner mechanics
binds this file at its negotiation; until then the store is under merge
freeze (2026-09-12, Phase C reconcile pending, owner go for any store write)
and this listing stands as recorded. Full decision record: RESEARCH_LOG
2026-09-12.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

from zft.gates.runners.pytest_runner import RunnerResult, run_pytest


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content))


def test_passing_suite(tmp_path):
    _write(tmp_path / "test_ok.py", """
        def test_ok():
            assert 1 + 1 == 2
    """)
    result = run_pytest(tmp_path)
    assert result.ok is True
    assert result.duration_ms > 0


def test_failing_suite_captures_tail(tmp_path):
    _write(tmp_path / "test_bad.py", """
        def test_bad():
            assert 1 == 2
    """)
    result = run_pytest(tmp_path)
    assert result.ok is False
    assert "assert" in result.tail


def test_timeout_kills_run(tmp_path):
    _write(tmp_path / "test_hang.py", """
        def test_hang():
            while True:
                pass
    """)
    result = run_pytest(tmp_path, timeout_s=2)
    assert result.ok is False
    assert result.timed_out is True
    assert result.duration_ms < 30_000


def test_explicit_test_paths_select_the_suite(tmp_path):
    # gate-campaign always runs a specific test file — a broken forwarding of
    # test_paths must not silently pass by collecting the whole sandbox
    _write(tmp_path / "good" / "test_good.py", """\
        def test_ok():
            assert True
        """)
    _write(tmp_path / "bad" / "test_bad.py", """\
        def test_bad():
            assert False
        """)
    result = run_pytest(tmp_path, test_paths=["good/test_good.py"], timeout_s=60)
    assert result.ok is True, result.tail


# ---------------------------------------------------------------------------
# kill-shard pins (0920 runners cut): the runner's own contract, observed
# exactly — argv construction, default flags, and both RunnerResult paths
# pinned by full equality on deterministic fakes (subprocess + clock).
# ---------------------------------------------------------------------------

def test_run_pytest_argv_and_default_contract(tmp_path, monkeypatch):
    import zft.gates.runners.pytest_runner as pr
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="done\n", stderr="")

    monkeypatch.setattr(pr.subprocess, "run", fake_run)
    r = run_pytest(tmp_path, ["t_a.py"], timeout_s=7, env={"E": "1"},
                   junit_xml=Path("j.xml"), confcutdir=Path("/cc"))
    assert r.ok is True
    cmd, kwargs = calls[0]
    assert cmd == [sys.executable, "-m", "pytest", "-q", "-x", "--no-header",
                   "-p", "no:cacheprovider", "--junitxml=j.xml",
                   "--confcutdir=/cc", "t_a.py"]
    assert kwargs["timeout"] == 7
    assert kwargs["env"] == {"E": "1"}
    assert kwargs["cwd"] == tmp_path
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    # defaults: timeout_s=300, fail_fast=True (the -x), no paths appended
    run_pytest(tmp_path)
    cmd, kwargs = calls[1]
    assert kwargs["timeout"] == 300
    assert kwargs["env"] is None
    assert "-x" in cmd and "-q" in cmd
    assert cmd[-1] == "no:cacheprovider"


def test_run_pytest_timeout_result_exact(tmp_path, monkeypatch):
    import zft.gates.runners.pytest_runner as pr
    times = iter([1.0, 2.0, 3.0, 4.0])
    monkeypatch.setattr(pr.time, "perf_counter", lambda: next(times))

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1,
                                       output=b"o1\n\xff\no3\no4\no5\n",
                                       stderr=b"\xff")

    monkeypatch.setattr(pr.subprocess, "run", boom)
    r = run_pytest(tmp_path, timeout_s=1)
    # the bad byte decode-ignores away: stdout "o1\n\no3\no4\no5\n" +
    # stderr "" -> last four lines ["", "o3", "o4", "o5"]
    assert r == RunnerResult(ok=False, duration_ms=1000, timed_out=True,
                             tail="\no3\no4\no5")
    # no output at all: the `or b""` defaults must keep tail empty (never XXXX)
    def boom_silent(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1, output=None,
                                       stderr=None)

    monkeypatch.setattr(pr.subprocess, "run", boom_silent)
    r2 = run_pytest(tmp_path, timeout_s=1)
    assert r2 == RunnerResult(ok=False, duration_ms=1000, timed_out=True,
                              tail="")


def test_run_pytest_success_result_exact(tmp_path, monkeypatch):
    import zft.gates.runners.pytest_runner as pr
    times = iter([1.0, 2.0])
    monkeypatch.setattr(pr.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(pr.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout="l1\nl2\nl3\nl4\nl5\nl6\n", stderr=""))
    r = run_pytest(tmp_path)
    assert r == RunnerResult(ok=True, duration_ms=1000, timed_out=False,
                             tail="l3\nl4\nl5\nl6")
