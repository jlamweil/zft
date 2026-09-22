# P-008 – Gate self-verification & tool confidence

**ID**: P-008
**Version**: v1
**Status**: PROPOSED
**Date**: 2026-09-10
**Target baseline**: `designs/ARCHITECTURE.md` (baseline v0) D4; `attest/dsse.py`, `gates/l0-l2.py`, CI

## Motivation
ISO 26262 §8.4.6 and DO-330 require *tool confidence*: the verification tool must demonstrate its own correctness and determinism. Today nothing proves the gate does what it claims, and the live record is the proof of why that matters — Gap 001 was open, and an attempted "fix" added fake oracles that the gate accepted. The gate must be self-verifying.

## Current baseline text
- No self-test; no record of the gate's own code hashes in the attestation.
- L3 records producer/gate model labels but not the gate binary/source identity.
- `gate-campaign` can report `ok: true` while survivors exist (H9) — the verdict does not always mean what it appears to.

## Proposed delta (verified by H11; supports H12/P-005)
1. **Permanent gate self-test** — a CI/regression test that runs the Gap-001 adversarial probe and **asserts the gate is RED**. Verified: the prototype correctly detects the current regression (gate is still GREEN on provably-wrong work); ~0.6 s. This test flips GREEN only when P-005 lands.
2. **Gate manifest** — record `sha256` of the gate's own sources (`gates/l1.py`, `gates/l2.py`, `codegen/property_gen.py`) plus Python/pytest versions; ~0.12 s. 
3. **Attestation** — include the gate-manifest hash in the DSSE `TraceManifest` payload, so an attestation binds the **exact gate code** that produced it.
4. **Mutation honesty (from H9)** — either make surviving mutants red the campaign, or record survivors explicitly in the attestation (currently `ok:true` with survivors is misleading).

## Impact
Provides a tool-confidence artifact (self-test + gate hash) suitable for an ISO/DO-330 discussion; makes attestations reproducible and gate-identity-bound.

## Alternatives
Rejected: no self-test (unverifiable gate); external tool qualification only (a separate program; this is the in-repo evidence basis).

## Open questions
Self-test scope (Gap-001 probe only vs a suite of adversarial probes); gate-hash update policy on every gate change; whether survivors should be fatal or advisory.

## Validation checklist
- [ ] Self-test asserts the Gap-001 probe is RED; flips GREEN after P-005.
- [ ] Gate manifest hashed and included in the attestation.
- [ ] Mutation survivors are visible in the verdict/attestation.

## Changelog
- v1, 2026-09-10 — from H11; self-test + gate manifest + attestation binding, plus the H9 mutation-honesty note.
