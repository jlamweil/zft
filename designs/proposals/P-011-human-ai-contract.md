# P-011 – Human↔AI contract: signed human approval & subjective quarantine

**ID**: P-011
**Version**: v1
**Status**: PROPOSED
**Date**: 2026-09-10
**Target baseline**: `designs/ARCHITECTURE.md` (baseline v0) D1/D4/D6; `spec/schema.py`, `negotiate/sm.py`, `cli/main.py`, `attest/dsse.py`, `gates/l2.py`

## Motivation
A human↔AI contract is the **same artifact** with the human as consumer/author and the AI as producer — the framework's Contract/Clause/Producer/Consumer are roles, not identities. What is missing is a way to bind a **human identity and signature** to the `VALIDATED` transition: today `NegotiationSM.validate()` is unconditional (`negotiate/sm.py:52`), attestation keys are auto-generated (`cli/main.py:243`), and subjective (`judge`) clauses are flagged but **not quarantined** from deterministic coverage. Regulatory regimes (ISO 26262, DO-178C) require human sign-off and verification independence.

## Current baseline text
- `validate()` reaches `VALIDATED` with no party identity/signature (`sm.py:52`).
- `attest` mints a fresh ed25519 key per run (`main.py:243`) — no human key hook.
- `judge`/`process` check kinds exist (`schema.py:9`); L2 lists `judge_excluded` but a judge clause can remain unresolved without human sign-off.
- Clauses carry no `author`; there is no approval record.

## Proposed delta (minimal overlay; engine unchanged)
1. **Schema** — optional clause `author {name,keyid}` and `subjective {kind,reason}`; contract-level `approval {keyid,signature,timestamp}`.
2. **Negotiation SM** — `human_approve(sig,keyid)`; `validate()` raises `IllegalTransition` unless a human approval was recorded. (Counter/accept flow preserved.)
3. **CLI** — `zft approve --key <pub> --sig <file>` writes the `approval` block and flips to VALIDATED; `create` gains `--author-name`/`--author-keyid`.
4. **Attestation** — include `approval` in the DSSE predicate; `verify` checks it against a trusted human-key list.
5. **Gate** — a `subjective: true` clause without a matching approval is **uncovered** for deterministic coverage (listed under `judge_gated`), not silently counted.
6. **Asymmetric trust** — a `producer_is_ai` contract flag requires the P-005 oracle-first evidence **plus** a human approval after L2.

## Impact
Makes a human↔AI contract first-class and auditable: a producer cannot self-validate; subjective clauses no longer inflate coverage; the trace manifest becomes human-signed. Directly serves ISO 26262 / DO-178C human sign-off and independence objectives, and complements P-005 (evidence independence) and P-009 (interchange).

## Performance
Negligible: one signature verification (sub-ms) and a small JSON field; no change to L0–L2 cost.

## Anti-theater
- `validate()` with no prior `human_approve` must fail — no self-validation.
- A contract containing `subjective: true` without approval must be **uncovered**.
- `verify` with the wrong human key must fail.

## Correction
An advisory review claimed source-scope / reverse-coverage / non-code anchors are "already implemented". That is **false** per the verified hypotheses H1a, H10, H13 (extraction scans non-source dirs; reverse coverage is inert; Markdown anchors do not exist). Those requirements remain **open**; only the human-approval and subjective-quarantine rows are genuinely new designs here.

## Alternatives
Rejected: reuse the auto-generated attestation key (not a human identity); trust "who ran the CLI" (not cryptographically bound); forbid subjective clauses outright (the design intentionally allows them, quarantined).

## Open questions
Human-key format (PEM/JWK/securesystemslib dict); multi-approver signatures; whether human-attested subjective evidence is a `kind: human-judge`; escalation flow on a rejected subjective clause; whether approval binds to individual clauses or the whole contract.

## Validation checklist
- [ ] Schema accepts the new optional fields; existing contracts still validate.
- [ ] `validate()` requires `human_approve`.
- [ ] `zft approve` writes the approval block + DSSE predicate entry; `verify` enforces it.
- [ ] Subjective-without-approval is uncovered.
- [ ] Existing `check`/`gate` unchanged on contracts lacking the new fields.

## Changelog
- v1, 2026-09-10 — human identity + signed approval + subjective quarantine; asymmetric-trust flag.
