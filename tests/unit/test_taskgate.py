"""ENF task gate: writer-lane contract enforcement, read-only exemption,
post-task coverage verdict, audited decisions."""
import json
import subprocess
from pathlib import Path

from traceagent.taskgate import gate_after, gate_before

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
        [str(Path(__import__("sys").executable).parent / "traceagent"), "create",
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
    from traceagent.taskgate import classify

    for name in ("Explore", "explore", "Vision", "RESEARCHER", "code-explorer"):
        assert classify(name) == "readonly", name
    assert classify("implementer") == "writer"
    assert classify("general-purpose") == "writer"
