"""C-25/C-26/C-27: L2 orchestration, repro, L3 stub + model labeling."""
import json

from traceagent.debug.ledger import RunLedger
from traceagent.gates.l2 import run_l2
from traceagent.gates.l3 import build_gate_log


def _seed(tmp_path):
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    tests = tmp_path / "tests"
    tests.mkdir()
    node_bound = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": "GATE-INV-01", "domain": "g", "title": "expired",
        "status": "VALIDATED", "version": 1, "content_hash": "0" * 64,
        "invariants": [{"id": "GATE-INV-01", "statement": "WHEN expired THE SYSTEM SHALL reject",
                        "property": "forall t: expired(t) => validate(t) == err('Unauthorized')",
                        "check": {"kind": "property"}}],
        "external_links": [],
    }
    (spec / "gate-inv-01.json").write_text(json.dumps(node_bound))
    judge = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000002",
        "alias": "GATE-STYLE-01", "domain": "g", "title": "style",
        "status": "VALIDATED", "version": 1, "content_hash": "1" * 64,
        "invariants": [{"id": "GATE-STYLE-01", "statement": "THE SYSTEM SHALL look nice",
                        "property": "aesthetic(code) == HIGH",
                        "check": {"kind": "judge", "notes": "subjective"}}],
        "external_links": [],
    }
    (spec / "gate-style-01.json").write_text(json.dumps(judge))
    (tests / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\n'
        "def test_bound():\n    assert True\n"
    )
    (tmp_path / "oracle_GATE-INV-01.py").write_text("def expired(t):\n    return t > 100\n")
    return tmp_path


# @trace("GATE-JUDGE-QUARANTINE")
def test_l2_fast_green_on_mini_repo(tmp_path):
    root = _seed(tmp_path)
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L2-fast"}, repo=root)
    verdict = run_l2(root, tier="fast", ledger=led)
    led.close()
    assert verdict.ok, verdict.rejection
    assert verdict.coverage["coverage"] == "1/2", "judge-gated clause excluded from deterministic coverage"  # noqa: E501
    assert verdict.coverage["judge_excluded"] == ["GATE-STYLE-01"]


def test_l2_uncovered_clause_fails_with_names(tmp_path):
    root = _seed(tmp_path)
    # drop the binding so GATE-INV-01 is uncovered
    (root / "tests" / "test_bound.py").unlink()
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L2-fast"}, repo=root)
    verdict = run_l2(root, tier="fast", ledger=led)
    led.close()
    assert verdict.ok is False
    assert verdict.rejection["clause_ids"] == ["GATE-INV-01"]


# GATE-MUTATION-KILL: l2.py uncovered = sorted(...) -> uncovered = None survived
# the mutmut 3.7 campaign (2026-09-05): L1's red masks verdict.ok, so the
# uncovered rejection itself must be asserted
def test_l2_uncovered_rejection_names_gap_and_blames_contract(tmp_path):
    root = _seed(tmp_path)
    (root / "tests" / "test_bound.py").unlink()
    verdict = run_l2(root, tier="fast")
    assert any(f.startswith("uncovered clauses") for f in verdict.failures), verdict.failures
    assert verdict.rejection["fault"] == "contract"


# GATE-MUTATION-KILL: l2.py `if not l1_verdict.ok:` -> `if l1_verdict.ok:`
# survived the campaign: an L1 red with clean coverage must still red L2
def test_l2_extends_failures_when_l1_red(tmp_path):
    root = _seed(tmp_path)
    (root / "tests" / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\n'
        "def test_bound():\n    assert False\n"
    )
    verdict = run_l2(root, tier="fast")
    assert verdict.ok is False
    assert any("GATE-INV-01: bound suite failed" in f for f in verdict.failures)
    assert verdict.rejection["clause_ids"] == ["GATE-INV-01"]


def test_repro_reruns_failed_units(tmp_path):
    root = _seed(tmp_path)
    (root / "tests" / "test_bound.py").unlink()
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L2-fast"}, repo=root)
    v1 = run_l2(root, tier="fast", ledger=led)
    led.close()
    assert v1.ok is False

    # restore, repro must re-execute and recover
    (root / "tests" / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\ndef test_bound():\n    assert True\n')
    from traceagent.debug.repro import repro

    result = repro(root, tmp_path / "runs", led.run_id)
    assert result.recovered is True


# @trace("GATE-MODEL-INDEPENDENCE")
def test_gate_log_labels_model_dependence():
    events = [
        {"event": "l0", "ok": True},
        {"event": "l1_clause", "alias": "A", "ok": True},
    ]
    same = build_gate_log(events, producer_model="m", gate_model="m",
                          judge_excluded=[], deterministic_coverage="5/6")
    assert same["model_dependent"] is True
    diff = build_gate_log(events, producer_model="m", gate_model="g",
                          judge_excluded=[], deterministic_coverage="5/6")
    assert diff["model_dependent"] is False


def test_gate_log_skips_malformed_events():
    events = [
        {"event": "run_start"},  # no ok — used to KeyError the projection
        None,
        {"event": "l0", "ok": True},
    ]
    log = build_gate_log(events, producer_model="m", gate_model="g",
                         judge_excluded=[], deterministic_coverage="1/1")
    assert log["stages"] == {"l0": True}


def test_l2_corrupt_store_degrades_to_red(tmp_path):
    root = _seed(tmp_path)
    (root / ".zft" / "specs" / "g" / "gate-inv-01.json").write_text("{broken")
    verdict = run_l2(root, tier="fast")
    assert verdict.ok is False
    assert any("evidence collection failed" in f for f in verdict.failures)
    assert verdict.rejection["code"] == "L2_ACCEPTANCE"


def _add_deferred_clause(root, alias="GATE-DEFER-01"):
    spec = root / ".zft" / "specs" / "g"
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000003",
        "alias": alias, "domain": "g", "title": "deferred impact query",
        "status": "VALIDATED", "version": 1, "content_hash": "3" * 64,
        "invariants": [{"id": alias, "statement": "WHEN queried THE SYSTEM SHALL trace",
                        "check": {"kind": "manual"}}],
        "external_links": [],
    }
    (spec / "gate-defer-01.json").write_text(json.dumps(node))


# GATE-MUTATION-KILL: l2.py deferred.get(alias, milestone) ->
# deferred.get(None, milestone) survived the campaign: a clause deferred to a
# later milestone (contract meta.target_milestone) must be exempt from coverage
def test_l2_deferred_clause_is_not_due(tmp_path):
    root = _seed(tmp_path)
    _add_deferred_clause(root)
    (root / ".zft" / "contracts").mkdir()
    (root / ".zft" / "contracts" / "contract.json").write_text(json.dumps({
        "meta": {"current_milestone": "v0",
                 "target_milestone": {"GATE-DEFER-01": "v0.1"}}}))
    verdict = run_l2(root, tier="fast")
    assert verdict.ok, verdict.failures
    assert all("GATE-DEFER-01" not in f for f in verdict.failures)


# GATE-MUTATION-KILL: l2.py run_l1(root, ledger=ledger) -> ledger=None
# survived the campaign: the embedded L1 run must record its summary and
# clause events into the shared ledger
def test_l2_ledger_receives_l1_events(tmp_path):
    root = _seed(tmp_path)
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L2-fast"}, repo=root)
    verdict = run_l2(root, tier="fast", ledger=led)
    led.close()
    assert verdict.ok, verdict.failures
    record = RunLedger.load(tmp_path / "runs", led.run_id)
    assert any(e["event"] == "l1" for e in record.events), \
        "embedded L1 summary must reach the shared ledger"
    assert any(e["event"] == "l1_clause" and e.get("alias") == "GATE-INV-01"
               for e in record.events)


def _write_contract(root, meta):
    contracts = root / ".zft" / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    (contracts / "contract.json").write_text(json.dumps({"meta": meta}))


def test_l2_reverse_coverage_configured_slice(tmp_path):
    """meta.element_roots makes the declared-universe direction live: bound
    elements count as justified, unbound ones are listed out-of-contract.
    The baseline direction is still inert here (no baseline seeded) and says
    so — that warning is the only one."""
    root = _seed(tmp_path)
    (root / "tests" / "test_unbound.py").write_text("def test_free():\n    assert True\n")
    _write_contract(root, {"element_roots": ["tests"]})
    verdict = run_l2(root, tier="fast")
    assert verdict.ok, verdict.rejection
    assert len(verdict.warnings) == 1
    assert "TR-REVERSE-COVERAGE baseline absent" in verdict.warnings[0]
    assert verdict.coverage["elements_total"] == 2
    assert verdict.coverage["elements_justified"] == 1
    assert verdict.coverage["out_of_contract"] == ["tests/test_unbound.py"]


def test_l2_reverse_coverage_unconfigured_warns_vacuous(tmp_path):
    """No element_roots: the 0/0 report must warn, not pose as complete."""
    root = _seed(tmp_path)
    verdict = run_l2(root, tier="fast")
    assert verdict.ok, "the vacuous direction warns; it does not red the gate"
    assert len(verdict.warnings) == 2, (
        "both inert directions speak: unconfigured universe + absent baseline")
    assert "TR-REVERSE-COVERAGE vacuous" in verdict.warnings[0]
    assert "element_roots" in verdict.warnings[0]
    assert "TR-REVERSE-COVERAGE baseline absent" in verdict.warnings[1]
    assert verdict.coverage["elements_total"] == 0
    assert verdict.coverage["elements_justified"] == 0


def test_l2_reverse_coverage_configured_but_empty_warns(tmp_path):
    """Configured roots that match no deliverable files warn, naming the roots."""
    root = _seed(tmp_path)
    _write_contract(root, {"element_roots": ["tests/absent", "docs"]})
    verdict = run_l2(root, tier="fast")
    assert verdict.ok
    assert len(verdict.warnings) == 2
    assert "matched no deliverable files" in verdict.warnings[0]
    assert "tests/absent" in verdict.warnings[0]
    assert "TR-REVERSE-COVERAGE baseline absent" in verdict.warnings[1]
