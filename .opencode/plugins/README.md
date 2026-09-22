# zft for opencode — contract enforcement at two boundaries

Two small opencode plugins that wire the [`zft`](https://github.com/jlamweil/zft)
contract gate into an opencode session. Both are **silent outside a zft
workspace** — they no-op unless the project has a `.zft/` store, so installing
them globally pollutes nothing.

| Plugin | File | Hooks | What it enforces |
| --- | --- | --- | --- |
| **dispatch gate** | [`zft-gate.ts`](./zft-gate.ts) | `tool.execute.before` / `after` on the built-in `task` tool | Every subagent dispatch is either **bound to a contract** or explicitly recorded as ungated (`zft task-gate`). Blocks contract-less writer dispatches *before* they spawn; prepends the coverage verdict to the result. |
| **lint gate** | [`zft-lint-gate.js`](./zft-lint-gate.js) | `tool.execute.after` on `edit` / `write` | Every edit that lands in the contract corpus (`<root>/.zft/**`) is re-checked by L0 (`zft lint`) — the same gate CI runs, seconds after the edit instead of at commit time. |

This is **traceability enforcement**. Neither plugin proves the deliverable
*satisfies* the contract: the dispatch gate proves a contract was bound and
records the coverage verdict; the lint gate proves the store stayed
internally consistent. A producer can still ship a bound-but-fake test
(`assert True`) — see [`docs/KNOWN-GAPS.md`](../../docs/KNOWN-GAPS.md)
Gap 001. Treat the reports as binding records, not as proof of acceptance.

## Requirements

- **opencode** (built against the `1.18.x` plugin API)
- **Python 3.12+** and the CLI: `pip install zft` (or `uv pip install zft`)
- The `zft` executable reachable **one** of these ways (checked in this order):
  `ZFT_BIN` env var → `<project>/.venv/bin/zft` → `zft` on `PATH`
  → `python3 -m zft.cli.main` (lint gate only; falls back to
  `traceagent.cli.main` for the published 0.2.x wheel). Verify with `zft` —
  it should print the usage block and exit 0.

No npm dependencies. The TypeScript plugin uses only `node:child_process`
/ `node:fs` / `node:path` and a type-only import of `@opencode-ai/plugin`;
opencode transpiles it at load, so there is nothing to build.

## Install

opencode auto-loads every `.js` / `.ts` file in the plugin directories at
startup — **no `opencode.json` entry is needed** — and an opencode restart is
required for any change to take effect:

- project-scoped: `<project>/.opencode/plugins/`
- global: `~/.config/opencode/plugins/`

Copy the two files from the repository's `.opencode/plugins/` directory into
whichever scope you want (global = every zft project; project = one repo,
travels with the clone):

```bash
# global (recommended — you only do this once)
mkdir -p ~/.config/opencode/plugins
cp zft-gate.ts zft-lint-gate.js ~/.config/opencode/plugins/

# …or project-scoped, in the repo that has the .zft/ store
mkdir -p .opencode/plugins
cp zft-gate.ts zft-lint-gate.js .opencode/plugins/
```

Add the skill so the agent knows the workflow (authoring clauses, binding
deliverable elements, running the gate, reading typed rejections):

```bash
mkdir -p ~/.config/opencode/skills/zft
cp ../skills/zft/SKILL.md ~/.config/opencode/skills/zft/SKILL.md
```

**Restart opencode.** If both a global and a project copy are present, an
in-process guard makes only the first one register hooks — a dispatch is
never double-gated and an edit never double-linted.

### First run in a new project

```bash
# 1. scaffold a clause (writes .zft/specs/<domain>/<alias>.json, DRAFT)
zft create --alias EXPORT-413 --domain protocol \
  --title "Export size limit" \
  --statement "The export endpoint rejects payloads > 10 MB with 413" \
  --property "size > 10MB -> status == 413" --kind test

# 2. create the contract that binds it (directory is not auto-created)
mkdir -p .zft/contracts
cat > .zft/contracts/export.json <<'EOF'
{"contract_id": "0196f8a1-2e4a-7a3f-9c1b-8d5e6f7a8b9c",
 "name": "export", "status": "DRAFT", "version": 1, "created": "2026-09-21",
 "clause_ids": ["EXPORT-413"], "meta": {}}
EOF

# 3. verify
zft lint .          # L0 green
```

Then describe subagent work against that contract (below). Nothing is
enforced until a contract exists — the gates are opt-in per project via the
`.zft/` store.

## Daily use

**Dispatching work.** Put a `[contract: <name>]` marker in the task
description; `<name>` resolves to `.zft/contracts/<name>.json`:

```
Fix the export endpoint to reject oversized payloads [contract: export]
```

- **Read-only lanes are exempt** (`explorer`, `explore`, `code-explorer`,
  `librarian`, `oracle`, `analyst`, `councillor`, `vision`,
  `vision-consultant`, `researcher`) — they cannot mutate the deliverable, so
  they pass ungated with a recorded reason. Every other subagent type
  (including unknown ones) is a **writer** and needs the marker.
- **Escape hatch:** `[ungated: <reason>]` allows a writer dispatch and audits
  the reason (`override: true`). Use it deliberately — it appears in the log.
- **Blocked dispatch:** the block reason (the CLI's JSON) is embedded in the
  tool error the orchestrator sees, so it can adapt: add the marker, switch
  to a read-only lane, or declare the override.

**After the subagent finishes**, the coverage verdict is prepended to the
tool result as `[zft gate] coverage verdict …` — green (`covered`) or
`[zft gate] coverage verdict: MISSING clauses` plus the JSON listing the
unbound clause IDs. The verdict is non-blocking information for the
orchestrator; act on it before accepting the deliverable.

**Editing the store.** Every edit to `<root>/.zft/**` is re-linted. In
`observe` mode (default) the outcome is recorded and a failure only warns;
in `enforce` mode an L0 failure is thrown back into the session with the
findings, so the agent must repair the store before continuing. Note L0 is
**store-wide**: one torn `content_hash` anywhere fails every in-corpus edit
until fixed.

## Audit trails

Every decision is one JSONL line — never delete these by hand, they are the
evidence layer:

- `<root>/.zft/audit.log` — every dispatch decision (allow / block / verdict /
  error) with lane, phase, contract, override flag and reason.
- `<root>/.zft/gates-hook/log.jsonl` — every edit-gate decision
  (`allow` / `deny` / `passthrough` / `gate_unavailable` / `outside_root`)
  with the L0 exit code and findings tail.

## Configuration

| Env var | Meaning |
| --- | --- |
| `ZFT_BIN=<path>` | Point both plugins at a specific `zft` executable. |
| `ZFT_GATE_DISABLED=1` | Disable the dispatch gate entirely. |
| `ZFT_HOOK_MODE=observe\|enforce` | Lint gate: record-only (default) or block on L0 failure. |
| `ZFT_ALLOW_UNGATED=1` | Authorize writer dispatches without the marker (audited as overrides). |

opencode's own `OPENCODE_PURE=1` disables all plugin loading — the escape
hatch if a plugin ever breaks startup.

## Safety model

The gates are designed so a plugin fault can never take the session down:

- **Dispatch gate fails open.** A missing binary, spawn error, gate timeout
  (30 s), or any unexpected exit code (other than the deliberate policy
  block) lets the dispatch proceed with a warning on stderr. Only `exit 1`
  from `task-gate before` blocks.
- **Lint gate fails closed in `enforce` mode** — a broken or missing gate is
  recorded as `gate_unavailable` and *blocks*, never green. In `observe`
  mode it only records. (Different policies on purpose: a misconfigured
  dispatch gate must not stop work; a silently-green lint gate would defeat
  its purpose.)
- Exceptions in the `after` hooks never escape — the subagent result and the
  edit always reach the caller.
- Both plugins are scoped to `.zft/` projects and can be killed with one env
  var. The lint gate writes nothing outside the store root.

## Exit codes of the CLI seams

`zft task-gate before|after --subagent <type> --description <text>`

| exit | meaning | dispatch-gate behaviour |
| --- | --- | --- |
| 0 | allowed / recorded | proceed; `after` verdict prepended |
| 1 | policy rejection (`before`) | dispatch **blocked**, reason embedded in the tool error |
| 1 | coverage verdict with missing clauses (`after`) | verdict **surfaced**, non-blocking |
| 2/other | internal / usage error | fail open + stderr warning |

`zft lint <root>`: `0` = `L0 PASSED`, `1` = `L0 FAILED` (findings on stdout),
anything else is treated as a broken gate.

## Troubleshooting

- **Nothing happens when I dispatch.** The plugins only load where `.zft/`
  exists at the session directory. Confirm the store, confirm `zft` runs from
  the session's environment, and **restart opencode** — plugin changes
  (including the install) are not hot-reloaded.
- **`GATE_UNAVAILABLE` / gate never green.** The configured `zft` cannot run:
  check `ZFT_BIN`, or `pip install zft` for the right interpreter.
- **Every in-corpus edit fails L0.** One broken clause anywhere fails the
  whole store. `zft lint .` names it; the usual cause is a hand-edited
  `content_hash` (recompute via `spec.canon.canonical_hash` or just `zft
  create`).
- **Dispatch blocked but I have a contract.** The marker must be in the task
  *description*, the contract file must be `.zft/contracts/<name>.json`, and
  the subagent type must not be a read-only lane unless you mean it.

## For developers

The plugins are deliberately tiny and stdlib-only; the policy they enforce
lives in the Python CLI (`src/zft/taskgate.py` for dispatch,
`src/zft/spec/lint.py` for L0) — these files are only transport. A Codex
counterpart binds the same two boundaries for that client; decision tables
and log schemas are kept identical on purpose.

**Verify without a live opencode** by importing a plugin and driving its
hooks with synthetic inputs (opencode passes `args` on `output` in the
`before` phase and on `input` in `after` — that shape is what the plugins
read). With `bun` available and a `zft` on `PATH`:

```ts
import { ZftGate } from "./.opencode/plugins/zft-gate.ts"

const hooks = await ZftGate({ directory: "/path/to/store-root", sessionID: "t" })
// writer dispatch without a contract marker -> must throw
await hooks["tool.execute.before"]!(
  { tool: "task", sessionID: "t", callID: "1" },
  { args: { subagent_type: "general", description: "fix a typo" } },
)
// read-only lane -> must not throw
await hooks["tool.execute.before"]!(
  { tool: "task", sessionID: "t", callID: "2" },
  { args: { subagent_type: "explorer", description: "read the code" } },
)
```

**Verify end to end** in a throwaway project: scaffold a clause + contract
(see *First run*), then dispatch work from opencode and inspect
`.zft/audit.log` and `.zft/gates-hook/log.jsonl` — every dispatch and every
in-corpus edit must produce exactly one record.
