"""zft metrics — read-only statistics over .zft/runs ledgers.

Pins the run-summary shape, crash-class taxonomy, flake detection,
coverage trends, per-window/per-commit breakdowns, timing percentiles,
JSONL tail mode, and the read-only guarantee. All ledgers here are
synthesized through the real RunLedger writer so the reader is tested
against the exact bytes the gates produce.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from io import StringIO
from pathlib import Path

import pytest

from zft.debug.ledger import RunLedger
from zft.debug.metrics import aggregate, dora, scan_runs, tail_runs

# ---------------------------------------------------------------- helpers

def make_run(runs_root: Path, stage="check", events=(), commit="a" * 40,
             dirty=True, tier="fast", mtime=None, torn_tail=False) -> str:
    """One synthesized run through the real writer; returns the run_id."""
    led = RunLedger.start(runs_root, {"stage": stage, "tier": tier,
                                      "git_commit": commit, "dirty": dirty},
                          repo=None)
    for ev in events:
        led.append(ev)
    led.close()
    if torn_tail:  # simulate a torn mid-write: partial last line, no newline
        p = led.dir / "events.jsonl"
        with open(p, "ab") as fh:
            fh.write(b'{"event": "l1", "ok": tru')
    run_id = led.run_id
    if mtime is not None:
        os.utime(led.dir / "manifest.json", (mtime - 5, mtime - 5))
        os.utime(led.dir / "events.jsonl", (mtime, mtime))
    return run_id


def l1_clause(alias, ok=True, cached=False, duration_ms=None, reason=None):
    ev = {"event": "l1_clause", "alias": alias, "cached": cached, "ok": ok}
    if duration_ms is not None:
        ev["duration_ms"] = duration_ms
    if reason is not None:
        ev["reason"] = reason
    return ev


DAY1 = 1789938000.0  # some fixed epoch second
DAY2 = DAY1 + 86400


# ------------------------------------------------------------ run summary

def test_healthy_check_run_is_complete(tmp_path):
    make_run(tmp_path / "runs", stage="check", events=[
        {"event": "l0", "ok": True, "failures": [], "warnings": []},
        l1_clause("A", ok=True),
        {"event": "l1", "executed": 1, "failures": [], "ok": True},
        {"event": "l2", "ok": True, "failures": [], "tier": "fast",
         "coverage": {"coverage_ratio": 1.0}, "warnings": []},
    ])
    runs = scan_runs(tmp_path / "runs")
    r = runs[0]
    assert r["stage"] == "check"
    assert r["terminal"] == "l2"
    assert r["complete"] is True
    assert r["crashed"] is False
    assert r["crash_class"] is None
    assert r["ok"] is True
    assert r["coverage_ratio"] == 1.0


def test_crash_class_check_died_after_l1(tmp_path):
    make_run(tmp_path / "runs", stage="check", events=[
        {"event": "l0", "ok": True, "failures": [], "warnings": []},
        l1_clause("A", ok=True),
        {"event": "l1", "executed": 1, "failures": [], "ok": True},
    ])
    r = scan_runs(tmp_path / "runs")[0]
    assert r["complete"] is False
    assert r["crashed"] is True
    assert r["crash_class"] == "died-after-l1"


def test_crash_class_l2fast_died_mid_campaign(tmp_path):
    make_run(tmp_path / "runs", stage="L2-fast", events=[
        {"event": "mutant_verdict", "name": "m1", "ok": False,
         "in_scope": True, "timed_out": False, "duration_ms": 100},
    ])
    r = scan_runs(tmp_path / "runs")[0]
    assert r["crashed"] is True
    assert r["crash_class"] == "died-mid-campaign"


def test_crash_class_empty_run(tmp_path):
    make_run(tmp_path / "runs", stage="L2-fast", events=[])
    r = scan_runs(tmp_path / "runs")[0]
    assert r["crashed"] is True
    assert r["crash_class"] == "died-before-first-event"


def test_l0_rejection_is_clean_fail_not_crash(tmp_path):
    make_run(tmp_path / "runs", stage="check", events=[
        {"event": "l0", "ok": False, "failures": ["bad spec"], "warnings": []},
    ])
    r = scan_runs(tmp_path / "runs")[0]
    assert r["crashed"] is False
    assert r["ok"] is False
    assert r["crash_class"] is None
    assert r["rejected"] is True


def test_negotiate_completed_not_crash(tmp_path):
    make_run(tmp_path / "runs", stage="negotiate", events=[
        {"event": "cfp", "contract": "x", "clauses": 3},
        {"event": "validated", "version": 2},
    ])
    r = scan_runs(tmp_path / "runs")[0]
    assert r["complete"] is True
    assert r["crashed"] is False


def test_unknown_stage_never_classified_crash(tmp_path):
    make_run(tmp_path / "runs", stage="mystery", events=[{"event": "x"}])
    r = scan_runs(tmp_path / "runs")[0]
    assert r["crashed"] is False
    assert r["crash_class"] == "unknown-stage"


def test_torn_tail_counted_not_parsed(tmp_path):
    make_run(tmp_path / "runs", stage="check", events=[
        {"event": "l0", "ok": True, "failures": [], "warnings": []},
        {"event": "l2", "ok": True, "failures": [], "tier": "fast",
         "coverage": {"coverage_ratio": 1.0}, "warnings": []},
    ], torn_tail=True)
    r = scan_runs(tmp_path / "runs")[0]
    assert r["torn_lines"] == 1
    assert r["terminal"] == "l2"  # the torn fragment is not a terminal
    assert r["complete"] is True


def test_duration_from_manifest_to_events_mtime(tmp_path):
    make_run(tmp_path / "runs", mtime=DAY1)
    r = scan_runs(tmp_path / "runs")[0]
    assert r["duration_ms"] == pytest.approx(5000, abs=1)
    assert r["ts"] == pytest.approx(DAY1, abs=0.001)


# -------------------------------------------------------------- aggregate

def test_aggregate_stage_and_crash_histogram(tmp_path):
    make_run(tmp_path / "runs", stage="check", events=[
        {"event": "l2", "ok": True, "failures": [], "tier": "fast",
         "coverage": {"coverage_ratio": 1.0}, "warnings": []}], mtime=DAY1)
    make_run(tmp_path / "runs", stage="check", events=[
        {"event": "l1", "ok": True}], mtime=DAY1 + 60)
    make_run(tmp_path / "runs", stage="L2-fast", events=[], mtime=DAY2)
    rep = aggregate(scan_runs(tmp_path / "runs"))
    assert rep["n_runs"] == 3
    assert rep["stages"]["check"]["runs"] == 2
    assert rep["stages"]["check"]["crashed"] == 1
    assert rep["stages"]["L2-fast"]["crashed"] == 1
    assert rep["crash_classes"] == {"died-after-l1": 1,
                                    "died-before-first-event": 1}
    assert rep["span"]["first"] == pytest.approx(DAY1, abs=0.001)
    assert rep["span"]["last"] == pytest.approx(DAY2, abs=0.001)


def test_flake_mixed_outcome_alias(tmp_path):
    make_run(tmp_path / "runs", commit="c1" * 20, events=[
        l1_clause("FLAKY", ok=True), l1_clause("SOLID", ok=True),
    ], mtime=DAY1)
    make_run(tmp_path / "runs", commit="c1" * 20, events=[
        l1_clause("FLAKY", ok=False, reason="timeout"),
        l1_clause("SOLID", ok=True),
        l1_clause("ONLYFAIL", ok=False),
    ], mtime=DAY1 + 60)
    make_run(tmp_path / "runs", commit="c2" * 20, events=[
        l1_clause("FLAKY", ok=True),  # passes on c2: mixed overall, not in-commit
    ], mtime=DAY2)
    rep = aggregate(scan_runs(tmp_path / "runs"))
    flaky = rep["flake"]["aliases"]
    assert flaky["FLAKY"] == {"pass": 2, "fail": 1}
    assert "SOLID" not in flaky
    assert "ONLYFAIL" not in flaky  # always-fail is broken, not flaky
    assert rep["flake"]["n_flaky"] == 1
    assert rep["flake"]["by_commit"]["c1" * 20] == ["FLAKY"]
    assert rep["flake"]["by_commit"]["c2" * 20] == []


def test_cached_clause_outcomes_do_not_count_as_flake_evidence(tmp_path):
    make_run(tmp_path / "runs", events=[l1_clause("A", ok=True, cached=True)],
             mtime=DAY1)
    make_run(tmp_path / "runs", events=[l1_clause("A", ok=False, cached=True)],
             mtime=DAY1 + 60)
    rep = aggregate(scan_runs(tmp_path / "runs"))
    assert rep["flake"]["n_flaky"] == 0  # cache replay ≠ execution evidence


def test_coverage_trend_per_window(tmp_path):
    for ratio, ts in ((0.5, DAY1), (0.75, DAY1 + 60), (1.0, DAY2)):
        make_run(tmp_path / "runs", events=[
            {"event": "l2", "ok": True, "failures": [], "tier": "fast",
             "coverage": {"coverage_ratio": ratio}, "warnings": []}],
            mtime=ts)
    rep = aggregate(scan_runs(tmp_path / "runs"), window="day")
    trend = {t["window"]: t for t in rep["coverage"]["trend"]}
    d1 = rep["windows"][0]["window"]
    d2 = rep["windows"][1]["window"]
    assert trend[d1]["coverage_mean"] == pytest.approx(0.625)
    assert trend[d1]["coverage_min"] == pytest.approx(0.5)
    assert trend[d2]["coverage_max"] == pytest.approx(1.0)
    assert rep["coverage"]["overall"]["first"] == pytest.approx(0.5)
    assert rep["coverage"]["overall"]["last"] == pytest.approx(1.0)


def test_windows_bucket_runs_per_day(tmp_path):
    make_run(tmp_path / "runs", events=[], mtime=DAY1)
    make_run(tmp_path / "runs", events=[], mtime=DAY1 + 60)
    make_run(tmp_path / "runs", events=[], mtime=DAY2)
    rep = aggregate(scan_runs(tmp_path / "runs"), window="day")
    assert [w["runs"] for w in rep["windows"]] == [2, 1]


def test_per_repo_breakdown(tmp_path):
    make_run(tmp_path / "runs", commit="c1" * 20, events=[
        {"event": "l2", "ok": True, "failures": [], "tier": "fast",
         "coverage": {"coverage_ratio": 1.0}, "warnings": []}], mtime=DAY1)
    make_run(tmp_path / "runs", commit="c2" * 20, events=[
        {"event": "l1", "ok": True}], mtime=DAY2)
    rep = aggregate(scan_runs(tmp_path / "runs"))
    assert rep["repos"]["c1" * 20]["runs"] == 1
    assert rep["repos"]["c1" * 20]["ok"] == 1
    assert rep["repos"]["c2" * 20]["crashed"] == 1


def test_timing_percentiles_from_clause_and_mutant_events(tmp_path):
    make_run(tmp_path / "runs", events=[
        l1_clause("A", duration_ms=100), l1_clause("B", duration_ms=200),
        l1_clause("C", duration_ms=300), l1_clause("D", cached=True),
        {"event": "mutant_verdict", "name": "m", "ok": True,
         "in_scope": True, "timed_out": False, "duration_ms": 800},
    ], mtime=DAY1)
    rep = aggregate(scan_runs(tmp_path / "runs"))
    t = rep["timing"]["l1_clause_ms"]
    assert t["p50"] == 200 and t["p90"] == 300 and t["max"] == 300
    assert t["cached_share"] == pytest.approx(0.25)
    assert rep["timing"]["mutant_ms"]["p50"] == 800


def test_gate_pass_fail_counts(tmp_path):
    make_run(tmp_path / "runs", events=[
        {"event": "l0", "ok": True, "failures": [], "warnings": []},
        {"event": "l2", "ok": True, "failures": [], "tier": "fast",
         "coverage": {"coverage_ratio": 1.0}, "warnings": []}], mtime=DAY1)
    make_run(tmp_path / "runs", events=[
        {"event": "l0", "ok": False, "failures": ["x"], "warnings": []}],
        mtime=DAY1 + 60)
    make_run(tmp_path / "runs", stage="L2-fast", events=[
        {"event": "campaign_summary", "ok": True, "total": 5, "killed": 5,
         "in_scope_killed": 1, "in_scope_total": 1, "resumed": 0,
         "timed_out": 0}], mtime=DAY1 + 120)
    rep = aggregate(scan_runs(tmp_path / "runs"))
    assert rep["gates"]["l0"] == {"pass": 1, "fail": 1}
    assert rep["gates"]["l2"] == {"pass": 1, "fail": 0}
    assert rep["gates"]["campaign"] == {"pass": 1, "fail": 0}


# ------------------------------------------------------------- tail mode

def test_tail_last_n_chronological_jsonl(tmp_path):
    for i, ts in enumerate((DAY1, DAY1 + 60, DAY1 + 120)):
        make_run(tmp_path / "runs", events=[{"event": "l1", "ok": True}],
                 mtime=ts)
    lines = tail_runs(tmp_path / "runs", n=2)
    assert len(lines) == 2
    assert lines[0]["ts"] < lines[1]["ts"]  # chronological, oldest first
    assert lines[-1]["ts"] == pytest.approx(DAY1 + 120, abs=0.001)
    assert [json.loads(json.dumps(r)) == r for r in lines] == [True] * len(lines)


# ------------------------------------------------------------ read-only

def test_scan_is_read_only_over_ledgers(tmp_path):
    make_run(tmp_path / "runs", events=[
        {"event": "l2", "ok": True, "failures": [], "tier": "fast",
         "coverage": {"coverage_ratio": 0.9}, "warnings": []}], mtime=DAY1)
    root = tmp_path / "runs"
    before = {}
    for p in sorted(root.rglob("*")):
        st = p.stat()
        before[p] = (hashlib.sha256(p.read_bytes()).hexdigest()
                     if p.is_file() else None, st.st_mtime_ns)
    scan_runs(root)
    aggregate(scan_runs(root))
    tail_runs(root, n=5)
    for p, (digest, mtime) in before.items():
        st = p.stat()
        assert (hashlib.sha256(p.read_bytes()).hexdigest()
                if p.is_file() else None) == digest
        assert st.st_mtime_ns == mtime


# ------------------------------------------------------------------- CLI

def _cli(args):
    from zft.cli.main import main
    out, err = StringIO(), StringIO()
    saved = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        code = main(args)
    finally:
        sys.stdout, sys.stderr = saved
    return code, out.getvalue(), err.getvalue()


def test_cli_metrics_summary_and_json_and_tail(tmp_path):
    make_run(tmp_path / ".zft" / "runs", events=[
        {"event": "l2", "ok": True, "failures": [], "tier": "fast",
         "coverage": {"coverage_ratio": 1.0}, "warnings": []}], mtime=DAY1)
    make_run(tmp_path / ".zft" / "runs", events=[
        {"event": "l1", "ok": True}], mtime=DAY1 + 60)
    root = str(tmp_path)

    code, out, _ = _cli(["metrics", root])
    assert code == 0
    assert "2 runs" in out

    code, out, _ = _cli(["metrics", "--format", "json", root])
    assert code == 0
    rep = json.loads(out)
    assert rep["n_runs"] == 2

    code, out, _ = _cli(["metrics", "--tail", "1", root])
    assert code == 0
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0]["crash_class"] == "died-after-l1"


def test_cli_metrics_refuses_missing_runs_dir(tmp_path):
    code, _, err = _cli(["metrics", str(tmp_path)])
    assert code == 1
    assert "no runs" in err.lower()


# ------------------------------------------------- the DORA five
#
# ops/DORA-METRICS-MAP.md layer 2: deployment frequency = gate-passed
# landings per repo per window; lead time = change arrival (first gate
# contact of a commit — ledgers carry no commit timestamp, and the module
# derives every number from ledger bytes + mtimes) -> first gate-green;
# CFR = gate-fail runs, flake = fail->pass on the SAME commit; recovery
# = red -> green per commit; rework = gate re-runs per change. --dora is
# the same read-only observer: a section, never a gate.

GREEN_CHECK = [{"event": "l2", "ok": True, "failures": [], "tier": "fast",
                "coverage": {"coverage_ratio": 1.0}, "warnings": []}]
RED_L1 = [{"event": "l1", "ok": False}]


def test_dora_deployment_frequency_landings_per_repo_per_window(tmp_path):
    make_run(tmp_path / "runs", commit="c1" * 20, events=GREEN_CHECK, mtime=DAY1)
    make_run(tmp_path / "runs", commit="c1" * 20, events=GREEN_CHECK,
             mtime=DAY1 + 60)
    make_run(tmp_path / "runs", commit="c2" * 20, events=GREEN_CHECK, mtime=DAY2)
    make_run(tmp_path / "runs", commit="c2" * 20, events=RED_L1, mtime=DAY2 + 60)
    d = dora(scan_runs(tmp_path / "runs"), window="day")
    df = d["deployment_frequency"]
    assert df["landed_total"] == 3  # the red run landed nothing
    assert df["days_active"] == 2
    assert df["mean_per_active_day"] == pytest.approx(1.5)
    assert df["per_repo"]["c1" * 20]["total"] == 2
    assert len(df["per_repo"]["c1" * 20]["per_window"]) == 1
    assert sum(df["per_repo"]["c1" * 20]["per_window"].values()) == 2
    assert sum(df["per_repo"]["c2" * 20]["per_window"].values()) == 1


def test_dora_lead_time_change_arrival_to_green(tmp_path):
    # c1: arrived (first gate contact) at DAY1, green 600s later
    make_run(tmp_path / "runs", commit="c1" * 20, events=RED_L1, mtime=DAY1)
    make_run(tmp_path / "runs", commit="c1" * 20, events=GREEN_CHECK,
             mtime=DAY1 + 600)
    # c2: arrived, never green — pending, not a measured span
    make_run(tmp_path / "runs", commit="c2" * 20, events=RED_L1, mtime=DAY1)
    d = dora(scan_runs(tmp_path / "runs"))
    lt = d["lead_time_ms"]
    assert lt["n"] == 1
    assert lt["p50"] == pytest.approx(600_000.0)
    assert lt["max"] == pytest.approx(600_000.0)
    assert lt["pending"] == 1


def test_dora_change_failure_rate_and_same_commit_flake(tmp_path):
    # c1: fail then pass, NO source change between (same commit) = flake
    make_run(tmp_path / "runs", commit="c1" * 20, events=RED_L1, mtime=DAY1)
    make_run(tmp_path / "runs", commit="c1" * 20, events=GREEN_CHECK,
             mtime=DAY1 + 60)
    # c2: always fails = broken, not flaky
    make_run(tmp_path / "runs", commit="c2" * 20, events=RED_L1, mtime=DAY1)
    make_run(tmp_path / "runs", commit="c2" * 20, events=RED_L1,
             mtime=DAY1 + 60)
    d = dora(scan_runs(tmp_path / "runs"))
    cfr = d["change_failure_rate"]
    assert cfr["gate_fail_runs"] == 3
    assert cfr["runs_with_gates"] == 4
    assert cfr["rate"] == pytest.approx(0.75)
    assert cfr["flake_commits"] == 1
    assert cfr["commits_with_fails"] == 2
    assert cfr["flake_rate"] == pytest.approx(0.5)


def test_dora_recovery_red_to_green_per_commit(tmp_path):
    # c1: red DAY1 -> green DAY1+600 = one recovery span of 600s
    make_run(tmp_path / "runs", commit="c1" * 20, events=RED_L1, mtime=DAY1)
    make_run(tmp_path / "runs", commit="c1" * 20, events=GREEN_CHECK,
             mtime=DAY1 + 600)
    # c2: red, red — never recovered, no span
    make_run(tmp_path / "runs", commit="c2" * 20, events=RED_L1, mtime=DAY1)
    make_run(tmp_path / "runs", commit="c2" * 20, events=RED_L1, mtime=DAY2)
    # c3: green only — no red, no span
    make_run(tmp_path / "runs", commit="c3" * 20, events=GREEN_CHECK, mtime=DAY1)
    d = dora(scan_runs(tmp_path / "runs"))
    rec = d["recovery_ms"]
    assert rec["n"] == 1
    assert rec["p50"] == pytest.approx(600_000.0)
    assert rec["max"] == pytest.approx(600_000.0)
    assert rec["red_commits"] == 2  # c1 and c2 saw a red


def test_dora_rework_reruns_per_change(tmp_path):
    make_run(tmp_path / "runs", commit="c1" * 20, events=RED_L1, mtime=DAY1)
    make_run(tmp_path / "runs", commit="c1" * 20, events=GREEN_CHECK,
             mtime=DAY1 + 60)
    make_run(tmp_path / "runs", commit="c1" * 20, events=GREEN_CHECK,
             mtime=DAY1 + 120)
    make_run(tmp_path / "runs", commit="c2" * 20, events=GREEN_CHECK, mtime=DAY1)
    d = dora(scan_runs(tmp_path / "runs"))
    rw = d["rework"]
    assert rw["commits"] == 2
    assert rw["rerun_runs"] == 2  # c1's runs beyond its first
    assert rw["max_reruns"] == 2
    assert rw["rate"] == pytest.approx(0.5)  # 2 reruns / 4 runs


def test_dora_empty_board_is_honest(tmp_path):
    d = dora([])
    assert d["deployment_frequency"]["landed_total"] == 0
    assert d["deployment_frequency"]["per_repo"] == {}
    assert d["deployment_frequency"]["mean_per_active_day"] is None
    assert d["lead_time_ms"] == {"n": 0, "p50": None, "p90": None,
                                 "max": None, "pending": 0}
    assert d["change_failure_rate"]["rate"] is None
    assert d["change_failure_rate"]["flake_rate"] is None
    assert d["recovery_ms"]["n"] == 0 and d["recovery_ms"]["p50"] is None
    assert d["rework"]["rate"] is None


def test_cli_metrics_dora_flag_adds_section_default_omits_it(tmp_path):
    make_run(tmp_path / ".zft" / "runs", events=GREEN_CHECK, mtime=DAY1)
    root = str(tmp_path)
    code, out, _ = _cli(["metrics", "--format", "json", root])
    assert code == 0 and "dora" not in json.loads(out)
    code, out, _ = _cli(["metrics", "--format", "json", "--dora", root])
    assert code == 0
    rep = json.loads(out)
    assert "dora" in rep
    assert rep["dora"]["deployment_frequency"]["landed_total"] == 1
    code, out, _ = _cli(["metrics", "--dora", root])  # summary renders too
    assert code == 0 and "dora" in out.lower()
    from zft.cli.main import USAGE
    assert "[--dora]" in USAGE["metrics"]
