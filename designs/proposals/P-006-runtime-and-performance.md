# P-006 – Runtime & performance architecture

**ID**: P-006
**Version**: v2
**Status**: PROPOSED
**Date**: 2026-09-10
**Target baseline**: `designs/ARCHITECTURE.md` (baseline v0); implementation of `lineage/extract.py`, `gates/l1.py`, `gates/l2.py`, `cli/main.py`

## Motivation — measured (30 clauses, 35 test files)
| Metric | Measured |
|---|---|
| startup / import / `lint` / `task-gate` | ~0.01 / 0.01 / 0.05 / 0.01 s |
| **`zft extract`** | **4.58 s** — and unsound (see below) |
| `zft impact` | 4.57 s |
| **`zft check`** | **≈ 14.7 s** (extraction runs **3×**; mutation is separate) |

`extract_bindings` uses `root.rglob("*")` with **no ignore set**: 5,268 candidate files (`.venv` 3,448, `.opencode` 1,697), and it **harvests non-source bindings** — 41 total, **2 from `.zft/sandbox/`**. That is both the dominant cost and an integrity hole.

## Proposed delta (v2 — verified)
1. **Extraction integrity + cache.** Ignore set matched on **any path component** (`.git`, `.venv`, `node_modules`, `.zft`, `__pycache__`) + per-file cache keyed `st_mtime_ns + size`, storing `sha256` on a miss. Verified: **4.58 s → 0.424 s**, 39 bindings, **0 non-source**; warm lookup < 1 ms. (Seconds-resolution mtime false-hits on same-size edits — use nanoseconds.)
2. **Single extraction pass + single L1 call.** `extract_bindings` runs 3× per `check` (`l2.py:38`, `l1.py:58`, `main.py:125`→`l1.py:58`). Share one extraction; drop the duplicate `run_l1`.
3. **Batch property verification.** One pytest session for all property clauses (`l1.py:114` runs one subprocess per clause). Verified: per-clause verdicts + isolation preserved, **0.26 s vs 1.29 s**.
4. **Mutation (H9 findings).** Own runner (`mutmut_runner.py`), not mutmut's engine. Two defects: `--scope` filters **attribution, not execution**; **surviving mutants do not red the campaign**. Fix: make scope an execution filter, parallelise mutant subprocesses, per-clause mutant budget + kill-on-first-survivor. `src/` has 291 mutants (~0.43 s each).
5. **Dispatch gate.** Keep `task-gate` thin (0.01 s); no daemon; optional LRU cache of contract loads.
6. **Language.** Python 3.12 is adequate — cost is filesystem walk + subprocess spawn, not interpreter speed. No rewrite.

## Budgets (verified / projected)
| Budget | Target | Actual |
|---|---|---|
| `lint` | < 100 ms | 50 ms |
| `task-gate` | < 50 ms | 10 ms |
| warm `extract` | < 0.5 s | **0.42 s** (verified) |
| fast `check` | ≤ 5 s | **≈ 0.4–0.5 s** after (1)+(2) (ESTIMATE from 14.7 s measured) |
| mutation campaign | bounded | needs (4) defects fixed; ESTIMATE |

## Alternatives
Rejected: Bazel/incremental build system (too heavy); commit-time index (fragile); persistent daemon (over-engineered); Rust rewrite (no measured need).

## Open questions
Ignore-file format; cache-invalidation policy (mtime_ns vs sha256 exactness); CPU-limited parallelism; whether `check` shares one extraction pass with `impact`.

## Validation checklist
- [ ] Ignore set + cache; warm extract < 0.5 s; no non-source bindings.
- [ ] One extraction pass + single `run_l1`.
- [ ] Property clauses verified in one pytest session.
- [ ] Mutation scope is an execution filter; survivors red the campaign; budget bounded.
- [ ] Perf regression asserts the budgets.

## Changelog
- v1, 2026-09-10 — measured bottlenecks, integrity hole, staged plan, budgets.
- v2, 2026-09-10 — folded verified evidence (H1, H6, H8, H9); corrected `check` to 14.7 s; added the 3× extraction, the `st_mtime_ns` cache key, and the two mutation defects.
