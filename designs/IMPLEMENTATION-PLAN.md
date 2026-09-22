# Implementation Plan — zft v0 (v1.1, oracle-corrected)

> Status: planning only — **no implementation yet**. Ground truth: [ARCHITECTURE.md](ARCHITECTURE.md) (D1–D6), [VERIFIED-DESIGNS.md](VERIFIED-DESIGNS.md), contract store [`.zft/specs/`](../.zft/specs/) (26 clauses, PROPOSED).
> v1.1 changelog (oracle review): §7 lists 12 corrections; the material ones are the mutant-cost model re-derivation (v1.1 was optimistic ~10–50×), the coverage-gate vs deferred-clauses contradiction (would have kept CI red for 12 days), parallelization of WP-1 with consumer validation, the in-process-suite cost re-model, and the equivalent-mutant decidability wording fix.

---

## 0. Duration model (measured basis + corrected projections)

All numbers marked **measured** come from the `/tmp/traceagent-loop` lab; projections are marked and use the corrected cost model (§0.1).

| Operation | Measured | Basis | Checkpoint? |
| --- | --- | --- | --- |
| L0 contract lint (26 nodes) | <0.1 s | `tools/contract_lint.py` | no |
| EARS + DSL parse (26 clauses) | <0.05 s | v1b lab script, 100% compile | no |
| Property suite, 1 predicate × 200 examples | ~0.4 s incl. pytest boot; **in-process body ≈ 0.1–0.2 s** | V2 run | cache verdict |
| Gherkin fallback, 26 scenarios | 0.26 s | V3 run | no |
| ast-grep extraction, per file | ms-scale | V4 run | no |
| ast-grep extraction, ~5k-file repo | *projected* 5–15 s | benchmarked in C-19b before M3 exit | **yes** — per-file JSONL |
| mutmut campaign, 28 mutants / 45-line module | 1.1 s wall, 3.7 s user (≈3.4× fork parallelism) | V5 run | **yes** — per-mutant verdicts |
| **mutmut campaign, 500-line module** | **corrected projection: 3–15 min wall** (see model) | §0.1 | **yes** |
| **mutmut campaign, 5k-line module** | **corrected projection: 0.5–2.5 h** without scope filtering; ≪ with clause scoping | §0.1 | **yes + resumable + budget guard** |
| DSSE sign / verify | ms-scale | V8 run | no |
| Delta replay + conflict scan (26-clause store) | ms-scale | V9 run | no |
| a2a task round-trip (wire) | ms-scale | V7 run | no |
| Judge calls (L3, future) | seconds–minutes, non-deterministic | — | **yes — verdict cache keyed by (clause hash, payload digest, model id, prompt version)** |

### 0.1 Mutant-cost model (corrected — v1.1)

v1.1 naively extrapolated 39 ms/mutant linearly. **That number is wall-time per mutant on a module whose suite runs in-process and cheap; per-mutant cost is actually `mutant_setup + suite_body_time`, and suite body dominates as predicates/tests grow.** The corrected model:

```
wall(campaign) ≈ boot + mutants_in_scope × (suite_body_time / workers)   [kill-on-first-failure shortens most runs]
suite_body_time ≈ examples × example_time × tests_bound_to_clause        [examples is a tunable, not a constant]
```

Measured constants (V5/V2): boot ≈ 0.3 s per pytest invocation (amortized to ~0 by mutmut's in-process fork model); example_time ≈ 0.5–1 ms; fork parallelism ≈ 3.4× (POSIX fork — see risk R4).

**Worked projections** (26-clause contract, predicate-bound tests ≈ 6 tests × 200 examples):
- 500-line module: ≈310 in-scope-free mutants × (1.2 s / 3.4 workers) ≈ **2 min wall** (v1.1 claimed 12 s — wrong by ~10×; the claimed number ignored that suite_body_time, not boot, dominates).
- 5k-line module: ≈3.1k mutants → ≈**20 min wall** unscoped; with clause-scoped filtering (~30% in scope) ≈ **6 min**, with `examples` reduced to 50 on first pass ≈ **2–3 min**.

**Consequence baked into the plan:** the L2 gate treats full campaigns as the *escalation path*, not the default — L2-fast (examples=50, in-scope only) runs per commit; L2-full (examples=200+, all mutants) runs pre-merge or on survivors. This keeps the >5 min checkpoint tier rare.

**Benchmark guard (new, C-19b):** a `bench/` harness measures parse/codegen/extraction/per-mutant suite constants and asserts budget ceilings as tests. Projection drift becomes CI-red, not a surprise.

## 1. Debuggability model (binding) — corrected in three places

1. **Run ledger.** Every run gets `run_id` (UUIDv7) → `.zft/runs/<run_id>/`: `manifest.json` (tool versions, **git commit + dirty status**, seeds, input digests), `events.jsonl` (fsync every 50 events; **crash-safe: trailing partial line ignored on load**), `sandbox/` retained on failure.
2. **Typed rejections everywhere**: `{code, clause_ids, fault: contract|implementation|environment, expected, actual, evidence_refs, repro}` — human text generated from the object.
3. **Reproduction**: `zft repro <run_id>` re-runs only failed checks with pinned seeds; **repro checks out the manifest's git commit first** (v1.1 missed that a repro against a dirty/moved tree is a lie).
4. Pure cores + injected runners (unchanged).
5. Debug flags: `ZFT_LOG=debug`, `ZFT_KEEP_SANDBOX=1`, `--fail-fast`, `--trace-stage`.
6. **Self-dogfood with milestone scoping**: CI runs `zft check .` but evaluates only clauses whose `target_milestone` is ≤ current milestone (§3 WP-0 correction) — otherwise deferred clauses would keep CI permanently red.
7. **Cache placement (new)**: verdict cache lives in `.zft/cache/` and is *exported/imported by CI cache actions* keyed on lockfile + input-digest set; otherwise the L1 cache never pays off in CI (cold every run).

## 2. Repo layout (target) — unchanged from v1.0, plus

```
bench/          benchmark harness + budget tests (C-19b)   # NEW
```
and one correction: `tools/contract_seed.py` / `contract_lint.py` are **retained until WP-2 C-06 supersedes them**, then deleted in their own commit (atomic hygiene: migration and deletion are separate).

## 3. Work packages, commits, durations

Commit discipline unchanged: every commit green, one concern, ≤~400 lines, message cites clause IDs, refactors isolated. **Estimate honesty: each WP estimate carries ±50%; milestone boundaries (M0–M4) are go/no-go reviews with re-planning authority.**

### WP-0 — Contract finalization (consumer gate) — 0.5 h consumer time; **schedules in parallel, see dependency note**
| ID | Task | Clauses |
| --- | --- | --- |
| C-00 | Consumer review of 26 clauses; apply patch P1; **record deferrals in contract manifest meta: `target_milestone` per clause (TR-IMPACT-QUERY → v0.1, ATT-EXTERNAL-IMPORT → v0.1)**; a2a state-semantics corrections into D6 | all |

**Dependency correction:** WP-1 is clause-independent and proceeds **in parallel** with WP-0. Only WP-2's C-10 (patch application) and everything consuming clause content (WP-3+) gate on VALIDATED. v1.1 serialized these unnecessarily.

### WP-1 — Package bootstrap — 0.5 d (parallel with WP-0)
| ID | Deliverable | Notes |
| --- | --- | --- |
| C-01 | pyproject, src layout, pinned deps (ast-grep-py 0.45.3, mutmut 3.7.x, securesystemslib/in-toto 3.1.x, a2a-sdk exact pin, hypothesis, pytest, pytest-bdd) | pins required: lab observed breaking drift (in-toto models removal; a2a pydantic→protobuf) |
| C-02 | CI: ruff, pytest, property smoke, **CI cache import/export for `.zft/cache`** | §1.7 |
| C-03 | Run ledger skeleton — **with trailing-line recovery**; manifest records git commit + dirty + seeds | §1.1, §1.3 |

### WP-2 — Spec store productization — 1 d (needs VALIDATED from C-10 onward)
| ID | Deliverable | Verification | Clauses |
| --- | --- | --- | --- |
| C-04 | `spec/canon.py` §5.2 hash + golden vectors | golden (V9 fixtures) | ID-002 |
| C-05 | `spec/schema.py` (§5.1 + `target_milestone` in manifest meta), `identity.py` UUIDv7 | unit | ID-001 |
| C-06 | `spec/lint.py` + `store.py` + CLI `lint/create`; **delete superseded `tools/` scripts in this commit** | self-check on 26 | GATE-L0-HASH-VERIFY, GATE-DUPLICATE-CLAUSES |
| C-07 | `spec/delta.py` + `registry/conflicts.py` | V9 scenarios as integration tests | CON-AMEND-VIA-DELTAS, ID-CONFLICT-HALT |

### WP-3 — DSL v1 — 1.5 d
| ID | Deliverable | Verification | Clauses |
| --- | --- | --- | --- |
| C-08 | `dsl/ears.py` (5 EARS forms) | golden 26/26 (V1) | DSL-TRIGGER-PREDICATE-ENFORCEMENT |
| C-09 | `dsl/predicate.py` parser + **`DSL_VERSION` constant recorded into generated artifacts** | golden + round-trip property; 26/26 (V1b) | DSL-TRIGGER-PREDICATE-ENFORCEMENT |
| C-10 | **Apply consumer-approved P1** to `.zft/specs`; ledger records bumps | lint green | (store) |
| C-11 | `dsl/strategies.py` + **explicit non-expressible route to judge** | unit | DSL-COMPILE-GENERATORS, DSL-JUDGE-ESCAPE-HATCH |
| C-12 | `dsl/oracle.py` oracle-artifact generation **+ regression fixture: oracle-divergent mutant must be killed (the `expired_gt_to_lt` case)**; **key management note: dev keys via env/keystore, production key custody deferred** | V2 oracle fixture as regression test | GATE-EVIDENCE-KIND |

### WP-4 — Codegen — 1.5 d
| ID | Deliverable | Verification | Clauses |
| --- | --- | --- | --- |
| C-13 | `codegen/property_gen.py` (oracle-bound, derandomized, binder→strategy) | golden + V2 mini-module | DSL-COMPILE-GENERATORS |
| C-14 | `codegen/gherkin_gen.py` fallback | V3 fixture: 26/26 collect+pass | TR-FORWARD-COVERAGE (fallback) |
| C-15 | `gates/runners/pytest_runner.py` (timeout, durations, seeds) | unit w/ fake runner + smoke | GATE-EVIDENCE-KIND |
| C-16 | Sandbox `also_copy` manifest generated from predicate references | V5 lesson as integration test | GATE-MUTATION-ATTRIBUTION |

### WP-5 — Lineage + benchmarks — 2 d (**+0.5 d vs v1.1: C-19b added**)
| ID | Deliverable | Verification | Clauses |
| --- | --- | --- | --- |
| C-17 | ast-grep YAML rules + runner (per-language kinds) | V4 fixtures 5/5 | TR-UNRESOLVED-BINDINGS-FAIL |
| C-18 | `lineage/symbols.py` incl. wrapper descent | V4b move/rename tests | TR-IMPACT-QUERY |
| C-19 | `lineage/extract.py` CLI + per-file JSONL | determinism property (V4) | TR-DETERMINISTIC-EXTRACTION |
| **C-19b** | **`bench/` harness: parse, codegen, extraction, per-mutant suite constants; budget ceilings asserted as tests** | benchmarks run in CI nightly; regression = red | (design-gate for §0 model) |
| C-20 | `lineage/matrix.py` bi-directional coverage builder | unit + synthetic repo | TR-FORWARD-COVERAGE, TR-REVERSE-COVERAGE |

### WP-6 — Gates, checkpoints, survivors — 2.5 d
| ID | Deliverable | Verification | Clauses |
| --- | --- | --- | --- |
| C-21 | `gates/l0.py` with ledger events | self-check | GATE-L0-HASH-VERIFY, GATE-DUPLICATE-CLAUSES |
| C-22 | `gates/l1.py` verdict cache (digest-keyed; CI-cache import/export wired) | V2 fixture; cache-hit second run <50 ms | GATE-EVIDENCE-KIND |
| C-23 | `mutmut_runner.py`: scoped campaign, per-mutant events, resume; **worker count configurable; documented fork() POSIX constraint (observed deprecation warning) with subprocess-worker fallback** | V5 fixture + resume-after-kill test | GATE-MUTATION-ATTRIBUTION |
| C-24 | `gates/survivors.py` classifier — **output taxonomy corrected: {refinement-signal, other-clause, equivalent-suspect}** (equivalence is undecidable in general; suspects are *excluded from kill-rate denominators* and recorded, never auto-approved) | V5 fixtures: boundary → consumer routing; equivalent-suspect excluded from denominator | GATE-MUTATION-ATTRIBUTION |
| C-25 | `gates/l2.py` **two-tier: L2-fast (examples=50, in-scope, per commit) / L2-full (pre-merge)** + typed verdicts | mini-repo integration | TR-FORWARD-COVERAGE, TR-REVERSE-COVERAGE |
| C-26 | `debug/repro.py` — **checks out run's commit**, re-runs failed units only | injected-failure repro test | CON-TYPED-REJECTIONS |
| C-27 | `gates/l3.py` judge stub: quarantine + **model-dependence labeling unit test (same producer/gate model ⇒ coverage flagged model_dependent)**; **judge verdict cache per §0 row** | unit | GATE-JUDGE-QUARANTINE, GATE-MODEL-INDEPENDENCE |

### WP-7 — Attestation — 1 d
| ID | Deliverable | Verification | Clauses |
| --- | --- | --- | --- |
| C-28 | `attest/dsse.py` + predicate **`https://traceagent.dev/attestations/TraceManifest/v1`** (versioned URI constant; new predicate shape ⇒ new version) | V8 fixtures | ATT-SIGNED-ACCEPTANCE |
| C-29 | `cli attest` (binds contract version, clause hashes, tree hash, gate log, tools) | tamper test (V8) | ATT-SIGNED-ACCEPTANCE |
| C-30 | `cli export` — attested manifests only; **milestone-scoped coverage totals** | unit: refuses unattested run; deferred clauses excluded from due coverage | ATT-EXPORTS-FROM-ATTESTATIONS |

### WP-8 — Negotiation + a2a — 1.5 d
| ID | Deliverable | Verification | Clauses |
| --- | --- | --- | --- |
| C-31 | `negotiate/sm.py` 7-transition pure SM | V7 transition goldens; illegal transitions rejected | CON-VALIDATED-OR-NO-START, CON-COUNTER-RECORDED |
| C-32 | `negotiate/a2a_adapter.py` **+ malformed-payload typed-rejection tests** (V7 verified happy path only) | V7 wire round-trip + negative tests | PRT-A2A-ENVELOPE |
| C-33 | CLI `negotiate` flows updating status + history | scripted negotiation → VALIDATED | CON-VALIDATED-OR-NO-START |
| C-34 | Retry loop: rejection → INPUT_REQUIRED → revise → accept (bounded) | integration cycle test | CON-TYPED-REJECTIONS |

### WP-9 — Self-dogfood — 1 d
| ID | Deliverable | Verification |
| --- | --- | --- |
| C-35 | `zft check .` milestone-scoped, in CI (L2-fast tier) | pipeline green on itself |
| C-36 | First real findings routed as refinement signals | ledger shows classification + routing |
| C-37 | Runbooks (run/resume/repro), decision-log statuses → Implemented | docs review |

## 3bis. Coverage-gate scoping rule (correction — resolves the v1.1 contradiction)

Self-dogfood CI would have failed forever on `TR-IMPACT-QUERY` and `ATT-EXTERNAL-IMPORT` (VALIDATED-but-stretch clauses with no implementation). Rule introduced: every clause carries `target_milestone` in contract manifest meta; `zft check` evaluates coverage **only over clauses due at or before the current milestone**; deferred clauses appear in the attestation under `deferred` (visible, auditable, non-blocking). A clause due at M-n that is not covered by M-n is CI-red — deferral requires a manifest amendment, never silence.

## 4. Milestones (±50% estimate honesty)

| Milestone | Contents | Duration (cum.) | Go/no-go review |
| --- | --- | --- | --- |
| M0 | WP-0 validation **(parallel)** + WP-1 bootstrap | 0.5 d | pins + CI green |
| M1 | WP-2 + WP-3 — store & DSL, 100% corpus compile, P1 applied | 3 d | golden tests stable |
| M2 | WP-4 + WP-5 — codegen & lineage, **benchmarks within budgets** | 6 d | budget test green |
| M3 | WP-6 — gates with checkpoint/resume/repro | 8.5 d | resume + repro demos pass |
| M4 | WP-7 + WP-8 + WP-9 — attestation, negotiation, self-dogfood | 12 d | self-check green; v0 definition-of-done below |

**v0 definition-of-done (exit criteria):** (a) CI `zft check .` green (milestone-scoped); (b) every VALIDATED clause covered {implemented | deferred-with-record}; (c) repro demonstrates injected-failure recovery; (d) benchmark budgets green; (e) at least one real survivor routed through the full taxonomy to the consumer.

## 5. Risk register (adds R6–R8)

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| a2a-sdk protobuf churn | high (observed) | exact pin; only `a2a_adapter.py` may import it |
| ast-grep grammar drift | medium (observed) | declarative YAML rules; V4 fixtures gate regressions |
| mutmut sandbox vs oracle artifacts | medium (observed) | generated `also_copy` manifest |
| **fork() portability** (mutmut parallelism is POSIX; deprecation warning observed in lab) | medium | worker count configurable; subprocess-worker fallback; L2 runner isolated behind runner interface |
| **mutant-cost model drift** (v1.1 was 10–50× optimistic) | high until C-19b | benchmark guard asserts budgets; projections re-derived from measured constants, not assumptions |
| hypothesis derandomize vs cache validity | medium | seed part of cache key |
| scope creep in DSL grammar | medium | grammar frozen to corpus needs; new form ⇒ failing golden test first |
| **consumer-validation stall** (WP-0 blocks WP-2+) | medium | WP-1 parallelized; bootstrap cannot violate clause semantics |

## 6. Explicitly out of scope for v0
LLM-judge implementations (stub + quarantine only) · ReqIF/ALM export (strictdoc spike separate) · automated multi-model independence enforcement (labeling only) · autonomous negotiation agents (human/script-driven CLI; LLM hooks are stubs) · production key custody (dev env keys only).

## 7. Oracle-review correction log (v1.0 → v1.1)

| # | Finding (what would have gone wrong) | Correction |
| --- | --- | --- |
| 1 | Mutant-cost projections linear in 39 ms/mutant ignored that in-process **suite body time** dominates as tests grow → L2 durations optimistic ~10–50× | §0.1 re-derived cost model; two-tier L2-fast/L2-full; worked projections corrected |
| 2 | No benchmark task — duration model had no enforcement mechanism | C-19b `bench/` budget tests |
| 3 | **Self-dogfood CI contradiction**: deferred stretch clauses (TR-IMPACT-QUERY, ATT-EXTERNAL-IMPORT) would fail coverage forever | §3bis milestone scoping + `target_milestone` manifest field; deferrals recorded at WP-0 |
| 4 | WP-1 needlessly serialized behind consumer validation | parallelized; only C-10+ gates on VALIDATED |
| 5 | "Equivalent mutant" classification overclaimed (undecidable in general) | taxonomy becomes equivalent-**suspect**; excluded from denominators, recorded, never auto-approved |
| 6 | Ledger crash-consistency: partial trailing JSONL line on crash | recovery rule in C-03 |
| 7 | Repro against moved/dirty tree is unreliable | manifest records git commit + dirty; repro checks out |
| 8 | L1 cache useless in CI without cache persistence | §1.7 CI cache import/export keyed on lockfile + digests |
| 9 | mutmut fork() is POSIX-only (deprecation warning observed) | risk R4 + configurable workers + subprocess fallback |
| 10 | C-12 oracle design had no regression test tying it to the V2 failure | oracle-divergent-kill fixture required in C-12 |
| 11 | GATE-MODEL-INDEPENDENCE labeling logic untested; judge verdicts not checkpointed | C-27 labeling unit test + verdict cache per §0 |
| 12 | Tools migration and deletion mixed into one commit | deletion split into its own atomic commit (C-06 note) |
