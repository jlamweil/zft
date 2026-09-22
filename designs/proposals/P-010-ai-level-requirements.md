# P-010 – AI-level requirements (adopt findings as clauses)

**ID**: P-010
**Version**: v1
**Status**: PROPOSED
**Date**: 2026-09-10
**Target baseline**: `designs/ARCHITECTURE.md` (baseline v0); introduces a new **AI-conduct** requirement set

## Motivation
The design-verification loop (rounds 1–5) produced a set of **verified** findings about how agents/gates must behave — chiefly that *presence is not evidence*. These are currently prose in proposals. To make them binding on the AI side, they should become first-class **clauses** the gate can enforce.

## Current baseline text
- D6 interaction protocol defines producer/consumer roles and typed rejections, but no requirements on the AI's own evidence discipline.
- The v0 contract (`traceagent-v0`) has 30 clauses; none express AI-conduct obligations.
- `docs/AI-REQUIREMENTS.md` lists the ten requirements (currently documentation only).

## Proposed delta
1. **Author 10 clauses** in domain `ai-conduct` (statements and properties as listed in `docs/AI-REQUIREMENTS.md`): `AI-EXECUTED-EVIDENCE`, `AI-INDEPENDENT-ORACLE`, `AI-CONTRACT-PIN`, `AI-SOURCE-SCOPE`, `AI-REVERSE-COVERAGE`, `AI-NONCODE-ANCHOR`, `AI-TOOL-CONFIDENCE`, `AI-EXTERNAL-IDENTITY`, `AI-HUMAN-APPROVAL`, `AI-SUBJECTIVE-QUARANTINE`.
2. **Defer them to milestone `v1`** via contract `meta.target_milestone`, so they are visible/auditable but **do not block the v0 gate** (same mechanism as `TR-IMPACT-QUERY`/`ATT-EXTERNAL-IMPORT`).
3. **Upgrade each to `kind: property`** with a consumer oracle (P-005) when its enforcing proposal lands, so the requirement is *executed*, not asserted.
4. **Contract scope question**: AI-conduct requirements are a distinct concern from the product contract; either keep them in `traceagent-v0` with deferrals, or introduce multi-contract support (open question).

## Verified evidence (basis)
| Requirement | Finding | Proposal |
|---|---|---|
| AI-EXECUTED-EVIDENCE / AI-INDEPENDENT-ORACLE / AI-CONTRACT-PIN | H2a–f, H12 | P-005 |
| AI-SOURCE-SCOPE | H1a–c, H6 | P-006 |
| AI-REVERSE-COVERAGE / AI-NONCODE-ANCHOR | H10, H13 | P-007 |
| AI-TOOL-CONFIDENCE | H11 | P-008 |
| AI-EXTERNAL-IDENTITY | H17, H17a, H19 | P-009 |
| AI-HUMAN-APPROVAL / AI-SUBJECTIVE-QUARANTINE | human↔AI design | P-011 |

## Impact
Turns the loop's findings into enforceable AI-conduct requirements; gives ISO/assurance a requirement basis for the tool/agent behaviour. Deferred, so no disruption to the current gate.

## Performance
Negligible: clauses are static JSON; deferral excludes them from coverage. Adding them grows the corpus (30 → 40 nodes) and gherkin scenarios; `check` remains green (deferred).

## Anti-theater
Each AI-conduct clause is bound to a *negative control*: the requirement is only satisfied by executed evidence; e.g. `AI-EXECUTED-EVIDENCE` fails if a clause is accepted via `assert True` (P-008 self-test).

## Alternatives
Rejected: leave findings as prose (unenforceable); encode as a second product contract immediately (multi-contract support doesn't exist — loader risk); make them v0-due (would red the gate before enforcement exists).

## Open questions
Multi-contract vs deferral; domain naming (`ai-conduct` vs `agent`); whether AI-conduct clauses should be `kind: process` (human-attested) rather than `property`; how the set evolves as the design loop continues.

## Validation checklist
- [ ] 10 clauses authored + registered; `check` stays green (deferred).
- [ ] Each clause has a defined enforcement mechanism (P-005/P-006/P-007/P-008/P-009/P-011).
- [ ] Negative-control test exists per requirement (later, when upgraded to `property`).

## Changelog
- v1, 2026-09-10 — from the verified loop (rounds 1–5): findings adopted as AI-level requirements; see `docs/AI-REQUIREMENTS.md`.
