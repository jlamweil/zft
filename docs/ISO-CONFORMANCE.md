# ISO / Regulatory Conformance Mapping

*This document provides a pragmatic mapping between the objectives of major
standards and the artefacts implemented by **traceagent**.  The mapping is
intended to show how traceagent can be used as a **back‑bone** within an ISO‑
conformant development process.  It does **not** claim that traceagent itself is
qualified as a certified tool (e.g. DO‑330 TQL‑1).  Where a claim cannot be
verified, it is marked **UNVERIFIED**.

---

## 1. ISO/IEC/IEEE 29148 – Requirements Engineering

| Objective (section) | Traceagent artefact | Status | Evidence (file / line) | What is required to meet it |
|---|---|---|---|---|
| **Unique identifier** – each requirement shall have a globally unique ID. | Clause node `node_id` (UUIDv7) – e.g. `.zft/specs/identity/id-uuidv7-alias.json` (line 1) | **Met** | `src/traceagent/spec/identity.py:6‑12` (UUIDv7 generator) | Ensure all clauses are minted via `new_uuid7()` and stored in `.zft/specs/`. |
| **Attributes** – status, version, traceability attributes. | Clause JSON fields `status`, `version`, `content_hash` (see `.zft/specs/*/*.json`). | **Met** | `src/traceagent/spec/canon.py:13‑19` (hash & excluded attrs) | Populate `status` and `version` consistently; tool already validates via L0. |
| **Traceability** – bidirectional links between requirements and design/implementation. | `@trace("ALIAS")` annotations extracted by Tree‑Sitter (`src/traceagent/lineage/extract.py`), trace matrix (`src/traceagent/lineage/matrix.py`). | **Met** (forward) / **Partial** (reverse) | `src/traceagent/lineage/matrix.py:12‑24` (coverage report) | Implement element‑anchor extraction for non‑code artefacts (docs, models) to achieve full reverse coverage. |
| **Verification** – each requirement shall be verifiable by test or analysis. | Verification gates L1/L2 (property suites, mutation testing). | **Partial** – property strings are not yet executable (Gap 001). | `src/traceagent/gates/l1.py:74‑80` (property clause handling) | Execute clause DSL or require consumer‑supplied oracle (see Proposal P‑004). |
| **Consistency** – requirements shall be consistent and non‑contradictory. | Contract amendment workflow with delta sync (`src/traceagent/registry/conflicts.py`). | **Met** | `src/traceagent/registry/conflicts.py` (conflict detection) | No further action needed. |

> *Caveat:* Exact clause numbers for these objectives are **UNVERIFIED** (the standard is paywalled); the table rows are labelled by objective name only.

*References*: ISO/IEC/IEEE 29148:2018 — clause numbers UNVERIFIED (paywalled); "attributes" is §5.2.8 per a public TOC extract.

---

## 2. IEC 62304 – Medical Device Software Lifecycle

| Objective (clause) | Traceagent artefact | Status | Evidence | Required work |
|---|---|---|---|---|
| **4.2.1 Software requirements** – traceable from user needs to software requirements. | Contract clause store (`.zft/specs/`) contains requirements; each clause can carry `external_links` to medical‑device need IDs. | **Met** (structure) | `src/traceagent/spec/store.py` (loading) | Populate `external_links` with medical‑device IDs; export to ReqIF for system‑level traceability. |
| **5.5 Verification** – unit, integration, system testing, and verification of requirements. | Gates L1 (property suites) and L2 (mutation testing). | **Partial** – property DSL not executable (Gap 001). | `src/traceagent/gates/l2.py:66‑73` (coverage) | Add executable property evaluation (see P‑004). |
| **6.3 Configuration Management** – controlled changes, versioning. | Git‑first storage (`.zft/specs/`), immutable UUIDv7 IDs, version field, delta sync (`src/traceagent/spec/delta.py`). | **Met** | `src/traceagent/spec/identity.py` (UUID), `src/traceagent/registry/conflicts.py` (conflict detection) | No change. |
| **6.4 Problem Resolution** – traceable defect handling. | Run ledger (`.zft/runs/<run_id>/manifest.json`) records failures, typed rejections, and repro commands. | **Met** | `src/traceagent/debug/ledger.py` (event logging) | Integration with external defect‑tracking (JIRA) optional. |

*References*: IEC 62304:2006 +A1:2015, clauses 4.2.1, 5.5, 6.3, 6.4.

---

## 3. ISO 26262 (Part 6 & Part 8) – Automotive Functional Safety

| Objective (part/section) | Traceagent artefact | Status | Evidence | Needed to fulfil |
|---|---|---|---|---|
| **6.4.2.1 Safety requirements** – each safety requirement must be uniquely identified and traceable. | Clause IDs (UUIDv7) with optional `safety_class` attribute (can be added). | **Partial** – attribute not yet defined. | `src/traceagent/spec/canon.py` (hash generation) | Extend clause schema to include `safety_class` (ASIL) and update lint. |
| **6.4.3 Verification** – independent verification of each safety requirement. | L2 gate runs mutation testing, independent of producer model; model‑independence flag in attestation (`src/traceagent/attest/dsse.py:23‑25`). | **Partial** – independence currently labelled but not enforced. | `src/traceagent/attest/dsse.py:23‑25` (model_dependent) | Enforce that gate model differs from producer model (policy). |
| **8.4.6 Tool confidence** – tools used for safety‑critical verification must be qualified (TQL). | DSSE attestation provides cryptographic proof of gate outcomes; gate code is deterministic and covered by the pytest suite (`tests/`). | **Partial** – tool qualification not performed. | `tests/unit/` (pytest suite) | Perform DO‑330 style tool‑qualification audit (traceability of test cases, coverage evidence). |
| **8.4.7 Configuration Management** – version control of safety artefacts. | Git‑first store, immutable clause IDs, version field, audit log (`.zft/audit.log`). | **Met** | `src/traceagent/taskgate.py` (audit logging) | No further change. |

*References*: ISO 26262:2018, Part 6 §6.4.2.1, §6.4.3; Part 8 §8.4.6, §8.4.7 (secondary sources; primary paywalled).

---

## 4. DO‑178C & DO‑330 – Avionics Software Certification

| Objective (DO‑178C §) | Traceagent artefact | Status | Evidence | Gap / Work |
|---|---|---|---|---|
| **4.1 Requirements coverage** – traceability from high‑level requirements to low‑level code. | Trace matrix (`src/traceagent/lineage/matrix.py`) provides forward coverage; contracts act as high‑level requirements. | **Partial** – reverse coverage (code → requirement) not fully covered for non‑code artefacts. | `src/traceagent/lineage/matrix.py:5‑24` | Extend `extract_bindings` to capture non‑code elements (e.g., doc sections). |
| **9.1 Structural coverage** – statement, decision, MC/DC coverage metrics. | Mutation testing (`gates/l2.py` + `mutmut_runner.py`) approximates coverage; reports killed mutants. | **Partial** – not a formal structural coverage metric. | `src/traceagent/gates/mutmut_runner.py` | Add integration with coverage tools (e.g., `coverage.py`) to produce DO‑178C coverage reports. |
| **11.1 Verification independence** – verification shall be performed by a tool or personnel independent of the implementer. | Gate runs on CI separate from producer; model‑independence flag (`attest/dsse.py`). | **Partial** – independence is labelled but not enforced. | `src/traceagent/attest/dsse.py:24‑25` | Policy enforcement: gate must run on a separate CI runner with distinct model identifier. |
| **12.2 Tool qualification (DO‑330)** – classification of tools, qualification evidence. | DSSE attestation, deterministic execution, audit log (no regression suite). | **Missing** – no formal TQL documentation or evidence package. | N/A | Produce a DO‑330 qualification dossier: test cases, tool version control, independence proof. |

*References*: DO‑178C Revision 2, Sections 4.1, 9.1, 11.1, 12.2; DO‑330 (Tool Qualification), Sections 1‑3 (secondary sources; primary paywalled).

---

## 5. ReqIF (OMG) – Requirements Interchange Format

| Objective | Traceagent artefact | Status | Evidence | Needed |
|---|---|---|---|---|
| Exchange of requirements with IDs, attributes, and trace links. | Export command (`zft export`) emits the trace matrix and DSSE summary; ReqIF generation is **not** in the open-source package. | **Missing (open source)** | `src/traceagent/attest/export.py` (contains no ReqIF logic) | ReqIF import/export is a proprietary **enterprise** feature, implemented in `private/enterprise/zft/reqif/` (see ATT-EXTERNAL-IMPORT, v0.1). |

*References*: ReqIF 1.2 (OMG, July 2016) — no "Section 4 (Traceability)"; traceability is expressed via `SpecRelation` elements.

---

## 6. (Optional) ISO/IEC/IEEE 42010 – Architecture Description

| Objective | Traceagent artefact | Status | Evidence | Gap |
|---|---|---|---|---|
| Architecture viewpoints, models, and decisions. | Decision records D1‑D6 in `designs/ARCHITECTURE.md`; architecture diagram in `README`. | **Partial** – no formal model exchange format. | `designs/ARCHITECTURE.md` (sections D1‑D6) | Define a view model (e.g., ArchiMate) and export to a standard format. |

---

## 7. ISO/IEC 25010 – Software Quality Model

| Quality characteristic | Traceagent support | Status |
|---|---|---|
| Functional suitability | Clause‑to‑implementation binding, verification gates. | **Partial** (see Gap 001). |
| Reliability | Mutation testing, deterministic gates, audit log. | **Met** |
| Security | DSSE attestation, signed manifests. | **Partial** – no threat modelling. |
| Maintainability | Bi‑directional traceability, immutable IDs, Git‑first ALM. | **Met** |
| Portability | Language‑agnostic clause format, AST‑grep extraction. | **Met** |

*References*: ISO/IEC 25010:2011, Section 4 (Characteristics).

---

## 8. Summary of Gaps & Actions

| Gap | Standard | Artefact missing / partial | Action |
|---|---|---|---|
| **Gap 001** – Gate verifies traceability, not conformance. | ISO 29148 §7.4, IEC 62304 §5.5, ISO 26262 §6.4.3, DO‑178C §11.1 | L1 does not execute clause `property` DSL; `test`‑kind clauses have no evidence. | Implement executable property evaluation or consumer‑owned oracle (Proposal P‑004). |
| Tool qualification evidence for DO‑330 / ISO 26262. | DO‑330, ISO 26262 §8.4.6 | No formal TQL package. | Produce qualification dossier, add coverage tooling. |
| Reverse coverage for non‑code artefacts. | ISO 29148 §6.5, ISO 26262, DO‑178C | `extract_bindings` limited to `@trace` in code. | Extend lineage extraction plugins for docs, models. |
| ASIL attribute in clause schema. | ISO 26262 §6.4.2.1 | Not present. | Extend clause JSON schema, update L0 lint. |

---

*This matrix is intentionally conservative.  Organizations can achieve full compliance by extending the listed artefacts, tightening policies, and performing the required qualification activities.*
