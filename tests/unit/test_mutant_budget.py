"""WP-C3: bounded mutation budget and fail-fast execution controls."""

from types import SimpleNamespace

from traceagent.gates.runners import mutmut_runner
from traceagent.gates.runners.mutmut_runner import run_campaign
from traceagent.gates.sandbox import prepare_sandbox

MODULE = """def alpha():
    return 1 == 2

def beta():
    return 2 != 3

def gamma():
    return 3 > 4
"""

TESTS = """from module import alpha, beta, gamma

def test_alpha():
    assert alpha()

def test_beta():
    assert beta()

def test_gamma():
    assert gamma()
"""


def _prepare(tmp_path):
    src = tmp_path / "src"
    tests = tmp_path / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "module.py").write_text(MODULE)
    (tests / "test_module.py").write_text(TESTS)
    return prepare_sandbox(
        tmp_path / "sandbox",
        mutate_paths=[src / "module.py"],
        also_copy=[tests],
    )


def _make_fake_run_pytest_env(sandbox, ok):
    calls = []

    def fake_run_pytest_env(*args, **kwargs):
        # Count only mutated-module executions; the post-campaign reverse
        # check restores the original module before calling pytest.
        if (sandbox / "module.py").read_text() != MODULE:
            calls.append(1)
        return SimpleNamespace(ok=ok, timed_out=False, duration_ms=0)

    return calls, fake_run_pytest_env


def test_max_mutants_caps_execution(tmp_path, monkeypatch):
    sandbox = _prepare(tmp_path)
    calls, fake = _make_fake_run_pytest_env(sandbox, ok=False)
    monkeypatch.setattr(mutmut_runner, "_run_pytest_env", fake)
    result = run_campaign(sandbox, test_paths=["tests/test_module.py"],
                          max_mutants=1)
    assert len(calls) == 1
    assert result.executed == 1
    assert result.total_mutants > 1
    assert result.survivors == []


def test_fail_fast_stops_at_first_survivor(tmp_path, monkeypatch):
    sandbox = _prepare(tmp_path)
    calls, fake = _make_fake_run_pytest_env(sandbox, ok=True)
    monkeypatch.setattr(mutmut_runner, "_run_pytest_env", fake)
    result = run_campaign(sandbox, test_paths=["tests/test_module.py"],
                          fail_fast=True)
    assert len(calls) == 1
    assert result.executed == 1
    assert len(result.survivors) == 1
    assert result.ok is False
