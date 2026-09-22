# P-005 – Conformance mechanism: oracle-first, contract-pinned

**ID**: P-005
**Version**: v2
**Status**: PROPOSED
**Date**: 2026-09-10
**Target baseline**: `designs/ARCHITECTURE.md` (baseline v0) §4 / D4-L1

## Motivation
Gap 001: `check` proves a binding exists, not that the implementation satisfies the clause. A live incident made it concrete: a "fix" added `oracle_<ALIAS>.py` stubs and an L1 change that only checked the file **exists** — the oracle was never executed and the tests passed via the producer's `assert True`. **Presence is not evidence; the gate must execute the check itself.**

## Current baseline text
- L1 runs the **producer's** bound test files for property clauses (`gates/l1.py:110`); the clause `property` string is never compiled.
- `oracle_<ALIAS>.py` is consulted only for the cache key (`gates/l1.py:91-95`); never imported.
- `kind: test` clauses (the `create` default) get no execution evidence at all (`l1.py:75`).

## Proposed delta (v2 — revised by verified evidence)
For `check.kind == "property"`, accept evidence only from a **gate-executed, contract-pinned, consumer-owned oracle**:
1. **Oracle location** — consumer-owned (`.zft/oracles/oracle_<ALIAS>.py`, path declared in the contract), **not** the producer tree or repo root.
2. **Interface** — `def check():` executed in a subprocess with the fixture root on `sys.path`; failure ⇒ clause RED.
3. **Pin** — the contract records the oracle `sha256`; L1 verifies the pin **before** execution. Mismatch ⇒ `L1_ORACLE_PIN_MISMATCH` (fault: producer), no execution.
4. **Contract integrity** — the agreed contract-manifest `sha256` is verified at gate entry; drift ⇒ `L0_CONTRACT_HASH_DRIFT` (fault: contract), no oracle execution.
5. **Evidence** — `evidence_refs` records oracle/suite/contract hashes; the L1 cache key includes the oracle digest, so any oracle change invalidates cached verdicts.

## Verified evidence (rounds 1–4)
| Claim | Result |
|---|---|
| the oracle is never executed today | sentinel never fired; `ok=True` regardless → **presence-only** |
| gate-integrated execution works | correct→GREEN, wrong impl→RED, mutated oracle→RED, no/empty/wrong-name oracle→RED |
| execution is cheap | ~10–15 ms/clause; subprocess ~0.01 s |
| batched in one session | per-clause verdicts + isolation; mutating 1 of 5 fails only that clause; 0.26 s vs 1.29 s |
| pin model | substitution→`L1_ORACLE_PIN_MISMATCH`; pin tamper→`L0_CONTRACT_HASH_DRIFT`; oracle change invalidates cache and flips verdict |

**H12 supersedes H2f:** the static "must import the target" guard was a heuristic; the contract-pin + contract-hash model is the deterministic trust boundary.

## Anti-theater acceptance (mandatory)
- Mutating the oracle's expected value flips the verdict RED.
- A property clause with only a producer `assert True` is RED.
- Producer substitution of the oracle is rejected (pin mismatch); pin tampering is rejected (contract drift).

## Impact
Independent, executed evidence for property clauses; closes the exploitable half of Gap 001. Cheap (~10–15 ms/clause) and batchable.

## Alternatives
Rejected: presence-only checks; a formal compiler (too heavy); manual process sign-off (reintroduces judgment); the H2f static guard (evadable; replaced by the pin model).

## Open questions
Oracle path convention and authoring workflow; whether to also hash the oracle into the clause `content_hash` or keep it contract-pinned; sandbox isolation level; independent proof for critical `kind: test` clauses (deferred).

## Validation checklist
- [ ] Clause schema + oracle interface + contract pin defined.
- [ ] L1 verifies the pin, executes the oracle, records evidence hashes.
- [ ] Anti-theater tests (mutation→RED; producer-only→RED; substitution/tamper→typed rejection) pass.
- [ ] Real oracles for `ID-CONTENT-CHANGE`, `TR-DETERMINISTIC-EXTRACTION`.
- [ ] L1 within P-006 budget.

## Changelog
- v1, 2026-09-10 — option space, recommendation, anti-theater test.
- v2, 2026-09-10 — folded verified evidence (H2a–f, H12); replaced the static guard with the contract-pin trust model.
