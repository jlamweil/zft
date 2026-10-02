"""metrics: read-only statistics over .zft/runs ledgers (INT-086).

Sister reader to debug/ledger.py: never writes. Every number is derived
from ledger bytes and filesystem mtimes. Depends on nothing above the
debug layer (plan §2 dependency direction). `dora()` adds the five DORA
keys (ops/DORA-METRICS-MAP.md layer 2) over the same summaries —
`zft metrics --dora` (WQ-043); same read-only observer, a section, never
a gate.

Crash taxonomy (the stop-hook crash class: runs that died mid-report):
- check runs must terminate on an `l2` event; anything else is a death,
  EXCEPT a terminal `l0` — that is a clean L0 rejection (the CLI exits 1
  after emitting it by design), counted as `rejected`, not crashed.
- L2-fast (mutation campaign) runs must terminate on `campaign_summary`;
  death after any `mutant_verdict` is `died-mid-campaign`, death before
  any event is `died-before-first-event`.
- negotiate runs are resumable by design — no `validated` means
  `unfinished-negotiation`, observed but not a crash.
- unknown stages are never classified (`unknown-stage`).

Wall-clock timing is mtime-derived: manifest.json is written once at
run start, events.jsonl is appended until close, so
`events_mtime - manifest_mtime` bounds the run duration.

Keys starting with "_" on a run summary are internal aggregates for
`aggregate()`; `public_summary()` strips them for JSONL output.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# stage -> the event a clean close always leaves last
EXPECTED_TERMINAL = {
    "check": "l2",
    "L2-fast": "campaign_summary",
    "negotiate": "validated",
}
# terminals that mean "the gate said no, cleanly" — a fail, not a death
CLEAN_REJECTIONS = {("check", "l0")}
NOT_CRASH_CLASSES = (None, "unknown-stage", "unfinished-negotiation")


def _window_key(ts: float, window: str = "day") -> str:
    t = time.gmtime(ts)
    if window == "hour":
        return time.strftime("%Y-%m-%dT%H:00", t)
    return time.strftime("%Y-%m-%d", t)


def dora(runs: list[dict], window: str = "day") -> dict:
    """The five DORA keys over run summaries (ops/DORA-METRICS-MAP.md,
    layer 2). Same observer discipline as aggregate(): derived from
    ledger-derived summaries, never touching a gate.

    deployment frequency  gate-passed landings (ok runs) per repo per
                          window
    lead time            change arrival -> first gate-green, per commit.
                          Ledgers carry no commit timestamp and this
                          reader derives everything from ledger bytes +
                          mtimes, so 'arrival' is the commit's FIRST run
                          (first gate contact) — the honest derivable
                          anchor. A commit never green is counted
                          `pending`, never turned into a span.
    change failure rate   gate-fail runs / runs with gate evidence;
                          flake = a commit that both failed and passed
                          (fail -> pass with NO source change) —
                          flake_commits / commits_with_fails
    recovery             red -> green per commit (chronological; a green
                          with no open red is not a recovery)
    rework               gate re-runs per change: runs beyond a commit's
                          first (repeated gate runs = reworked
                          verification), rate over all runs

    No measurement is a measured zero: rates/percentiles are None when
    their denominator is empty.
    """
    per_repo: dict[str, dict] = {}
    landed = 0
    days: set[str] = set()
    by_commit: dict[str, list[dict]] = {}
    fail_runs = gated_runs = 0
    for r in runs:
        commit = r["git_commit"] or "?"
        by_commit.setdefault(commit, []).append(r)
        if r["ok"] is True:
            landed += 1
            days.add(_window_key(r["ts"], window))
            repo = per_repo.setdefault(commit, {"total": 0, "per_window": {}})
            repo["total"] += 1
            wk = _window_key(r["ts"], window)
            repo["per_window"][wk] = repo["per_window"].get(wk, 0) + 1
        if any(v is False for v in r["gate_outcomes"].values()):
            fail_runs += 1
        if any(v is not None for v in r["gate_outcomes"].values()):
            gated_runs += 1

    lead_spans: list[float] = []
    pending = 0
    recovery_spans: list[float] = []
    red_commits = 0
    rerun_runs = 0
    max_reruns = 0
    flake_commits = commits_with_fails = 0
    for commit, cruns in by_commit.items():
        cruns = sorted(cruns, key=lambda r: (r["ts"], r["run_id"]))
        reruns = len(cruns) - 1
        rerun_runs += max(0, reruns)
        max_reruns = max(max_reruns, reruns)
        outcomes = [r["ok"] for r in cruns]
        if any(o is False for o in outcomes):
            commits_with_fails += 1
            red_commits += 1
            if any(o is True for o in outcomes):
                flake_commits += 1
        first_ok = next((r for r in cruns if r["ok"] is True), None)
        if first_ok is None:
            pending += 1
        else:
            lead_spans.append((first_ok["ts"] - cruns[0]["ts"]) * 1000)
        open_red = None
        for r in cruns:
            if r["ok"] is False:
                if open_red is None:
                    open_red = r["ts"]
            elif r["ok"] is True and open_red is not None:
                recovery_spans.append((r["ts"] - open_red) * 1000)
                open_red = None

    def _ms(vals: list[float]) -> dict:
        s = sorted(vals)
        return {"n": len(s), "p50": _percentile(s, 0.5),
                "p90": _percentile(s, 0.9), "max": s[-1] if s else None}

    lead = _ms(lead_spans)
    lead["pending"] = pending
    rec = _ms(recovery_spans)
    rec["red_commits"] = red_commits
    return {
        "deployment_frequency": {
            "landed_total": landed,
            "days_active": len(days),
            "mean_per_active_day": round(landed / len(days), 2)
            if days else None,
            "per_repo": dict(sorted(per_repo.items())),
        },
        "lead_time_ms": lead,
        "change_failure_rate": {
            "gate_fail_runs": fail_runs,
            "runs_with_gates": gated_runs,
            "rate": round(fail_runs / gated_runs, 4) if gated_runs else None,
            "flake_commits": flake_commits,
            "commits_with_fails": commits_with_fails,
            "flake_rate": round(flake_commits / commits_with_fails, 4)
            if commits_with_fails else None,
        },
        "recovery_ms": rec,
        "rework": {
            "commits": len(by_commit),
            "rerun_runs": max(0, rerun_runs),
            "max_reruns": max_reruns,
            "rate": round(rerun_runs / len(runs), 4) if runs else None,
        },
    }


def _percentile(sorted_vals: list, q: float):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, round(q * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def public_summary(run: dict) -> dict:
    """The JSONL-facing view: private `_`-keys stripped."""
    return {k: v for k, v in run.items() if not k.startswith("_")}


def scan_run(run_dir: Path) -> dict | None:
    """One run's summary from manifest + events + mtimes. Read-only.

    Returns None only when the directory is not a run (no events.jsonl).
    """
    events_path = run_dir / "events.jsonl"
    if not events_path.is_file():
        return None
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        manifest = {}

    events: list[dict] = []
    torn_lines = 0
    for line in events_path.read_bytes().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            torn_lines = 1  # torn tail write — counted, never parsed
            break

    stage = manifest.get("stage")
    terminal = events[-1].get("event") if events else None
    expected = EXPECTED_TERMINAL.get(stage)
    complete = expected is not None and terminal == expected
    rejected = (stage, terminal) in CLEAN_REJECTIONS

    if expected is None:
        crash_class = "unknown-stage" if stage is not None else None
    elif complete or rejected:
        crash_class = None
    elif not events:
        crash_class = "died-before-first-event"
    elif stage == "L2-fast" and terminal == "mutant_verdict":
        crash_class = "died-mid-campaign"
    elif stage == "negotiate":
        crash_class = "unfinished-negotiation"
    else:
        crash_class = f"died-after-{terminal}"

    # wall-clock: manifest written once at start, events appended until close
    manifest_mtime = _mtime(run_dir / "manifest.json")
    events_mtime = _mtime(events_path)
    duration_ms = None
    if manifest_mtime and events_mtime > manifest_mtime:
        duration_ms = round((events_mtime - manifest_mtime) * 1000)

    coverage_ratio = None
    for ev in reversed(events):
        if ev.get("event") == "l2" and isinstance(ev.get("coverage"), dict):
            ratio = ev["coverage"].get("coverage_ratio")
            if isinstance(ratio, (int, float)):
                coverage_ratio = float(ratio)
            break

    gate_outcomes: dict[str, bool | None] = {}
    for gate, event_name in (("l0", "l0"), ("l1", "l1"), ("l2", "l2"),
                             ("campaign", "campaign_summary")):
        val = next((ev.get("ok") for ev in reversed(events)
                    if ev.get("event") == event_name), None)
        gate_outcomes[gate] = val if isinstance(val, bool) else None

    clause_stats: dict[str, dict[str, int]] = {}
    clause_ms: list[int] = []
    mutants = {"count": 0, "killed": 0, "timed_out": 0, "duration_ms": 0}
    for ev in events:
        if ev.get("event") == "l1_clause":
            alias = ev.get("alias", "?")
            slot = clause_stats.setdefault(
                alias, {"pass": 0, "fail": 0, "cached": 0})
            if ev.get("cached"):
                slot["cached"] += 1
            elif ev.get("ok") is True:
                slot["pass"] += 1
            elif ev.get("ok") is False:
                slot["fail"] += 1
            if isinstance(ev.get("duration_ms"), (int, float)):
                clause_ms.append(int(ev["duration_ms"]))
        elif ev.get("event") == "mutant_verdict":
            mutants["count"] += 1
            if ev.get("ok"):
                mutants["killed"] += 1
            if ev.get("timed_out"):
                mutants["timed_out"] += 1
            if isinstance(ev.get("duration_ms"), (int, float)):
                mutants["duration_ms"] += int(ev["duration_ms"])

    return {
        "run_id": manifest.get("run_id", run_dir.name),
        "ts": events_mtime,
        "stage": stage,
        "tier": manifest.get("tier"),
        "git_commit": manifest.get("git_commit"),
        "dirty": manifest.get("dirty"),
        "terminal": terminal,
        "complete": complete,
        "crashed": crash_class not in NOT_CRASH_CLASSES,
        "rejected": rejected,
        "crash_class": crash_class,
        "torn_lines": torn_lines,
        "ok": terminal is not None and events[-1].get("ok") is True,
        "duration_ms": duration_ms,
        "coverage_ratio": coverage_ratio,
        "gate_outcomes": gate_outcomes,
        "clause_stats": clause_stats,
        "mutants": mutants,
        "_clause_ms": clause_ms,
    }


def scan_runs(runs_root: Path | str) -> list[dict]:
    """Every run under runs_root, chronological by events mtime. Read-only."""
    root = Path(runs_root)
    if not root.is_dir():
        return []
    runs = (s for d in sorted(root.iterdir()) if d.is_dir()
            if (s := scan_run(d)) is not None)
    return sorted(runs, key=lambda r: (r["ts"], r["run_id"]))


def tail_runs(runs_root: Path | str, n: int | None = None,
              follow: bool = False, poll_s: float = 2.0, stop=None):
    """JSONL tail mode: the last n run summaries, chronological, public
    keys only — a list when follow=False, a generator streaming newer
    runs as they land when follow=True (stop() truthy ends the loop —
    the injection seam tests use; the CLI maps KeyboardInterrupt)."""
    if not follow:
        runs = [public_summary(r) for r in scan_runs(runs_root)]
        return runs[-n:] if n is not None else runs
    def _stream():
        emitted: set[str] = set()
        while True:
            for r in scan_runs(runs_root):
                if r["run_id"] in emitted:
                    continue
                emitted.add(r["run_id"])
                yield public_summary(r)
            if stop is not None and stop():
                return
            time.sleep(poll_s)
    return _stream()


def aggregate(runs: list[dict], window: str = "day") -> dict:
    """Fold run summaries into the report: stages, crashes, gates, flake,
    coverage trend, per-repo and per-window breakdowns, timing."""
    stages: dict[str, dict] = {}
    crash_classes: dict[str, int] = {}
    gates = {g: {"pass": 0, "fail": 0}
             for g in ("l0", "l1", "l2", "campaign")}
    alias_totals: dict[str, dict[str, int]] = {}
    alias_by_commit: dict[str, dict[str, dict[str, int]]] = {}
    coverage_series: list[tuple[float, float]] = []
    repos: dict[str, dict] = {}
    windows: dict[str, dict] = {}
    run_ms: list[int] = []
    clause_ms: list[int] = []
    clause_cached = clause_total = 0
    mutant_ms: list[int] = []
    first_ts = last_ts = None

    def _bucket(ts: float) -> str:
        t = time.gmtime(ts)
        if window == "hour":
            return time.strftime("%Y-%m-%dT%H:00", t)
        return time.strftime("%Y-%m-%d", t)

    for r in runs:
        ts = r["ts"]
        first_ts = ts if first_ts is None else min(first_ts, ts)
        last_ts = ts if last_ts is None else max(last_ts, ts)

        st = stages.setdefault(r["stage"] or "?",
                               {"runs": 0, "complete": 0, "crashed": 0,
                                "rejected": 0, "ok": 0})
        st["runs"] += 1
        st["complete"] += r["complete"]
        st["crashed"] += r["crashed"]
        st["rejected"] += r["rejected"]
        st["ok"] += r["ok"]

        if r["crash_class"]:
            crash_classes[r["crash_class"]] = \
                crash_classes.get(r["crash_class"], 0) + 1

        for gate, ok in r["gate_outcomes"].items():
            if ok is True:
                gates[gate]["pass"] += 1
            elif ok is False:
                gates[gate]["fail"] += 1

        commit = r["git_commit"] or "?"
        repo = repos.setdefault(commit, {"runs": 0, "ok": 0, "crashed": 0})
        repo["runs"] += 1
        repo["ok"] += r["ok"]
        repo["crashed"] += r["crashed"]

        for alias, s in r["clause_stats"].items():
            tot = alias_totals.setdefault(alias, {"pass": 0, "fail": 0})
            tot["pass"] += s["pass"]
            tot["fail"] += s["fail"]
            slot = alias_by_commit.setdefault(commit, {}).setdefault(
                alias, {"pass": 0, "fail": 0})
            slot["pass"] += s["pass"]
            slot["fail"] += s["fail"]

        if r["coverage_ratio"] is not None:
            coverage_series.append((ts, r["coverage_ratio"]))

        wkey = _bucket(ts)
        w = windows.setdefault(wkey, {"window": wkey, "runs": 0, "ok": 0,
                                      "crashed": 0, "coverage": []})
        w["runs"] += 1
        w["ok"] += r["ok"]
        w["crashed"] += r["crashed"]
        if r["coverage_ratio"] is not None:
            w["coverage"].append(r["coverage_ratio"])

        if r["duration_ms"] is not None:
            run_ms.append(r["duration_ms"])
        clause_ms.extend(r.get("_clause_ms", ()))
        clause_cached += sum(s["cached"] for s in r["clause_stats"].values())
        clause_total += sum(sum(s.values())
                            for s in r["clause_stats"].values())
        if r["mutants"]["duration_ms"]:
            mutant_ms.append(r["mutants"]["duration_ms"])

    # flake: mixed executed outcomes overall; by_commit isolates the
    # classic same-commit flake from benign across-commit drift
    flaky_aliases = {a: c for a, c in alias_totals.items()
                     if c["pass"] > 0 and c["fail"] > 0}
    by_commit = {
        commit: sorted(a for a, c in per.items()
                       if c["pass"] > 0 and c["fail"] > 0)
        for commit, per in alias_by_commit.items()}
    for commit, aliases in by_commit.items():
        if aliases:
            repos.setdefault(commit, {"runs": 0, "ok": 0, "crashed": 0})
        repos[commit]["flaky"] = aliases

    cov_vals = [v for _, v in sorted(coverage_series, key=lambda x: x[0])]
    ordered_windows = sorted(windows.values(), key=lambda w: w["window"])

    def _trend_row(w: dict) -> dict:
        covs = w.pop("coverage")
        return {**w,
                "coverage_mean": (sum(covs) / len(covs)) if covs else None,
                "coverage_min": min(covs) if covs else None,
                "coverage_max": max(covs) if covs else None}

    return {
        "n_runs": len(runs),
        "span": {"first": first_ts, "last": last_ts},
        "stages": stages,
        "crash_classes": dict(sorted(crash_classes.items())),
        "gates": gates,
        "flake": {"aliases": dict(sorted(flaky_aliases.items())),
                  "n_flaky": len(flaky_aliases),
                  "by_commit": by_commit},
        "coverage": {
            "trend": [_trend_row(dict(w)) for w in ordered_windows
                      if w["coverage"]],
            "overall": {"first": cov_vals[0] if cov_vals else None,
                        "last": cov_vals[-1] if cov_vals else None,
                        "min": min(cov_vals) if cov_vals else None,
                        "max": max(cov_vals) if cov_vals else None},
        },
        "repos": repos,
        "windows": [_trend_row(dict(w)) for w in ordered_windows],
        "timing": {
            "run_ms": _pcts(run_ms),
            "l1_clause_ms": {**_pcts(clause_ms),
                             "cached_share": (clause_cached / clause_total)
                             if clause_total else None},
            "mutant_ms": _pcts(mutant_ms),
        },
    }


def _pcts(vals: list) -> dict:
    s = sorted(vals)
    return {"p50": _percentile(s, 0.5), "p90": _percentile(s, 0.9),
            "max": s[-1] if s else None}


def render(rep: dict) -> str:
    """Human summary — one line per concern, ~78 cols max."""
    out: list[str] = []

    def fmt_ts(ts):
        return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) if ts else "-"

    out.append(f"zft metrics — {rep['n_runs']} runs, "
               f"{fmt_ts(rep['span']['first'])} .. "
               f"{fmt_ts(rep['span']['last'])} (UTC)")
    for stage, s in sorted(rep["stages"].items()):
        out.append(f"stage {stage}: {s['runs']} runs, {s['complete']} complete,"
                   f" {s['crashed']} crashed, {s['rejected']} rejected,"
                   f" {s['ok']} terminal-ok")
    if rep["crash_classes"]:
        hist = " ".join(f"{k}={v}"
                        for k, v in rep["crash_classes"].items())
        out.append(f"crash classes: {hist}")
    out.append("gates: " + " | ".join(
        f"{name} pass {c['pass']} fail {c['fail']}"
        for name, c in rep["gates"].items()))
    if rep["flake"]["n_flaky"]:
        out.append(f"flaky aliases ({rep['flake']['n_flaky']}): " + ", ".join(
            f"{a} ({c['fail']}f/{c['pass']}p)"
            for a, c in rep["flake"]["aliases"].items()))
    else:
        out.append("flaky aliases: none")
    cov = rep["coverage"]["overall"]
    if cov["first"] is not None:
        out.append(f"coverage: first {cov['first']:.3f} -> last {cov['last']:.3f}"
                   f" (min {cov['min']:.3f} max {cov['max']:.3f})")
    t = rep["timing"]
    out.append(f"timing: run p50 {_fmt_ms(t['run_ms']['p50'])}"
               f" p90 {_fmt_ms(t['run_ms']['p90'])}"
               f" | l1_clause p50 {_fmt_ms(t['l1_clause_ms']['p50'])}"
               f" p90 {_fmt_ms(t['l1_clause_ms']['p90'])}"
               + (f" (cached {t['l1_clause_ms']['cached_share']:.0%})"
                  if t["l1_clause_ms"]["cached_share"] is not None else ""))
    for w in rep["windows"]:
        cov_s = (f", coverage mean {w['coverage_mean']:.3f}"
                 if w["coverage_mean"] is not None else "")
        out.append(f"window {w['window']}: {w['runs']} runs, {w['ok']} ok,"
                   f" {w['crashed']} crashed{cov_s}")
    if rep.get("dora"):
        out.append(_render_dora(rep["dora"]))
    return "\n".join(out)


def _render_dora(d: dict) -> str:
    """The DORA block as one dense line per concern pair (~78 cols)."""
    df = d["deployment_frequency"]
    lt = d["lead_time_ms"]
    cfr = d["change_failure_rate"]
    rec = d["recovery_ms"]
    rw = d["rework"]

    def pct(v):
        return "-" if v is None else f"{v:.0%}"

    def n_p(v, fmt):
        return fmt(v) if v is not None else "-"

    lead_s = (f"p50 {n_p(lt['p50'], _fmt_ms)} p90 {n_p(lt['p90'], _fmt_ms)}"
              f" (pending {lt['pending']})")
    rec_s = (f"n {rec['n']}, p50 {n_p(rec['p50'], _fmt_ms)}"
             f" max {n_p(rec['max'], _fmt_ms)} (red commits {rec['red_commits']})")
    return " | ".join([
        f"dora landings: {df['landed_total']} over {df['days_active']} days"
        f" (mean {df['mean_per_active_day'] if df['mean_per_active_day'] is not None else '-'}/day)",
        f"lead: {lead_s}",
        f"cfr: {cfr['gate_fail_runs']}/{cfr['runs_with_gates']}"
        f" = {pct(cfr['rate'])}, flake commits {cfr['flake_commits']}"
        f"/{cfr['commits_with_fails']} = {pct(cfr['flake_rate'])}",
        f"recovery: {rec_s}",
        f"rework: {rw['rerun_runs']} rerun runs / {rw['commits']} commits"
        f" = {pct(rw['rate'])} (max {rw['max_reruns']})",
    ])


def _fmt_ms(v) -> str:
    if v is None:
        return "-"
    return f"{v / 1000:.1f}s" if v >= 10_000 else f"{v:.0f}ms"
