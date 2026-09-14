"""C-21: L0 gate — lint failures as ledger events with typed rejection shape."""

from traceagent.debug.ledger import RunLedger
from traceagent.gates.l0 import run_l0


def test_l0_green_on_own_store(tmp_path):
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    led = RunLedger.start(tmp_path, manifest={"stage": "L0"}, repo=repo)
    verdict = run_l0(repo, ledger=led)
    led.close()
    assert verdict.ok is True
    assert verdict.failures == []
    record = RunLedger.load(tmp_path, led.run_id)
    assert record.events[-1]["event"] == "l0" and record.events[-1]["ok"] is True


# GATE-MUTATION-KILL: l0.py rejection = None -> "" on the green path survived
# the campaign: a green verdict carries no rejection, typed as None
def test_l0_green_verdict_rejection_is_none(tmp_path):
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    verdict = run_l0(repo)
    assert verdict.ok is True
    assert verdict.rejection is None


# @trace("CON-TYPED-REJECTIONS")
def test_l0_failure_is_typed(tmp_path):
    import subprocess

    subprocess.run(
        ["cp", "-r", str(tmp_path), str(tmp_path) + "_x"], capture_output=True
    )  # no-op to keep tmp fixture simple
    empty = tmp_path / "empty"
    empty.mkdir()
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L0"}, repo=tmp_path)
    verdict = run_l0(empty, ledger=led)
    led.close()
    assert verdict.ok is False
    assert verdict.rejection["fault"] == "implementation"
    assert verdict.rejection["code"] == "L0_STORE_INTEGRITY"
    record = RunLedger.load(tmp_path / "runs", led.run_id)
    assert record.events[-1]["event"] == "l0" and record.events[-1]["ok"] is False


def test_l0_crash_degrades_to_red_not_raise(tmp_path):
    # a corrupt contract file makes lint_store itself raise — L0 must report, not crash
    import json

    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": "L0-CRASH-01", "domain": "g", "title": "t",
        "status": "VALIDATED", "version": 1, "content_hash": "0" * 64,
        "invariants": [], "external_links": [],
    }
    (spec / "l0-crash-01.json").write_text(json.dumps(node))
    contracts = tmp_path / ".zft" / "contracts"
    contracts.mkdir()
    (contracts / "broken.json").write_text("{not json")
    verdict = run_l0(tmp_path)
    assert verdict.ok is False
    assert any("integrity check crashed" in f for f in verdict.failures)
    assert verdict.rejection["code"] == "L0_STORE_INTEGRITY"
    # GATE-MUTATION-KILL: the crash finding's rendered text is contractual —
    # msg prefix plus the byte-exact hint line (dropped/cased/bracketed hint
    # text must fail here)
    crash = next(f for f in verdict.failures
                 if f.startswith("integrity check crashed ("))
    assert crash.endswith(
        "\n  hint: inspect the store/contract files; lint must not crash silently")


# GATE-MUTATION-KILL: l0.py stage-label mutations (stage=None/"XXL0XX"/"l0"),
# rejection dict-key mutations ("XXclause_idsXX", "XXexpectedXX", "XXactualXX",
# "XXevidence_refsXX") and ledger-key mutations ("XXfailuresXX") survived the
# 2026-09-05 campaign: the typed verdict shape is contractual
def test_l0_verdict_and_rejection_shape_are_contractual(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L0"}, repo=tmp_path)
    verdict = run_l0(empty, ledger=led)
    led.close()
    assert verdict.ok is False
    assert verdict.stage == "L0"
    assert verdict.rejection == {
        "code": "L0_STORE_INTEGRITY",
        "clause_ids": [],
        "fault": "implementation",
        "expected": "schema-valid, hash-consistent clause store",
        "actual": verdict.failures,
        "evidence_refs": [],
    }
    record = RunLedger.load(tmp_path / "runs", led.run_id)
    ev = record.events[-1]
    assert ev["event"] == "l0" and ev["ok"] is False
    assert ev["failures"] == verdict.failures
