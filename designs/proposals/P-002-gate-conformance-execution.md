# P-002 – Gate conformance execution

**ID**: P-002

**Version**: v1

**Status**: PROPOSED

**Date**: 2026‑09‑10

**Target baseline**: `designs/ARCHITECTURE.md` (baseline **v0**)

## Motivation
An adversarial probe (documented in `docs/KNOWN-GAPS.md` Gap 001) demonstrated that `zft check` accepts a provably wrong implementation.  The clause's declared `property` string (`answer() == 42`) was never compiled or executed; the gate only verified that a bound test file existed (forward traceability) and that the test passed (`assert True`).  Consequently, a producer can pass the gate with a fake test, violating the principle *"deterministic verification > probabilistic judgment"*.

## Current baseline text
- **L2** (`gates/l2.py:49`) performs only *binding‑existence* coverage:
  ```python
  report = coverage_report(bindings, set(due))
  ```
- **L1** (`gates/l1.py:75`) skips any clause whose `check.kind` is not `property`:
  ```python
  if "property" not in kinds:
      continue
  ```
- For property clauses, **L1** runs only the producer‑authored test files (`gates/l1.py:110`):
  ```python
  result = run_pytest(root, test_files, timeout_s=examples_timeout_s)
  ```
- The clause’s `property` field is free‑form prose; a grep of the entire `src/zft` tree finds **no references** to this string (see `docs/KNOWN-GAPS.md` step 5).
- The DSL for clause invariants is noted as a *v0 blocker* in **D1** of `designs/ARCHITECTURE.md`.

## Proposed delta
Amend **D4‑L1** and the Gap 001 entry to enforce execution of clause semantics:
1. **Compile/execute the clause’s `property`** – either by:
   - Translating the property DSL into a pytest test (property‑DSL → pytest codegen), **or**
   - Requiring a consumer‑owned oracle file ``oracle_<ALIAS>.py`` (already hashed at `gates/l1.py:91‑95`).
2. **Treat `assert True` clauses as failing** – a clause whose property reduces to a trivial truth must cause the L1 gate to red.
3. **Update L1 to run the generated/property test** instead of only the producer‑bound suite.
4. **Document the change** in `designs/ARCHITECTURE.md` under D4‑L1, stating that property clauses are now mechanically verified.
5. **Add a validation step** to the Gap 001 probe: the same test must now produce a RED verdict.

## Impact
- The acceptance gate will reject implementations that violate the clause semantics, closing Gap 001.
- Guarantees deterministic verification for property‑kind clauses, aligning with the framework’s core principle.
- Provides a clear path for future DSL extensions (non‑code deliverables) and oracle‑based checks.

## Alternatives
(a) **Property‑DSL → pytest codegen** – compile the DSL into an executable test suite (recommended).
(b) **Consumer‑supplied oracle** – require an ``oracle_<ALIAS>.py`` file that the gate executes; this leverages the existing cache‑key logic (`gates/l1.py:91‑95`).
(c) **Mandatory negative controls** – producers must include a failing assertion (e.g., `assert answer() != 41`) in the bound test; this catches simple cheats but relies on the producer to anticipate the attack.

## Open questions
- **DSL scope**: how far should the property DSL support non‑code artifacts (e.g., documentation claims)?
- **Oracle ownership**: who creates/maintains the ``oracle_<ALIAS>.py`` files, and how are they versioned?
- **Sandboxing**: what runtime isolation is required for executing generated property tests or oracle code?

## Validation checklist
- [ ] Run the Gap 001 probe (`PROBE‑STRICT` clause) and verify that ``zft check .`` is **RED** (exit 1).
- [ ] Confirm that a clause with `property: "assert True"` now causes L1 to fail.
- [ ] Verify that a valid ``oracle_<ALIAS>.py`` file is read, hashed, and influences the cache key (as in `gates/l1.py:91‑95`).
- [ ] Ensure that `run_l1` now executes the generated/property test rather than only the producer‑bound suite.
- [ ] Update the documentation in `designs/ARCHITECTURE.md` to reflect the new verification semantics.

## Changelog
- **v1, 2026‑09‑10** – Created proposal to make L1 execute clause properties / require oracle, fixing Gap 001.