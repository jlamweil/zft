# ZFT (Zero-Friction Traceability) — Brand Architecture & Identity System

---

## 1. Brand Identity Overview

* **Primary Name:** **ZFT**
* **Expanded Identity:** **Zero-Friction Traceability**
* **CLI Command:** `zft`
* **Canonical Directory & Schemas:** `.zft/specs/**`
* **Tagline:** *Contract-grounded verification for multi-agent work.*
* **Positioning Statement:** ZFT is the developer-first, contract-driven traceability and verification layer for multi-agent software engineering. It bridges non-deterministic AI agent outputs with deterministic, auditor-defensible software compliance.

---

## 2. Brand Hierarchy & System Architecture

```
                                    THE ZFT BRAND SYSTEM
                                              │
      ┌───────────────────────────────────────┼───────────────────────────────────────┐
      ▼                                       ▼                                       ▼
ZFT (The Brand & Core Engine)           TraceAgent (Research Codename)            .zft (The Spec Standard)
• CLI tool binary (`zft`)               • Academic paper title subtitle          • On-disk specification format
• Package name (`pip install zft`)      • System architecture framing            • Contract schemas & metadata
• Managed Cloud & Enterprise IP         • Citation & research anchor             • Trace manifest file outputs

```

### Strategic Separation: Open Standard vs. Commercial Value

| Dimension | Public / Open Source (ZFT Core) | Proprietary / Enterprise (ZFT Cloud) |
| --- | --- | --- |
| **Package / Artifact** | `zft` CLI, `.zft` schemas, local gate engine | Hosted Trace Registry, ALM Sync Engines |
| **Target Audience** | Developers, Agent Frameworks, Researchers | Enterprise Engineering Leaders, CISOs |
| **Value Delivered** | Local L0–L1 verification, invariant parsing | Cross-repo lineage graphs, 1-click ISO/ReqIF audits |
| **Licensing** | Apache 2.0 (sole open-source license — HB-1 decision 2026-09-13, no BSL) | Commercial License |

---

## 3. Brand Voice, Tone & Messaging Matrix

### Core Tone

* **Rigorous & Deterministic:** Speak like a compiler or verification framework (Rust, Cargo, Tree-Sitter). Avoid AI hype, buzzwords ("magic", "revolutionary"), and vague promises.
* **Developer-First:** Concise, CLI-native, and zero-fluff. Prioritize fast feedback loops, clear status codes, and precise mechanical error messages.
* **Auditor-Defensible:** Direct, evidence-backed, and unambiguous when addressing compliance, contracts, and attestation.

### Messaging Matrix by Audience

```
                                     AUDIENCE MESSAGING
                                              │
      ┌───────────────────────────────────────┼───────────────────────────────────────┐
      ▼                                       ▼                                       ▼
AI / AGENT DEVELOPERS                   ENTERPRISE COMPLIANCE LEADERS             ACADEMIC / RESEARCHERS
"Stop relying on LLM vibes.              "Turn multi-agent software development   "Contract-first verification
Contract-grounded acceptance criteria    into an auditor-defensible, continuous   combining static analysis,
and deterministic verification gates."   compliance pipeline."                     properties, and mutation testing."

```

---

## 4. Visual Identity & CLI Formatting Guidelines

### Logo & Typography Concept

* **Symbol:** A stylized **Z** intersecting a mathematical check mark ($\checkmark$) or linked node icon, evoking both speed ("Zero-Friction") and cryptographic verification ("Traceability").
* **Terminal Brand Palette (ANSI Colors):**
* **Primary Brand Accent:** Bright Cyan (`#00E5FF`) — used for headers, binary name, and main status calls.
* **Pass / Validated:** Green (`#00FF87`) — used for passed L0–L3 gates, validated clauses, and passing properties.
* **Fail / Rejection:** Coral Red (`#FF3366`) — used for failed invariants, mutant survivals, and structural errors.
* **Muted Metadata:** Slate / Dim Gray (`#6C7A89`) — used for hashes, line numbers, and file paths.



### Standard Terminal Output Format (`zft gate`)

```text
ZFT (Zero-Friction Traceability) v0.1.0
Contract: .zft/specs/auth/JWT-VALIDATE.json [v2]
Deliverable: git:a1b2c3d (src/auth/jwt.py)

┌── Verification Gates ──────────────────────────────────────────┐
│ [PASS] L0 Static Integrity    (schema, hashes, duplicate check)│
│ [PASS] L1 Local Check         (10,000 property cases executed) │
│ [PASS] L2 Merge Gate          (41/41 mutants killed)           │
└────────────────────────────────────────────────────────────────┘

Trace Manifest: .zft/manifest.json (Signed)
Status: ACCEPTED (Coverage: 12/12 clauses, 87/87 elements)

```

---

## 5. Ecosystem & Integration Positioning

ZFT is **infrastructure middleware**, not a standalone agent runner. It integrates into existing agent stacks rather than replacing them.

```
┌────────────────────────────────────────────────────────────────────────┐
│ AGENT FRAMEWORKS (LangGraph, CrewAI, AutoGen, Claude Code, A2A)        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ generates contract & work
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ ZFT VERIFICATION LAYER (`zft gate` / Trace Manifest)                   │
│ L0 Static → L1 Inner Loop → L2 Mutation → L3 Cryptographic Attest      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ exports verified evidence
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ COMPLIANCE & ALM OUTPUTS (ReqIF, ISO 26262, Jira, DOORS, Polarion)     │
└────────────────────────────────────────────────────────────────────────┘

```

---

## 6. Official Terminology Glossary

* **ZFT Engine:** The deterministic core parser, static analyzer, and verification runner.
* **Clause:** An atomic, individually verifiable obligation stored in `.zft/specs/`.
* **Trace Manifest:** The compiled, signed payload binding deliverable elements to contract clauses with evidence.
* **Gate (L0–L3):** Sequential checkpoints enforcing static integrity (L0), local tests (L1), mutation/coverage (L2), and signed attestation (L3).
* **Fault Attribution:** The mechanism that classifies an L2 gate failure as either a **Contract Fault** (under-specified clause) or an **Implementation Fault** (buggy deliverable).

---

## 7. Package & Repository Namespace Matrix

| Platform | Registry Handle | Status / Usage |
| --- | --- | --- |
| **GitHub Repo** | `[github.com/](https://github.com/)<org>/zft` | Primary open-source code repository |
| **PyPI (Python)** | `pip install zft` | Python CLI and core engine library |
| **npm (JS/TS)** | `npm install @zft/core` | Node/TypeScript bindings and schema checkers |
| **crates.io (Rust)** | `cargo install zft-cli` | High-performance CLI binary (if built in Rust) |
| **Paper Citation** | *ZFT: Contract-Grounded Traceability for Multi-Agent Systems* | arXiv / Academic publication reference |
