# ECOSYSTEM_RANKING — adoption surfaces ranked by value ÷ effort ÷ risk

> Status: verdict, 2026-09-06; **rev. 2, same evening** — corrected against
> `docs/research/DSH_INTEGRATION.md` after it landed, plus primary-source
> checks (opencode.ai/docs/plugins; badlogic/pi-mono + pi.dev/docs; GitHub API
> for dsh repo metadata). Ranks the five adoption surfaces for traceagent
> (CI gate, OpenCode plugin, Pi integration, MCP server, DSH integration) and
> fixes a build order with kill criteria per option. Corrections are marked
> inline with their sources; superseded first-pass claims stay visible inside
> those markers rather than being silently rewritten.
>
> **Provenance.** The first pass was written from the brief's four weights
> only — *DSH preview instability, Pi minimalism fit, OpenCode dogfood
> proximity, CI determinism* — because neither integration doc was on disk at
> the time. `DSH_INTEGRATION.md` has since landed (itself carrying a §0
> "Corrections to the research brief", verified against a pinned clone); its
> findings drive the rev-2 changes in §1–§4. `PI_INTEGRATION.md` is **still
> missing** — the Pi section (#3) therefore remains brief-weighted, now
> backed by repo-level primary sources. Repo baseline unchanged: `dbe4dcd` +
> the uncommitted overnight changes (C-39…C-41 track: JCS, typed DSSE verify,
> findings deny/warn, sandbox env isolation).
>
> Repo facts this leans on: CLI verbs `lint / check / negotiate / attest /
> export / create / repro / gate-campaign / verify / extract` with exit codes
> 0/1/2 and typed JSON rejections (`docs/RUNBOOK.md`; the last two verbs are
> omitted from the runbook's daily loop but exist — `cli/main.py:286` and
> `cli/main.py:85` — first pass missed them, and they are load-bearing for
> DSH_INTEGRATION.md §3.7's CLI-as-seam contract); run ledgers recording seeds, git
> commit, dirty flag, tool versions, with `repro` re-executing failed units;
> findings split deny/warn prototyped (C-41, `spec/findings.py`); exactly one
> dev signing key, threshold 1, no identity binding (DSL_ROADMAP R-09/R-12
> "Today" sections); 26-clause self-check corpus, 24/24 due clauses bound;
> 270 unit tests, ~2 min.

## 0. TL;DR

Value/Effort/Risk 1–5 (effort 5 = most work; risk 5 = most likely to burn a
week and produce nothing durable). Same scale convention as DSL_ROADMAP §0.

| Rank | Option | Value | Effort | Risk | One-line verdict |
|---|---|---|---|---|---|
| 1 | **CI gate (pre-commit + CI)** | 5 | 1 | 1 | The trust anchor. Deterministic, zero third-party API exposure, everything else inherits its verdicts. |
| 2 | **OpenCode plugin** (`tool.execute.after`, `session.idle`) | 4 | 2 | 2 | The thesis testbed. First time the gates meet a real producer agent in-loop — the feedback loop the roadmap is starving for. |
| 3 | **Pi integration** | 3 | 1 | 2 | The portability proof. Minimalism-fit makes it cheap; do it second-to prove the CI recipe generalizes beyond one harness. |
| 4 | **DSH integration** (DeepSeek Harness plugin) | 3 | 4 | 4 | *Rev 2: swapped above MCP.* Design complete and verified (`docs/research/DSH_INTEGRATION.md`); instability is promised but priced (~6 dev-days + 0.5–1 d per upstream minor, doc §4) and engineered loud, not silent. Build iff the maintenance budget is accepted. |
| 5 | **MCP server** | 3 | 3 | 4 | Right idea, wrong month. Without per-agent identity (R-12) the main new capability it unlocks is producer self-attestation — the exact failure the product exists to kill. Blocked on a missing roadmap item, not a budget. |

**Build order (rev 2): CI gate → OpenCode plugin → Pi → DSH (budget-gated,
design ready) → MCP (gated on R-12).** Dependency logic, not just ratio
order: the plugin's entire value proposition is "the same gate as CI, earlier
in the loop" — it has nothing credible to surface until CI runs the identical
command and gets the identical verdict. Pi then proves the recipe is
harness-agnostic. DSH and MCP are *consumers* of that portability, which is
why both rank behind it regardless of their raw reach. The rev-2 swap at the
tail: DSH's blocker became a *priced* budget (DSH_INTEGRATION.md §4), while
MCP's is a *missing prerequisite* (R-12) — a payable cost outranks a blocked
one.

## 1. Weights applied (where each one bit)

- **CI determinism** → drove #1. It is the only option whose risk profile is
  fully under our control: same inputs → same verdict, and the determinism
  machinery (seed capture in run manifests, `repro`, digest-keyed cache
  invalidation) is already built and exercised by 270 tests. Determinism is
  not just a property here, it's the product claim — a verification gate
  that flakes trains every consumer to re-run it until green, which is
  vibes-based acceptance with extra steps.
- **OpenCode dogfood proximity** → drove #2. CONTEXT.md §6's design
  implication says layer onto existing agent infra; DSL_ROADMAP §4 wants
  real-corpus calibration data and LLM-in-the-loop negotiation exercise.
  The plugin is the only option that *generates* that data as a byproduct
  of the maintainer's normal day. Proximity also de-risks: no packaging,
  no publishing, feedback latency of minutes.
- **Pi minimalism fit** → drove #3 and its effort=1. Pi's ethos (small
  core, user-land tools, no framework lock-in) is traceagent's ethos
  (git-native, no server, CLI-first). The predicted integration shape is a
  thin wrapper over the CLI, which is the same artifact the CI gate needs —
  so the marginal work after #1 is near zero, and the payoff is the
  second data point that kills the "works in one harness" objection.
- **DSH preview instability** → drove #5 in the first pass; **rev 2 moves DSH
  to #4**. The instability itself is confirmed, not softened — upstream
  promises compatibility-breaking changes outright (upstream `README.md:11–13`,
  quoted in DSH_INTEGRATION.md §0). What changed is its *shape*: the landed
  design converts churn into loud, typed failures (pinned release + 3-event
  surface + CI typecheck + fail-loud on timeout/misconfig — doc §3.3, §3.5,
  §5 R1/R7), so the weight now bites on **effort and a maintenance budget**
  (~6 dev-days plus 0.5–1 d per upstream minor, doc §4) rather than on
  "wait". The first pass's core fear — silent gate skips, runs that stop
  happening without anyone noticing — is specifically what that design rules
  out; what remains is a malicious-or-sloppy harness unloading the plugin,
  which is why tamper-evidence rests on the DSSE signature, not the hook
  (doc §3.1).

## 2. The options in detail

### #1 · CI gate — pre-commit hook + CI pipeline

**Shape.** `traceagent check .` (L0 + coverage + L1 fast tier) as a
pre-commit hook (`.pre-commit-hooks.yaml`) and as the CI job; `gate-campaign`
(L2 mutation) stays a scheduled/manual job, not per-push. Deliverables:
pinned environment (uv.lock already exists), an exit-code contract test
(0/1/2 with typed JSON on stdout), and a documented seed policy for L1
(properties run under recorded seeds; CI failure reproduction = `repro <run>`).

**Why #1.** It is the reference implementation of the only claim that
matters: *the same gate, the same verdict, re-runnable by anyone, anywhere.*
Every other option is a delivery mechanism for these verdicts. Effort is
lowest of the five because the runbook loop is already written and already
says "CI runs the same thing" — the work is pinning and proving it, not
building it. The overnight sandbox hardening (env isolation, placement
guards) removed the main hermeticity excuse.

**Kill criteria (any one, held after two consecutive fix attempts → demote
to L0-only-in-CI and re-scope):**
- K-CI-1: `check .` over the 26-clause corpus exceeds a 5-minute CI budget
  (fast tier, no mutation) — a gate slower than the tests it polices won't
  be tolerated by its own maintainer.
- K-CI-2: more than one flaky red per 20 green-capable runs after seed
  pinning — determinism weight fails on our own doorstep.
- K-CI-3: keeping gates hermetic in CI requires more than one day of
  additional sandbox/env work beyond what landed overnight.

### #2 · OpenCode plugin — `tool.execute.after` + `session.idle` (via `event`)

> **API precision (rev 2; source: opencode.ai/docs/plugins, fetched
> 2026-09-06).** `tool.execute.after` is a direct plugin hook (and also an
> event name); `session.idle` is *not* a hook — it is an event type consumed
> inside the generic `event` hook (`event.type === "session.idle"`). Plugins
> are TS modules typed by `@opencode-ai/plugin`; v0 needs no packaging — a
> file under `.opencode/plugins/` (project) or `~/.config/opencode/plugins/`
> (global) auto-loads at startup, npm deps via `bun install` at startup. The
> first pass's "two hooks" phrasing collapsed this distinction; the design
> below is unaffected.

**Shape.** TS plugin, one hook + one event listener, two tiers borrowed from
the findings split (C-41): `tool.execute.after` on edit/write tools runs
L0-class checks only (seconds budget — schema, hashes, alias/dup lint,
deny-tier findings only); `session.idle` runs full `check`, renders typed
rejections (`{code, clause_ids, fault, expected, actual, repro}`) back into
the session, and on green can offer `attest`. Later: `negotiate` as the
contract-authoring moment at session start.

**Why #2.** Dogfood proximity is worth more than reach right now: the
framework's open risks are behavioral (will an agent *act* on a typed
rejection? does the deny/warn split survive contact with real sessions?),
and only in-loop usage answers them. It converts the maintainer's ordinary
work into the real-corpus calibration the roadmap explicitly wants, at zero
marginal scheduling cost. It depends on #1 for credibility, which is why it
is not #1.

**Kill criteria:**
- K-OC-1: the after-edit tier adds ≥2–3 s to typical edits in practice →
  drop the fast tier, keep `session.idle` only (partial survival, not a kill).
- K-OC-2: after two weeks of dogfooding, typed rejections have never changed
  agent behavior (agent ignores or loops) → the in-loop hypothesis is dead;
  keep CI-only and re-aim the plugin work at the *human*-review surface.
- K-OC-3: plugin API churn forcing a rewrite twice in one month → park the
  plugin; the retry recipe is the DSH playbook (pin the release, minimal
  surface, CI typecheck — DSH_INTEGRATION.md §5), not a rewrite, unless
  `session.idle` alone proves stable enough to keep.
- K-OC-4: warn-tier noise exceeds ~1 advisory per session after tuning —
  the human will nuke the plugin before the month is out.

### #3 · Pi integration

> **Sourcing note (rev 2, checked 2026-09-06; `PI_INTEGRATION.md` still
> missing).** Primary sources verified at repo level:
> [badlogic/pi-mono](https://github.com/badlogic/pi-mono) — MIT, TypeScript,
> self-described "AI agent toolkit: unified LLM API, agent loop, TUI, coding
> agent CLI … our self extensible coding agent" (packages
> `@earendil-works/pi-agent-core` / `pi-ai` / `pi-tui`) — and
> [pi.dev/docs](https://pi.dev/docs): extensions are "TypeScript modules for
> tools, commands, events, and custom UI", shareable as Pi Packages, with
> SDK / RPC (stdin–stdout JSONL) / JSON-event-stream modes as alternative
> integration seams. The README states no minimalist manifesto in so many
> words — "minimalism fit" remains the brief's characterization; what is
> *verified* is the self-extension model and the deliberate absence of a
> built-in permission system (sandboxing delegated outward), which is
> consistent with it. Pi-specific API claims below stay at this sourcing
> level until the doc lands.

**Shape.** Documented recipe + thin wrapper exposing `check`/`attest` as a
custom tool in pi's extension model (a TS module — same artifact class as the
OpenCode plugin; the RPC/JSON-stream modes are the fallback seam if a tool
subscription proves too coarse). The artifact should be
≈ the same "run CLI, parse JSON verdict" glue as the pre-commit hook.
This option is as much a *constraint on #1* as a separate build: it forces
the CI recipe to stay harness-agnostic (no CI-specific coupling), which is
exactly the discipline we want.

**Why #3.** Minimalism fit cuts both ways: low effort (no plugin SDK to
fight, predicted wrapper ≲100 LOC), but also smaller strategic payoff than
the big-harness options — it proves portability more than it distributes.
Cheapest possible hedge against "traceagent is welded to one harness," and
it retires that objection with a second green check→attest cycle on a
radically different agent.

**Kill criteria:**
- K-PI-1: the honest wrapper exceeds ~100 LOC or needs any pi-internal
  fork — violates the minimalism fit that is the entire reason this ranks
  #3; if it's not cheap, the weight was wrong and the option reverts to
  the MCP bucket.
- K-PI-2: after one completed attempt, no second harness (Pi or otherwise)
  has run a green check→attest cycle → stop; portability is being
  maintained speculatively at that point.

### #4 · DSH integration — DeepSeek Harness plugin

> **Correction pass (rev 2, 2026-09-06 evening) — the first pass scored DSH
> without the doc and was wrong on three load-bearing points.** Sources:
> `docs/research/DSH_INTEGRATION.md` (which itself verifies against a pinned
> clone of `deepseek-ai/deepseek-harness` @ `d347e703`, master 2026-09-04,
> package `0.1.3-alpha.1`), plus a fresh GitHub API metadata check today.
> 1. *"A gate that silently doesn't happen is the failure mode."* — The
>    designed integration fails loud: turn-end gate timeout/crash steers with
>    the error and never silently passes (doc §3.3), misconfiguration fails at
>    load (doc §3.5), and CI pins the exact dsh release and typechecks the
>    plugin against its TS types, so a break is a compile/load error rather
>    than a missed run (doc §5 R1/R7). Residual risk is bounded churn, not
>    silence — but churn is *promised*: "THERE WILL BE COMPATIBILITY-BREAKING
>    CHANGES" (upstream `README.md:11–13`, via doc §0).
> 2. *Effort 3.* — The doc's own estimate is **~6 dev-days** for v0.1 (§4,
>    M1–M4) plus **0.5–1 d per upstream minor** during preview → effort 4,
>    the largest single spend in this ranking.
> 3. *"Wait for stability."* — No longer the default stance: the mitigation
>    set (pin + 3-event surface + `ignorable: true` records + CLI-as-seam)
>    converts stability into a *budget*. The build question becomes "is
>    0.5–1 d per upstream minor acceptable?", not "has DSH stabilized?"

**Verified identity (doc §0 header; GitHub API re-checked 2026-09-06).** DSH
is the **DeepSeek Harness** (`deepseek-ai/deepseek-harness`) — "Everything is
a Plugin" on a vendored Cordis kernel, MIT, **213,948 stars** at 25,173 forks
(the research brief's "~186k" was stale — the doc already corrects this and
today's API response confirms 213,948) — the largest audience of the five
surfaces, which is what moves value 2 → 3.

**API corrections that shaped the ranking (doc §0, verified against the
clone):** plugins are **TypeScript-only** — dsh's Python side is a
subprocess/JSON-RPC client SDK with no plugin host — so traceagent
integrates as a thin TS bundle driving the CLI, with the CLI as the versioned
seam (doc §3.7; this is why the `verify`/`extract` CLI verbs matter). Turn-end
interception is **`agent/turn-stopping`** (serial; objects by *steering*, so
the producer gets the typed failure payload and another step — D6's bounded
typed rejections on a native channel, doc §3.3); `turn/end` is a session-log
record type, not a hook (doc §0.1). `tools/pre-execute` offers
allow/deny/ask only, no argument rewriting (doc §0.2), and becomes the
clause-store/evidence-path integrity gate (doc §3.2). Config is Schemastery,
not zod (doc §0.4), failing loud at load (§3.5); every session record type we
add must be written `ignorable: true` or stock readers refuse the log
(doc §3.4, §5 R3).

**Why #4.** A complete, verified design with the churn tax priced (doc §3–§4)
outranks a blocked option: MCP cannot be built honestly until per-agent
identity lands, while DSH's blocker is a payable maintenance budget. It stays
behind Pi (#3) because Pi is ~a day's work that de-risks the
harness-agnostic claim DSH's plugin then reuses, and behind OpenCode (#2)
because proximity — the maintainer's daily loop — still beats audience for
calibration value. Trust-model note (doc §3.1): the plugin sits *inside* the
harness trust boundary; path policy is discipline, tamper-evidence is the
DSSE signature plus key custody. The same integrity rule that blocks MCP
applies here: attestation must never become the acceptance act while
`model_dependent` is an honor-system claim (R-12) — in dsh v0.1 attestation
is a *record* of a green pipeline, which is the right order.

**Kill criteria:**
- K-DSH-1 (budget): actual maintenance exceeds **2 dev-days per quarter**
  while preview persists → park it. The doc's own estimate (0.5–1 d per
  upstream minor, §4) lands at ~1.5–3 d/quarter at a monthly minor cadence —
  this criterion is exactly the line the estimate flirts with, so it gets
  measured from M4 onward, not assumed.
- K-DSH-2 (seam): upstream removes or breaks `agent/turn-stopping` +
  `tools/pre-execute` + `session.append` without replacement before M4 lands
  → the doc's surface assumption fails; back to watch-and-wait. *(Replaces
  the first pass's K-DSH-2 "no session-end event point", rendered obsolete by
  the doc's event map, §2.)*
- K-DSH-3 (integrity): if `attestOnGreen` ever becomes the acceptance act in
  place of the gates — rather than a record of a green pipeline — stop until
  R-12 identities exist.

**Entry condition:** build after Pi, iff the K-DSH-1 budget is accepted up
front; demand-pull (a deliverable that must ship through dsh) unblocks it
earlier only with the budget still enforced.

### #5 · MCP server

**Shape (if/when built).** Tools mirroring CLI verbs (check, verify,
export-summary, negotiate), server started out-of-band, never auto-attesting.

**Why #5, not higher (rev 2 swapped it below DSH — see §2 #4).** MCP's
promise is harness-agnostic reach — but the
CLI already *is* the universal adapter: any agent that can execute a shell
(which is all of them) can run `traceagent check`. The server adds a second
surface to keep byte-compatible with the first (tool schemas, transport,
lifecycle) for marginal coverage gain. Worse, the *new* capability it
unlocks today is letting a producer agent call `attest` on its own work —
with one dev key, threshold 1, and `model_dependent` as an honor-system
claim (R-12 "Today"), that is self-graded homework with a cryptographic
rubber stamp. This is the option where risk isn't churn, it's integrity.

**Entry criteria (re-enter the build order when met — these are the
R-12/R-09 milestones):**
- E-MCP-1: per-agent signing identities registered in a trust root land, so
  "who called attest" is a verifiable claim, and the server can refuse
  producer-graded attestations by policy (R-05).
- E-MCP-2: a concrete second consumer demands MCP specifically (an actual
  request beats the speculative-reach argument).

**Kill criteria:**
- K-MCP-1: built anyway and the tool surface drifts from the CLI within one
  minor version → consolidate back to CLI-only; two surfaces diverging in a
  verification product is a defect factory.

## 3. Sequencing and effort budget

Aligned with DSL_ROADMAP's scale (1 = hours–1 day, 2 = 1–2 days,
3 = 2–4 days): **#1 is effort 1, #2 is effort 2 (v0 drops into
`.opencode/plugins/` — no packaging), #3 is effort 1 given #1's glue, #4
(DSH) is ~6 dev-days plus a preview-maintenance stipend (DSH_INTEGRATION.md
§4) — the largest single spend in the set — and #5 (MCP) is deferred until
R-12 fires.** Weeks 1–2: CI gate landed and determinism proven (kill
criteria measured, not guessed). Weeks 2–4: OpenCode plugin in daily
dogfood, generating the behavior data that K-OC-2 adjudicates. Then Pi as
the portability checkpoint (~a day). Then the DSH decision: accept the
budget → M1–M4; decline → it parks, and the active shortlist is CI +
OpenCode + Pi only. The ranking's main output remains *what not to build
yet*: no MCP server, and no harness work that couples the gate's core to
any single integration surface.

## 4. What would flip the order

- **A real consumer appears with an MCP-only requirement** → MCP jumps the
  queue *with* E-MCP-1 still enforced.
- **Two consecutive dsh upstream minors cost >2 dev-days each** → the
  K-DSH-1 budget is empirically blown; DSH parks and re-swaps below MCP
  until it leaves preview.
- **`PI_INTEGRATION.md` lands with an extension story unlike the assumed
  one** (e.g., no subprocess seam, Python-only tooling, heavyweight SDK) →
  Pi's effort-1 score dies and it re-swaps with DSH; until then Pi's #3
  rests on the brief's weight plus repo-level verification only (pi-mono
  README; pi.dev/docs).
- **OpenCode plugin API turns out to be unable to surface rich typed
  rejections** (e.g., hooks can only pass strings into the loop) → Pi and
  OpenCode swap; the harness with the better verdict-rendering surface wins
  #2 regardless of proximity.
