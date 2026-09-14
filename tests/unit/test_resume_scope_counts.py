"""WP-C4: scope-aware checkpoint + resume preserves in-scope counts."""
import json
from types import SimpleNamespace

from zft.gates.runners import mutmut_runner
from zft.gates.runners.mutmut_runner import run_campaign
from zft.gates.sandbox import prepare_sandbox

MODULE = "def alpha():\n    return 1 == 2\n\n\ndef beta():\n    return 2 != 3\n"
TESTS = (
    "from module import alpha, beta\n\n"
    "def test_alpha():\n    assert alpha()\n\n"
    "def test_beta():\n    assert beta()\n"
    "def test_alpha_again():\n    assert not alpha()\n"
)


def _prepare(tmp_path):
    src = tmp_path / "src"
    tests = tmp_path / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "module.py").write_text(MODULE)
    (tests / "test_module.py").write_text(TESTS)
    return prepare_sandbox(tmp_path / "sandbox",
                           mutate_paths=[src / "module.py"], also_copy=[tests])


def test_checkpoint_stores_scope_and_resume_preserves_counts(tmp_path, monkeypatch):
    sandbox = _prepare(tmp_path)

    def killed(*args, **kwargs):
        # Mutants "killed" for a deterministic, count-stable checkpoint.
        return SimpleNamespace(ok=False, timed_out=False, duration_ms=0)

    monkeypatch.setattr(mutmut_runner, "_run_pytest_env", killed)

    r1 = run_campaign(sandbox, test_paths=["tests/test_module.py"],
                      scope_functions={"alpha", "beta"})
    assert r1.in_scope_total > 0
    assert r1.executed == r1.in_scope_total

    checkpoint = sandbox / ".zft" / "cache" / "mutants.json"
    state = json.loads(checkpoint.read_text())
    assert state, "campaign must write a checkpoint"
    assert all(isinstance(v, dict) and "in_scope" in v for v in state.values()), state

    r2 = run_campaign(sandbox, test_paths=["tests/test_module.py"],
                      scope_functions={"alpha", "beta"}, resume=True)
    assert r2.executed == 0, "resumed run must not re-execute mutants"
    assert r2.resumed == r1.in_scope_total
    assert r2.in_scope_total == r1.in_scope_total
    assert r2.in_scope_killed == r1.in_scope_killed
