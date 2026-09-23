# Implementation Plan v2 — Verified Design Set (P-005…P-011)

**Status**: PLAN (proposed; no implementation yet) · **Date**: 2026-09-11
**Revision**: v2.1 — critically reviewed (`ora-3`); valid corrections applied, invalid advice rejected (§10).
**Baseline**: design baselines `designs/IMPLEMENTATION-PLAN.md` (v0) and `designs/ARCHITECTURE.md` (v0) stay **frozen**. The **contract is intentionally mutable** (`.zft/`) — it is the plan's target, not a frozen design baseline. This plan is additive.

---

## 0. Scope, inputs, non-goals

**Scope.** Implement the verified design set: P-006 (runtime/perf), P-005 (oracle-first conformance), P-007 (reverse coverage + non-code anchors), P-008 (gate self-verification), P-009 (ReqIF/ALM interchange), P-011 (human↔AI contract), and finally **promote the already-materialized `ai-conduct` clauses** (P-010) from deferred to enforced.

**Inputs.** `designs/proposals/HYPOTHESES.md` (all measured), `docs/RUNBOOK.md` (existing checkpoint/debug), `designs/ARCHITECTURE.md` (D1–D6), `docs/AI-REQUIREMENTS.md`, and the code seams: `gates/l0-l3.py`, `lineage/extract.py`, `lineage/matrix.py`, `gates/runners/mutmut_runner.py`, `debug/ledger.py`, `debug/repro.py`, `cli/main.py`, `negotiate/sm.py`, `attest/dsse.py`, `spec/store.py`.

**Current state (do not re-plan).** The features below **do not exist yet** — that is the premise of this plan, not a defect. Already done: `ai-conduct` clauses (10 `PROPOSED` nodes, registered, **deferred to `v1`**; `check` green 40 nodes / 29 due / 29-29), and dispatch enforcement (P-001). There is **no** "create clauses" work — only **promotion**.

**Non-goals.** UI beyond the `approve` command; non-Python/Rust/TS extraction languages; multi-contract merging (loader takes the last contract alphabetically — `spec/store.py:41`); a persistent daemon; dispatcher-table refactors.

---

## 1. Execution principles

1. **TDD** — each WP starts with a failing test that encodes the observable (e.g. missing oracle → `L1_ORACLE_PIN_MISMATCH`).
2. **Test scaffolding first** — the test file for a WP lands (failing) before its implementation; for shared-file waves, add temporary no-op stubs so intermediate commits stay green.
3. **Atomic commits** — one logical change per commit; after each commit the **targeted tests + `lint`** are green. Full suite runs at **wave boundaries** (≈192 s — see §4).
4. **Contract-first** — the gate's own changes are governed by the `ai-conduct` clauses; "presence is not evidence" applies to our own work.
5. **Checkpoint everything long** — any run > ~10 s must be resumable.
6. **Determinism** — fixed seeds; ledgers record git commit, seeds, tool versions.

---

## 2. Dependency-ordered waves

```
Wave A (foundation, perf)   P-006a  extraction ignore-set + cache + single extraction   (speeds all)
Wave B (conformance core)   P-005   oracle-pin + execute + batch + cache identity       ← linchpin
Wave C (mutation correctness) P-006b scope→execution, survivors red, resume, repro-mutants
Wave D (coverage)           P-007   D1 enumerate → D2 reverse coverage → D3 md anchors
Wave E (tool confidence)    P-008   Gap-001 self-test (passes after B) + gate manifest
Wave F (interchange)        P-009   ReqIF import/export + external_links + ALM halt
Wave G (human↔AI)           P-011   schema + SM approval + CLI + attestation + subjective quarantine
Wave H (promotion)          P-010   upgrade ai-conduct clauses to kind:property + remove v1 deferrals
```

Edges: **A → all** (speed only; not a correctness dependency); **D1 → D2**; **B → E1** (self-test flips GREEN after B); **{A…G} → H**. Waves C, F, G are independent of each other. Wave H is last: it flips the requirements to gating, so the gate goes green *only because* A–G satisfied them.

---

## 3. Work packages

Durations are **effort** estimates; *(run)* = measured command runtime unless **EST**.

### Wave A — P-006a · extraction integrity + cache · *governing clause:* `AI-SOURCE-SCOPE`
| WP | Goal | Files | Test (fail→green) | Commit | Effort | Run |
|---|---|---|---|---|---|---|
| A1 | Ignore set matched on **any path component** (`.git/.venv/node_modules/.zft/__pycache__`) | `lineage/extract.py` | `test_extract_ignore` — cold ≤0.5 s, **0** non-source bindings | `feat: source-scoped binding extraction` | ~0.5 d | 4.58 s → **0.42 s** *(run)* |
| A2 | Per-file cache `st_mtime_ns+size → bindings` (sha256 on miss) | `lineage/extract.py` | `test_extract_cache` — warm hit; edit invalidates; contract-version change invalidates | `perf: per-file extraction cache` | ~0.5 d | warm **<0.01 s** *(run, EST)* |
| A3 | One extraction pass; drop duplicate `run_l1` (`main.py:124-126`; `run_l2` already runs L1) | `cli/main.py` | `test_single_extraction` — `extract_bindings` called exactly once | `refactor: single extraction pass in check` | ~0.3 d | `check` 14.7 s → **≈0.5 s** *(run, EST)* |

### Wave B — P-005 · oracle-first conformance · *governing clauses:* `AI-EXECUTED-EVIDENCE`, `AI-INDEPENDENT-ORACLE`, `AI-CONTRACT-PIN`
| WP | Goal | Files | Test (fail→green) | Commit | Effort | Run |
|---|---|---|---|---|---|---|
| B1 | Contract pins the oracle (`oracle_file` + `oracle_sha256` in schema); L1 verifies **before** execution | `spec/schema.py`, `gates/l1.py` | `test_oracle_pin` — mismatch → `L1_ORACLE_PIN_MISMATCH` (fault=producer) | `feat: contract-pinned oracle` | ~1 d | ~0.01 s *(run)* |
| B2 | L1 **executes** `oracle_<ALIAS>.py:check()`; producer-only evidence → RED; records `evidence_refs` (oracle/suite/contract hashes) | `gates/l1.py` | `test_oracle_exec` — correct→GREEN, wrong impl→RED, mutated oracle→RED | `feat: execute consumer oracle in L1` | ~1.5 d | ~10–15 ms/clause *(run)* |
| B3 | Batch oracle checks into **one** pytest session (per-clause verdicts preserved) | `gates/l1.py`, `gates/runners/pytest_runner.py` | `test_oracle_batch` — 5 oracles, mutate 1, only that clause reds; ≤0.3 s | `perf: batched oracle verification` | ~1 d | **0.26 s / 5** *(run)* |
| B4 | Contract-manifest hash verified at gate entry (drift → `L0_CONTRACT_HASH_DRIFT`) | `gates/l0.py` | `test_contract_drift` | `feat: contract hash drift detection` | ~0.5 d | negligible |
| B5 | `_cache_key` extended to include **gate source hash + `DSL_VERSION` + contract hash** (invalidate on gate/clause change) | `gates/l1.py` | `test_cache_identity` — a gate change forces a cache miss | `fix: cache key binds gate and contract identity` | ~0.5 d | negligible |

### Wave C — P-006b · mutation correctness (H9 defects) · *governing clause:* `AI-EXECUTED-EVIDENCE`
| WP | Goal | Files | Test (fail→green) | Commit | Effort |
|---|---|---|---|---|---|
| C1 | `--scope` becomes an **execution filter** (today attribution-only; `mutmut_runner.py:118-120`) | `gates/runners/mutmut_runner.py` | `test_scope_execution` — out-of-scope mutants are not run | `fix: mutation scope filters execution` | ~1 d |
| C2 | **Surviving mutants red the campaign** (`ok` currently = final verification only, `:158`); survivors recorded in attestation | `mutmut_runner.py`, `gates/l2.py` | `test_survivors_red` — a survivor ⇒ `ok=False` | `fix: mutation survivors fail the campaign` | ~0.5 d |
| C3 | Optional parallel mutant subprocesses + per-clause budget | `mutmut_runner.py` | `test_mutant_budget` | `perf: bounded parallel mutation` | ~1 d |
| C4 | **Checkpoint stores `in_scope` + outcome**; wire `--resume` through CLI (`main.py` currently passes only defaults) | `mutmut_runner.py`, `cli/main.py` | `test_resume_scope_counts`, `test_gate_campaign_resume` | `feat: resumable, scope-aware mutation campaign` | ~1 d |
| C5 | `repro` **re-runs failed mutants** from the ledger (today only L0/L1, `repro.py`) | `debug/repro.py` | `test_repro_mutants` | `feat: repro re-runs failed mutants` | ~0.5 d |

### Wave D — P-007 · reverse coverage + non-code anchors · *governing clauses:* `AI-REVERSE-COVERAGE`, `AI-NONCODE-ANCHOR`
| WP | Goal | Files | Test | Commit | Effort | Run |
|---|---|---|---|---|---|---|
| D1 | `list_all_elements` (Python defs/classes + Markdown headings) | `lineage/matrix.py` | `test_list_all_elements` — 859 elements | `feat: enumerate deliverable elements` | ~1 d | ~0.02 s |
| D2 | `(file,symbol)`-granular `coverage_report`; baseline-diff rule (24 flags / 0 FP); file-gate backstop | `lineage/matrix.py`, `gates/l2.py`, `.zft/baseline/` | `test_reverse_coverage` — a new public unbound symbol reds | `feat: baseline-diff reverse coverage` | ~1.5 d | <0.1 s |
| D3 | Markdown `<!-- @trace("ALIAS") -->` anchors (fence-safe, rename-stable) | `lineage/extract.py` | `test_md_anchor` — deterministic; survives rename/move | `feat: Markdown @trace anchors` | ~1 d | negligible |

### Wave E — P-008 · tool confidence · *governing clause:* `AI-TOOL-CONFIDENCE`
| WP | Goal | Files | Test | Commit | Effort | Run |
|---|---|---|---|---|---|---|
| E1 | Permanent **Gap-001 self-test**: runs the adversarial **probe fixture** and asserts the gate returns RED; flips GREEN after B | `tests/unit/test_gate_self.py` | `test_gate_self` | `test: gate self-verification (Gap-001)` | ~0.5 d | **0.6 s** |
| E2 | Gate manifest (sha256 of `gates/l1.py`, `l2.py`, `codegen/property_gen.py` + tool versions) embedded in the DSSE attestation; `verify` checks it | `attest/dsse.py` | `test_gate_manifest`, `test_verify_manifest` | `feat: gate source manifest in attestation` | ~0.5 d | **0.12 s** |

### Wave F — P-009 · interchange · *governing clause:* `AI-EXTERNAL-IDENTITY`

> **Enterprise extraction (2026-09-11):** Wave F shipped as ReqIF certification
> export/import + enterprise ALM connectors, then was **moved out of the
> open-source package** into the proprietary tree: `private/enterprise/zft/reqif/`,
> `private/enterprise/zft/alm/`, tests under `private/enterprise/tests/`
> (`test_reqif_import.py`, `test_reqif_export.py`, `test_reqif_ids.py`,
> `test_alm_sync.py`). The `zft sync` CLI command and the `reqif` export
> format were removed from the public `zft` package.

| WP | Goal | Files | Test | Commit | Effort | Run (EST) |
|---|---|---|---|---|---|---|
| F1 | ReqIF 1.2 import → clause nodes; populate `external_links` | `reqif/importer.py` (new) | `test_reqif_import` | `feat: ReqIF 1.2 import` | ~1.5 d | ~0.2 s |
| F2 | ReqIF export (from attested manifest); XSD-validated | `reqif/exporter.py`, `attest/export.py` | `test_reqif_export` — round-trip byte-identical | `feat: ReqIF 1.2 export` | ~1.5 d | ~0.15 s |
| F3 | Identifier normalization (prefix digit-leading UUIDs; NCName) + tolerant validation mode | `reqif/*` | `test_reqif_ids` | `fix: ReqIF identifier normalization` | ~1 d | negligible |
| F4 | ALM bi-directional merge (reuse `spec/delta.py` + `registry/conflicts.py`); halt-on-conflict | `alm/sync.py` (new) | `test_alm_conflict` — divergent halt w/ typed diff; deterministic | `feat: halt-on-conflict ALM merge` | ~1.5 d | negligible |

### Wave G — P-011 · human↔AI contract · *governing clauses:* `AI-HUMAN-APPROVAL`, `AI-SUBJECTIVE-QUARANTINE`
| WP | Goal | Files | Test | Commit | Effort |
|---|---|---|---|---|---|
| G1 | Optional schema fields: clause `author`, `subjective`; contract `approval` | `spec/schema.py` | `test_schema_extension` | `feat: human-AI contract schema fields` | ~0.5 d |
| G2 | `NegotiationSM.human_approve(sig,keyid)`; `validate()` requires it | `negotiate/sm.py` | `test_human_approve` | `feat: signed human approval transition` | ~1 d |
| G3 | CLI `zft approve --key --sig`; `create --author-*` | `cli/main.py` | `test_cli_approve` | `cli: approve command` | ~1 d |
| G4 | Attestation embeds `approval`; `verify` checks trusted human keys | `attest/dsse.py` | `test_attest_approval` | `attest: include human approval` | ~0.5 d |
| G5 | Subjective clause without approval → uncovered (`judge_gated`) | `gates/l2.py` | `test_subjective_quarantine` | `gate: quarantine subjective clauses` | ~0.5 d |

### Wave H — P-010 · promote `ai-conduct` clauses to enforced · *all 10 clauses*
| WP | Goal | Files | Test | Commit | Effort |
|---|---|---|---|---|---|
| H1 | Upgrade `ai-conduct` clauses `kind: test` → `kind: property`; author **real** consumer oracles `oracle_AI-*.py` implementing each requirement | `.zft/specs/ai-conduct/*.json`, `.zft/oracles/*` | per-clause oracle tests (correct→GREEN, mutated oracle→RED) | `feat: enforceable AI-conduct clauses` | ~2 d |
| H2 | **Remove the `v1` deferrals** so the 10 clauses become `due` (leave `ATT-EXTERNAL-IMPORT` deferred) | `.zft/contracts/traceagent-v0.json` | `check` green **because met**; `test_check_green_on_repo` expects **due = 39** | `chore: promote AI-conduct clauses to due` | ~0.3 d |

---

## 4. Run durations & checkpointing

| Step | Runtime | Long? | Checkpoint / resume |
|---|---|---|---|
| Extraction (cold) | **0.42 s** | no | per-file cache `.zft/cache/extract.json`; invalidate on contract-version change |
| Extraction (warm) | <0.01 s (EST) | no | cache hit |
| `lint` | 0.05 s | no | pure |
| L1 oracle (per clause) | **10–15 ms** | no | `.zft/cache/l1/<alias>.json`, key now binds oracle+gate+contract identity (B5) |
| L1 oracle (batch of ~N) | **0.26 s / 5** | no | same cache |
| `check` (fast) | 14.7 s → **≈0.5 s** (EST) | no | single run ledger |
| **Mutation campaign** (291 mutants × ~0.43 s) | **≈125 s** | **YES** | `.zft/cache/mutants.json`; **C4** adds `in_scope` to each entry and wires `--resume` through the CLI so a resumed run recomputes scope counts correctly; kill-on-first-survivor budget bounds worst case |
| **Full pytest suite** (308 tests) | **≈192 s** | **YES** | not checkpointable — run **only at wave boundaries**; per-commit runs the targeted subset; optionally `pytest -x`/shard/`pytest-xdist` |
| Gate self-test (Gap-001) | **0.6 s** | no | deterministic |
| Gate manifest | **0.12 s** | no | in `.zft/attest.json` |
| ReqIF import/export | ~0.2 / ~0.15 s (EST) | no | snapshot under `.zft/reqif/` |
| Human approval | negligible | no | approval block in contract JSON |

**Rule:** the two long runs are the **mutation campaign** (checkpointed, C4 makes resume correct) and the **full test suite** (wave boundaries only). Every run writes `.zft/runs/<run_id>/` (`manifest.json` + `events.jsonl`, fsync every 50; torn tails ignored).

---

## 5. Debuggability plan

- **Distinct typed rejections** (each with `clause_ids`): `L1_ORACLE_PIN_MISMATCH`, `L1_ORACLE_FAIL`, `L0_CONTRACT_HASH_DRIFT`, `L2_REVERSE_COVERAGE`, `L2_SUBJECTIVE_UNQUARANTINED` — not just the generic `L1_PROPERTY_EVIDENCE`.
- **Ledger events**: `extract_done`, `cache_hit`/`cache_miss`, `oracle_exec` (+ `oracle_executed: true` on the clause event), `mutant_verdict` (with `in_scope`), `gate_manifest_created`.
- **`repro <run_id>`**: re-execute failed units; **C5** extends it to failed mutants.
- **`ZFT_LOG=debug`** per-decision logging; **`ZFT_KEEP_SANDBOX=1`** retains the mutation sandbox for autopsy.
- **Determinism**: fixed seeds; **B5** binds the L1 cache key to gate + contract identity so a code/contract change invalidates stale verdicts.
- **`--dry-run`** on `check`/`approve`.
- **Gate self-test** (E1): runs the probe **fixture** (a property clause `answer()==42` with impl `41` + producer `assert True`); the gate is GREEN on it today, so the self-test **detects the regression**; after B it goes GREEN-as-passing.

---

## 6. Atomic commit sequence (flattened, ordered)

**A** 1. `feat: source-scoped binding extraction` · 2. `perf: per-file extraction cache` · 3. `refactor: single extraction pass in check`
**B** 4. `feat: contract-pinned oracle` · 5. `feat: execute consumer oracle in L1` · 6. `perf: batched oracle verification` · 7. `feat: contract hash drift detection` · 8. `fix: cache key binds gate and contract identity`
**C** 9. `fix: mutation scope filters execution` · 10. `fix: mutation survivors fail the campaign` · 11. `perf: bounded parallel mutation` · 12. `feat: resumable, scope-aware mutation campaign` · 13. `feat: repro re-runs failed mutants`
**D** 14. `feat: enumerate deliverable elements` · 15. `feat: baseline-diff reverse coverage` · 16. `feat: Markdown @trace anchors`
**E** 17. `test: gate self-verification (Gap-001)` · 18. `feat: gate source manifest in attestation`
**F** 19. `feat: ReqIF 1.2 import` · 20. `feat: ReqIF 1.2 export` · 21. `fix: ReqIF identifier normalization` · 22. `feat: halt-on-conflict ALM merge`
**G** 23. `feat: human-AI contract schema fields` · 24. `feat: signed human approval transition` · 25. `cli: approve command` · 26. `attest: include human approval` · 27. `gate: quarantine subjective clauses`
**H** 28. `feat: enforceable AI-conduct clauses` · 29. `chore: promote AI-conduct clauses to due`

Invariant per commit: `lint` + that WP's tests green. For shared files (`l1.py` B1–B3/B5; `cli/main.py` A3/C4/G3), land the test first and use temporary no-op stubs so each intermediate commit is green and independently revertible. Full suite at wave boundaries. Total: **29 commits**.

---

## 7. Verification & acceptance

| Wave | Acceptance |
|---|---|
| A | cold extract ≤0.5 s, **0** non-source bindings; `extract_bindings` called once; `check` ≤5 s |
| B | probe fixture → **RED**; correct oracle+impl → GREEN; mutating the oracle flips; substitution → `L1_ORACLE_PIN_MISMATCH`; pin tamper → `L0_CONTRACT_HASH_DRIFT`; gate change invalidates cache (B5) |
| C | out-of-scope mutants not executed; any in-scope survivor ⇒ `ok=False`; resume recomputes scope counts; `repro` re-runs failed mutants |
| D | `list_all_elements` = 859; baseline-diff = 24 flags / 0 FP; new public unbound symbol reds; md anchors deterministic |
| E | self-test detects the regression pre-B, passes post-B; attestation carries the gate manifest and `verify` checks it |
| F | ReqIF round-trip identity-stable + byte-identical; `external_links` populated; ALM conflict halts with typed diff |
| G | `validate()` requires a signed human approval; subjective-without-approval is uncovered; `verify` rejects the wrong key |
| H | `check` green with the 10 clauses **due (because met)**; `test_check_green_on_repo` expects **due = 39**; AI-conduct clauses executed via real oracles |

**End-to-end:** on a clean repo, `zft check .` → `ok:true`, **`due` = 39** (`ATT-EXTERNAL-IMPORT` remains the only deferred clause), coverage 39/39, gate manifest (+ human approval where applicable) in the attestation.

---

## 8. Risk register

| ID | Risk | Mitigation / rollback |
|---|---|---|
| R1 | `--scope` filters attribution, not execution (H9) | C1 makes it an execution filter; test asserts out-of-scope mutants don't run |
| R2 | Survivors don't red the campaign (H9) | C2 makes survivors fatal; recorded in attestation |
| R3 | Stale extraction/oracle cache | cache key binds contract version + gate hash + oracle digest (B5, A2) |
| R4 | Oracle pin drift (valid oracle rejected) | validate oracle hash when contract flips `VALIDATED` |
| R5 | Human key loss | trusted-key registry `.zft/trusted_keys.json` + `trust-add` CLI, audited |
| R6 | Markdown anchor edge cases (fences, escapes) | anchor only on comment lines; unit tests for fences/escapes |
| R7 | ReqIF identifier collisions / digit-leading UUIDs | `R_`/`RA_` prefix + NCName-safe normalization; tolerant mode |
| R8 | Perf regression reintroduced | CI perf test asserts `check` ≤5 s and single extraction |
| R9 | Multi-contract loader ambiguity (`store.py:41`) | keep AI-conduct items in `traceagent-v0`; H2 edits in place (no new contract file) |
| R10 | Resume silently loses scope counts / `--resume` unwired | C4: scope-aware checkpoint schema + CLI `--resume`; tests |
| R11 | Large waves touch shared files → red intermediate commits | test-first + no-op stubs; targeted green per commit; full suite at wave boundaries |
| R12 | Placeholder/fake oracles reintroduced (anti-theater) | H1 requires **real** oracles; the E1 self-test and mutated-oracle test catch fakes |

Rollback: revert the offending atomic commit; each commit is individually green.

---

## 9. Out of scope

Persistent extraction daemon; additional languages; full multi-contract merge semantics; production key custody; autonomous LLM-in-the-loop negotiation; production-grade mutation parallelism beyond the bounded budget; CLI dispatcher-table refactors.

---

## 10. Critical review log (ora-3, 2026-09-11)

**Accepted** — genuine gaps in v2 folded in:
1. `--resume` unwired in the CLI → **C4**.
2. Checkpoint `mutants.json` lacks `in_scope` → **C4**.
3. `_cache_key` does not bind gate/contract identity → **B5**.
4. `repro` cannot re-run failed mutants → **C5**.
5. Distinct typed rejection codes + `oracle_executed` ledger flag → §5.
6. `verify` should check the manifest / coverage → **E2/§7**.
7. Baseline-freeze wording (contract is mutable) → header/§0.
8. Shared-file commits need stubs to stay green → §1/§6.

**Rejected** (wrong or harmful):
1. **"Add placeholder oracles that return `True`" (H1).** Rejected outright — this is exactly the fake-oracle anti-theater the whole design exists to prevent. H1 requires **real** oracles that fail when mutated.
2. **"After promotion `due` = 40."** Wrong: `ATT-EXTERNAL-IMPORT` stays deferred to `v0.1`, so **due = 39** (40 nodes − 1 deferred). The plan's 39 is correct.
3. **"Wave C depends on Wave B."** Mutation correctness is independent of oracle execution; no edge.
4. **"F depends on E" / "G depends on F for `external_links`."** Spurious — interchange exposes `external_links`; the human↔AI wave is orthogonal.
5. **"Renaming the promoted contract file."** No new contract is created; H2 edits `traceagent-v0.json` in place.
6. **Structural refactors (dispatcher table, new cache/pin packages).** Optional; out of scope (§9).
7. Most "CRITICAL: feature X does not exist" items are **restatements of the plan's own WPs**, not defects — the plan's premise is that these features are to be built.

---
*Prepared 2026-09-11. Runtimes measured from `designs/proposals/HYPOTHESES.md` unless marked EST. No implementation performed.*

---

## 11. Execution progress (2026-09-11)

Baseline: `082b71d` (pre-plan working state, scratch excluded). All commits below are TDD + verified (lint + check green at each).

**Wave A — done:** `33c709e` A1 · `b970637` A2 · `1889b9c` A2b · `863279a` A3. Effect: extract 4.5 s → 0.02 s warm; `check` 14.7 s → **≈0.4 s**.

**Wave B — done:** `1153bfa` B1 pin · `53f0993` B2 execute consumer oracle · `ba20641` L1 evidence_refs · `b6eab5e` B3 batch · `8aab683` B3b all-oracles-run (no fail-fast) · `11d192f` B4 contract-hash drift · `a4716a2`+`8b0e506` B5 cache-key identity. Anti-theater verified on the real corpus.

**Wave C — C1–C4 done, C5 deferred:** `ac26622` C1 scope is an execution filter · `5e1d719` C2 survivors red · `62b88b0` C3 bounded budget + fail-fast · `4a552be` C4 scope-aware checkpoint + CLI `--resume`.
- **True mutation parallelism deferred** (C3): shared module file → unsafe concurrency without per-worker sandboxes; budget + fail-fast shipped instead.
- **C5 deferred**: replaying a campaign needs the run manifest to record `module` + `tests` + `scope`; add that before C5.

Also `2fd719a` fixed a pre-existing red test (`test_store_golden` accepts valid non-`VALIDATED` statuses). Repo full suite green.

**Remaining:** C5 · D · E · F · G · H.
**Known enforcement gap:** the dispatch plugin gates only the `task` tool; **direct orchestrator writes (`edit`/`write`/`bash`) are not contract-gated in-session** (only at commit/push via hooks). See P-001 open question.
