# POSITIONING — the acceptance layer, and nothing else

> Status: verdict, 2026-09-07. The one-page answer to *what is traceagent,
> which layer does it own, who competes there, and what do we refuse to
> become*. Distills [CONTEXT.md](../CONTEXT.md),
> [docs/research/competitor-landscape.md](research/competitor-landscape.md),
> [ECOSYSTEM_RANKING.md](research/ECOSYSTEM_RANKING.md), and
> [DSL_ROADMAP.md](research/DSL_ROADMAP.md); positioned deliberately against the
> failure mode of [DITlieD/ELAI-archive](https://github.com/DITlieD/ELAI-archive)
> (§4 — an abandoned agent-harness research project whose postmortem is the
> cleanest available statement of how this category kills its builders).
> Read this before proposing a feature; the linked docs are the evidence.

## 0. TL;DR

| Question | Answer |
|---|---|
| **Mission** | traceagent is the acceptance layer for multiagent work: it turns pre-agreed, clause-IDed contracts into deterministic, fail-closed verification and signed attestations — so that "done" is a checked artifact, not a judgment call. |
| **Layer owned** | **Acceptance** — spec verification + attestation: contract authoring & negotiation → deterministic gates (L0–L3) → trace manifest → signed DSSE evidence. |
| **Not our layer** | Harness, orchestration, model routing, runtime policy, observability. Commodity or wrong object; we standardize over them, never compete with them. |
| **Direct competition** | The niche is effectively empty. Closest product: rtmx (~31★ — no negotiation, no evidence tiers, no bi-directional coverage). No player combines negotiation + deterministic coverage in both directions + evidence tiers + signed attestation. |
| **Adjacent giants** | Harness frameworks (CrewAI, MAF, LangGraph, OpenAI SDK), spec platforms (Spec Kit, Kiro), observability (LangSmith/Langfuse). Absorption threats and distribution channels — none holds the artifact. |
| **Anti-scope** | One pipeline, dogfooded daily on this repo, integrated only through thin CLI seams. The ELAI postmortem is the operating constraint (§4), not a footnote. |

## 1. Mission

> **traceagent is the acceptance layer for multiagent work: it turns
> pre-agreed, clause-IDed contracts into deterministic, fail-closed
> verification and signed attestations — so that "done" is a checked
> artifact, not a judgment call.**

Every phrase is a boundary, not decoration:

- **acceptance layer** — the layer that renders accept/reject on a
  deliverable. Everything before it (planning, tools, transport) and after
  it (dashboards, telemetry) is someone else's layer.
- **pre-agreed, clause-IDed contracts** — acceptance criteria exist *before*
  work starts, are *negotiated* between producer and consumer, and every
  clause is individually addressable. No contract, no validation.
- **deterministic, fail-closed** — compile/property/mutation/symbol evidence
  from model-independent gates; missing evidence is red, never silently
  skipped (`gates/l1.py:79`, `gates/l2.py:63`); LLM judgment exists only for
  clauses declared subjective at authoring and is visibly excluded from
  deterministic coverage claims (`attest/dsse.py:111`).
- **signed attestations** — the verdict outlives the session as an auditable
  DSSE artifact recording coverage in *both* directions (missed requirements
  and unjustified deliverable elements).
- **not a judgment call** — the thing being replaced: approval-by-conversation,
  LLM-as-judge vibes, self-graded homework.

First user: this repo — the 26-clause self-check corpus gates traceagent's
own development, and the adoption build order starts with CI and the
maintainer's own harness (ECOSYSTEM_RANKING §0). First buyer: any team that
must answer, after the fact, *which agreed item was missed and whose fault
is it* — currently unable to, because acceptance lives in transcripts.

## 2. The layer we own — and the layers we refuse

```
 models                          commodity, churns monthly
─────────────────────────────────────────────────────────────────
 harness & orchestration         LangGraph · CrewAI · MS Agent
 (how agents run)                Framework · OpenAI Agents SDK ·
                                 Dify · Spring AI          ← giants
─────────────────────────────────────────────────────────────────
 protocols & transport           A2A · MCP   (rails, not products)
─────────────────────────────────────────────────────────────────
 runtime policy & observability  OPA/Rego · LangSmith · Langfuse
 (what happened)                 · OTel
─────────────────────────────────────────────────────────────────
▶ ACCEPTANCE — traceagent        contracts (EARS) · negotiation
 (was it done as agreed?)        (A2A ext) · gates L0–L3 ·
                                 trace manifest · DSSE attestation
─────────────────────────────────────────────────────────────────
 notations & fabrics we build    EARS (Mavin) · Gherkin/BDD ·
 on — not layers we occupy       in-toto/DSSE · Sigstore trust models
```

Tracing answers *what happened*. Acceptance answers *was it what was
agreed*. That distinction (CONTEXT.md §2: "observability, not
traceability") is the whole positioning: every incumbent on the bands above
either records execution or decides how agents run — none owns the artifact
that decides whether the work passes.

Owning the layer means owning four artifact types and the verbs on them:

| Artifact | Verbs | Where |
|---|---|---|
| Contract (clause store, EARS-authored) | `create`, `lint`, `negotiate` | `dsl/ears.py`, `spec/`, `negotiate/` |
| Verification verdict | `check`, `repro`, `gate-campaign` | `gates/l0–l3` |
| Trace manifest (clause ↔ element) | `extract` | `lineage/` |
| Attestation (signed evidence) | `attest`, `verify`, `export` | `attest/dsse.py` |

The CLI is the layer's only mandatory interface — any agent that can execute
a shell can be gated, so every harness integration is a thin consumer of the
same verbs (ECOSYSTEM_RANKING §2 #5). We meet every harness; we belong to none.

Refusals, each recorded somewhere enforceable:

- **No orchestration** — graph execution, crews, planners are commodity
  (CONTEXT.md §1). We standardize *over* them (A2A extension, guardrail-callable).
- **No harness features** — no context management, memory, model routing, or
  agent sandboxing. Our sandbox executes *gates*, not agents (`gates/sandbox.py`).
- **No LLM-as-judge** except quarantined, declared-subjective clauses (decision D4).
- **No policy language** — we absorbed OPA's admission conventions (deny/warn
  findings, default-deny, decision logs) and refused the Rego dependency
  (DSL_ROADMAP §3): the pipeline is the product, not an evaluator.
- **No server** — git-native distribution (D5); no Rekor/Trillian until
  attestation crosses org boundaries (DSL_ROADMAP §3).
- **No second tool surface** — MCP waits for per-agent identity (R-12);
  today its only new capability is producer self-attestation, the exact
  failure the product exists to kill (ECOSYSTEM_RANKING §2 #5).

## 3. Competition: an empty niche between crowded neighbors

### 3.1 The niche (direct — same layer, small, unoccupied)

| Player | What they have | Why the niche stays ours |
|---|---|---|
| **rtmx** (~31★) | The closest product: requirements-as-CSV in git, status derived from test results, MCP access for agents | No negotiation, no evidence tiers, no bi-directional coverage; human-authored prose requirements |
| **duvet** (AWS) | Bi-directional spec↔implementation annotations, derived compliance reports | One RFC-style document, annotation-only binding, human reviewer, no gates |
| **strictdoc** | Traceable requirement nodes, ReqIF | No agents, no verification — we *adapt* it (store + ReqIF), not fight it |
| **Pact / Pactflow** | Owns the contract-test mental model (`can-i-deploy`) in the API world | API interactions, not agent deliverables — a concept competitor and interop target |

### 3.2 Adjacent giants (absorption threats, distribution channels)

| Giant | Their layer | Why they don't hold ours today | What changes it |
|---|---|---|---|
| CrewAI · MS Agent Framework · LangGraph · OpenAI Agents SDK | harness | Guardrails/handoffs are consumer-side code with no persistent, negotiated artifact | Any of them ships persistent "task contracts" (competitor-landscape §4) |
| GitHub Spec Kit (133k★) · Amazon Kiro · OpenSpec (67k★) | spec-driven platforms | Human-gated; coverage is LLM keyword-inference; one agent under human supervision | **Kiro adds multi-agent handoffs with criteria-bound evidence — the venn-kill scenario** |
| LangSmith · Langfuse · Braintrust | observability | Spans/tokens/tool calls are a different data model than clause↔element edges | Bolting eval-gates onto traces still doesn't produce a trace matrix |
| IBM DOORS · Jama · Polarion | enterprise ALM | Document/ALM-centric; no agent-native motion | None — ReqIF import/export makes them *channels*, not enemies |

### 3.3 The crowded neighbors are different objects

| Neighbor | What it actually is | Our relationship |
|---|---|---|
| **EARS (Mavin)** | A requirements *notation* | Our authoring surface (`dsl/ears.py`) — we add the enforcement engine the notation never had |
| **Gherkin/BDD** | Executable specs for human-written code with human-written tests | Our codegen's fallback artifact for prose clauses; complementary |
| **OPA/Rego** | A policy evaluation engine | Absorbed the admission shape (deny/warn, default-deny, decision logs); refused the dependency |
| **Sigstore/SLSA** | Attestation packaging + trust fabric for *build* artifacts | Reuse DSSE/in-toto packaging for a new subject — agent deliverables; SLSA levels reshaped into negotiated assurance terms (R-03) |
| **AutoDSL research** | Academic runtime contract enforcement | Watch-list; standardization risk only if someone publishes a contract object at A2A/MCP before we do |
| **Dify / Spring agent DSLs** | DSLs describing *how agents run* (orchestration config) | Different object entirely — acceptance DSLs describe *what "done" means*; their existence validates the category |

### 3.4 The moat, stated once

Every player above is missing at least one of the four things only
traceagent combines (competitor-landscape §3):

1. **Negotiation between agents** — a binding pre-work agreement, not human
   approval gates.
2. **Deterministic coverage in both directions** — clause→element *and*
   element→clause, mechanically extracted, not LLM-inferred audits.
3. **Evidence tiers** — compile/property/mutation/symbol evidence from a
   model-independent gate, with fault attribution (surviving mutants ⇒
   contract fault; failing clause ⇒ implementation fault).
4. **Attestation** — signed manifests making acceptance auditable after the
   fact, exportable to the ReqIF/regulated world.

## 4. Positioned against ELAI-archive's death

[DITlieD/ELAI-archive](https://github.com/DITlieD/ELAI-archive) (18★ at the
2026-09-07 fetch) is an abandoned, MIT-licensed archive of a local-first,
model-agnostic agent harness — 883 commits, a 659-entry "feature catalog"
the README itself clarifies as "plan units and experiments — not 659 working
features." The postmortem, quoted:

> "I used it to try too many ideas headlessly, not as software I relied on
> for actual work." … "It became overengineered, and I abandoned it." …
> "build software you want to use that solves your problems, not all the
> problems you know about."

The uncomfortable, useful reading: an abandoned harness independently
converged on the same mechanisms traceagent is built from. The README's five
salvageable ideas are all present here — which is *validation of the
mechanisms* and a *warning about the packaging*. The ideas were never what
killed ELAI; building all of them, for no one, in one harness, was.

| ELAI salvageable idea | In traceagent today | What we took / left |
|---|---|---|
| Evidence outside the generating agent | Gates are deterministic, model-independent programs; `model_dependent` and `judge_excluded` are published *into the signed predicate*, not honored on trust (`attest/dsse.py:111`) | Took fully. It is the product's first principle |
| Fail-closed verification | Default-deny: a clause without a binding is red, not skipped (`gates/l1.py:79`, `gates/l2.py:63`); subjective clauses quarantined visibly | Took fully |
| Journals & replay | Run ledger records seeds, git commit, dirty flag, tool versions (`debug/ledger.py`); `repro` re-executes failures; digest-keyed L1 verdict cache (`gates/l1.py:28`); hash-chain + decision replay staged (R-08, R-10) | Took; hardening is roadmap, not rewrite |
| Bounded workers | Bounded, typed rejections with retry budget (negotiation SM); env-isolated sandbox for gate execution (`gates/sandbox.py`); fault attribution (`gates/l2.py:77`) | Took the *purpose* — completion decisions live in the gate, not the model. Left the harness machinery: we bound producers, we don't host them |
| Code retrieval | Mechanical extraction of deliverable elements from the artifact (Tree-sitter/section-anchor lineage, D3; `lineage/extract.py`) | Took the verification use only (evidence binding). Deliberately left the harness use — no repo-map-for-context feature |

Three operating rules, derived from the postmortem and enforced by existing
repo documents:

1. **Dogfood or it isn't real.** ELAI died as software its author didn't
   rely on. Traceagent's first consumer is its own build (self-check corpus,
   CI gate as adoption surface #1, OpenCode plugin in the maintainer's daily
   loop — ECOSYSTEM_RANKING §0). If the gates can't police their own repo,
   this positioning is fiction.
2. **One pipeline, finished.** ELAI accumulated 659 experiments. Traceagent
   has one pipeline — contract → verify → attest — and the roadmap's
   anti-steals (DSL_ROADMAP §3) are *explicit refusals*, not deferrals:
   no Rego, no Rekor server, no keyless OIDC, no SLSA build-platform levels.
3. **Refuse harness gravity.** Every integration is a thin CLI consumer
   (pre-commit hook; plugin wrappers bounded at ~100 LOC — kill criterion
   K-PI-1). The gate's core couples to no harness, and "no harness work
   that couples the gate's core to any single integration surface" is the
   ranking's stated main output (ECOSYSTEM_RANKING §3).

**Litmus test for any proposed feature:** does it strengthen the acceptance
layer's artifacts (contract, evidence, verdict, attestation), or is it
harness gravity — context, memory, routing, orchestration, a runtime? If the
latter, it belongs in someone else's harness, and building it is how this
project dies.

## 5. When this document changes

Full trigger list with reasoning lives in competitor-landscape §4. The ones
that would rewrite §3 here:

- **Kiro ships multi-agent handoffs with criteria-bound evidence** — the
  venn-kill; reassess the whole page.
- **Any harness vendor ships persistent, negotiated task contracts** — the
  integration wedge narrows; positioning shifts from "the layer" to "the
  standard the layer speaks."
- **A2A or MCP publishes a contract/artifact-policy extension first** — the
  standardization window closes; join instead of lead.
- **rtmx gains traction or funding** — the niche has an occupant; the
  differentiation table becomes sales collateral.
- **Pactflow announces LLM/agent support** — likely a partner, not a threat;
  interop beats war.
