"""C-39: remaining CLI seams — gate, repro, create (advertised in usage)."""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_gate_campaign_via_gate_alias(tmp_path):
    oracle = tmp_path / "oracle.py"
    oracle.write_text("def expired(t):\n    return t > 100\n")
    oracle_arg = str(oracle)
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "gate",
         "--module", "src/zft/spec/lint.py",
         "--tests", "tests/unit/test_lint_store.py",
         "--scope", "lint_store",
         "--oracle", oracle_arg,
         str(REPO)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["in_scope_total"] >= 1
    assert out["killed"] >= 1


def test_repro_run_id_required_and_valid():
    r = subprocess.run([sys.executable, "-m", "zft.cli.main", "repro", "deadbeef"],
                       capture_output=True, text=True)
    assert r.returncode == 1, "repro on missing run must fail cleanly"
    assert "no_such_run" in (r.stdout + r.stderr).lower()


def test_absolute_root_enforced_at_gate_attest_repro_boundary():
    from zft.cli.main import _abs_root

    for cmd in ("gate", "gate-campaign", "attest", "repro"):
        assert _abs_root(cmd, Path(".")).is_absolute(), cmd
    assert _abs_root("lint", Path(".")) == Path("."), "other cmds stay as given"


def test_create_adds_clause_to_store(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "create",
         "--alias", "X-DEMO", "--domain", "x", "--title", "Demo clause",
         "--statement", "WHEN demo, THE SYSTEM SHALL work",
         "--property", "forall x: ok(x)", "--kind", "test",
         str(tmp_path)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    node = json.loads((tmp_path / ".zft" / "specs" / "x" / "x-demo.json").read_text())
    assert node["status"] == "DRAFT"
    assert node["version"] == 1


def test_split_root_resolves_relative_to_absolute():
    from zft.cli.main import _split_root

    rest, root = _split_root(["--scope", "a,b", "some/rel/root"])
    assert rest == ["some/rel/root"]
    assert root.is_absolute()
    assert root == Path("some/rel/root").resolve()
    rest2, root2 = _split_root([])
    assert rest2 == []
    assert root2.is_absolute(), "default root '.' must resolve too"


def test_gate_rejects_missing_root():
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "gate",
         "--module", "m.py", "--tests", "t.py", "/nonexistent/root/xyz"],
        capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "does not exist" in r.stdout
