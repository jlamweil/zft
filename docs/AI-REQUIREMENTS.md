# AI-Level Requirements

Requirements on how the **AI (agent) side** of a traceagent contract must operate. Each is a behavioural obligation derived from a **verified** finding and is proposed for adoption as a clause. Status: **PROPOSED** (not yet enforced).

Rationale in one line: **presence is not evidence** — an AI may not claim conformance from an artifact that merely exists; the gate must execute and pin the evidence.

| ID | Requirement (EARS) | Rationale (verified finding) | Enforced by |
|---|---|---|---|
| **AI-EXECUTED-EVIDENCE** | WHEN a clause is accepted, THE SYSTEM SHALL require evidence produced by executing the clause, not merely a bound element that exists. | H2a/H2d: the gate accepted a wrong implementation behind a producer `assert True` | P-005, P-008 |
| **AI-INDEPENDENT-ORACLE** | WHEN a producer submits a property clause, THE SYSTEM SHALL verify it against a consumer-owned oracle pinned in the contract. | H2b/H2c/H12: oracle execution works, is cheap, and flips on mutation | P-005 |
| **AI-CONTRACT-PIN** | WHEN the gate evaluates a contract, THE SYSTEM SHALL reject content whose contract or oracle hash differs from the agreed pin. | H12: producer oracle substitution / pin tamper | P-005 |
| **AI-SOURCE-SCOPE** | WHEN the gate extracts trace bindings, THE SYSTEM SHALL read only declared source scope and never caches, sandboxes, or dependency trees. | H1a: 2 of 41 bindings came from `.zft/sandbox/`; extraction 4.58 s | P-006 |
| **AI-REVERSE-COVERAGE** | WHEN a deliverable adds a public element, THE SYSTEM SHALL require a clause binding or fail the gate. | H10: reverse coverage is inert (`elements=None`) | P-007 |
| **AI-NONCODE-ANCHOR** | WHEN a clause addresses a document section, THE SYSTEM SHALL anchor it to a stable section identity. | H13: Markdown `@trace` anchors are deterministic and rename-stable | P-007 |
| **AI-TOOL-CONFIDENCE** | WHEN the gate attests, THE SYSTEM SHALL record the gate's own source hashes and a passing self-test. | H11: a self-test detects the Gap-001 regression; manifest is cheap | P-008 |
| **AI-EXTERNAL-IDENTITY** | WHEN the system imports an external requirement, THE SYSTEM SHALL preserve its external identity across round-trip. | H17/H17a: ReqIF round-trip is identity-stable; `ATT-EXTERNAL-IMPORT` is unmet | P-009 |
| **AI-HUMAN-APPROVAL** | WHEN a human validates a contract, THE SYSTEM SHALL record a signed human approval as the validation gate. | human↔AI contract needs a first-class human sign-off | P-011 |
| **AI-SUBJECTIVE-QUARANTINE** | WHEN a clause is subjective, THE SYSTEM SHALL quarantine judgment from deterministic coverage and require explicit sign-off. | CONTEXT §7 open question 5 (judge clauses) | P-011 |

## Property form (for future clause materialization)
Each requirement has a mechanical predicate, e.g. `forall c accepted: executed_evidence(c)`, `forall b in bindings: in_scope(b.file)`, `forall i: preserves(i, external_id(i))`, `forall v: human(v) => signed_approval(v)`.

## Notes
- These are **requirements on the AI/agent and the gate**, distinct from product clauses (D1–D6). They are proposed as clauses in domain `ai-conduct`, **deferred to milestone `v1`** so they do not block the current v0 gate (the deferral mechanism is the one introduced for `TR-IMPACT-QUERY`).
- `AI-HUMAN-APPROVAL` and `AI-SUBJECTIVE-QUARANTINE` depend on the human↔AI contract extension (P-011).
- Each becomes *enforced* only when upgraded from `kind: test` to `kind: property` with a consumer oracle (P-005) — otherwise the requirement is once again only asserted.
