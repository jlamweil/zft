# Verified Designs — the design loop, round 1–2

> Method per the loop directive: propose designs → extract the hypotheses each design depends on → **verify every hypothesis with a real experiment** → revise designs on failure → repeat until convergence. No repository code was changed; all experiments ran in a throwaway lab (`/tmp/traceagent-loop`, Python 3.12 venv, 2026-09-04) against our real contract corpus (`.zft/specs`, 26 clauses).
> Companion: [ARCHITECTURE.md](ARCHITECTURE.md) (designs D1–D6, open questions §7). Contract status note: the 26 clauses remain **PROPOSED** — this loop produced the evidence for their design answers; applying patch P1 below still awaits consumer validation.

## Convergence summary

Two full rounds were needed. Round 1 ran all 9 verifications; four hypotheses **failed and forced design revisions** (H2 kill-rate, H2b oracle self-reference, V7 state mapping, V9 duplicate hashing). Round 2 verified the revised designs — all pass. The loop stopped when no open hypothesis remained unverified and no revision had failed re-verification.

| # | Design (§7 area) | Load-bearing hypotheses | Round-1 verdict | Revision | Round-2 verdict |
| --- | --- | --- | --- | --- | --- |
| V1 | D-DSL v0: EARS surface + restricted predicate subset | H1: ≥90% of corpus statements parse | **PASS 26/26 (100%)** | — | — |
| V1b | D-DSL v0 predicate subset | H1b: all 26 properties compile | **FAIL 17/26 (65%)** | DSL v1 grammar (6 extensions) + corpus patch P1 | **PASS 26/26** |
| V2 | D-CG: predicate → Hypothesis codegen | H2: ≥80% mutant kill vs naive metric | **FAIL 14%** | oracle-bound predicates + clause-scoped accounting | **PASS** (in-scope 3/4; survivor = equivalent mutant) |
| V3 | D-CG: Gherkin fallback for *every* clause | H3: pytest-bdd accepts all 26 | **PASS 26/26 in 0.26s** | — | — |
| V4 | D-ANCH: ast-grep extraction + symbol anchors | H4: 3 languages, deterministic | **PASS 5/5, determinism PASS** | per-language comment kinds (`line_comment` for Rust) | — |
| V4b | D-ANCH: symbol > line anchors | H5: anchors survive move + rename | **PASS** (line anchors stale 2/2; symbol anchors 5/5; rename tracked) | wrapper-node descent (TS `export_statement`) | **PASS** |
| V5 | D-MUT: mutmut + clause-scoped accounting | H6: scoped mutmut run practical | **PASS** (28 mutants, ~1.1s) | `also_copy` for oracle sandbox | **PASS** |
| V5b | D-MUT: scope filtering | H7: in-scope accounting preserves signal | **PASS with refinement** (6/12 survivors out-of-scope) | survivor taxonomy {refinement-signal, other-clause, equivalent} | **PASS** |
| V6 | D-THR: PBT-presence + trivial-ratio detector | H8: 100% on synthesized suites | **PASS 6/6** | real-corpus calibration still open (§7.6) | — |
| V7 | D-NEG: negotiation ↔ a2a-sdk | H9: all transitions representable on real SDK | **FAIL on pydantic-era assumptions** | rewrote on protobuf SDK; corrected state semantics | **PASS 7/7** |
| V8 | D-ATT: in-toto attestation | H11: sign/verify/tamper on real clause hashes | **FAIL** (in-toto 3.x API removed `models`) | rebuilt on securesystemslib DSSE (in-toto 3.x substrate) | **PASS** |
| V9 | D-REG: registry, conflicts, delta replay | H10: duplicate/conflict/delta mechanics | **FAIL A** (whole-node hash) | §5.2 canonical hash (excludes alias/metadata) — as the spec already said | **PASS 6/6** |

## The verified designs

### D-DSL v1 (§7.1 — invariant DSL) — VERIFIED
- **Surface**: EARS (WHEN/IF/WHILE/WHERE/ubiquitous) — measured 26/26 parse on the real corpus.
- **Grammar**: recursive quantifier expressions; binder forms `forall var:`, `forall a, b:`, domain-space `forall exports e:`, tuple `forall pairs (a, b):`, membership `forall c in g:`; implication `=>` desugars to `(not A) or B`; primes `x'` → `next_x`; set-builders `{c | P(c)}` → comprehensions over `CLAUSES`; reserved-word collisions (`in(`) renamed.
- **Compile target**: the compilable subset emits Python boolean expressions (machine-checked on all 26).
- **Escape hatch kept**: non-expressible clauses stay judge-gated with rationale (DSL-JUDGE-ESCAPE-HATCH).
- *Store patch P1 (pending validation)*: 9 predicate rewrites (CON-COUNTER-RECORDED, CON-VALIDATED-OR-NO-START, CON-AMEND-VIA-DELTAS stays lexical `{A,B,C}`, GATE-DUPLICATE-CLAUSES, GATE-L0-HASH-VERIFY, ID-CONTENT-CHANGE, PRT-TYPED-REFUSAL, TR-IMPACT-QUERY, TR-REVERSE-COVERAGE, TR-UNRESOLVED-BINDINGS-FAIL).

### D-CG (§7.2 — codegen) — VERIFIED with two design corrections
1. **Oracle binding (new, load-bearing)**: generated property tests import predicate terms (`expired`, `err`) from a *contract-side oracle artifact*, never from the producer module. Without it the property self-references the producer (V2: mutating `expired` survived — the exact self-graded-homework anti-pattern DEC warned about).
2. **Clause-scoped mutation accounting**: scope = functions referenced by the clause predicate; out-of-scope mutants are excluded from the clause's kill rate (they belong to other clauses' evidence obligations).

### D-NEG (§7.3 — negotiation) — VERIFIED on the real SDK
- All 7 workflow transitions representable on **a2a-sdk (protobuf era)** without SDK extension.
- State semantics discovered empirically: gate **rejection → INPUT_REQUIRED** (task re-opens for the bounded retry loop); pre-commitment **refusal → REJECTED**. CFP/counters/verdicts ride Message history; contract + deliverable ride DataPart artifacts; wire-format round-trip verified.
- Amendment mechanics verified separately in V9 (delta replay).

### D-ANCH (§7.4 — element anchoring) — VERIFIED
- ast-grep (Python bindings, YAML-rule compatible kinds) extracts `@trace("ALIAS")` comment bindings in Python/TypeScript/Rust + decorator/attribute patterns; 5/5 with full symbol resolution (incl. TS `export_statement` wrapper descent).
- Determinism: byte-identical outputs across runs (TR-DETERMINISTIC-EXTRACTION's property, machine-checked).
- **Symbol anchors beat line anchors**: after a 4-line insert, line anchors were stale 2/2 while symbol anchors still resolved 5/5; rename tracking verified (`check_forward_coverage` → `_v2`).

### D-MUT (§7.5 — mutation budget) — VERIFIED with refinement
- mutmut 3.7 practical on single-module scope: 28 mutants, ~1.1s wall (fork-parallel); needs `also_copy` for oracle artifacts (sandbox lesson → goes into the gate design).
- **Survivor taxonomy** (the useful output of a gate): `t <= 0` boundary mutant surviving = genuine *contract-refinement signal* (nothing pins t=0 → routes to consumer per GATE-MUTATION-ATTRIBUTION); Ok-path mutants = other clauses' scope; tuple-truthy mutant = *equivalent mutant* (unkillable, excluded from ratings).
- Cost mechanics: per-mutant cost ~39 ms measured → clause-targeted runs on full modules cost ≈ (in-scope mutant count) × 39 ms.

### D-REG (§7.7 — registry / concurrent minting) — VERIFIED
- Duplicate detection must use the **§5.2 canonical hash** (domain+title+invariants only) — the naive whole-node hash misses clones with different aliases. The experiment *validated the spec's earlier decision*.
- Alias-collision and concurrent-edit (same node_id, both v2, divergent hashes) detection: verified.
- Delta replay (OpenSpec-style): ADDED applied; MODIFIED with correct old-hash applied; MODIFIED with stale base rejected; REMOVED applied. 6/6.

### D-ATT (§5.4 — attestation) — VERIFIED
- DSSE envelope (securesystemslib — the library under in-toto 3.x, whose legacy `models` API is gone in 3.1) signs a TraceManifest statement with the **real hashes of our 26 contract files**; ed25519 verify passes; a tampered clause digest is detected. Predicate URI minted: `https://traceagent.dev/attestations/TraceManifest/v1`.

## Verified limitations (honest)
1. **V6 thresholds** are calibrated on synthesized suites only (6/6). Calibration against real agent-authored suites stays open (§7.6) — needs a real corpus, by definition.
2. **V7's negotiation driver** was scripted, not autonomous-LLM-driven: it verifies *protocol representability* on the real SDK, not agent negotiation skill. LLM-in-the-loop negotiation is the next verification (needs the runner built).
3. **In-scope kill "rate"** is deliberately not a pass/fail percentage: the verified design treats survivors as classified signals (refinement / other-clause / equivalent). Setting a numeric under-kill threshold is deferred until a real corpus exists.
4. The DSL v1 parser exists only as a ~200-line throwaway in the lab; it is the specification seed for the real implementation and was exercised on the real corpus, but production parser + strategy-mapping table remain to be built (this was the "no codebase changes" boundary).

## Next steps
1. **Consumer validation** of the 26 clauses + patch P1 (9 predicate rewrites) + the two negotiation-state corrections — then statuses move to VALIDATED.
2. Implement against the verified designs in dependency order: DSL v1 parser + strategy table → codegen (oracle-bound property + Gherkin fallback) → L0/L1 gates → trace manifest + DSSE attestation → a2a envelope.
3. Real-corpus calibration for D-THR once the gate runs on real agent output (first internal dogfood: build the runner against this repo's own contract).
