# P-007 – Reverse coverage & non-code anchors

**ID**: P-007
**Version**: v1
**Status**: PROPOSED
**Date**: 2026-09-10
**Target baseline**: `designs/ARCHITECTURE.md` (baseline v0) D3 / §5.3; `lineage/matrix.py`, `lineage/extract.py`, `gates/l2.py`

## Motivation
Reverse coverage is documented (clause `TR-REVERSE-COVERAGE`) but inert: `l2.py:49` calls `coverage_report(bindings, set(due))` with no `elements`, so `out_of_contract` is always `[]` and `elements_justified` is 0. "Unjustified deliverable element = scope creep" is one of the framework's two load-bearing coverage directions, and it is not enforced.

## Current baseline text
- `matrix.py:16-17` compares `elements` against `{b["file"]}` → **file-granularity only**; element ids therefore yield `elements_justified = 0`.
- `extract_bindings` only knows Python/TypeScript/Rust comment anchors; Markdown is invisible.
- Every binding in this repo lives in `tests/`; `src/` has zero anchors.

## Proposed delta (verified by H10/H13)
1. **Element enumeration** — `list_all_elements(root)`: Python functions/classes (ast) + Markdown headings (slug). Measured: 476 py + 383 md = **859 elements**.
2. **Baseline-diff enforcement (primary)** — flag **new public top-level non-test `src` elements since the contract baseline** with no binding. Measured: **24 flags, 0 observed false positives** (vs 90% false positives for a naive "flag all unbound" rule).
3. **Backstops** — (a) any *new* non-test `src` file with zero bindings; (b) element-level flagging with exemptions for `tests/`, `_private`, nested; (c) do **not** statically flag the pre-existing 82 public symbols.
4. **Matrix granularity** — extend to `(file, symbol)` comparison so element-level coverage is meaningful.
5. **Non-code anchors** — `<!-- @trace("ALIAS") -->` on the line immediately above a Markdown heading yields a deterministic binding `{alias, file, line, symbol=slug}`. Verified: rename-stable (comment is identity; slug is metadata), move-tolerant (file/line update), fence-safe, and composes with `coverage_report`.

## Impact
Makes the second coverage direction real; enables ISO 29148/26262/DO-178C non-code traceability; detects scope creep since a baseline without drowning in false positives.

## Alternatives
Rejected: file-granularity only (misses element creep); flag-all-unbound (90% FP); manual review (judgment).

## Open questions
Which commit defines the baseline; anchor syntax for non-Markdown artifacts (diagrams, schemas); exemption policy approval; how headings become "gate-relevant" for md docs.

## Validation checklist
- [ ] `list_all_elements` + `(file, symbol)` matrix granularity.
- [ ] Baseline-diff rule flags new unbound public `src` symbols (≈24 on the current tree, 0 FP).
- [ ] Markdown `@trace` anchors extract deterministically and survive rename/move.
- [ ] A deliberately unbound new element makes the gate RED.

## Changelog
- v1, 2026-09-10 — from H10/H13: baseline-diff reverse coverage + Markdown anchors, with measured false-positive analysis.
