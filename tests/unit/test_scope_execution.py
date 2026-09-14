"""Wave C / WP-C1: `--scope` must be an execution filter, not attribution-only.

Before this fix, run_campaign computed `in_scope` (for the ledger event and
in_scope_* counters) but still wrote and executed every generated mutant —
scope only coloured attribution. With a scope given, out-of-scope mutants
must never touch the module: no write, no pytest run.

Contract under test: executed == in_scope_total < total_mutants, verified by
spying on _run_pytest_env and inspecting the module content at each run.
"""
from zft.gates.runners import mutmut_runner
from zft.gates.runners.mutmut_runner import run_campaign
from zft.gates.sandbox import prepare_sandbox

MODULE = """def alpha(x):
    return x + 1

def beta(x):
    return x > 5
"""

# beta's test is irrelevant to the assertion: its mutant must not run at all.
TESTS = """from module import alpha, beta

def test_alpha():
    assert alpha(1) == 2
    assert alpha(-1) == 0

def test_beta():
    assert beta(10) is True
"""

ALPHA_MUTANT = MODULE.replace("return x + 1", "return x - 1")
BETA_MUTANT = MODULE.replace("return x > 5", "return x < 5")


def _prepare(tmp_path):
    src = tmp_path / "src"
    tests = tmp_path / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "module.py").write_text(MODULE)
    (tests / "test_module.py").write_text(TESTS)
    return prepare_sandbox(tmp_path / "sandbox",
                           mutate_paths=[src / "module.py"], also_copy=[tests])


def test_scope_filters_execution_not_just_attribution(tmp_path, monkeypatch):
    sandbox = _prepare(tmp_path)
    original = (sandbox / "module.py").read_text()
    contents: list[str] = []
    real = mutmut_runner._run_pytest_env

    def spy(sbx, test_paths, timeout_s, repo_root):
        contents.append((sbx / "module.py").read_text())
        return real(sbx, test_paths, timeout_s, repo_root)

    monkeypatch.setattr(mutmut_runner, "_run_pytest_env", spy)
    result = run_campaign(sandbox, test_paths=["tests/test_module.py"],
                          scope_functions={"alpha"})

    mutant_runs = [c for c in contents if c != original]
    assert result.total_mutants == 2, "one mutant per function in the fixture"
    assert result.in_scope_total == 1
    assert len(mutant_runs) == result.in_scope_total, \
        "only in-scope mutants may be executed"
    assert len(mutant_runs) < result.total_mutants, \
        "out-of-scope mutants must not be executed"
    assert result.executed == result.in_scope_total
    # the beta mutant (line 5) must never have reached the sandbox module
    assert BETA_MUTANT not in contents
    assert ALPHA_MUTANT in contents, "the in-scope mutant is still executed"
    # exactly one extra run: the final reverse check on the original module
    assert contents[-1] == original
    assert len(contents) == len(mutant_runs) + 1
