# Fleet Adoption Proof — `zft metrics` over the gate-run ledgers

Dated: 2026-10-07 · Lane: T22 (`TASKS-CONCURRENT-WORKER.md`) · zft version key: 0.2.0
Checkout of record: yuguerten `~/zft-public` @ `1f9709d` (`f1429fe` in history), remote
`github.com/jlamweil/zft`. No push, no tag, no version bump, no publish (owner acts pending,
WQ-090/145).

## Method

- `zft metrics` was run **from the yuguerten zft-public checkout** with
  `--format json` per root:
  `PYTHONPATH=$HOME/zft-public/src python3 -c "import sys; sys.argv=['zft','metrics','<root>','--format','json']; from zft.cli.main import main; sys.exit(main())"`
  (module resolved to `/home/jlam/zft-public/src/zft/cli/main.py` — asserted before each run).
  **Operational note:** the pip-installed `zft` in `~/.local/lib/python3.12/site-packages`
  (0.2.0 wheel) predates the metrics line and answers `unknown command: metrics` — the
  checkout code is what ran.
- The gaia ledgers were snapshotted **read-only** onto yuguerten
  (`rsync -a` into `/tmp/t22-ledger-staging/`; sources untouched — `.zft/runs` is read-only
  by rule; zcode-remote-driver was never written to by this lane):
  - `/tmp/t22-ledger-staging/traceagent` ← gaia `/home/jlam/1/traceagent/.zft/runs` — **4750** run dirs
  - `/tmp/t22-ledger-staging/zcode` ← gaia `/home/jlam/zcode-remote-driver/.zft/runs` — **781** run dirs
    (the brief said 777 as of 10-06; +4 from the concurrent WQ-184/fix-6 workqueue run —
    expected snapshot drift, not a defect)
  - `~/zft-public` ← yuguerten's own checkout `.zft/runs` — **396** run dirs
- `scan_runs` is read-only over `events.jsonl` + `manifest.json` + mtimes; zero writes to
  any ledger. Each host's `n_runs` equals its run-dir count exactly (4750 / 781 / 396).
- Raw per-root aggregate outputs are committed beside this report for reproducibility:
  `2026-10-07-adoption-{traceagent-gaia,zcode-remote-driver-gaia,yuguerten-zft-public}.json`
  Regenerate with the command above against those roots.

## Fleet totals

**5927 runs** across 3 repos · **644 distinct commits** · span **2026-09-15 → 2026-10-06** (UTC).

| repo (host) | runs | span (UTC) | distinct commits | ok | crashed | rejected (typed) |
|---|---|---|---|---|---|---|
| `1/traceagent` (gaia) | 4750 | 09-15 08:12 → 10-05 20:00 | 174 | 3896 (check) + 709 (L2-fast) | 972 + 16 | 41 |
| `zcode-remote-driver` (gaia) | 781 | 09-26 17:42 → 10-06 18:53 | 463 | 781 | 0 | 0 |
| `zft-public` (yuguerten) | 396 | 10-01 19:58 → 10-03 22:32 | 7 | 93 (check) + 74 (L2-fast) | 0 | 0 |

### Verdict distribution (fleet, per `aggregate()` terminal classifications)

- **ok** (terminal event `ok: true`): **5553 / 5927 = 93.7%**
- **crashed**: **988 (16.7%)** — all on traceagent, all on **2026-09-15, the ledger's first day**:
  `died-after-l1` 972 · `died-before-first-event` 11 · `died-mid-campaign` 5. Zero crashes on
  every subsequent day (16 traceagent days + 10 zcode days + 3 yuguerten days).
- **rejected** (clean typed rejection): **41** — all traceagent check stage.
- The remainder reached their terminal event without ok/crash/rejection (completed but
  gate-failed runs, e.g. l2 fails). Per-stage exact counts:

| stage | runs | complete | crashed | rejected | ok |
|---|---|---|---|---|---|
| check | 5117 | 4504 | 972 | 41 | 4770 |
| L2-fast | 809 | 793 | 16 | 0 | 783 |
| negotiate | 1 | 1 | 0 | 0 | 0 |

### Gate verdicts (pass/fail, fleet)

`l0` 5117/0 · `l1` 4932/144 · `l2` 4674/402 · `campaign` 783/10

## Per-host detail

### gaia `/home/jlam/1/traceagent` — 4750 runs

gates l0 4014p/0f · l1 3964p/9f · l2 3800p/173f · campaign 709p/10f.
Flake aliases (2): `ID-CONTENT-CHANGE` 433p/9f, `TR-DETERMINISTIC-EXTRACTION` 434p/9f
(benign same-commit flake, sub-2.5%). Coverage first=1.0, last=1.0, min=0.0, max=1.0.
Timing: run p50 3886ms, p90 6056ms, max 4009480ms; L1 clause p50 305ms, p90 458ms,
**cached_share 91.1%**.

### gaia `/home/jlam/zcode-remote-driver` — 781 runs

All green: 0 crashes, 0 flake, all gates pass (781/781 at l0/l1/l2), coverage flat at 1.0,
10 consecutive active days, run p50 2482ms, p90 4495ms, max 9511ms. Still live at snapshot
(6 runs on 10-06).

### yuguerten `~/zft-public` — 396 runs

gates l0 322p/0f · l1 187p/135f · l2 93p/229f · campaign 74p/0f. Zero crashes.
Run p50 449ms, p90 1230ms; L1 clause p50 675ms, cached_share 57.5%. Coverage 0.0 → 1.0
across the span (matches the WQ-145 re-baseline window).
**Note:** the metrics flake heuristic (pass>0 ∧ fail>0) labels the two root-oracle clauses
(`ID-CONTENT-CHANGE` 2p/135f, `TR-DETERMINISTIC-EXTRACTION` 2p/135f) as "flaky"; the
asymmetry vs traceagent (~433p/9f each) shows these are **systematic** rejections on the
public cut, not random flake. Heuristic refinement is a post-v0.3.0 candidate, noted in
the scope doc anomalies.

## Trend (per-day, UTC)

- traceagent (17 active days): the entire crash cluster is day-1 — 988/988 crashed runs on
  2026-09-15 (2468 runs that day); the following 16 days are zero-crash, latest day
  (10-05) 123 runs / 123 ok.
- zcode (10 consecutive days): all days 100% ok (2 → 135 → 6 runs per day).
- yuguerten (3 days): ok 32/167 (10-01) → 132/226 (10-03); per-day coverage mean 0.0 → 1.0.

## Reading

- The crash-class visibility INT-086 demanded ("the stop-hook crash class visibility") is
  real and bounded: 972 `died-after-l1` crashes, all on the first ledger day, none since —
  16 days × 2 gaia repos + 3 yuguerten days run crash-free.
- 91.1% L1 clause cached-share on traceagent is the Wave A/B cache + determinism work
  (Plan V2 §5) showing up in fleet timing.
- Adoption: 3 repos, 5927 gate runs, 644 commits under measurement; zcode-remote-driver is
  100% ok across its full 10-day span. This is the dogfood evidence for the v0.3.0
  debuggability-metrics launch story (`docs/release/v0.3.0-SCOPE.md`).

## Constraints honored

- Read-only over every ledger: gaia `.zft/runs` rsynced, never modified; zcode-remote-driver
  untouched (its concurrent WQ-184 writer continued unimpeded).
- No version bump, no tag, no push, no publish; PUBLISH-RUNBOOK steps 2–5 not executed
  (owner acts).
- Gate for this artifact: `tests/unit/test_metrics.py` **28/28 green** (2026-10-07, from the
  checkout; `PYTHONPATH=$HOME/zft-public/src python3 -m pytest tests/unit/test_metrics.py -q`).
