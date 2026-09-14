# Pi (`earendil-works/pi`) — Integration Design for a traceagent Pi Package

> Researched and designed 2026-09-06. Primary source: shallow clone of
> [earendil-works/pi](https://github.com/earendil-works/pi) at commit
> `9767ba275f3e9a5ee0f5c5342249b629ab1b2282` (main, 2026-09-06),
> `@earendil-works/pi-coding-agent` version `0.85.1`. Repo metadata fetched via
> GitHub API on 2026-09-06: **102,374 stars** (the research brief's "~90k" is
> stale), MIT license, description "AI agent toolkit: unified LLM API, agent
> loop, TUI, coding agent CLI". All `pi` file:line citations below refer to the
> pinned clone (mono-repo root unless prefixed `packages/coding-agent/`); all
> `traceagent` citations to this repo.
> Design context: [`designs/ARCHITECTURE.md`](../../designs/ARCHITECTURE.md)
> (D4 gate tiers, D6 protocol), sibling design
> [`DSH_INTEGRATION.md`](DSH_INTEGRATION.md) (same gate suite on a
> plugin-everything harness — useful contrast).

## 0. Corrections to the research brief (verified against the clone)

The brief was accurate on every load-bearing claim. Four precisions:

1. **Stars stale**: ~90k → **102,374** (GitHub API, 2026-09-06).
2. **"skills (capability packages: instructions+tools)"** — skills bundle
   *instructions + helper scripts/assets* per the Agent Skills standard
   (`docs/skills.md:7`); they do **not** register tools. Tools come only from
   extensions (`pi.registerTool`). A skill can only *instruct* the model to run
   a script, and "models don't always do this" (`docs/skills.md:69`) — which is
   exactly why enforcement cannot live in a skill (see §7).
3. **"50+ extension examples"** → 69 top-level `.ts` examples plus 10
   subdirectory examples (79 entries under `packages/coding-agent/examples/extensions/`),
   including the cited `permission-gate.ts`.
4. **Housekeeping**: `pi.dev` is the package gallery, not the repo homepage
   (GitHub `homepage` field is empty; gallery at `docs/packages.md:137`). The
   mono-repo is "pi-mono" — packages `ai`, `agent`, `tui`, `chord`, `client`,
   `coding-agent`, `evals`, `protocol`, `server`, `session-backends`,
   `telemetry`.

Confirmed verbatim from the brief: MIT (`LICENSE`); deliberately **no MCP** —
"Build CLI tools with READMEs (see Skills), or build an extension that adds
MCP support" (`README.md:499`; note `README.md:395` lists "MCP server
integration" as an *extension* someone could build); **no sub-agents**
(`README.md:501`); **no permission popups** — "build your own confirmation flow
with extensions" (`README.md:503`); TypeScript extension modules; prompt
templates (`docs/prompt-templates.md`); RPC + SDK + print/JSON modes
(`docs/rpc.md`, `docs/sdk.md`, `docs/json.md`).

## 1. What `pi` is (verified facts we build on)

- **Runtime**: TypeScript ESM mono-repo; the coding agent loads extensions as
  TypeScript via **jiti — no compilation step** (`docs/extensions.md:179`).
  Minimal core by policy: workflow behavior is pushed into extensions, skills,
  prompt templates, and packages (`docs/usage.md:307-309`).
- **Extension shape**: a module with a default-exported factory receiving
  `ExtensionAPI` (`pi`), sync or async (`docs/extensions.md:156-176`). Loaded
  from `~/.pi/agent/extensions/` (global) or `.pi/extensions/` (project-local,
  **only after project trust**, `docs/extensions.md:113`), hot-reloadable with
  `/reload`, or one-off via `pi -e ./ext.ts` (`docs/extensions.md:7`).
  "Extensions run with your full system permissions and can execute arbitrary
  code. Only install from sources you trust." (`docs/extensions.md:111`).
- **Interception points** (lifecycle diagram `docs/extensions.md:277-349`):
  `tool_call` — fires after `tool_execution_start`, before execution — can
  **block** via `{ block: true, reason?, terminate? }` and can **mutate
  `event.input` in place** with no re-validation afterwards
  (`docs/extensions.md:786-793`); `tool_result` can modify results (middleware
  chain, `docs/extensions.md:844-875`); `input` can intercept/transform user
  input; `session_before_*` can cancel; `before_agent_start` can inject a
  message and rewrite the system prompt. Crucially, **`turn_end` and
  `agent_settled` are notification-only** — there is no interception at turn
  close (`docs/extensions.md:601-613`, `567-581`).
- **Session log**: JSONL, versioned (v3), tree-structured entries. Extensions
  persist state with `pi.appendEntry(customType, data)` → `CustomEntry`:
  "Extension state persistence. **Does NOT participate in LLM context**"
  (`docs/session-format.md:263-271`); restore pattern on `session_start`
  (`docs/extensions.md:1480-1487`). `pi.sendMessage` is the counterpart that
  *does* enter LLM context (`docs/extensions.md:1416-1437`). No
  required-on-read rule: stock readers tolerate unknown custom entries — no
  `ignorable`-flag dance like dsh.
- **No approval service** — by design. The shipped `permission-gate.ts` example
  builds its own confirmation with `ctx.ui.select`, and **blocks by default
  when there is no UI** (`packages/coding-agent/examples/extensions/permission-gate.ts:20-23`).
  `ctx.hasUI` is false in print (`-p`) and JSON modes (`docs/extensions.md:970-974`);
  `ctx.mode` is `"tui" | "rpc" | "json" | "print"`.
- **Subprocess helper**: `pi.exec(command, args, { signal, timeout })` →
  `{ stdout, stderr, code, killed }` (`docs/extensions.md:1668-1675`).
- **Built-in tools** (the names our gate switches on): `bash`
  (`src/core/tools/bash.ts:376`), `write` (`write.ts:50`), `edit`
  (`edit.ts:149`), `read`, `grep`, `find`, `ls`, `powershell`. `write`/`edit`
  inputs carry `path`; `bash` carries `command`.
- **Skills**: Agent Skills standard directories with `SKILL.md` frontmatter
  (`name`, `description` required; name `^[a-z0-9-]{1,64}$`, description ≤1024
  chars — `docs/skills.md:140-161`). Locations: `~/.pi/agent/skills/`,
  `~/.agents/skills/`, project `.pi/skills/` and `.agents/skills/` (post-trust),
  package `skills/` dirs, or `pi.skills` manifest entries
  (`docs/skills.md:24-34`). Progressive disclosure: descriptions in the system
  prompt, full `SKILL.md` read on demand; `/skill:name` forces it
  (`docs/skills.md:65-91`).
- **Packages**: distribution is npm/git/local via `pi install`
  (`docs/packages.md:23-27`); `-l` writes project settings (`.pi/settings.json`),
  which the team shares and pi auto-installs on startup after trust
  (`docs/packages.md:43`). A package declares resources under a `pi` manifest
  key: `{ "extensions": [...], "skills": [...], ... }` (`docs/packages.md:116-135`).
  Pi-bundled imports (`@earendil-works/pi-coding-agent`, `typebox`, …) go in
  `peerDependencies` with `"*"` ranges and are not bundled; other runtime deps
  in `dependencies` (`docs/packages.md:169-190`).
- **Modes for automation**: `--mode json` emits the session event stream as
  JSON lines on stdout (`docs/json.md`); RPC mode drives pi programmatically
  (`docs/rpc.md`); print mode is one-shot. These are our *observer* surface,
  not our enforcement surface.

## 2. The interception surface we map onto

Same gate suite as the dsh design, relocated to pi's flatter event model:

| Gate need | dsh mechanism (DSH_INTEGRATION.md §2) | pi mechanism | pi citation |
| --- | --- | --- | --- |
| Contract/evidence integrity gate | `tools/pre-execute` waterfall, `{allow\|deny\|ask}` | `tool_call` handler → `{ block: true, reason }` | `docs/extensions.md:778-793` |
| Dangerous-command confirmation | `{kind:'ask'}` → harness approval service | **self-built**: `ctx.ui.confirm`/`ctx.ui.select`; no-UI ⇒ deny | `permission-gate.ts:19-26`, `README.md:503` |
| Result substitution (v0: observe only) | `tools/post-execute` | `tool_result` middleware (unused by us in v0) | `docs/extensions.md:844-875` |
| Turn-end check gate | `agent/turn-stopping` (serial, steer) | **no interception at turn close** — `agent_settled` + `pi.sendUserMessage(..., {deliverAs:"followUp"})` steering *loop* (§3.3) | `docs/extensions.md:567-581`, `1439-1467` |
| Turn/commit record | `turn/end` session record | `turn_end` event (notification) + session JSONL entries | `docs/extensions.md:601-613` |
| Evidence firehose | `session/event` emit | `--mode json` event stream (external collector) | `docs/json.md` |
| Gate/attestation outcome into log | `session.append` + declaration merging, `ignorable: true` | `pi.appendEntry("traceagent/*", …)` custom entries — log-only, tolerated by stock readers | `docs/session-format.md:263-271` |
| Full mutation campaign on demand | `ctx.tools.register` | `pi.registerTool` | `docs/extensions.md:1365-1414` |
| Check/attest workflows | plugin services + CLI | **skills** (instructions) driving the **CLI via bash** — the pi-native "CLI tools with READMEs" pattern | `README.md:499`, `docs/skills.md` |
| Human `!` shell escape | — (n/a) | `user_bash` event could be gated too; **v0 skips** (human typed it) | `docs/extensions.md:879-906` |

## 3. Design: `traceagent-pi` package

One pi package — extensions + skills — with the traceagent CLI as the only
execution seam. No gate logic in TypeScript beyond policy matching; everything
mechanical stays in Python.

### 3.1 Trust model (stated plainly)

Identical conclusion to dsh §3.1, weaker framing: a pi extension is
same-privilege in-process code ("your full system permissions",
`docs/extensions.md:111`) and can be unmounted by whoever controls the
harness — so path policy is **contract discipline, not a security boundary**.
Tamper-evidence rests on the DSSE ed25519 signature and key custody, exactly as
before. Pi's project-trust gate (`docs/extensions.md:355-368`) is a deployment
prerequisite, not an enforcement mechanism of ours. What the integration
enforces is traceagent's principle: "contracts must be cheap to satisfy
honestly and expensive to fake" (`CONTEXT.md` §4.3).

### 3.2 `tool_call` — contract & evidence integrity gate

Pure in-process TypeScript (no subprocess — same decision as dsh §3.2:
deterministic, cheap, per-call):

- **Deny** `write`/`edit` whose `path` resolves (against `ctx.cwd`) into
  `policy.protectPaths` (default `['.zft/**', '.traceagent/**']`) or outside
  the project root. The clause store changes only through negotiation
  (`traceagent negotiate`); evidence dirs only through the pipeline. Denial
  reasons name the seam: `protected by traceagent: .zft/specs/... (amend via
  contract negotiation, clause <alias>)`. Same denial shape as
  `protected-paths.ts` (`examples/extensions/protected-paths.ts:13-29`).
- **Ask** on `bash`/`powershell` matching `policy.askCommands` (default
  `['git push*', 'rm -rf*']`) — `ctx.ui.confirm`, and **deny when
  `!ctx.hasUI`** (print/JSON/automation), following the shipped
  permission-gate precedent (`permission-gate.ts:20-23`).
- **Never mutate `event.input`**: pi performs no re-validation after handler
  mutations (`docs/extensions.md:786-788`) — the same reason dsh's pre-execute
  excludes rewriting; we deny, we don't launder calls.
- **Observe mode** (`policy.mode: "observe"`): record every decision via
  `appendEntry` but `allow` instead of `deny` — shadow-run before enforcing.
- Ordering guarantee we rely on: before `tool_call` handlers run, pi drains
  prior agent events through `AgentSession`, so `ctx.sessionManager` is current
  through the assistant tool-call message (`docs/extensions.md:782-784`). In
  parallel tool mode a block affects only that call — fine for us, each call is
  judged independently (`docs/extensions.md:793`).

### 3.3 Turn-close check — a steering *loop*, not a wall

Honest mapping of dsh's `agent/turn-stopping` gate, respecting that **pi has no
turn-close interception**:

- Config-gated (`check.onSettled`, default **false**): on `agent_settled`
  (pi will not auto-continue — `docs/extensions.md:567-570`), run
  `traceagent check <root>` via `pi.exec` under `check.timeoutS` (default 300).
  Parse the JSON (keys: `ok`, `failures`, `due`, `deferred`, `l1`,
  `gate_log`, `coverage` — `src/traceagent/cli/main.py:178-188`).
- On `ok: false` and retries left: `pi.sendUserMessage(<bounded rejection:
  failures with clause IDs, due/deferred counts, deterministic_coverage>,
  { deliverAs: "followUp" })` — this starts a corrective turn. This is
  traceagent's D6 "bounded, typed rejections naming clause IDs" as a
  producer-facing loop, `check.maxRetries` (default 3) after which the
  extension stops steering and notifies the human (`ctx.ui.notify`,
  error-styled) — the human consumer is the wall the loop escalates to.
- On timeout/CLI crash: **fail loud** — notify with the error, never silently
  pass; the partial run stays resumable via `traceagent repro <run_id>`
  (ledger checkpoint/resume, `src/traceagent/cli/main.py:235-251`).
- Enforce/observe symmetry: in observe mode the loop reports but does not
  steer.
- **Small traceagent-side fix this surfaces**: `check` output does not include
  the `RunLedger` `run_id`, so the extension correlates its record with
  `.traceagent/runs/` by newest-dir heuristics today; add `run_id` to the check
  JSON (one line + test) and drop the heuristic.

Enforcement at `tool_call` + steering loop + signature is the right honesty
budget for a harness whose philosophy is "no permission popups": within a
session the gate disciplines the producer; across sessions the DSSE envelope
is what actually binds.

### 3.4 EARS check as skill (not enforcement — instructions)

`skills/traceagent-check/` — `SKILL.md` (frontmatter `name: traceagent-check`,
description tuned for triggers like "check the contract", "why is the gate
red", "validate against clauses", "EARS") plus `references/pipeline.md`
(L0→L1→L2 tier reference, `designs/ARCHITECTURE.md` D4). Body instructs the
agent to:

1. Lint first: `traceagent lint .` — L0 static findings with `✗/⚠` rendering
   (`src/traceagent/cli/main.py:65-83`); author clauses with
   `traceagent create --alias --domain --title --statement --kind` where
   `--statement` must parse as EARS:
   `[<WHEN|IF|WHILE|WHERE> <trigger>,] THE SYSTEM <SHALL|MUST> <response> [.]`
   — failures raise layered diagnostics (problem, excerpt, expected grammar,
   fix hint; `src/traceagent/dsl/ears.py:1-7`).
2. Run `traceagent check .`; read the JSON: `failures` name clause IDs and the
   responsible role (surviving mutants ⇒ contract fault → spec agent; valid
   clause failing ⇒ implementation fault → producer, bounded retries);
   `gate_log.judge_excluded` lists clauses judged subjectively and excluded
   from `deterministic_coverage` claims.
3. Before merge/attest: full mutation campaign `traceagent gate --module M
   --tests T [--scope …]` (`main.py:191-233`) — minutes, so never inside a
   turn-close loop; the registered tool (§3.2's sibling, below) or plain bash.

The skill is the *workflow carrier*; it must never be the *enforcer* — the
model can skip reading it (`docs/skills.md:69`). Enforcement lives in §3.2;
the skill makes honest compliance cheap.

**Registered tool for the campaign**: `pi.registerTool("traceagent_gate")`
(typebox params `module`, `tests`, `scope?`) wrapping `traceagent gate` via
`pi.exec` with a long timeout, returning the JSON summary (`ok`, `killed`,
`in_scope_killed/total`, `survivors`) — the deliberate, on-demand path dsh
gave a registered tool too (dsh §3.3). `promptSnippet`/`promptGuidelines`
written per the naming rule (`docs/extensions.md:1373-1375`).

### 3.5 Attest as CLI tool (the pi-native shape)

`traceagent attest` / `verify` / `export` / `repro` / `negotiate` stay pure
CLI, invoked by the agent through bash — this *is* pi's stated pattern ("No
MCP. Build CLI tools with READMEs", `README.md:499`). `skills/traceagent-attest/SKILL.md`
is that README: preconditions (green `check` + green full `gate`),
`traceagent attest .` → envelope at `.traceagent/attest.json` + rotating
public key at `.traceagent/attest-key.pub.json` (`main.py:253-272`),
self-check `traceagent verify --key-in .traceagent/attest-key.pub.json`,
human-readable matrix `traceagent export --format matrix`, and the key-custody
warning (ephemeral signer; `--key-out` to a custody path for durable
verification). No auto-attest in the extension (contrast dsh §3.4's
`attestOnGreen`) — attestation is a deliberate act by whoever owns the key.

### 3.6 Feeding the session log

```ts
// gate outcome for one settled run — log-only, never model-visible
pi.appendEntry("traceagent.gate", {
  ok, runId, gitCommit, failures, due, deferred,
  deterministicCoverage: coverage, gateLog,
})
// policy decision (observe mode records allows too)
pi.appendEntry("traceagent.policy", { tool: event.toolName, decision, reason })
```

Custom entries persist in the session JSONL (`docs/session-format.md:267`) and
are replayed on `session_start` to restore `/traceagent-status`
(`docs/extensions.md:1480-1487`). No `ignorable`-flag concern: pi readers
tolerate unknown custom entries, unlike dsh's required-on-read rule. Cross-ref
remains the traceagent `RunLedger` — two append-only logs, each attesting the
other. If a turn narrative *should* reach the model (e.g. "gate red, fix
these"), that goes through `sendUserMessage`, not entries — "model-visible ⟺
logged" cuts the other way here: entries are for auditors, messages for
agents.

### 3.7 Config and fail-loud behavior

No schema-validation framework in pi-land; hand-validate at `session_start`
(the factory must not spawn processes or read project state — pi warns
factories may run in invocations that never start a session,
`docs/extensions.md:222-224`). Project-local config at `.pi/traceagent.json`,
honored only when `ctx.isProjectTrusted()` (`docs/extensions.md:994-998`),
same tunables as dsh §3.5 minus plugin-framework specifics:

```jsonc
{
  "root": ".",
  "bin": "traceagent",
  "policy": {
    "mode": "observe",                       // "enforce" when trusted
    "protectPaths": [".zft/**", ".traceagent/**"],
    "askCommands": ["git push*", "rm -rf*"]
  },
  "check": { "onSettled": false, "timeoutS": 300, "maxRetries": 3 }
}
```

Misconfiguration (missing `.zft/`, unresolvable `bin` — probe `--help` once at
`session_start`): loud `ctx.ui.notify` + persistent `ctx.ui.setStatus`
"traceagent: DISABLED (misconfig)" + handlers no-op. dsh could refuse to load;
pi cannot — the compensating control is the loud, visible disable plus the
`/traceagent-status` command showing why. Protocol constants stay fixed, not
config: record `customType` strings, the DSSE predicate URI, CLI flags
(`AGENTS.md` principle carried over from dsh §3.5).

### 3.8 File layout, install

```
traceagent-pi/
├── package.json            # pi manifest; peerDeps: @earendil-works/pi-coding-agent,
│                           #   typebox ("*"); keywords: ["pi-package"]
├── README.md
├── extensions/
│   └── traceagent-gate.ts  # single file (~250 lines): config resolve, tool_call gate,
│                           #   agent_settled loop, registerTool, /traceagent-status,
│                           #   appendEntry records
├── skills/
│   ├── traceagent-check/
│   │   ├── SKILL.md
│   │   └── references/pipeline.md
│   └── traceagent-attest/
│       └── SKILL.md
└── test/                   # vitest, typechecked against pinned pi 0.85.1
```

```sh
pi install -l /abs/path/traceagent-pi                       # local path, project settings
pi install -l git:github.com/<org>/traceagent-pi@v0.1.0     # pinned for teams
# project settings auto-install on startup once the project is trusted (packages.md:43)
```

Glob-matching for `protectPaths` uses a `dependencies` copy of `minimatch`
(pi itself matches scoped models with minimatch, `docs/extensions.md:1017`) —
allowed since only pi-bundled packages belong in `peerDependencies`
(`docs/packages.md:169-190`).

## 4. Effort estimate

| Milestone | Work | Est. |
| --- | --- | --- |
| M1 | Package scaffold (`pi` manifest, peerDeps), config resolution + validation at `session_start`, `/traceagent-status`, `bin` probe | 0.5 d |
| M2 | `tool_call` gate: write/edit path protection, bash/powershell ask→(UI\|deny), observe/enforce, `traceagent.policy` records | 1 d |
| M3 | Check integration: `agent_settled` loop (exec, JSON parse, followUp steering, retry bound), `traceagent_gate` registered tool, `run_id` in check JSON (traceagent side, 1 line + test) | 1 d |
| M4 | Skills: `traceagent-check` (+ pipeline reference), `traceagent-attest` | 0.5 d |
| M5 | E2E against real pi: `pi install -l`, TUI session red→green, print-mode deny degradation, `/reload` of the extension, session replay with our custom entries, CI pinned to pi 0.85.x (typecheck + handler unit tests) | 1.5 d |
| **v0.1 total** | | **~4.5 dev-days** |
| Maintenance | Per upstream minor (0.85.x moves fast — pushed today): re-run M5 smoke, chase event-type changes | 0.5 d each |

Cheaper than dsh (~6 d): no service/capability-seam machinery, no config
schema framework, jiti means no build step, and the whole enforcement surface
is one event handler plus two registrations.

## 5. Risks & mitigations

| # | Risk (evidence) | Mitigation |
| --- | --- | --- |
| R1 | **Fast-moving upstream**: v0.85.1 at HEAD dated today; preview-era API | Pin exact pi version in CI; keep surface at 1 event + 2 registrations + `appendEntry` so breakage is a small typed compile error (typecheck against pinned pi in CI) |
| R2 | **No turn-close interception**: the check gate is a steering loop, not a wall (`docs/extensions.md:601-613` notification-only) | Accept and document: in-session discipline = `tool_call` denies + bounded steering loop; cross-session binding = DSSE signature + human consumer. Escalation path when retries exhaust is the human, not a block |
| R3 | **`tool_call` input mutation is unvalidated** (`docs/extensions.md:786-788`) | We never mutate inputs — deny-only, so the footgun is structurally avoided |
| R4 | **No-UI modes** (`-p`, `--mode json`): `ctx.hasUI` false, so ask-flows can't confirm | Ask degrades to deny (shipped `permission-gate.ts:20-23` precedent); `policy.mode: "observe"` for CI shadow runs |
| R5 | **Project trust gating**: project-local extension/skills load only post-trust (`docs/extensions.md:113`) | Deployment step: pre-trust via `trust.json`/`defaultProjectTrust` in producer automation; misconfig fails loud (§3.7) so an unloaded gate is visible, not silent |
| R6 | **Subprocess latency** at `agent_settled` (Python CLI, seconds) | Only L2-fast in the loop; full campaign only via the registered tool; `timeoutS` + fail-loud + `repro` resume |
| R7 | **Factory footgun**: factories may run in invocations with no session (`docs/extensions.md:222-224`) | All I/O deferred to `session_start`/handlers; idempotent `session_shutdown` cleanup |
| R8 | **Session format churn** (v3 migration, `docs/session-format.md:25-27`) | We only use stable `CustomEntry`; never parse pi's session file ourselves — write via `appendEntry`, read via `getEntries()`; M5 replays with stock pi |
| R9 | **Parallel tool batches**: a blocked call doesn't stop preflighted siblings (`docs/extensions.md:793`) | Per-call determinism makes this safe; note in denial reason that batched siblings may still run (observable, auditable) |

## 6. Alternatives considered

- **MCP server**: impossible and wrong — pi has no MCP client by design
  (`README.md:499`); the CLI+SKILL.md pairing *is* the pi-idiomatic integration.
- **SDK/RPC/JSON-mode observer only** (`docs/sdk.md`, `docs/rpc.md`,
  `docs/json.md`): can watch the event stream but cannot block a tool call —
  kept as a complementary CI collector (same role as the dsh §6 "pure-Python
  observer" alternative), never the enforcement path.
- **Skills-only** (no extension): rejected — a skill the model never reads
  enforces nothing (`docs/skills.md:69`); "deterministic verification >
  probabilistic judgment" (`CONTEXT.md` §4.2) requires the gate in
  `tool_call`, not in prose.
- **Forking pi / patching the loop**: rejected, same as dsh §6 — pi's whole
  contract is "aggressively extensible so it doesn't have to dictate your
  workflow" (`README.md:497`); a fork forfeits that.

## 7. Sources

- Clone `earendil-works/pi` @ `9767ba275f3e9a5ee0f5c5342249b629ab1b2282`
  (main, 2026-09-06), `@earendil-works/pi-coding-agent` v`0.85.1`, MIT. Key
  files: `README.md`, `packages/coding-agent/docs/{extensions,skills,packages,
  session-format,json,rpc,sdk,usage}.md`,
  `packages/coding-agent/examples/extensions/{permission-gate,protected-paths}.ts`,
  `packages/coding-agent/examples/plugins/pi-example-plugin/package.json`,
  `packages/coding-agent/src/core/tools/{bash,write,edit,read}.ts`.
- GitHub API repo metadata (stars 102,374; MIT; pushed_at 2026-09-06), fetched
  2026-09-06.
- traceagent: `src/traceagent/cli/main.py` (check/gate/attest/verify/lint
  surfaces, absolute-root binding), `src/traceagent/dsl/ears.py` (EARS grammar
  + layered diagnostics), `CONTEXT.md` (§4 principles, §5 D4/D6),
  `docs/research/DSH_INTEGRATION.md` (comparative design on dsh).
