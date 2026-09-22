"""C-41 / R-01: structured gate findings with deny/warn tiers (OPA convention).

Golden shape pinned by tests/golden/findings.json: a finding is a fixed
six-key dict {alias, code, file, hint, msg, severity}; rules accumulate
(never first-exit); denies block the gate, warns publish as advisories.
`lint_store` keeps its legacy seam — rendered DENY strings only.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from zft.spec.canon import canonical_hash
from zft.spec.findings import DENY, WARN, Finding, partition, render_finding
from zft.spec.lint import collect_findings, lint_store

REPO = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((REPO / "tests" / "golden" / "findings.json").read_text())


# --- store fixtures -----------------------------------------------------------

def _valid_node(alias: str, status: str, title: str, seq: int) -> dict:
    node = {
        "node_id": f"018f3a2b-9e41-7100-8000-00000000000{seq}",
        "alias": alias,
        "domain": "g",
        "title": title,
        "status": status,
        "version": 1,
        "content_hash": "",
        "invariants": [{"id": f"{alias}-INV-01", "statement": "WHEN a THE SYSTEM SHALL b",
                        "property": "forall x: ok(x)", "check": {"kind": "test"}}],
        "external_links": [],
    }
    node["content_hash"] = canonical_hash(node)
    return node


def _seed_composite_store(tmp_path: Path) -> Path:
    """One schema-deny node + one DRAFT warn + one DEPRECATED warn."""
    spec_dir = tmp_path / ".zft" / "specs" / "g"
    spec_dir.mkdir(parents=True)
    bad = _valid_node("G-BAD", "VALIDATED", "t", 0)
    del bad["title"]  # exactly one schema error: 'title' is a required property
    (spec_dir / "bad-clause.json").write_text(json.dumps(bad))
    (spec_dir / "good-clause.json").write_text(
        json.dumps(_valid_node("G-ONE", "DRAFT", "alpha", 1)))
    (spec_dir / "z-clause.json").write_text(
        json.dumps(_valid_node("G-TWO", "DEPRECATED", "beta", 2)))
    return tmp_path


# --- Finding value semantics --------------------------------------------------

def test_finding_rejects_unknown_severity():
    with pytest.raises(ValueError, match="severity"):
        Finding(code="X", severity="fatal", msg="m")


def test_finding_rejects_non_str_code_and_empty_msg():
    with pytest.raises(TypeError, match="code"):
        Finding(code=7, severity=DENY, msg="m")
    with pytest.raises(ValueError, match="message"):
        Finding(code="X", severity=WARN, msg="  ")


def test_to_dict_is_fixed_six_key_shape():
    f = Finding(code="R", severity=WARN, msg="m", hint="h", alias="A-1", file="a.json")
    assert f.to_dict() == {"alias": "A-1", "code": "R", "file": "a.json",
                           "hint": "h", "msg": "m", "severity": "warn"}
    bare = Finding(code="R", severity=DENY, msg="m")
    assert bare.to_dict() == {"alias": None, "code": "R", "file": None,
                              "hint": "", "msg": "m", "severity": "deny"}


def test_render_prefers_file_location_and_appends_hint():
    f = Finding(code="R", severity=DENY, msg="m", hint="do x", file="a.json")
    assert render_finding(f) == "a.json: m\n  hint: do x"
    assert render_finding(Finding(code="R", severity=DENY, msg="m")) == "m"


def test_partition_splits_by_severity():
    d = Finding(code="D", severity=DENY, msg="m")
    w = Finding(code="W", severity=WARN, msg="m")
    denies, warns = partition([w, d, w])
    assert denies == [d] and warns == [w, w]


# --- golden: shape, catalog, composite case ------------------------------------

def test_golden_shape_contract():
    assert GOLDEN["shape"]["keys"] == ["alias", "code", "file", "hint", "msg", "severity"]
    assert GOLDEN["shape"]["severities"] == [DENY, WARN]
    codes = [r["code"] for r in GOLDEN["rules"]]
    assert len(codes) == len(set(codes)), "rule codes must be unique"
    severities = {r["code"]: r["severity"] for r in GOLDEN["rules"]}
    assert severities["CLAUSE_STATUS_DRAFT"] == WARN
    assert severities["STORE_NODE_SCHEMA"] == DENY


def test_golden_composite_store_matches_fixture(tmp_path):
    """The shape proof: real lint run over a real store == golden, byte-shape for byte-shape."""
    root = _seed_composite_store(tmp_path)
    case = GOLDEN["cases"][0]
    assert [f.to_dict() for f in collect_findings(root)] == case["expected_findings"]
    assert lint_store(root) == case["expected_lint_store"]


def test_emitted_codes_and_severities_stay_within_golden_catalog(tmp_path):
    """Any new rule must enter the golden catalog — shape drift fails here."""
    catalog = {r["code"]: r["severity"] for r in GOLDEN["rules"]}
    emitted = collect_findings(_seed_composite_store(tmp_path))
    emitted += collect_findings(tmp_path / "nonexistent-root")
    for f in emitted:
        assert f.code in catalog, f"uncatalogued rule {f.code}"
        assert f.severity == catalog[f.code], f"{f.code} severity drifted"


def test_lint_store_warn_only_store_stays_green(tmp_path):
    """Warns are advisory: the legacy denies-only seam must not see them."""
    spec_dir = tmp_path / ".zft" / "specs" / "g"
    spec_dir.mkdir(parents=True)
    (spec_dir / "good-clause.json").write_text(
        json.dumps(_valid_node("G-ONE", "DRAFT", "alpha", 1)))
    assert lint_store(tmp_path) == []
    warns = collect_findings(tmp_path)
    assert len(warns) == 1 and warns[0].code == "CLAUSE_STATUS_DRAFT"


# --- run_l0: denies block, warns publish ----------------------------------------

def test_run_l0_warn_only_store_is_green_with_published_warnings(tmp_path):
    from zft.debug.ledger import RunLedger
    from zft.gates.l0 import run_l0

    root = tmp_path / "store"
    spec_dir = root / ".zft" / "specs" / "g"
    spec_dir.mkdir(parents=True)
    (spec_dir / "good-clause.json").write_text(
        json.dumps(_valid_node("G-ONE", "DRAFT", "alpha", 1)))
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L0"}, repo=tmp_path)
    verdict = run_l0(root, ledger=led)
    led.close()
    assert verdict.ok is True
    assert verdict.failures == []
    assert verdict.rejection is None
    golden_warns = [f for f in GOLDEN["cases"][0]["expected_findings"]
                    if f["severity"] == WARN]
    assert verdict.warnings == [golden_warns[0]]
    record = RunLedger.load(tmp_path / "runs", led.run_id)
    ev = record.events[-1]
    assert ev["event"] == "l0" and ev["ok"] is True
    assert ev["warnings"] == verdict.warnings


def test_run_l0_deny_blocks_and_still_publishes_warns(tmp_path):
    from zft.debug.ledger import RunLedger
    from zft.gates.l0 import run_l0

    root = _seed_composite_store(tmp_path)
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L0"}, repo=tmp_path)
    verdict = run_l0(root, ledger=led)
    led.close()
    case = GOLDEN["cases"][0]
    assert verdict.ok is False
    assert verdict.failures == case["expected_lint_store"]
    assert verdict.rejection["code"] == "L0_STORE_INTEGRITY"
    assert verdict.rejection["actual"] == verdict.failures
    assert verdict.warnings == [f for f in case["expected_findings"]
                                if f["severity"] == WARN]
    record = RunLedger.load(tmp_path / "runs", led.run_id)
    ev = record.events[-1]
    assert ev["warnings"] == verdict.warnings
    assert ev["failures"] == verdict.failures


# --- gate log publication (L3 projection) ----------------------------------------

def test_gate_log_publishes_l0_warnings_only_when_provided():
    from zft.gates.l3 import build_gate_log

    events = [{"event": "l0", "ok": True}]
    legacy = build_gate_log(events, producer_model="p", gate_model="g",
                            judge_excluded=[], deterministic_coverage="1/1")
    assert "l0_warnings" not in legacy  # legacy projection unchanged
    warns = [{"alias": "A-1", "code": "CLAUSE_STATUS_DRAFT", "file": "a.json",
              "hint": "h", "msg": "m", "severity": "warn"}]
    published = build_gate_log(events, producer_model="p", gate_model="g",
                               judge_excluded=[], deterministic_coverage="1/1",
                               l0_warnings=warns)
    assert published["l0_warnings"] == warns


# --- CLI seams -------------------------------------------------------------------

def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "zft.cli.main", *args],
                          capture_output=True, text=True)


def test_cli_lint_warn_only_exits_zero_and_shows_warning(tmp_path):
    spec_dir = tmp_path / ".zft" / "specs" / "g"
    spec_dir.mkdir(parents=True)
    (spec_dir / "good-clause.json").write_text(
        json.dumps(_valid_node("G-ONE", "DRAFT", "alpha", 1)))
    r = _cli("lint", str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "L0 PASSED" in r.stdout
    assert "1 warning(s)" in r.stdout
    assert "⚠" in r.stdout and "CLAUSE_STATUS_DRAFT" not in r.stdout  # code is internal; msg shows


def test_cli_lint_deny_exits_one_and_warns_still_reported(tmp_path):
    root = _seed_composite_store(tmp_path)
    r = _cli("lint", str(root))
    assert r.returncode == 1
    assert "L0 FAILED — 1 error(s), 2 warning(s)" in r.stdout
    assert "✗" in r.stdout and "⚠" in r.stdout


def test_check_pipeline_publishes_l0_warnings():
    r = _cli("check", str(REPO))
    assert r.returncode == 0, r.stdout + r.stderr
    assert '"l0_warnings": []' in r.stdout  # real store is all-VALIDATED: no warns today
