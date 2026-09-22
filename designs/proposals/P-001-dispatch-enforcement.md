# P-001 – Dispatch‑enforcement layer

**ID**: P-001

**Version**: v1

**Status**: PROPOSED

**Date**: 2026‑09‑10

**Target baseline**: `designs/ARCHITECTURE.md` (baseline **v0**)

## Motivation
The framework currently permits an orchestrator to dispatch a writer sub‑agent (e.g. `fixer`, `implementer`, `designer`, `general`, or an unknown lane) and accept its result without any contract binding or gate enforcement.  The existing git‑hook enforcement only fires on commit/push; the skill is advisory.  This creates a gap where work can be produced without the required contract `[contract: <name>]` marker, undermining the contract‑first guarantee.

## Current baseline text
> The interaction layer is advisory; orchestrators may dispatch sub‑agents freely.  Validation gates (`zft check`) run after the sub‑agent finishes, but there is no pre‑dispatch contract enforcement.  Git hooks fire only on commit/push and do not block sub‑agent dispatch.

## Proposed delta
1. **Add a new subsection** under the Interaction Layer (section D6) in `designs/ARCHITECTURE.md` titled **"Dispatch Enforcement"** describing the following enforcement model.
2. **Amend D6 (Interaction protocol)** to include:
   - A **pre‑dispatch gate** (`zft task‑gate before`) that inspects the sub‑agent type and the task description.
   - A **post‑task verdict** (`zft task‑gate after`) that reports forward coverage of the contract’s due clauses.
3. **CLI specification** (`src/zft/taskgate.py`):
   - Command: `zft task‑gate before|after --subagent <type> --description <text>`
   - Exit codes: `0` – allow/covered, `1` – block/missing, `2` – usage/error.
   - Emits a JSON payload on stdout.
   - Writer lanes (``fixer``, ``implementer``, ``designer``, ``general`` and any unknown type) require a ``[contract: <name>]`` marker that resolves to ``.zft/contracts/<name>.json``.
   - Read‑only lanes (``explorer``, ``explore``, ``code‑explorer``, ``librarian``, ``oracle``, ``analyst``, ``councillor``, ``vision``, ``vision‑consultant``, ``researcher``) are exempt.
   - An override marker ``[ungated: <reason>]`` or the environment variable ``ZFT_ALLOW_UNGATED=1`` permits a writer lane without a contract; the decision is recorded with ``gated: false``.
4. **Audit log** – every decision appends a single JSONL line to ``<traceagent‑root>/.zft/audit.log`` (see `append_audit`).
5. **Opencode plugin** (`.opencode/plugin/traceagent-gate.ts`):
   - Wraps the built‑in ``task`` tool; runs the CLI in the ``before`` phase and blocks dispatch on exit 1.
   - In the ``after`` phase it prepends a ``[zft gate] <report>`` annotation to the sub‑agent result.
   - Scoped to projects containing ``.zft``; fails‑open on internal errors.
   - Idempotent registration (global guard).
   - Kill switches: ``ZFT_GATE_DISABLED=1`` (disable gate) and ``OPENCODE_PURE=1`` (disable all plugins).

## Impact
- Enforces contract use at the moment a writer sub‑agent is spawned, preventing accidental or adversarial omission of contracts.
- Provides a deterministic audit trail (`.zft/audit.log`).
- Immediate feedback to orchestrators; a blocked dispatch halts downstream work.
- Distinguishes writer vs read‑only lanes, preserving flexibility for exploratory tools.

## Alternatives
1. **No enforcement** – rely solely on developer discipline and post‑hoc review (current state).
2. **Git‑hook‑only enforcement** – extend git hooks to reject commits with writer sub‑agents lacking a contract (but does not stop dispatch at runtime).
3. **Central orchestrator policy** – modify the orchestrator to check contracts before invoking the ``task`` tool (requires changes in every orchestrator implementation).

## Open questions
- How should future, custom sub‑agent types be classified (writer vs read‑only) without code changes?
- Should the plugin also emit metrics (e.g., number of gated dispatches) for monitoring?
- What is the desired behaviour when the contract file is malformed or missing? (Current implementation blocks.)
- **Direct orchestrator writes bypass the gate entirely** — the plugin gates only the `task` tool, so `edit`/`write`/`apply_patch`/shell writes by the primary agent are neither bound nor audited. Documented as `docs/KNOWN-GAPS.md` **Gap 002**; decision: document only until the enforcement design is validated. Candidate fix: non‑blocking audit of direct writes (strict behind `ZFT_GATE_STRICT=1`).

## Validation checklist
- [ ] Running ``zft task‑gate before`` for a writer lane **without** a ``[contract: …]`` marker exits with code 1 and logs a JSONL entry with `gated: false`.
- [ ] Providing a valid contract marker results in exit 0 and `gated: true`.
- [ ] The ``[ungated: …]`` marker or ``ZFT_ALLOW_UNGATED=1`` allows the dispatch and records `gated: false`.
- [ ] The ``after`` command reports coverage (verdict `covered` or `missing`) and exits with 0/1 accordingly.
- [ ] The Opencode plugin blocks a writer dispatch lacking a contract (observed in ``.zft/audit.log`` on 2026‑09‑10) and allows a dispatch with a contract.
- [ ] Audit log entries contain fields `ts`, `subagent`, `lane`, `phase`, `gated`, `contract`, and `reason`/`verdict` as appropriate.

## Changelog
- **v1, 2026‑09‑10** – Created proposal introducing dispatch‑enforcement layer and associated CLI/plugin specifications.