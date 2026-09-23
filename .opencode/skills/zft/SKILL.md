---
name: zft
description: Contract-first, traceable coding work using zft. Use when starting or reviewing non-trivial coding work that must be provably traceable: author clause contracts, bind deliverable elements with @trace("ALIAS"), run the zft gate, and produce/export the trace manifest. Trigger on "zft", "traceagent", "contract-first", "clause", "coverage", "traceability", "trace matrix", or when accepting/rejecting a delegated deliverable.
---

# zft

## When to use / not to use

**Use** when you need provable, contract‑first traceability:
- Starting non‑trivial coding work that must be bound to a clause contract.
- Accepting or rejecting a delegated deliverable.
- Checking clause coverage or exporting the trace matrix.

**Do not use** for trivial fixes, work without a contract, or pure observability (LangSmith, OTel, etc.).

## Invocation

Run from the repository root. The console script `zft` (package `zft`, source `src/zft/`) is installed; in this repo use `.venv/bin/zft` if it is not on `PATH`.

There is **no** `--help`. A bare `zft` prints:
```
usage: zft <lint|extract|check|impact|gate|repro|attest|verify|export|negotiate|create|baseline|driver-gate|mutation-bar|task-gate> [root]
```
Exit codes: `0` green, `1` typed rejection (JSON printed), `2` usage error.

## Author a clause (before the work)

```bash
zft create \
  --alias <ALIAS> \
  --domain <domain> \
  --title "<title>" \
  --statement "WHEN <trigger>, THE SYSTEM SHALL <response>" \
  --property "<predicate>" \
  --kind test .
```
- Only `--alias` is required; `--domain` defaults to `misc`; `--title` defaults to the alias; `--kind` defaults to `test` (other kinds seen: `property`, `type`, `judge`, `process`).
- Writes `.zft/specs/<domain>/<alias-lowercase>.json` containing `status: "DRAFT"`, `version: 1`, a generated UUIDv7 `node_id`, and a `content_hash`.
- No CLI to attach a clause to a contract – manually add the alias to the `clause_ids` array in `.zft/contracts/<name>.json`.

## Bind a deliverable element

Place a comment directly **above** the test/function that implements the clause:
```python
# @trace("ALIAS")   # Python
```
```c
// @trace("ALIAS")   // other languages
```
Aliases match `[A-Z0-9-]+` (uppercase). `zft extract` dumps the binding list as JSON. The dogfood corpus binds tests in `tests/unit/`.

## Gates

- `zft lint` – fast L0 (schema, content hashes, alias/duplicate detection). Use as a commit‑hook. In an opencode session the [edit gate](../../plugins/README.md) runs this automatically on every `.zft/**` edit (`ZFT_HOOK_MODE=enforce` blocks on failure).
- `zft check .` – full local gate: L0 → coverage → L1 property evidence → L2‑fast; prints JSON `{stage, ok, due, deferred, l1, gate_log, coverage, failures}`. Slower (runs pytest, mutation, gherkin). Green requires every **DUE** clause to be covered; clauses in contract `meta.target_milestone` beyond v0 are **deferred** and do not block. A green `check` proves **traceability, not conformance**: it does binding‑coverage for due clauses, L0 integrity, and bound‑suite execution for `kind: property` clauses — the clause's declared `property` is never compiled or executed (see `docs/KNOWN-GAPS.md`, Gap 001).
- `zft gate-campaign --module <path> --tests <path> [--scope f1,f2] [--oracle <path>] [--conftest <path>] [--sandbox <dir>] [root]` – deep L2 mutation campaign (`gate` is an alias).
- `zft repro <run_id> [root]` – re‑executes only the failed units of a run.

## Acceptance artifacts

- `zft attest .` writes a signed DSSE **TraceManifest** to `.zft/attest.json`; `--key-out <path>` also writes the public key.
- `zft verify .` verifies the signature **and** re‑derives clause digests from the live store; requires the public key (`--key <path>`, default `.zft/attest.pub.json`).
- `zft export --format matrix` (or `summary`) prints the trace matrix; it **REFUSES** if there is no attestation.

## Orchestrator acceptance rule

For a delegated deliverable, do **not** accept on prose. Run `zft check .`; accept only when it is green **and** the exported trace matrix maps **each** contract clause to a deliverable element with evidence. **When delegating a writer lane in a governed project, the task description must contain a `[contract: <name>]` marker that resolves to the relevant contract.** A green `check` proves **traceability, not conformance** — do not accept correctness on it alone; independently execute the clause's property/oracle against the deliverable (see `docs/KNOWN-GAPS.md`, Gap 001). On exit 1, reject with the typed JSON `{code, clause_ids, fault, expected, actual, evidence_refs}` and route:
- `fault: "implementation"` → back to the producer.
- `fault: "contract"` → back to the spec author.

## Coverage semantics

- **Forward coverage** = % of due clauses with ≥ 1 trace link.
- **Reverse coverage** = % of deliverable elements justified by a clause.
- Both are load‑bearing; unresolved bindings cause gate failure.
- Run ledgers live in `.zft/runs/<run_id>/`.

## Files and paths

| Path | Purpose |
| ---- | ------- |
| `.zft/specs/**` | Clause JSON files |
| `.zft/contracts/<name>.json` | Contract definitions; `clause_ids` list |
| `.zft/attest.json` | Signed DSSE TraceManifest (from `attest`) |
| `.zft/attest-key.pub.json` | Public key (default for `verify`) |
| `.zft/runs/<run_id>/` | Run ledgers |

## Dispatch enforcement (opencode plugin)

The `zft task-gate` commands enforce contract‑binding at the subagent‑dispatch boundary.

- **Commands**
  - `zft task-gate before --subagent <type> --description <text>` – runs before a subagent is spawned.
    - Exit 0: dispatch allowed (recorded).
    - Exit 1: policy rejection (blocked).
    - Exit 2 or other: internal/usage error – the plugin fails open (dispatch proceeds).
    - Emits a JSON object on stdout describing the decision.
  - `zft task-gate after --subagent <type> --description <text>` – runs after the subagent finishes, prepending a coverage verdict to the tool output. Exit 0 = `covered`; exit 1 = verdict with **missing** clause IDs (surfaced to the orchestrator, non-blocking — act on it before accepting the deliverable); exit 2 = error (ignored).

- **Plugin** (`.opencode/plugins/zft-gate.ts`) wraps the built‑in `task` tool: it calls `task-gate before` to possibly block the dispatch, and `task-gate after` to prepend a gate report. A sibling plugin (`.opencode/plugins/zft-lint-gate.js`) runs `zft lint` on every `.zft/**` edit.
  - Auto‑activates only in directories containing a `.zft/` folder.
  - Requires an opencode restart after changes.
  - Install and full reference: [`.opencode/plugins/README.md`](../../plugins/README.md).

- **Writer lanes** (e.g. `fixer`, `implementer`, `designer`, `general`, or any unknown type) must include a `[contract: <name>]` marker in the task description; the name resolves to `.zft/contracts/<name>.json`.
- **Read‑only lanes** – `explorer`, `explore`, `code‑explorer`, `librarian`, `oracle`, `analyst`, `councillor`, `vision`, `vision‑consultant`, `researcher` – are exempt from the contract requirement.

- **Override** – a dispatch can be allowed without a contract by adding `[ungated: <reason>]` to the description, or by setting the environment variable `ZFT_ALLOW_UNGATED=1`. The audit log records `override: true` and the provided reason.

- **Kill switches** – set `ZFT_GATE_DISABLED=1` to disable the gate entirely, or `OPENCODE_PURE=1` to prevent any plugins from loading.

- **Binary override** – `ZFT_BIN` can point to a custom `zft` executable; otherwise the plugin prefers `<repo>/.venv/bin/zft`, then `zft` on the system `PATH`. An explicit `ZFT_BIN` that cannot run is authoritative: the dispatch gate fails open, the lint gate fails closed in `enforce` mode.

- **Audit log** – every decision (allow, block, error, verdict) appends a single JSONL line to `<repo>/.zft/audit.log` with timestamp, subagent, lane, phase, and details.

- **Scope** – this is **traceability** enforcement only; it does **not** validate that the subagent’s output satisfies the contract’s clauses (see [`docs/KNOWN-GAPS.md`](../../../docs/KNOWN-GAPS.md), Gap 001).

## Gotchas

- `DRAFT` status is schema‑valid; the clause `content_hash` **excludes** the `status` field.
- No CLI to append clauses to a contract – edit `clause_ids` manually.
- `zft check` is slow; use `lint` for frequent commits.
- `export` requires a prior attestation.
- Never hand‑edit `content_hash`.
