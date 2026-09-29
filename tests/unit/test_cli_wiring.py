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
    assert out["baseline_ok"] is True


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


CAPABLE = '[{"permission": "edit", "pattern": "*", "action": "allow"}]'
DENY_BOTH = ('[{"permission": "edit", "pattern": "*", "action": "deny"},'
             ' {"permission": "bash", "pattern": "*", "action": "deny"}]')


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_task_gate_capability_json_classifies_writer(tmp_path):
    """A 'researcher' (read-only by name) carrying a capable ruleset through
    --capability is classified a writer — so it is blocked without a contract."""
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "task-gate", "before",
         "--subagent", "researcher", "--description", "no contract",
         "--capability", CAPABLE],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["lane"] == "writer"
    assert payload["classification"]["source"] == "capability"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_task_gate_capability_json_classifies_readonly(tmp_path):
    """A 'fixer' (writer by name) carrying a fully-denied ruleset is exempt."""
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "task-gate", "before",
         "--subagent", "fixer", "--description", "no contract",
         "--capability", DENY_BOTH],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["lane"] == "readonly" and payload["allow"] is True
    assert payload["classification"]["source"] == "capability"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_task_gate_malformed_capability_falls_back_to_name(tmp_path):
    """Bad JSON degrades to the name fallback, never to a crash or an allow."""
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "task-gate", "before",
         "--subagent", "fixer", "--description", "no contract",
         "--capability", '{"not": valid json'],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["lane"] == "writer"
    assert payload["classification"]["source"] != "capability"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_task_gate_explain_classifies_without_enforcing(tmp_path):
    """--explain prints the trace and audits nothing."""
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "task-gate", "before",
         "--subagent", "researcher", "--description", "no contract",
         "--capability", CAPABLE, "--explain"],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["lane"] == "writer" and payload["source"] == "capability"
    assert not (tmp_path / ".zft" / "audit.log").exists()


# --- changeset-scoped after-gate (ENF-CHANGESET-VERDICT) -------------------

def _changeset_store(tmp_path):
    d = tmp_path / ".zft" / "contracts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "c.json").write_text(json.dumps(
        {"name": "c", "clause_ids": ["CLAUSE-1", "CLAUSE-2"]}))
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text('# @trace("CLAUSE-1")\n\n\ndef a():\n    return 1\n')
    (src / "b.py").write_text('# @trace("CLAUSE-2")\n\n\ndef b():\n    return 2\n')
    return src


# @trace("ENF-CHANGESET-VERDICT")
def test_task_gate_after_changed_flag_scopes(tmp_path):
    """--changed (repeatable) scopes the verdict to those paths."""
    src = _changeset_store(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "task-gate", "after",
         "--subagent", "fixer", "--description", "[contract: c]",
         "--changed", str(src / "a.py")],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["scope"]["mode"] == "changeset"
    assert payload["covered"] == ["CLAUSE-1"]
    assert payload["missing"] == ["CLAUSE-2"]


# @trace("ENF-CHANGESET-VERDICT")
def test_task_gate_after_scope_changeset_without_paths(tmp_path):
    """--scope changeset alone declares an (empty) changeset: nothing the
    subagent changed, so no prior coverage may be inherited."""
    _changeset_store(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "task-gate", "after",
         "--subagent", "fixer", "--description", "[contract: c]",
         "--scope", "changeset"],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 1, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["scope"] == {"mode": "changeset", "paths": 0, "since_ref": None}
    assert payload["covered"] == []
    assert payload["missing"] == ["CLAUSE-1", "CLAUSE-2"]


# @trace("ENF-CHANGESET-VERDICT")
def test_task_gate_after_default_is_tree_scope(tmp_path):
    _changeset_store(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "task-gate", "after",
         "--subagent", "fixer", "--description", "[contract: c]"],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["scope"]["mode"] == "tree"
    assert payload["covered"] == ["CLAUSE-1", "CLAUSE-2"]


# @trace("ENF-CHANGESET-VERDICT")
def test_task_gate_after_since_ref_forwarded(tmp_path):
    """--since-ref reaches the gate; an unresolvable ref is an error."""
    _changeset_store(tmp_path)
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "task-gate", "after",
         "--subagent", "fixer", "--description", "[contract: c]",
         "--since-ref", "no-such-ref"],
        capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["verdict"] == "error"
    assert "no-such-ref" in payload["reason"]


# @trace("ENF-CHANGESET-VERDICT")
def test_task_gate_usage_documents_changeset_flags():
    """The usage line is the public contract for the flag surface: every
    changeset flag must be advertised (an undocumented flag is a dead flag)."""
    r = subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "task-gate"],
        capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    for flag in ("--changed", "--since-ref", "--scope changeset"):
        assert flag in r.stdout, f"missing {flag} in usage: {r.stdout!r}"
