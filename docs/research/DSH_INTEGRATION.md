# DeepSeek Harness (`dsh`) — Integration Design for a traceagent Cordis Plugin

> Researched and designed 2026-09-06. Primary source: shallow clone of
> [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) at
> commit `d347e703908d0406b7a7ef80e3a0e594d86b2215` (master, 2026-09-04), package
> version `0.1.3-alpha.1`. Repo metadata fetched via GitHub API on 2026-09-06:
> **213,948 stars** (the research brief's "~186k" is stale), MIT license,
> description "Everything is a Plugin."
> All `dsh` file:line citations below refer to the pinned clone; all
> `traceagent` citations to this repo.
> Design context: [`designs/ARCHITECTURE.md`](../../designs/ARCHITECTURE.md) (D4 gate tiers, D6 protocol), research notes in this directory.

## 0. Corrections to the research brief (verified against the clone)

The brief was mostly accurate. Four claims needed correction before design:

1. **`turn/end` is not an interception event.** It is a *session-log record type*
   appended when a turn commits (`packages/core/agent/src/agent.ts:331`:
   `this.session.append('turn/end', { turn, reason: turnEnds! })`). The live
   interception point at turn close is **`agent/turn-stopping`** (serial waterfall,
   `packages/core/agent/src/runtime-types.ts:333`, awaited at `agent.ts:308`).
   A turn-end gate must hook `agent/turn-stopping` to act *before commit*, and/or
   consume `turn/end` records via the `session/event` firehose to act *after*.
2. **`tools/pre-execute` cannot rewrite arguments.** Its decision space is
   allow/deny/ask only — "Input rewriting is excluded because arguments are already
   logged and presented" (`packages/core/tools/src/index.ts:578-584`). Rewriting
   exists only at `agent/pre-step`, for *messages*. This suits us: our gate denies,
   it does not launder calls.
3. **Plugins are TypeScript only.** The Python side of `dsh` (`python/`) is a
   subprocess/JSON-RPC client SDK (`python/README.md:5-16`); there is **no Python
   plugin host**. traceagent is Python, so our plugin is a **thin TS adapter that
   drives the `traceagent` CLI as a subprocess**, with the CLI as the stable seam.
4. **Plugin config is Schemastery, not zod** (a vendored Standard-Schema validator,
   `vendor/schemastery`); plain config objects are rejected at load
   (`docs/user/develop/basic/config.md:45`).

Confirmed verbatim from the brief: MIT (`LICENSE`); "developer preview … THERE
WILL BE COMPATIBILITY-BREAKING CHANGES" (`README.md:11-13`); everything-is-a-plugin
on Cordis (`README.md:7`), with Cordis **vendored** under `vendor/cordis`
(`AGENTS.md:152-154`) and `@deepseek-ai/cordis` a peer dependency of every package
(`AGENTS.md:103`); `apply(ctx)` entry point (`docs/cordis-tutorial/01-first-plugin.md:11-19`);
YAML mounting via `cordis.yml` list / patch inserts; plugins hold the same
in-process privilege as the shipped model adapter (full `Context` access,
`inject`-based); append-only trajectory log confirmed as the session service.

## 1. What `dsh` is (verified facts we build on)

- **Runtime**: TypeScript ESM on Node ≥22.19 (`AGENTS.md:104`, `package.json:11-13`).
  Small native sidecar (`native/landlock-run`). Everything user-visible — LLM
  adapters, tools, session store, UI — is a Cordis plugin in the same process.
- **Plugin shape**: a function with `apply(ctx, config)`, an object with an
  `apply` method, or a `Service` subclass (`docs/cordis-primer.md:9-11`). Services
  are claimed by declaration merging and consumed via `export const inject =
  ['tools', 'sessions', …]`. "Registrations are effects" — every contribution goes
  through `ctx.effect()` / `ctx.on()` (`AGENTS.md:105`).
- **Event dispatch modes** (`docs/cordis-primer.md:17-27`): `emit` (observe),
  `waterfall` (around-middleware with return value), `parallel`, `serial`, `bail`.
  **Waterfall listeners MUST call `next()`**; returning without it short-circuits
  the chain (`AGENTS.md:109`). The generated, exhaustive event catalog is
  `docs/event-producer-consumer.md`.
- **Trajectory log**: event-sourced, append-only session log, in-memory store +
  JSONL persistence (`packages/core/session/src/index.ts:2`), one file per session
  at `<root>/<projectKey>/<session>/session.v2.jsonl`, **Zstandard-compressed by
  default** (`packages/session/session-persistence-jsonl/format.ts:53-55`),
  header record first (`format.ts:78-93`). Record envelope:
  `{ type, seq, time, data, ignorable? }` (`packages/core/session/src/types.ts:447-465`).
- **Log extension API**: `session.append(type, data)` (`session/src/index.ts:699-703`)
  with the type added to `SessionEventMap` by declaration merging — exactly what
  the shipped `dsh-session-title` plugin does (`packages/session/session-title/src/index.ts:71-79`).
  `SessionEventType` is "plugin-merged extensions included" (`types.ts:378-379`).
  **Required-on-read rule**: a reader that does not recognize an event type MUST
  refuse the log *unless* the record carries `ignorable: true` (`types.ts:465`) —
  so every record type we add must be written ignorable until our types ship in
  `dsh` itself.
- **AGENTS.md conventions** (verbatim excerpts, `AGENTS.md:105-118`):
  - "**Plugins, not loop changes**: new behavior goes on documented extension
    points; changing `agent-loop` requires updating docs/architecture.md." (L111)
  - "**A capability seam comprises Service Definition / Service Provider /
    Consumer roles.** It is complete, never one role; split only when roles evolve
    independently." (L112)
  - "**No hardcoded tunables in plugins**: deployment-varying choices are
    validated `Config` fields changeable from cordis.yml … Protocol constants,
    external specs, and security invariants stay fixed." (L115)
  - "**Explicit > implicit at package boundaries**: defaulting is an explicit
    `resolve(request): Spec` step … never a hidden `?? default` inside `run()`." (L114)
  - "**Misconfiguration fails loud** at load when self-contained" (L116);
    "Model-visible ⟺ logged" (L110); typed events use declaration merging (L107).

## 2. The interception surface we map onto

| Event | Mode | Fired at | Payload → listener power | traceagent use |
| --- | --- | --- | --- | --- |
| `tools/pre-execute` | waterfall | `tools/src/index.ts:1466-1469` | `(exec{name,args,agent}, next)` → `{kind:'allow'} \| {kind:'deny'; reason} \| {kind:'ask'}` (`index.ts:578-584`) | **Contract-integrity gate** (see §3.2) |
| `tools/post-execute` | waterfall | `index.ts:1735` (applied `1723-1757`) | `(exec, result, next)` → `{kind:'accept'; content?\|value}` or `{kind:'block'; feedback}` (`index.ts:590-593`) | v0: observe only (copy of result into gate evidence); substitution reserved |
| `agent/pre-step` | waterfall | `agent-loop/src/agent.ts:246-252` | `(payload{messages,turn,step}, next)` → `{kind:'reject'}` or `{kind:'enter', messages}` (`runtime-types.ts:58-65`) | **Unused by design** — we never rewrite user input (explicit-over-implicit) |
| `agent/turn-stopping` | serial | `agent.ts:308` | `({agent, turn}, …)`; an objecting listener **steers** (`agent.steer(...)`) | **Turn-end gate** (see §3.3) |
| `turn/end` | session record | `agent.ts:331` | log record `{turn, reason}` | Trigger for post-commit attestation (via `session/event`) |
| `session/event` | emit | every committed append (`session/src/index.ts:73`) | `(session, event)` | Evidence firehose correlating gate outcomes with `tool/call`/`tool/result`/`turn/*` records |

Not mapped, noted for completeness: `tools/execute` (around-wrapper; may change
only `exec.signal`), `agent/request` (frozen `LlmCallConfig` swap),
`system-prompt/assemble`, `approval/request`, `subagent/*`, `workflow/*`.

## 3. Design: `traceagent-dsh` bundle

One npm package (`traceagent-dsh`), **three internal services** per the capability-seam
convention — Service Definition / Provider / Consumer — split as separate packages
only if the roles evolve independently (per `AGENTS.md:112`):

```
┌─ Service Definition ─────────────────────────────┐
│ traceagent service (inject: ['traceagent'])      │
│   check(root, level)  → CheckResult              │
│   attest(root, keyOpts) → { envelope, keyid }    │
│   verify(root, keyIn) → VerifyResult             │
│   extract(root) → bindings[]                     │
├─ Service Provider ───────────────────────────────┤
│ traceagent-cli-runner: spawns the Python CLI     │
│ (bin, timeout, absolute-root binding, JSON in/   │
│ out, exit-code → typed error). The CLI is the    │
│ versioned seam; the plugin contains no gate      │
│ logic of its own.                                │
├─ Consumers ──────────────────────────────────────┤
│ traceagent-gates: listeners on                   │
│   tools/pre-execute + agent/turn-stopping        │
│ traceagent-log: session.append writer (§3.4)     │
└──────────────────────────────────────────────────┘
```

### 3.1 Trust model (stated plainly)

The plugin has the same privilege as every other plugin — it is *inside* the
harness trust boundary, so it is **not** a security boundary against the harness.
What it enforces is the *contract discipline*: producer agents cannot silently
edit the agreed clause store or the evidence trail, and turn completion is gated
on mechanically checked evidence. Tamper-evidence itself rests on the DSSE
signature, not on path policy (a malicious actor who controls the harness can
unload the plugin; they cannot forge the ed25519 signature).

### 3.2 `tools/pre-execute` — contract & evidence integrity gate

Pure in-process TS (no subprocess): cheap, deterministic, deny/allow/ask only.

- **Deny** writes into the clause store and evidence dirs (config
  `policy.protectPaths`, default `['.zft/**', '.traceagent/**']`) — the clause
  store changes only through the negotiation path (`traceagent negotiate`,
  A2A adapter), never by a producer's `write`/`edit` tool call. Denial reasons
  name the protected seam: `protected by traceagent: .zft/specs/... (amend via
  contract negotiation, clause <alias>)`.
- **Deny** writes/globs resolving outside the session workspace (`root`).
- **Ask** for configured dangerous commands (`policy.askCommands`, e.g.
  `git push*`, `rm -rf*`) — routes to the harness approval service.
- **`observe` mode** (config): every decision also appended as a
  `traceagent/policy` session record; `allow` instead of `deny` (for latency-free
  shadow-running before enabling enforcement).

This is traceagent principle "contracts must be cheap to satisfy honestly and
expensive to fake" (`CONTEXT.md` §4.3) enforced at the harness boundary.

> **M0 prototype (2026-09-06; removed 2026-09-11):** this exact seam was implemented and proven
> repo-local — no live dsh install — by `plugins/dsh/src/index.ts`
> (`apply(ctx)` + `resolveConfig` fail-loud Config + observe/enforce policy)
> with `plugins/dsh/test/registration.test.ts` proving the registration shape
> against a fake Cordis context (wired into pytest via
> `tests/unit/test_dsh_plugin_registration.py`). The prototype was pruned in
> `8951dc8` (integration still parked on HB-2); the registration shape it
> proved is preserved in this document.

### 3.3 `agent/turn-stopping` → turn-end gate (the brief's "turn/end")

When a turn is about to commit and `gates.turnEndLevel ≠ 'off'`, the consumer
spawns `traceagent check <root>` (the L2-FAST pipeline: L0 → L2-fast → L1 →
Gherkin fallback → gate log → reverse coverage; `src/traceagent/cli/main.py:120-189`)
under `gates.timeoutS` (default 300). On `ok: false`:

- **steer**, don't block — `turn-stopping` objects by steering, so the producer
  gets another step with the typed failure payload: the `failures` array, due /
  deferred clause counts, and `deterministic_coverage` from the check JSON. This
  is exactly traceagent's D6 "bounded, typed rejections naming clause IDs"
  surfaced through dsh's native steering channel.
- On timeout or CLI crash: **fail loud** (steer with the error; never silently
  pass — `AGENTS.md:116`, and our own gate philosophy).
- The full mutation campaign (`traceagent gate --module --tests`, minutes) is
  **not** a turn-end gate; it is exposed as a registered tool (`ctx.tools.register`)
  so the producer/consumer agents run it deliberately at L2 merge time, and it
  becomes mandatory before attestation (`gates.requireFullGate: true`).

After commit, the `session/event` consumer sees the `turn/end` record and the
writer (§3.4) persists the gate outcome for that turn.

### 3.4 Attest writer feeding the trajectory log

New session record types via declaration merging (pattern copied verbatim from
`session-title`, `packages/session/session-title/src/index.ts:71-79`); **all
written with `ignorable: true`** so stock readers pre-dating our types can still
replay the log (`types.ts:465`):

```ts
declare module '@deepseek-ai/dsh-session/types' {
  interface SessionEventMap {
    /** Gate outcome for one closed turn. Log-only, never model-visible. */
    'traceagent/gate': {
      turn: number
      level: 'L2-fast' | 'L2-full'
      ok: boolean
      runId: string            // cross-ref: .traceagent/runs/<run_id>/events.jsonl
      gitCommit: string | null
      failures: string[]       // clause-IDed rejections (D6)
      deterministicCoverage: string
      gateLog: { stages: Record<string, boolean>; judgeExcluded: string[] }
    }
    /** DSSE TraceManifest envelope signed on a green pipeline. */
    'traceagent/attestation': {
      turn: number
      envelope: { payloadType: string; payload: string; signatures: unknown[] }
      keyid: string
      predicateType: 'https://traceagent.dev/attestations/TraceManifest/v1'
    }
    /** Pre-execute policy decision (observe mode records allows too). */
    'traceagent/policy': {
      turn: number; tool: string
      decision: 'deny' | 'ask' | 'observe-allow'
      reason: string
    }
  }
}
```

On a green turn (`gates.attestOnGreen: true`), the writer runs
`traceagent attest <root>` (`cli/main.py:253-272`), reads the envelope from
`.traceagent/attest.json`, and appends a `traceagent/attestation` record. The
envelope is the in-toto Statement v1 / `TraceManifest/v1` predicate binding the
clause-store subject digests (`src/traceagent/attest/dsse.py:29-59`), so the
trajectory log gains a *verifiable* acceptance record, not just prose. Note the
CLI currently generates an ephemeral ed25519 signer and writes the public key
alongside (`--key-out`, default `.traceagent/attest-key.pub.json`); for durable
verification the deployment sets `keys.publicKeyOut` to a path under key custody
and later runs `traceagent verify --key-in`. Every record cross-references the
traceagent `RunLedger` run id (`src/traceagent/debug/ledger.py:44-89`, append-only
fsync'd JSONL) — two independent append-only logs, each attesting the other.

### 3.5 Validated Config surface (no hardcoded tunables)

Schemastery schema, validated before `apply`; cross-field checks + `deepFreeze`
in the service constructor (pattern: `session-title`, `index.ts:296-324`).

```ts
import { Schema, type z } from '@deepseek-ai/schemastery'

export interface Config {
  root: string                                   // traceagent project root; resolved absolute, must contain .zft/
  bin: string                                    // default 'traceagent'; or ['python','-m','traceagent']
  policy: {
    mode: 'enforce' | 'observe'                  // default 'observe' for v0.1
    protectPaths: string[]                       // default ['.zft/**', '.traceagent/**']
    askCommands: string[]                        // default ['git push*', 'rm -rf*']
  }
  gates: {
    turnEndLevel: 'L2-fast' | 'off'              // default 'L2-fast'
    timeoutS: number                             // default 300
    attestOnGreen: boolean                       // default true
    requireFullGate: boolean                     // default false — attest demands a green mutation campaign
  }
  keys: { publicKeyOut?: string }                // default '.traceagent/attest-key.pub.json'
  agentScope: 'all-agents' | 'producer-only'     // via @deepseek-ai/dsh-scope scoping
}
export const Config: Schema<Config> = Schema.object({
  root: Schema.string().required(),
  bin: Schema.string().default('traceagent'),
  policy: Schema.object({
    mode: Schema.union(['enforce', 'observe']).default('observe'),
    protectPaths: Schema.array(String).default(['.zft/**', '.traceagent/**']),
    askCommands: Schema.array(String).default(['git push*', 'rm -rf*']),
  }).default({}),
  gates: Schema.object({
    turnEndLevel: Schema.union(['L2-fast', 'off']).default('L2-fast'),
    timeoutS: Schema.number().default(300),
    attestOnGreen: Schema.boolean().default(true),
    requireFullGate: Schema.boolean().default(false),
  }).default({}),
  keys: Schema.object({ publicKeyOut: Schema.string() }),
  agentScope: Schema.union(['all-agents', 'producer-only']).default('all-agents'),
})
```

Misconfiguration fails loud at load: missing `root`/`.zft/`, unresolvable `bin`
(probe with `--help` at startup), unknown enum values — the plugin never starts
half-configured (`docs/cordis-tutorial/05-config.md:64-68`, `AGENTS.md:116`).
Protocol constants stay fixed (not config): the predicate URI, DSSE payload type,
and the session record names (`AGENTS.md:115` — "Protocol constants, external
specs, and security invariants stay fixed").

### 3.6 YAML mounting

Project overlay (patch), matching the shipped patch shape
(`packages/bundle/base/cordis.patch.yml:19-46`):

```yaml
# cordis.patch.yml
- insert:
    - id: traceagent
      name: traceagent-dsh
      config:
        root: .
        policy:
          mode: enforce
        gates:
          turnEndLevel: L2-fast
          attestOnGreen: true
```

Install as a third-party bundle (no marketplace; distribution is npm/git/tarball
+ the `dsh-plugin` GitHub topic, `docs/user/develop/basic/publish.md:35-101`):

```sh
dsh plugin --profile demo add ./traceagent-dsh          # local path / npm / github:
# from the Python SDK world:
dsh plugin --profile sdk add file:/abs/path/traceagent-dsh   # python/sdk/README.md:35-45
```

Layer order: bundle patches (profile `dsh.profile.bundles` order) → profile
`cordis.patch.yml` → `$DSH_HOME/cordis.patch.yml` → `--patch` argv; later layers
win per row, and a patch **replaces** a row's whole `config` (no deep merge —
`publish.md:114-123`).

### 3.7 What stays Python

All gate logic, codegen, mutation running, signing, and evidence storage remain
in traceagent (`src/traceagent/`). The plugin adds ~zero product logic; it is
wiring: spawn → parse JSON → decide → append. The CLI is the compatibility seam,
so dsh-side breakage is contained to ~3 listener signatures + `session.append`,
and traceagent-side changes ship without touching the plugin at all (same
contract as our CLI flags today: `check`, `gate`, `attest`, `verify`, `extract`).

## 4. Effort estimate

| Milestone | Work | Est. |
| --- | --- | --- |
| M1 | Bundle scaffold (TS ESM, `@deepseek-ai/cordis` peer dep), Schemastery Config + fail-loud resolution, CLI-runner service (spawn, timeout, absolute-root binding per our C-40 rule, exit-code → typed errors) | 1.5 d |
| M2 | `tools/pre-execute` policy gate + observe/enforce modes + `traceagent/policy` records | 1 d |
| M3 | `agent/turn-stopping` gate + steer-with-failures + `turn/end` attest writer + event-map merge | 1.5 d |
| M4 | E2E against real `dsh` (`dsh plugin add`, full session with a red→green producer), log-replay compat test (stock reader over log with our `ignorable` records), CI pinned to exact dsh version | 2 d |
| **v0.1 total** | | **~6 dev-days** |
| Maintenance | Per upstream minor during preview: re-run M4 smoke, chase type changes | 0.5–1 d each |

## 5. Preview-instability risks & mitigations

| # | Risk (evidence) | Mitigation |
| --- | --- | --- |
| R1 | **Promised breaking changes** — "THERE WILL BE COMPATIBILITY-BREAKING CHANGES" (`README.md:12`); "Public APIs are pre-stable" (`AGENTS.md:7`) | Pin the exact dsh release in CI + profiles; keep the plugin surface at 3 events + `session.append` + Schemastery config so a break is a small, typed compile error, not a behavioral drift |
| R2 | **Cordis is a vendored fork** (`vendor/cordis`) of upstream `cordiverse/cordis`; APIs may diverge from upstream docs | Import only `@deepseek-ai/cordis`, never upstream cordis packages; no direct `vendor/` imports (`AGENTS.md:152-154`) |
| R3 | **Required-on-read session log**: unrecognized non-ignorable record types make stock builds refuse the log (`types.ts:465`) | Every `traceagent/*` record written `ignorable: true`; CI test replays a log containing our records with an unmodified dsh reader |
| R4 | **Session file format/compression churn**: `session.v2.jsonl` + zstd default (`format.ts:53-55`) | We never parse dsh's log file ourselves — all writes via `session.append`, all reads via `session/event`; external consumers needing plaintext set `compression: 'none'` |
| R5 | **No Python plugin host** — traceagent must be a subprocess (latency at turn close; env/PATH fragility) | CLI is the seam; turn-end runs only L2-fast (seconds), full campaign on explicit tool call; `timeoutS` with fail-loud; `bin` probe at load |
| R6 | **Same-privilege trust model**: the gate runs inside the harness; unmounting it removes path enforcement | Treat path policy as discipline, not security; tamper-evidence is the DSSE signature + key custody (`keys.publicKeyOut`), documented in §3.1 |
| R7 | **Decision-type drift**: `PreToolDecision`/`PostToolDecision`/`PreStepDecision` shapes are pre-stable (`tools/src/index.ts:578-593`) | Typecheck the plugin against the pinned dsh's TS types in CI (compile-time breakage detection, R1's flip side) |
| R8 | **Steering semantics may change**: today `turn-stopping` objects by steering, not hard-blocking (`agent.ts:308`) | Accept steer as the contract for v0.1; if a hard gate is ever required, the fallback is `agent/pre-step` reject — at the cost of refusing a step that already happened, so prefer documenting the steer semantics upstream |

## 6. Alternatives considered

- **Pure-Python observer via `deepseek-harness-sdk`** (JSON-RPC over stdio,
  `python/README.md:5-16`): can watch events but has no Cordis `ctx` — no
  interception, no `session.append`, so no trajectory-log feeding and no
  enforcement. Kept as a *complementary* collector for dashboards, never the
  primary integration.
- **Upstream `cordiverse/cordis` plugin**: wrong target — dsh loads its vendored
  fork; upstream-Cordis compatibility is not a dsh compatibility claim.
- **Forking dsh / patching `agent-loop`**: violates `AGENTS.md:111`
  ("Plugins, not loop changes") and forfeits every upstream update. Rejected.

## 7. Sources

- Clone `deepseek-ai/deepseek-harness` @ `d347e703908d0406b7a7ef80e3a0e594d86b2215`
  (master, 2026-09-04), v`0.1.3-alpha.1`, MIT. Key files: `README.md`,
  `AGENTS.md`, `docs/cordis-primer.md`, `docs/cordis-tutorial/01-first-plugin.md`,
  `docs/cordis-tutorial/05-config.md`, `docs/user/develop/basic/config.md`,
  `docs/user/develop/basic/publish.md`, `docs/cookbook/extension-cookbook.md`,
  `docs/event-producer-consumer.md`, `packages/core/tools/src/index.ts`,
  `packages/core/agent/src/runtime-types.ts`, `packages/core/agent-loop/src/agent.ts`,
  `packages/core/session/src/{index,types}.ts`,
  `packages/session/session-persistence-jsonl/{src/format.ts,README.md}`,
  `packages/session/session-title/src/index.ts`,
  `packages/bundle/base/cordis.patch.yml`, `python/README.md`, `python/sdk/README.md`.
- GitHub API repo metadata (stars, license, pushed_at), fetched 2026-09-06.
- traceagent: `src/traceagent/cli/main.py`, `src/traceagent/attest/dsse.py`,
  `src/traceagent/debug/ledger.py`, `src/traceagent/gates/l3.py`,
  `CONTEXT.md` (§4 principles, §5 D4/D6).
