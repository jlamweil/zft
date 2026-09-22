# P-004 – ISO / Conformance Direction

**ID**: P-004

**Version**: v1

**Status**: PROPOSED

**Date**: 2026-09-10

**Target baseline**: `designs/ARCHITECTURE.md` (baseline **v0**)

## Motivation

Several of the standards mapped in `docs/ISO-CONFORMANCE.md` require **verification independence** and **tool confidence**:

* ISO 26262 §8.4.6 and DO‑330 §12.2 demand that the verification tool itself be qualified and that its results cannot be authored or graded solely by the producer.
* Gap 001 (see `docs/KNOWN-GAPS.md`) shows that the current L1 gate merely checks that a *bound* test exists, not that the clause’s declared `property` is actually exercised.  This violates the principle *"deterministic verification > probabilistic judgment"* and prevents the framework from claiming conformance to the verification‑independence requirements of the standards.

Adding an **Assurance / Conformance** dimension to the architecture makes these requirements explicit and provides a concrete roadmap for strengthening the gate.

## Current baseline text

Relevant sections of `designs/ARCHITECTURE.md` (v0):

* **D4 – Verification gates** (Tiered gates L0–L3).  L1 executes only the producer‑bound test suite; property clauses are not mechanically evaluated.
* **D2 – Clause identity** (UUIDv7 + content‑hash) – provides immutable identifiers, but no guarantee of independent evaluation.
* **D6 – Interaction protocol** – contracts are negotiated, but the gate does not enforce model independence.

No explicit notion of **tool confidence** (e.g., qualification level, deterministic reproducibility) or **verification independence** is recorded.

## Proposed delta

1. **Add a new evidence tier “independent‑verification”** to D4 (L1/L2).  The tier is satisfied only when:
   * The clause’s `property` DSL is compiled into a test that runs **outside** the producer’s codebase (e.g., in a separate CI runner), **or**
   * A consumer‑owned *oracle* file (`oracle_<ALIAS>.py`) is present and executed by the gate.
   * The gate records the **model identifier** of the producer and the **model identifier** of the gate; the attestation (`src/zft/attest/dsse.py`) must set `model_dependent: false` for the evidence tier to be considered *independent*.
2. **Extend L1 implementation** (`src/zft/gates/l1.py`):
   * Detect `property`‑kind clauses and, if a DSL compiler is available, generate a temporary pytest module that imports the target implementation and asserts the property.
   * If no DSL compiler is present, require the presence of `oracle_<ALIAS>.py`; the gate will execute the oracle in an isolated sandbox.
   * Fail the clause if neither mechanism is provided.
3. **Introduce a **tool‑confidence manifest** (`src/zft/attest/manifest.py` – new file) that records:
   * The gate version, git commit hash, and a deterministic hash of the gate’s source files.
   * Results of a **regression suite** (`bench/` tests) that exercise the gate itself.
   * The outcome is signed via DSSE (existing `attest/dsse.py`).
4. **Update the attestation payload** (`src/zft/attest/dsse.py`):
   * Add `tool_confidence` field containing the manifest hash and a boolean `qualified` flag (initially `false`).
   * The `model_dependent` flag must be `false` for any clause that uses the independent‑verification tier.
5. **Amend the negotiation state machine** (`src/zft/negotiate/sm.py`):
   * After contract validation, the consumer may annotate clauses with `verification: "independent"`.  The gate checks this flag and enforces the new tier.
   * Reject contracts that request the tier but do not provide an oracle or DSL support.
6. **Documentation updates**:
   * Add a new subsection *7. Assurance & Conformance* to `designs/ARCHITECTURE.md` describing the tier and its relationship to ISO/IEC/IEEE 29148, IEC 62304, ISO 26262, and DO‑178C.
   * Update `docs/ISO-CONFORMANCE.md` to change the status of verification‑independence from *Partial* to *Met* once the tier is implemented.

## Impact

| Impact area | Description |
|---|---|
| **Standard compliance** | Provides concrete evidence for verification independence (ISO 26262 §8.4.6, DO‑178C §11.1) and tool confidence (DO‑330). |
| **Security & robustness** | Executes property checks in an isolated sandbox, reducing risk of malicious test code. |
| **Developer workflow** | Producers must supply an oracle or accept that a clause will be rejected; this clarifies responsibility and discourages “assert True” hacks. |
| **Performance** | Additional L1 work incurs a modest runtime cost (DSL compilation or sandboxed oracle execution).  Benchmarks can be added to the existing `bench/` suite. |

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| (a) **Require only consumer‑owned oracle** – simpler to implement; already partially supported by L1 cache logic. | Minimal code change, clear separation of duties. | Places burden on consumer; DSL remains unused, limiting future automation. |
| (b) **Full DSL compilation to pytest** – automates property verification for all code‑targeted clauses. | Enables end‑to‑end automated verification; aligns with D1’s executable contract vision. | Requires a robust DSL parser and code generator; higher implementation effort (currently a v0 blocker). |
| (c) **Post‑gate manual review** – keep L1 as‑is, but add a mandatory human review step for property clauses. | No code change, immediate mitigation of Gap 001. | Re‑introduces subjective judgment, contrary to deterministic verification goal; does not satisfy independence requirements. |

## Open questions

1. **DSL scope** – How expressive must the property DSL be to cover typical safety‑critical invariants (e.g., temporal properties, state‑machine constraints)?
2. **Oracle ownership** – Should oracle files be version‑controlled alongside the contract or stored in a separate, protected repository?
3. **Sandboxing strategy** – Which isolation mechanism (e.g., `subprocess` with restricted environment, Docker container) provides sufficient security without excessive overhead?
4. **Tool‑qualification level** – What evidence is required to claim TQL‑1 for the gate (test coverage, mutability, independence proofs)?

## Validation checklist

- [ ] L1 fails when a `property`‑kind clause lacks both a DSL compiler and an `oracle_<ALIAS>.py` file.
- [ ] When an oracle is present, the gate executes it in an isolated sandbox and records a passing result.
- [ ] Attestation payload includes `tool_confidence` with a manifest hash and `qualified: false` flag.
- [ ] `model_dependent` is `false` for clauses verified via the independent‑verification tier.
- [ ] Negotiation SM rejects contracts that request the tier without providing required artefacts.
- [ ] Regression suite (`bench/`) runs and passes before a release of the gate.

## Changelog

- **v1, 2026‑09‑10** – Created proposal to add an independent‑verification evidence tier, tool‑confidence manifest, and associated protocol changes (addresses Gap 001 and standards’ independence requirements).
