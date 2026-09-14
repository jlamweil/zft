# Known Gaps — traceagent

A living register of known, unsolved weaknesses in the implemented system. Each gap: status, severity, self‑contained reproduction, root causes, what the tool still guarantees, and proposed fixes with tradeoffs.

## Gap 001 — Acceptance gate verifies traceability, not conformance

- **Status:** Open — documented 2026-09-10, unsolved
- **Severity:** High

### Summary

On 2026-09-10 an adversarial probe proved that `zft check` — the primary acceptance gate — accepts a provably wrong implementation. The clause's declared `property` string is never compiled or executed anywhere in `src/zft`; the gate verifies only that a bound test *exists* (forward traceability coverage), not that the implementation satisfies the clause. A producer can pass the gate with a fake `assert True` test bound to any clause, even when the implementation visibly violates the clause statement.

### At‑risk claims

- `CONTEXT.md` §4, principles 2–3: "deterministic verification > probabilistic judgment" and "contracts must be cheap to satisfy honestly and expensive to fake."
- `designs/ARCHITECTURE.md` D4 (verification gates): "L1 local verify (property execution)" — L1 currently executes the producer's bound suite, not the clause's property.

### Reproduction (fully self‑contained)

The probe corpus (originally at `/tmp/opencode/gate‑probe`). Create the following files in an empty directory:

**`src/probe/__init__.py`** (empty file)
```python

```
**`src/probe/calc.py`**
```python
"""Deliberately WRONG implementation for the adversarial gate probe.

The clause PROBE-STRICT requires 42; this returns 41 so the gate must catch it.
"""


def answer() -> int:
    return 41
```
**`pyproject.toml`**
```toml
[project]
name = "gate-probe"
version = "0"
requires-python = ">=3.12"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```
**`.zft/specs/probe/probe‑strict.json`**
```json
{
  "node_id": "01a08ad1-2963-7d51-804c-7cd9330d3ae3",
  "alias": "PROBE-STRICT",
  "domain": "probe",
  "title": "Strict answer",
  "status": "DRAFT",
  "version": 1,
  "content_hash": "816ce558495da741b9c59d8c253ca14f0745b2bb117cbeb2c243657da5770173",
  "invariants": [
    {
      "id": "PROBE-STRICT-INV-01",
      "statement": "WHEN the probe answer is requested, THE SYSTEM SHALL return 42",
      "property": "answer() == 42",
      "check": {
        "kind": "test"
      }
    }
  ],
  "external_links": []
}
```
**`.zft/contracts/probe.json`** (initial state – only `PROBE-STRICT` listed)
```json
{
  "contract_id": "00000000-0000-7000-8000-000000000001",
  "name": "gate-probe",
  "status": "VALIDATED",
  "version": 1,
  "created": "2026-09-10",
  "clause_ids": [
    "PROBE-STRICT"
  ],
  "meta": {},
  "validated": "2026-09-10"
}
```
**`tests/test_probe.py`** (initial state – only `PROBE-STRICT` bound)
```python
from probe.calc import answer


# @trace("PROBE-STRICT")
def test_answer():
    assert True  # FAKE: bound to the clause but verifies nothing
```
---
**Step 3 – Add a `kind: property` clause**

Add the file **`.zft/specs/probe/probe‑prop.json`**:
```json
{
  "node_id": "01a08ad1-c37b-7aec-9568-f43127d9f97e",
  "alias": "PROBE-PROP",
  "domain": "probe",
  "title": "Property probe",
  "status": "DRAFT",
  "version": 1,
  "content_hash": "3cf6d95d665f3af827b6049afb6c77d9de4cfc1985cd376969f116d3531ee580",
  "invariants": [
    {
      "id": "PROBE-PROP-INV-01",
      "statement": "WHEN the property probe runs, THE SYSTEM SHALL hold",
      "property": "forall x: true",
      "check": {
        "kind": "property"
      }
    }
  ],
  "external_links": []
}
```
And extend `tests/test_probe.py` with a second bound test (initially `assert True`):
```python
# @trace("PROBE-PROP")
def test_prop():
    assert True  # FAKE: bound to a property‑kind clause
```
---
**Step 4 – Change the bound test to `assert False`**

Edit `tests/test_probe.py` so that `test_prop` becomes:
```python
# @trace("PROBE-PROP")
def test_prop():
    assert False  # FAKE: bound to a property‑kind clause
```
---
### Commands and observed outputs (verbatim)

1. ``zft check .`` → ``ok: true``, ``due: 1``, ``coverage: 1/1``, ``l1.executed: 0``
2. ``zft gate-campaign --module src/probe/calc.py --tests tests/test_probe.py --scope answer .`` → ``ok: true, total: 0, killed: 0, in_scope_total: 0`` (the micro‑mutator does not mutate the constant ``41`` at all)
3. After adding ``PROBE-PROP`` (bound to ``assert True``) ``zft check .`` still ``ok: true``, ``coverage 2/2``
4. Direct ``run_l1`` (cache cleared): with ``assert True`` → ``executed: 1, ok: True``; after changing the bound test to ``assert False`` → ``executed: 1, ok: False, failures: ['PROBE-PROP: bound suite failed']``
5. ``grep`` across ``src/zft`` for any use of the invariant's ``property`` field → **no matches**
6. ``zft check`` reports ``l1.executed: 0`` even for property clauses because ``cli/main.py:124‑125`` calls ``run_l2`` (which itself calls ``run_l1`` at ``gates/l2.py:67``, populating the cache) and then calls ``run_l1`` again → cache hit.

### Root causes

- `src/traceagent/gates/l2.py:49` — ``coverage_report(bindings, set(due))`` is binding‑existence coverage; no ``elements``, no implementation execution.
- `src/traceagent/gates/l1.py:75` — ``if "property" not in kinds: continue`` (i.e., ``kind: test``, the ``create`` default, gets zero execution evidence).
- `src/traceagent/gates/l1.py:110` — ``run_pytest(root, test_files, ...)`` runs the producer‑written test file; the clause's ``property`` is unused.
- `src/traceagent/gates/runners/mutmut_runner.py:26‑34` — ``OPS`` only mutates ``== != > < +`` and ``return True/False``; no constant mutation.
- `src/traceagent/lineage/matrix.py:17` — ``out_of_contract`` is empty when ``elements`` is ``None`` (reverse coverage inert).

### What `check` *does* guarantee

- L0 schema + content‑hash integrity (via ``zft lint``).
- Alias/duplicate detection.
- Forward binding coverage: every **due** clause has ≥ 1 trace link.
- Gherkin render + collect (all clauses render and are exercised).
- Bound‑suite execution for ``kind: property`` clauses (L1) — but the suite is the producer's own test, not the clause's ``property``.
- Typed rejections (exit 1 with JSON ``{code, clause_ids, fault, expected, actual, evidence_refs}``).

### Why it matters

The differentiator is contract‑grounded acceptance: the gate should reject work that violates an agreed clause on mechanical evidence. As implemented, the gate decouples acceptance from clause semantics — a lazy or adversarial producer passes with ``assert True``. Conformance claims downstream (attestation, exported trace matrix) rest on a gate that never executed the property.

### Proposed solutions (with tradeoffs)

- **(a) Execute the clause's declared property / require a consumer‑supplied oracle for ``test``/``property`` kinds — *recommended*.**
  Restrict ``property`` to an executable DSL (or compile it to a gate‑owned pytest that runs against the deliverable module); alternatively require a consumer‑authored ``oracle_<ALIAS>.py`` (the L1 cache key at ``l1.py:91‑95`` already hashes such a file). Trade‑off: the DSL scope is the D1 v0 blocker (property strings today are unrunnable prose); non‑code deliverables need a per‑type executor; sandboxing the eval is non‑trivial.
- **(b) Require producer negative controls.**
  Bound tests must include assertions that fail against a known‑wrong implementation (e.g., ``assert answer() != 41``). Trade‑off: cheap, no DSL needed; but only catches the class of fakery the producer anticipates – an adversarial producer can still fake the control.
- **(c) Fold mutation into ``check``, add constant mutations, enforce reverse coverage.**
  Extend ``OPS`` (``mutmut_runner.py:26‑34``) with constant mutation, run an L2‑lite inside ``check``, and pass ``elements`` into ``coverage_report`` so ``out_of_contract`` is non‑vacuous (``matrix.py:17``). Trade‑off: ``check`` becomes slower; mutation still only models bugs the operators cover; reverse coverage depends on per‑artifact element enumeration (open question 4).
- **(d) Document the boundary (status quo).**
  Declare that ``check`` verifies traceability + integrity, not conformance; shift conformance burden to L2 campaigns and consumer‑side verification. Trade‑off: zero code change, honest; but the acceptance gate can still accept provably wrong code, and every green verdict needs a disclaimer.

### Future acceptance test

The above probe must make ``zft check`` **RED**.

## Gap 002 — Dispatch enforcement is delegation-boundary only (direct orchestrator writes bypass it)

- **Status:** Open — documented 2026-09-11; decision: **document only** until the enforcement design is validated
- **Severity:** Medium–High

### Summary
The opencode plugin gates **only the `task` tool** — `tool.execute.before`/`after` early-return unless `input.tool === "task"`. When the primary/orchestrator agent edits files **directly** (`edit`/`write`/`apply_patch`, or shell writes), no `zft task-gate` runs: no contract binding, no typed verdict, and **no audit line**. So the framework's enforcement applies to *delegated* work but not to the orchestrator's own work — "presence is not evidence" must also apply to which activity the gate covers.

### Why it matters
- A delegate-everything workflow is gated; a direct-edit workflow silently bypasses the gate. This was exercised while finishing WP-A3 and implementing WP-C4 directly.
- Partial mitigation: **pre-commit** runs `zft lint` and **pre-push** runs `zft check .`, so direct work *is* touched by zft at commit/push — but there is no edit-time contract binding or audit, and nothing ties a direct edit to a clause.

### Evidence
- Plugin guard code — `if (input.tool !== "task" || !active()) return;`
- `.zft/audit.log` contains only `task`-dispatch records (subagent before/after), no direct-edit records.

### Proposed solutions (design not yet validated — do not build yet)
- **(a) Audit direct writes (recommended first step).** Hook `edit`/`write`/`apply_patch` in governed projects → non-blocking `zft task-gate direct --tool <name> --file <path>` appends `{kind:"direct", tool, file}` to `.zft/audit.log`. Bypass becomes visible; zero friction.
- **(b) Strict direct gate (opt-in).** Same hook blocks a direct write without an active contract/run (`TRACEAGENT_GATE_STRICT=1`). Strong, but disruptive.
- **(c) Status quo.** Rely on commit/push hooks; keep the boundary documented.

### Decision (2026-09-11)
**Document only** for now — no enforcement implementation until the design is validated. Recorded here so the bypass is visible rather than silent.
