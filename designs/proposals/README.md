# Proposal Registry – Governance Model

**Validated baseline** – The authoritative design baseline is `designs/ARCHITECTURE.md` (baseline **v0**, validated 2026‑09‑04) together with `designs/IMPLEMENTATION-PLAN.md`.  These files are **never edited in place**; any change must be expressed as a *proposal* against a named baseline.

## Versioning
- Proposals are numbered `P‑NNN` (e.g. `P-001`).
- Each proposal carries an internal version (`v1`, `v2`, …).  Revisions are *append‑only*: a new version is added with a **Changelog** entry; the historical version remains immutable.
- The source of truth for proposal status is `designs/proposals/INDEX.md`.

## Lifecycle (mirroring clause status)
```
DRAFT → PROPOSED → VALIDATED → MERGED
           ↘ WITHDRAWN   ↘ SUPERSEDED
```
- **DRAFT** – initial authoring, internal.
- **PROPOSED** – formally submitted; appears in `INDEX.md`.
- **VALIDATED** – consumer (or designated reviewer) has signed off the proposal.
- **MERGED** – the proposal’s delta is incorporated, and the baseline version is bumped (e.g. `v0 → v0.1`).
- **WITHDRAWN / SUPERSEDED** – terminal states for proposals that are abandoned or replaced.

## Convergence rule
Multiple proposals may coexist and *compete*.  Conflicting proposals must be reconciled before any can reach **VALIDATED**.  Only a **VALIDATED** proposal can be merged into the baseline, guaranteeing an auditable trail of design evolution.

## Required proposal fields
Every proposal document must contain the following sections (in order):
- `ID`
- `Version`
- `Status`
- `Date`
- `Target baseline`
- `Motivation`
- `Current baseline text`
- `Proposed delta` (exact text changes, quoted where appropriate)
- `Impact`
- `Alternatives`
- `Open questions`
- `Performance` (cost/runtime budgets and measured figures, or explicit ESTIMATE markers)
- `Anti‑theater acceptance` (how the change proves it executed rather than merely exists, where applicable)
- `Validation checklist`
- `Changelog`

All fields must be filled; uncertain facts should be flagged as **open questions** rather than asserted.

---

*All new files are created under `designs/proposals/`.  No other files in the repository are modified.*