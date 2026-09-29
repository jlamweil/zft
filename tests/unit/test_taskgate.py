"""ENF task gate: writer-lane contract enforcement, read-only exemption,
post-task coverage verdict, audited decisions."""
import json
import subprocess
from pathlib import Path

from zft.taskgate import gate_after, gate_before

REPO = Path(__file__).resolve().parents[2]


def _write_contract(tmp_path, name="c", clause_ids=None):
    d = tmp_path / ".zft" / "contracts"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(
        {"name": name, "clause_ids": clause_ids if clause_ids is not None else []}))


# @trace("ENF-WRITER-REQUIRES-CONTRACT")
def test_writer_without_contract_blocks(tmp_path):
    code, payload = gate_before("fixer", "implement the thing", tmp_path)
    assert code == 1
    assert payload["allow"] is False
    assert payload["code"] == "ENF_WRITER_REQUIRES_CONTRACT"
    assert payload["lane"] == "writer" and payload["gated"] is False
    assert payload["contract"] is None and payload["override"] is False


# @trace("ENF-WRITER-REQUIRES-CONTRACT")
def test_writer_with_contract_allowed(tmp_path):
    _write_contract(tmp_path)
    code, payload = gate_before("fixer", "[contract: c] implement", tmp_path)
    assert code == 0
    assert payload["allow"] is True
    assert payload["gated"] is True and payload["override"] is False
    assert payload["contract"] == "c" and payload["lane"] == "writer"


# @trace("ENF-READONLY-EXEMPT")
def test_readonly_lane_exempt(tmp_path):
    code, payload = gate_before("explorer", "search only", tmp_path)
    assert code == 0
    assert payload["allow"] is True
    assert payload["gated"] is False
    assert payload["lane"] == "readonly" and payload["contract"] is None


# @trace("ENF-CONTRACT-VERDICT")
def test_after_verdict_covered_then_missing(tmp_path):
    # schema-valid clause node, produced by the real CLI in the tmp root
    r = subprocess.run(
        [str(Path(__import__("sys").executable).parent / "zft"), "create",
         "--alias", "X-CLAUSE", "--domain", "e",
         "--title", "X clause", "--statement", "WHEN x holds, THE SYSTEM SHALL hold",
         "--property", "forall x: ok(x)", "--kind", "test",
         str(tmp_path)],
        capture_output=True, text=True, cwd=str(REPO))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / ".zft" / "specs" / "e" / "x-clause.json").exists()

    _write_contract(tmp_path, clause_ids=["X-CLAUSE"])
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "t.py").write_text(
        '# @trace("X-CLAUSE")\n\n\n'
        "def check_x():\n    return True\n")

    code, payload = gate_after("fixer", "[contract: c]", tmp_path)
    assert code == 0
    assert payload["verdict"] == "covered"
    assert payload["contract"] == "c"
    assert payload["due"] == ["X-CLAUSE"]
    assert payload["covered"] == ["X-CLAUSE"]
    assert payload["missing"] == []

    (tests / "t.py").write_text("def check_x():\n    return True\n")
    code, payload = gate_after("fixer", "[contract: c]", tmp_path)
    assert code == 1
    assert payload["verdict"] == "missing"
    assert payload["covered"] == []
    assert payload["missing"] == ["X-CLAUSE"]


# @trace("ENF-AUDIT-LOGGED")
def test_override_decision_audited_ungated(tmp_path):
    code, payload = gate_before("fixer", "[ungated: hotfix]", tmp_path)
    assert code == 0
    assert payload["allow"] is True
    assert payload["override"] is True
    assert payload["gated"] is False

    log = tmp_path / ".zft" / "audit.log"
    assert log.exists()
    lines = [json.loads(line) for line in log.read_text().splitlines() if line]
    assert len(lines) == 1  # exactly one record per decision
    rec = lines[0]
    assert rec["phase"] == "before" and rec["subagent"] == "fixer"
    assert rec["lane"] == "writer"
    assert rec["override"] is True
    assert rec["gated"] is False
    assert "ts" in rec and "reason" in rec


def test_lane_classification_is_case_insensitive():
    """Zcode capitalizes agent types (Explore, Vision) — same lane either way."""
    from zft.taskgate import classify

    for name in ("Explore", "explore", "Vision", "RESEARCHER", "code-explorer"):
        assert classify(name) == "readonly", name
    assert classify("implementer") == "writer"
    assert classify("general-purpose") == "writer"


# --- capability-based classification (ENF-CAPABILITY-CLASSIFICATION) -------
# Cases pinned by oracle_CAPABILITY-CLASSIFICATION.py, derived from opencode
# source: PermissionRule = {permission, pattern, action}; evaluate() is
# findLast with a default of "ask"; merge() is flat() (no dedup).

_DENY_BOTH = [{"permission": "edit", "pattern": "*", "action": "deny"},
              {"permission": "bash", "pattern": "*", "action": "deny"}]


def _rules(**perms):
    """Build a ruleset from shorthand: edit='allow', bash={'*': 'deny'} ..."""
    out = []
    for perm, spec in perms.items():
        if isinstance(spec, str):
            out.append({"permission": perm, "pattern": "*", "action": spec})
        else:
            for pat, act in spec.items():
                out.append({"permission": perm, "pattern": pat, "action": act})
    return out


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_capability_both_denied_is_readonly():
    from zft.taskgate import classify
    assert classify("anything", _DENY_BOTH) == "readonly"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_capability_no_rules_means_producer():
    """opencode's evaluate() defaults to 'ask' when no rule matches, and
    'ask' can still mutate after approval — no rules is NOT read-only."""
    from zft.taskgate import classify
    assert classify("anything", []) == "writer"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_capability_catchall_allow_from_defaults():
    """opencode defaults include {permission: '*', pattern: '*', allow} and
    the wildcard permission name must match 'edit'/'bash'."""
    from zft.taskgate import classify
    catchall = [{"permission": "*", "pattern": "*", "action": "allow"}]
    assert classify("anything", catchall) == "writer"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_capability_ask_is_a_capability():
    from zft.taskgate import classify
    rules = _rules(edit="ask", bash={"*": "deny"})
    assert classify("anything", rules) == "writer"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_capability_later_rule_wins_over_earlier():
    """merge() is flat() with no dedup, so [allow, deny] must resolve to
    deny — a naive 'any allow' scan would misclassify this as producer."""
    from zft.taskgate import classify
    rules = [{"permission": "edit", "pattern": "*", "action": "allow"},
             {"permission": "edit", "pattern": "*", "action": "deny"}] + \
        [{"permission": "bash", "pattern": "*", "action": "deny"}]
    assert classify("anything", rules) == "readonly"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_capability_edit_synonyms_count():
    """opencode's disabled() treats edit/write/apply_patch as one group."""
    from zft.taskgate import classify
    rules = [{"permission": "write", "pattern": "*", "action": "deny"},
             {"permission": "apply_patch", "pattern": "*", "action": "deny"},
             {"permission": "bash", "pattern": "*", "action": "deny"}]
    assert classify("anything", rules) == "readonly"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_capability_granular_allow_is_producer():
    """The built-in plan agent denies edit catch-all but allows plan files:
    the last edit rule is a non-catch-all allow -> producer."""
    from zft.taskgate import classify
    rules = [{"permission": "*", "pattern": "*", "action": "allow"},
             {"permission": "edit", "pattern": "*", "action": "deny"},
             {"permission": "edit", "pattern": ".opencode/plans/*.md", "action": "allow"},
             {"permission": "bash", "pattern": "*", "action": "deny"}]
    assert classify("anything", rules) == "writer"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_capability_name_fallback_when_no_ruleset():
    """Without a ruleset the lane name still decides, exactly as before."""
    from zft.taskgate import classify
    assert classify("researcher", None) == "readonly"
    assert classify("implementer", None) == "writer"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_classify_trace_records_source_and_rules():
    from zft.taskgate import classify_trace
    tr = classify_trace("fixer", _DENY_BOTH)
    assert tr["lane"] == "readonly" and tr["source"] == "capability"
    assert tr["rules"] == _DENY_BOTH and tr["found"] is True
    tr = classify_trace("researcher", None)
    assert tr["lane"] == "readonly" and tr["source"] == "name"
    assert tr["found"] is False
    tr = classify_trace("fixer", None)
    assert tr["lane"] == "writer" and tr["source"] == "default"


# @trace("ENF-CAPABILITY-CLASSIFICATION")
def test_gate_before_uses_capability_ruleset(tmp_path):
    """A 'researcher' carrying a capable ruleset is gated as a writer;
    the payload and audit record both carry the classification trace."""
    from zft.taskgate import gate_before
    _write_contract(tmp_path, name="c")
    rules = _rules(edit="allow")
    code, payload = gate_before("researcher", "[contract: c]", tmp_path, rules=rules)
    assert code == 0 and payload["lane"] == "writer" and payload["gated"] is True
    assert payload["classification"]["source"] == "capability"
    rec = [json.loads(line) for line in
           (tmp_path / ".zft" / "audit.log").read_text().splitlines()]
    assert rec[-1]["classification"]["lane"] == "writer"


# --- changeset-scoped evidence (ENF-CHANGESET-VERDICT) ---------------------
# The after-gate's coverage verdict may be scoped to what the subagent
# actually changed: bindings outside the declared changeset do not count, so
# a subagent cannot inherit prior coverage. An unresolvable changeset is an
# error verdict (exit 2), never a silently unscoped (inflated) one.

def _git(tmp_path, *args):
    r = subprocess.run(
        ["git", "-c", "user.name=zft-test", "-c", "user.email=zft@test", *args],
        cwd=str(tmp_path), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def _changeset_store(tmp_path, clause_ids=("CLAUSE-1", "CLAUSE-2", "CLAUSE-3")):
    _write_contract(tmp_path, clause_ids=list(clause_ids))
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "a.py").write_text('# @trace("CLAUSE-1")\n\n\ndef a():\n    return 1\n')
    (src / "b.py").write_text('# @trace("CLAUSE-2")\n\n\ndef b():\n    return 2\n')
    return src


# @trace("ENF-CHANGESET-VERDICT")
def test_changeset_scope_counts_only_changed_paths(tmp_path):
    src = _changeset_store(tmp_path)
    code, payload = gate_after("fixer", "[contract: c]", tmp_path,
                               changed=[str(src / "a.py")])
    assert code == 1
    assert payload["verdict"] == "missing"
    assert payload["covered"] == ["CLAUSE-1"]
    assert payload["missing"] == ["CLAUSE-2", "CLAUSE-3"]
    assert payload["scope"]["mode"] == "changeset"
    assert payload["scope"]["paths"] == 1
    rec = json.loads((tmp_path / ".zft" / "audit.log").read_text().splitlines()[-1])
    assert rec["scope"]["mode"] == "changeset"


# @trace("ENF-CHANGESET-VERDICT")
def test_changeset_empty_reports_everything_missing(tmp_path):
    """A subagent that changed nothing cannot inherit prior coverage."""
    _changeset_store(tmp_path)
    code, payload = gate_after("fixer", "[contract: c]", tmp_path, changed=[])
    assert code == 1
    assert payload["covered"] == []
    assert payload["missing"] == ["CLAUSE-1", "CLAUSE-2", "CLAUSE-3"]
    assert payload["scope"]["paths"] == 0


# @trace("ENF-CHANGESET-VERDICT")
def test_changeset_directory_prefix_and_relative_paths(tmp_path):
    src = _changeset_store(tmp_path)
    code, payload = gate_after("fixer", "[contract: c]", tmp_path, changed=[str(src)])
    assert code == 1
    assert payload["covered"] == ["CLAUSE-1", "CLAUSE-2"]
    assert payload["missing"] == ["CLAUSE-3"]
    code, payload = gate_after("fixer", "[contract: c]", tmp_path,
                               changed=["src/a.py", "src/b.py"])
    assert payload["covered"] == ["CLAUSE-1", "CLAUSE-2"]
    assert payload["missing"] == ["CLAUSE-3"]


# @trace("ENF-CHANGESET-VERDICT")
def test_unscoped_after_stays_tree_mode(tmp_path):
    """Default behavior is unchanged: bindings anywhere in the tree count."""
    _changeset_store(tmp_path)
    code, payload = gate_after("fixer", "[contract: c]", tmp_path)
    assert payload["scope"]["mode"] == "tree"
    assert code == 1 and payload["missing"] == ["CLAUSE-3"]


# @trace("ENF-CHANGESET-VERDICT")
def test_since_ref_covers_tracked_and_untracked(tmp_path):
    src = _changeset_store(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    (src / "a.py").write_text('# @trace("CLAUSE-1")\n\n\ndef a():\n    return 11\n')
    (src / "c.py").write_text('# @trace("CLAUSE-3")\n\n\ndef c():\n    return 3\n')
    code, payload = gate_after("fixer", "[contract: c]", tmp_path, since_ref="HEAD")
    assert code == 1
    assert payload["covered"] == ["CLAUSE-1", "CLAUSE-3"]
    assert payload["missing"] == ["CLAUSE-2"]
    assert payload["scope"]["since_ref"] == "HEAD"
    assert payload["scope"]["paths"] >= 2


# @trace("ENF-CHANGESET-VERDICT")
def test_since_ref_and_changed_union(tmp_path):
    src = _changeset_store(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    code, payload = gate_after("fixer", "[contract: c]", tmp_path,
                               changed=[str(src / "a.py")], since_ref="HEAD")
    assert payload["covered"] == ["CLAUSE-1"]
    assert payload["missing"] == ["CLAUSE-2", "CLAUSE-3"]
    assert payload["scope"]["since_ref"] == "HEAD"


# @trace("ENF-CHANGESET-VERDICT")
def test_since_ref_unresolvable_is_error_not_inflated(tmp_path):
    _changeset_store(tmp_path)
    _git(tmp_path, "init", "-q")
    code, payload = gate_after("fixer", "[contract: c]", tmp_path,
                               since_ref="no-such-ref")
    assert code == 2
    assert payload["verdict"] == "error"
    assert "no-such-ref" in payload["reason"]
    # git prints its usage block after the diagnostic — name the fatal line,
    # not the trailing option table.
    assert "fatal:" in payload["reason"]
    assert "--output" not in payload["reason"]


# @trace("ENF-CHANGESET-VERDICT")
def test_since_ref_reason_names_fatal_not_usage_outside_repo(tmp_path):
    """Same reason rule where git prints the NOISIEST output: outside a repo
    it warns and then dumps its usage block, and the tail is pure option-
    table noise."""
    _changeset_store(tmp_path)
    code, payload = gate_after("fixer", "[contract: c]", tmp_path,
                               since_ref="no-such-ref")
    assert code == 2
    assert payload["verdict"] == "error"
    assert "Not a git repository" in payload["reason"]
    assert "--output" not in payload["reason"]


# @trace("ENF-CHANGESET-VERDICT")
def test_since_ref_without_git_is_error(tmp_path):
    _changeset_store(tmp_path)
    code, payload = gate_after("fixer", "[contract: c]", tmp_path, since_ref="HEAD")
    assert code == 2
    assert payload["verdict"] == "error"


# --- O1 instrumentation (gates-bench v3 prereg §1) --------------------------
# The v2 verdict's disclosed gap: no duration field exists anywhere in the
# gate's instrumentation. The plugin supplies since_ms/dispatch_id per
# dispatch; the core measures its own compute (gate_ms) and stamps all three
# on the audit record — additive only (T6 pins the v2 key set when the
# instrumentation is absent).

_V2_BEFORE_KEYS = {"ts", "subagent", "lane", "phase", "gated", "contract",
                   "override", "reason", "classification"}
_V2_AFTER_KEYS = {"ts", "subagent", "lane", "phase", "gated", "contract",
                  "verdict", "missing", "classification", "scope"}

_DISPATCH = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


def _records(root):
    log = Path(root) / ".zft" / "audit.log"
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def test_taskgate_audit_carry_gate_ms(tmp_path):
    """T1: instrumented invocations stamp an integer gate_ms >= 0 on both
    phases' records (the core's own compute, time.monotonic-derived)."""
    _write_contract(tmp_path, clause_ids=[])
    code, _ = gate_before("fixer", "[contract: c] work", tmp_path,
                          since_ms=1727600000000, dispatch_id=_DISPATCH)
    assert code == 0
    rec = _records(tmp_path)[-1]
    assert isinstance(rec["gate_ms"], int) and rec["gate_ms"] >= 0
    code, _ = gate_after("fixer", "[contract: c]", tmp_path,
                         since_ms=1727600000000, dispatch_id=_DISPATCH)
    assert code == 0
    rec = _records(tmp_path)[-1]
    assert isinstance(rec["gate_ms"], int) and rec["gate_ms"] >= 0


def test_taskgate_since_and_dispatch_passthrough(tmp_path):
    """T2: --since-ms/--dispatch-id reach both phases' records verbatim."""
    _write_contract(tmp_path, clause_ids=[])
    gate_before("fixer", "[contract: c] work", tmp_path,
                since_ms=1727600000123, dispatch_id=_DISPATCH)
    rec = _records(tmp_path)[-1]
    assert rec["since_ms"] == 1727600000123
    assert rec["dispatch_id"] == _DISPATCH
    gate_after("fixer", "[contract: c]", tmp_path,
               since_ms=1727600000456, dispatch_id=_DISPATCH)
    rec = _records(tmp_path)[-1]
    assert rec["since_ms"] == 1727600000456
    assert rec["dispatch_id"] == _DISPATCH


def test_taskgate_record_backward_compat(tmp_path):
    """T6: without the instrumentation flags the records carry exactly the
    v2 key set — a hand-run `zft task-gate ...` must stay byte-compatible."""
    _write_contract(tmp_path, clause_ids=[])
    gate_before("fixer", "[contract: c] work", tmp_path)
    rec = _records(tmp_path)[-1]
    assert set(rec) == _V2_BEFORE_KEYS
    gate_after("fixer", "[contract: c]", tmp_path)
    rec = _records(tmp_path)[-1]
    assert set(rec) == _V2_AFTER_KEYS


def test_taskgate_partial_instrumentation_stamps_gate_ms(tmp_path):
    """Only one of the two identity fields supplied: keys stay additive —
    whatever was supplied appears, gate_ms stamps, the other key stays
    absent (present iff supplied, prereg §1.3)."""
    _write_contract(tmp_path, clause_ids=[])
    gate_before("fixer", "[contract: c] work", tmp_path, since_ms=7)
    rec = _records(tmp_path)[-1]
    assert rec["since_ms"] == 7
    assert "dispatch_id" not in rec
    assert isinstance(rec["gate_ms"], int) and rec["gate_ms"] >= 0


def test_cli_taskgate_new_flags(tmp_path, monkeypatch, capsys):
    """T3: the CLI parses --since-ms/--dispatch-id and threads them into the
    records; the usage line names both flags; a malformed --since-ms is a
    usage error (exit 2), never a silent drop."""
    from zft.cli import main as cli_main
    _write_contract(tmp_path, clause_ids=[])
    monkeypatch.chdir(tmp_path)
    assert cli_main.main(["task-gate", "help"]) == 2
    usage = capsys.readouterr().out
    assert "--since-ms" in usage
    assert "--dispatch-id" in usage
    argv = ["task-gate", "before", "--subagent", "fixer",
            "--description", "[contract: c] work",
            "--since-ms", "1727600000123", "--dispatch-id", _DISPATCH]
    assert cli_main.main(argv) == 0
    rec = _records(tmp_path)[-1]
    assert rec["since_ms"] == 1727600000123
    assert rec["dispatch_id"] == _DISPATCH
    assert isinstance(rec["gate_ms"], int) and rec["gate_ms"] >= 0
    argv = ["task-gate", "after", "--subagent", "fixer",
            "--description", "[contract: c]",
            "--since-ms", "1727600000456", "--dispatch-id", _DISPATCH]
    assert cli_main.main(argv) == 0
    rec = _records(tmp_path)[-1]
    assert rec["since_ms"] == 1727600000456
    assert rec["dispatch_id"] == _DISPATCH
    argv = ["task-gate", "before", "--subagent", "fixer",
            "--description", "[contract: c] work",
            "--since-ms", "not-an-int"]
    assert cli_main.main(argv) == 2
    assert "since-ms" in capsys.readouterr().err
