# Hypothesis Register — design verification loop

Every design proposal rests on hypotheses. Each is empirically verified before the design is trusted. **All experiments run in `/tmp/opencode/**` against the installed package — no implementation/codebase changes.** Rounds 1–2: 2026-09-10.

## Round 1 — results

| ID | Hypothesis | Result | Status |
|---|---|---|---|
| H1a | `extract_bindings` walks the whole tree with no ignore set and ingests non-source bindings | 5,268 candidate files (`.venv` 3,448, `.opencode` 1,697); parse **4.58 s**; 41 bindings, **2 from `.zft/sandbox/`** | **VERIFIED** |
| H1b | an ignore set cuts extraction < 0.5 s, removes non-source bindings | **0.424 s**, 39 bindings, 0 non-source (orchestrator re-ran) | **VERIFIED** |
| H1c | the ignore must match **any** path component | top-level-only 2.01 s vs any-component 0.45 s (nested `.opencode/node_modules` dominates) | **VERIFIED** |
| H2a | L1 never executes the oracle (presence-only) | fixture oracle writes a sentinel then raises; `run_l1` → `ok=True`, sentinel **absent** | **VERIFIED** |
| H2b | a consumer oracle can be executed < 0.2 s/clause | ~0.008 s (lane); **0.00–0.01 s** (orchestrator re-ran) | **VERIFIED** |
| H2c | anti-theater works (mutating the oracle flips the verdict) | correct+correct PASS; correct+wrong FAIL; mutated+correct FAIL | **VERIFIED** |
| H3a | dispatch gate blocks writer w/o contract, allows w/ it, audits | block/allow/override entries present (22 lines) | **VERIFIED** |
| H3b | dispatch gate is cheap | 0.01 s | **VERIFIED** |
| H4a | per-invocation pytest startup dominates; batching helps | ~7.36 s vs 0.26 s (30 trivial); 1.41 s vs 1.07 s (2 real); direction clear, magnitude caveated | **VERIFIED** (direction) |
| H5a | ISO citations were accurate | "29148:**2021**" wrong (2018); ReqIF "2.0" wrong (1.2) | **PARTIAL** |

## Round 2 — results

| ID | Hypothesis | Result | Status |
|---|---|---|---|
| H2d | a **gate-integrated** oracle runner (L1-shaped) makes producer-only `assert True` RED and flips a mutated oracle | correct+correct GREEN; wrong+correct RED; mutated+correct RED; no-oracle RED; per-oracle 10–15 ms | **VERIFIED** |
| H2f | a defined interface rejects malformed oracles | empty / wrong callable name / never imports the target → all RED (pre-execution guard) | **VERIFIED** |
| H6a | the ignore set cannot drop a legitimate binding | 49 `@trace` in `tests/` + 1 docstring mention in `src/`; ignored dirs hold only sandbox **copies** | **VERIFIED** |
| H6b | a per-file cache is correct across edits | `(mtime,size)` cache invalidates on edit; warm hit faster. Caveat: same mtime+size with changed content could false-hit — use `sha256` for exactness | **VERIFIED** (with caveat) |
| H7a | `check` invokes L1 **twice** | `l2.py:67` calls `run_l1`; `main.py:124-125` calls `run_l2` then `run_l1` again | **VERIFIED** |
| H8a | `check` phase breakdown | L0 0.004 s; **L2-fast 9.18 s** (includes internal L1); 2nd L1 **4.62 s**; gherkin 0.28 s; **full `check` ≈ 14.70 s** | **VERIFIED — corrects the earlier "minutes" claim** |
| H5b | 29148:2018 / ReqIF citations | 29148 clause numbers **WRONG** (§5.2 = fundamentals; attributes §5.2.8; traceability/verification/consistency not those numbers); ReqIF **1.2**, no "Section 4", traceability via `SpecRelation`; 26262 §8.4.6, DO-178C §11.1, DO-330 **ACCURATE** (secondary) | **PARTIAL** |

**Key correction.** `zft check` is **~15 s** on this repo, not minutes — the heavy minutes belong to the mutation campaign (`gate-campaign`). And extraction is invoked ~3× per `check` (`run_l2` + its internal L1 + the duplicate L1), which is why ~14 s ≈ 3 × 4.6 s. That makes the extraction ignore-set + cache (P-006 §1) and removing the duplicate L1 (P-006 §5) the highest-leverage perf fixes.

## Round 3 — open hypotheses

| ID | Hypothesis | Method |
|---|---|---|
| H2e | oracle verification batched into **one** pytest session keeps per-clause verdicts + anti-theater isolation | mutate 1 of 5 oracles in a single session |
| H6c | a realistic per-file cache's cold/warm times and false-hit behaviour | honest re-measurement (prior 0.4 ms was implausible) |
| H8b | projected `check` time after ignore-set + cache + single L1 | phase arithmetic on a repo copy |
| H5c | authoritative 29148:2018 clause numbers + ReqIF 1.2 traceability section | public TOC / secondary sources |

## Design implication so far

P-005 and P-006 rest on **verified** ground: the gate genuinely does not execute oracles today (H2a/H2d), executing one is cheap and yields a real anti-theater signal (H2b/H2c/H2f), extraction is both slow and unsound (H1a) and is fixable to < 0.5 s (H1b/H6a), and the perf target is far from "minutes" (H8a).

## Round 3 — results

| ID | Hypothesis | Result | Status |
|---|---|---|---|
| H2e | batched oracle session keeps per-clause verdicts + anti-theater isolation | 5 oracles in **one** session → per-clause verdicts; mutating 1 oracle fails **only** that clause; **0.26 s vs 1.29 s** (≈5×) | **VERIFIED** |
| H6c | per-file cache correctness / false-hits | key `st_mtime_ns + size` is safe for realistic edits; **seconds-resolution mtime false-hits** on same-size content change; store `sha256` on miss for certainty; warm lookup < 1 ms over 80 source files | **VERIFIED** (with key caveat) |
| H8b | extraction call count + projection | `extract_bindings` runs **3×** per `check` (`l2.py:38`, `l1.py:58`, and `main.py:125`→`l1.py:58`); projected `check` **≈ 0.4–0.5 s** after ignore-set + cache + single L1 (ESTIMATE) | **VERIFIED** |
| H5c | 29148:2018 / ReqIF citations | `docs/ISO-CONFORMANCE.md` corrected (objective-name labels + UNVERIFIED caveat; ReqIF **1.2**, `SpecRelation`) | **RESOLVED** |

## Loop status — converged for this hypothesis set

All 21 hypotheses across rounds 1–3 are resolved; every design-critical one is **VERIFIED with real measurements**. The verified design:

- **P-005 (conformance):** an **oracle-first, gate-executed** mechanism — L1 imports and runs a consumer-owned `oracle_<ALIAS>.py` `check()`; producer-only `assert True` becomes RED; mutating the oracle flips the verdict; malformed/empty/wrong-name oracles are rejected; execution is ~10–15 ms/clause and batchable (5×).
- **P-006 (performance):** an **ignore set** (any path component) drops extraction 4.58 s → 0.42 s and removes the non-source integrity hole; a `(st_mtime_ns, size)` per-file cache makes warm extraction < 1 ms; batching property verification into one pytest session is ~5× faster with per-clause isolation; removing the duplicate `run_l1` saves the third extraction. Projected `check` **≈ 0.4–0.5 s** (from 14.7 s).

## Round 4 — results (residual areas verified)

| ID | Hypothesis | Result | Status |
|---|---|---|---|
| H9 | mutation campaign cost is bounded by scope + parallelism + budget | `gate-campaign` on `matrix.py`: 1 mutant, ~0.55 s; **`--scope` is attribution-only, not an execution filter**; **survivors do not red the campaign** (`ok` = final verification run). `src/` has 291 mutants; ~0.43 s/mutant. Fixes: make scope an execution filter, run mutant subprocesses in parallel, per-clause mutant budget + kill-on-first-survivor | **VERIFIED** (with 2 defects found) |
| H10 | reverse coverage can be enforced without false positives | `list_all_elements` = 859 (476 py + 383 md). `matrix.py` compares against `b["file"]` → **file-granular only**; element ids make `elements_justified` structurally 0. Naive "flag all unbound" = **90% false positives**; **baseline-diff rule = 24 flags, 0 observed FPs** (new public `src` symbols since the contract baseline). All bindings live in `tests/`; `src/` has zero anchors | **VERIFIED / REFINED** |
| H11 | tool-confidence manifest + self-test is implementable and cheap | self-test runs the Gap-001 probe and correctly reports the gate is (still) GREEN on wrong work → **detects the regression** (~0.6 s); manifest hashes l1/l2/property_gen + tool versions (~0.12 s) | **VERIFIED** |
| H12 | principled oracle trust model replaces the H2f heuristic | contract- **pinned** consumer oracle: oracle sha in cache key + `evidence_refs`; changing oracle → cache miss + verdict flip; producer substitution → `L1_ORACLE_PIN_MISMATCH` (fault=producer); pin tamper → `L0_CONTRACT_HASH_DRIFT` (fault=contract). Without contract-hash verification a swapped trivial oracle passes (GREEN) → **the pin + contract-hash check is essential** | **VERIFIED** |
| H13 | non-code (Markdown) anchors extend `@trace` deterministically | `<!-- @trace("ALIAS") -->` above a heading yields a deterministic binding; rename-stable (comment is identity), move-tolerant, fence-safe, composes with `coverage_report`; real repo has 0 md anchors (only prose) | **VERIFIED** |

## Loop status — converged (rounds 1–4)

All 26 hypotheses resolved; **every design-critical one verified with real measurements**. The consolidated designs:

- **P-005 v2** — oracle-first, **contract-pinned**, gate-executed conformance; producer-only evidence is RED; anti-theater proven; H12 pin model replaces the H2f heuristic.
- **P-006 v2** — ignore-set + `(st_mtime_ns,size)` extraction cache (4.58 s → 0.42 s, and unsound → sound); batched property verification (5×); single L1 call; projected `check` **≈ 0.4–0.5 s** (from 14.7 s measured).
- **P-007** — reverse coverage via a baseline-diff rule (24 flags, 0 FP) + Markdown `@trace` anchors.
- **P-008** — permanent Gap-001 self-test + gate/tool manifest hashed into the attestation (tool confidence).

Two defects surfaced by H9 worth recording: `gate-campaign --scope` filters *attribution*, not *execution*; and surviving mutants do not make the campaign exit red.

## Round 5 — ISO / interchange results

| ID | Hypothesis | Result | Status |
|---|---|---|---|
| H14 | ReqIF 1.2 is implementable from public artifacts | official XSD fetchable live (`omg.org/spec/ReqIF/20110401/reqif.xsd`, 43,869 B) + `driver.xsd`; minimal subset defined (SPEC-OBJECT / SPEC-OBJECT-TYPE / ATTRIBUTE-VALUE-* / SPEC-RELATION) | **VERIFIED** |
| H17 | ReqIF import→export→import is identity-stable and deterministic | 2 requirements + 1 trace link; external `IDENTIFIER` round-trips exactly; **export byte-identical across 3 in-process and 3 separate processes** (sha256 `7d739ef0…`); imported nodes pass the repo's own `validate_node` schema. **FEASIBLE.** Lossy: `domain`, `version`, invariant `id/property/check` re-derived | **VERIFIED** (lossy fields noted) |
| H17a | ReqIF `IDENTIFIER` vs zft UUIDv7 / alias rules | ReqIF `IDENTIFIER` is `xsd:ID` = NCName: must **start with a letter or `_`**; zft UUIDv7 starts with a **digit** → cannot be used raw; prefix or use `ALTERNATIVE-ID`. Lowercase external ids also break traceagent's uppercase alias rule. A real Polarion export **fails strict XSD** (duplicate `xs:ID` in nested `SPEC-HIERARCHY`) → tolerant validation needed | **VERIFIED** (design constraints) |
| H16 | ALM bi-directional conflict model (halt, never silent overwrite) | disjoint edits **merge**; same-clause divergent edits **halt** with a typed `DeltaError` + field-level resolution diff; identical concurrent edits **also halt** (no silent overwrite); **deterministic** across 5 runs | **VERIFIED** |
| H18 | `external_links` is populated/used | schema-declared but **never populated** (every clause `[]`), excluded from `content_hash`, unused by any runtime component | **VERIFIED** (declarative-only) |
| H19 | `ATT-EXTERNAL-IMPORT` is implemented | **No importer exists**; `export` emits only dsse/matrix/summary; the clause is `kind: test` so its property ("preserves external identity") is **not enforced** → it is a placeholder | **VERIFIED** (unmet) |

## Loop status — rounds 1–5

All 31 hypotheses resolved. New proposal **P-009** consolidates the interchange findings: ReqIF 1.2 import/export is **feasible and identity-stable**, ALM halt-on-conflict is **already supported by the existing delta/conflict semantics**, but `external_links` is inert and `ATT-EXTERNAL-IMPORT` needs enforcement — which ties back to **P-005** (upgrade the clause to `kind: property` with a consumer oracle).



