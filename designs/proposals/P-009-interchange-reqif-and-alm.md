# P-009 – Interchange: ReqIF import/export & ALM sync (`ATT-EXTERNAL-IMPORT`)

**ID**: P-009
**Version**: v1
**Status**: PROPOSED
**Date**: 2026-09-10
**Target baseline**: `designs/ARCHITECTURE.md` (baseline v0) §6 / D5; `attest/export.py`, `spec/schema.py`, `spec/delta.py`, `registry/conflicts.py`

## Motivation
`ATT-EXTERNAL-IMPORT` (deferred to v0.1) requires importing external ReqIF/ALM requirement records as clauses **preserving their external identity**. Today: `export` emits only `dsse`/`matrix`/`summary` (no ReqIF); `external_links` is schema-declared but never populated or read; and the clause is `kind: test`, so its property is not enforced. So the requirement is unmet.

## Current baseline text
- `attest/export.py`: `FORMATS = ("dsse", "matrix", "summary")` — no ReqIF.
- `spec/schema.py:43` declares `external_links`; `spec/canon.py:13` excludes it from `content_hash`; `cli/main.py:99` always writes `[]`. No runtime consumer.
- D5 promises "bi-directional ALM sync; conflicts halt with a structured resolution diff — never a silent CRDT overwrite."

## Proposed delta (verified by H14/H16/H17/H17a/H18/H19)
1. **ReqIF 1.2 import/export.** Root `<REQ-IF xmlns="http://www.omg.org/spec/ReqIF/20110401/reqif.xsd">`; map SPEC-OBJECT ↔ clause (statement/status), SPEC-RELATION ↔ trace link. Verified feasible: imported nodes pass the repo's `validate_node`; round-trip is identity-stable and **byte-deterministic**.
2. **Identifier normalization.** ReqIF `IDENTIFIER` is `xsd:ID` (NCName; must start with a letter/`_`). zft UUIDv7 starts with a digit → do **not** emit it raw; use a prefixed identifier and carry the stable id in `ALTERNATIVE-ID`. Normalize imported lowercase ids to traceagent's uppercase alias rule; add a **tolerant validation mode** (real Polarion exports fail strict XSD: duplicate `xs:ID`). 
3. **`external_links` becomes load-bearing** — populated on import (`{"system": "ReqIF", "external_id": ...}`), emitted on export; identity stable because it is already excluded from `content_hash`.
4. **Enforcement.** Upgrade `ATT-EXTERNAL-IMPORT` from `kind: test` to `kind: property` with a consumer oracle (P-005) so "preserves external identity" is **executed**, not asserted.
5. **ALM sync.** Reuse `spec/delta.py` + `registry/conflicts.py`: disjoint edits merge; same-clause divergence halts with a typed diff; identical concurrent edits also halt; deterministic (H16). No CRDT.

## Verified evidence
| Claim | Result |
|---|---|
| ReqIF 1.2 subset implementable | official XSD fetchable; minimal 2-req + 1-link doc XSD-valid |
| identity round-trip | `IDENTIFIER` preserved; export byte-identical across runs/processes |
| constraints | digit-leading UUIDs invalid as `xsd:ID`; lowercase aliases rejected; Polarion output non-conformant |
| ALM conflict | disjoint merge; divergent halt w/ typed diff; identical halt; deterministic |
| round-trip losses | `domain`, `version`, invariant `id/property/check` re-derived |

## Impact
Unblocks the last v0.1 clause and enables ISO/enterprise interchange (29148/26262/DO-178C trace matrices, ReqIF bundles) — but only useful once `external_links` is enforced (P-005).

## Alternatives
Rejected: depend on strictdoc for ReqIF (external, heavy; replicate the small subset instead); vendor-specific XML (defeats interchange); skip import (leaves the clause unmet).

## Open questions
Alias-normalization policy; attribute mapping (EARS statement ↔ ReqIF `LONG-NAME`/XHTML); `ReqIFz` bundle support; ALM transport (HTTP/webhook) and idempotent re-import; how much of the XSD to validate strictly vs tolerantly.

## Validation checklist
- [ ] ReqIF 1.2 import/export with identifier normalization + tolerant mode.
- [ ] `external_links` populated on import and emitted on export; identity stable.
- [ ] Round-trip deterministic (byte-identical) and lossless for external identity.
- [ ] `ATT-EXTERNAL-IMPORT` enforced via P-005 oracle (preserves external id).
- [ ] ALM merge halts on conflict with a typed diff (no silent overwrite).

## Changelog
- v1, 2026-09-10 — from H14/H16/H17/H17a/H18/H19: feasibility, identity round-trip, identifier constraints, ALM conflict model, and the P-005 enforcement dependency.
