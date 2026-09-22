# P-003 – Status & drift reconciliation

**ID**: P-003

**Version**: v1

**Status**: PROPOSED

**Date**: 2026‑09‑10

**Target baseline**: `designs/ARCHITECTURE.md` (baseline **v0**)

## Motivation
Several factual discrepancies have accumulated between the documented baseline and the actual repository state.  These drift issues obscure the true status of clauses, implementations, and tooling, making verification and planning error‑prone.

## Current baseline text
- `CONTEXT.md` §8 (line 100) states **26 clause nodes** in ``.zft/specs/``.
- `designs/IMPLEMENTATION-PLAN.md` C‑00 (line 71) also references **26 clauses**.
- The contract manifest (`.zft/contracts/traceagent-v0.json`) lists **30 clause IDs** and records a single deferred clause via `target_milestone` (`ATT‑EXTERNAL‑IMPORT`).
- `IMPLEMENTATION-PLAN.md` C‑18 mentions a non‑existent file `lineage/symbols.py`.
- `IMPLEMENTATION-PLAN.md` C‑19b references a missing ``bench/`` directory.
- The repository layout in `IMPLEMENTATION-PLAN.md` §2 omits several newly added artifacts: `src/zft/taskgate.py`, the Opencode plugin `.opencode/plugin/traceagent-gate.ts`, `src/zft/attest/jcs.py`, and `src/zft/lineage/impact.py`.
- `ARCHITECTURE.md` §4 does not document the `tier` parameter (`fast`/`full`) of `gates/l2.py`.
- `docs/KNOWN-GAPS.md` Gap 001 records the acceptance‑gate deficiency (traceability vs. conformance).

## Proposed delta
Rather than editing the baseline documents, this proposal records the verified facts as a **design‑level correction**:
- **Clause corpus**: 30 clause nodes (30 JSON spec files) with 29 due clauses; 1 deferred clause (`ATT‑EXTERNAL‑IMPORT`).
- **TR‑IMPACT‑QUERY**: now **implemented** (`src/zft/lineage/impact.py`, CLI `impact`, tests `tests/unit/test_impact.py`); no longer deferred.
- **ATT‑EXTERNAL‑IMPORT**: the only remaining v0.1 clause.
- **Missing artifacts**: `lineage/symbols.py` does not exist; symbol anchoring lives in `src/zft/lineage/extract.py::_enclosing_symbol`.
- **Missing bench directory**: `bench/` referenced in C‑19b is absent.
- **Undocumented tier**: `gates/l2.py` defines a `tier` argument (default `fast`; `full` is a documented option) which is not described in `ARCHITECTURE.md` §4.
- **Layout omissions**: the repo layout section should be updated to list the newly added files (taskgate, plugin, jcs, impact).
These statements are **recorded** in this proposal; the baseline files remain unchanged.

## Impact
- Provides an auditable, versioned record of the current state, preventing future confusion.
- Highlights concrete gaps that must be addressed in subsequent design cycles (e.g., documentation of L2 tier, inclusion of missing files).
- Clarifies that the contract corpus already contains 30 clauses, aligning tooling expectations (e.g., coverage calculations).

## Alternatives
1. **Directly edit baseline documents** – would violate the rule that the validated baseline is immutable.
2. **Ignore the drift** – leaves stakeholders with inaccurate information, increasing risk of mis‑aligned work.
3. **Create a separate errata document** – less formal than a proposal and less traceable.
The chosen approach follows the established **proposal‑first** workflow.

## Open questions
- None – all statements have been verified against the repository as of 2026‑09‑10.

## Validation checklist
- [ ] Verify clause count: `find .zft/specs -name "*.json" | wc -l` → **30**.
- [ ] Confirm one deferred clause via `cat .zft/contracts/traceagent-v0.json` – `"target_milestone": {"ATT-EXTERNAL-IMPORT": "v0.1"}`.
- [ ] Run `pytest tests/unit/test_impact.py` – all tests pass, confirming implementation.
- [ ] Check that `lineage/symbols.py` does not exist and that `_enclosing_symbol` is defined in `src/zft/lineage/extract.py`.
- [ ] Verify that `bench/` directory is absent.
- [ ] Confirm presence of `src/zft/taskgate.py`, `.opencode/plugin/traceagent-gate.ts`, `src/zft/attest/jcs.py`, and `src/zft/lineage/impact.py`.
- [ ] Ensure `gates/l2.py` defines a `tier` parameter (default `fast`) and that the value `full` is a documented option (though not currently used).
- [ ] Confirm that `docs/KNOWN-GAPS.md` includes Gap 001 describing the acceptance‑gate issue.

## Changelog
- **v1, 2026‑09‑10** – Created proposal documenting factual corrections and status reconciliation.