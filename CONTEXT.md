# TraceAgent — Project Context & Intent

> Status: living document. This is the entry point for the project. Detailed design docs live in [`designs/`](designs/); framework landscape research lives in [`docs/research/`](docs/research/).

## 1. What we are building

A **framework for multiagent work**: multiple LLM agents collaborating to produce deliverables (primarily software, but the model should not be code-only). The framework is not trying to be yet another orchestration library — orchestrators, planners, and tool plumbing are commodity. The differentiator is the **interaction layer between agents**:

1. **Contract-first interaction.** Before any work is validated, there is an explicit **contract** that the producing agent must fill in and satisfy. No contract, no validation. Validation is gated on the contract, not on another agent's (or an LLM judge's) vibes.
2. **Deliverable-to-contract traceability.** A deterministic, auditable mapping showing **which element of the deliverable fulfills which clause of the contract** — bi-directionally: every contract clause is covered by at least one deliverable element, and every deliverable element is justified by a contract clause (which kills scope creep and hallucinated work).

## 2. Problem statement

Current multiagent setups fail at the seams:

- **Handoffs are vibes-based.** A producer agent hands work to a consumer/reviewer, and "acceptance" is a natural-language judgment call. The reviewer LLM may approve shallow work; the producer may silently drop requirements. Nobody can say afterwards *why* work was accepted or rejected.
- **No pre-agreed definition of done.** Requirements are embedded in prompts, rediscovered (differently) by each agent, and drift as the task progresses. Two agents never literally agree on what "done" means.
- **Failure is undebuggable.** When the final deliverable is wrong, there is no artifact-level answer to "which agreed item was missed?" — you re-read the whole transcript and guess.
- **Tracing tools observe, but don't bind.** Existing "tracing" (LangSmith, OpenAI tracing, Langfuse) records *execution* (spans, tokens, tool calls). That is observability, not **traceability**: none of it links deliverable elements to the agreed contract they satisfy.

## 3. Vocabulary (ubiquitous language)

| Term | Meaning |
| --- | --- |
| **Contract** | A first-class, structured artifact agreed between producer and consumer *before* validation. Composed of **clauses**. |
| **Clause** | One atomic, individually verifiable statement of obligation ("the export endpoint rejects payloads > 10 MB with 413"). The unit of acceptance. |
| **Producer / Consumer** | The agent obligated to fill the contract, and the agent (or gate) entitled to validate against it. Roles, not identities — one agent can be both in different interactions. |
| **Deliverable** | The work product (code, tests, docs, analysis). Composed of **elements** (a function, a section, a test case, a claim). |
| **Trace link** | A deterministic edge `deliverable element → contract clause(s)`, plus evidence (test run, type check, hash). The mapping must be resolvable mechanically, not by re-reading prose. |
| **Coverage** | % of clauses with ≥1 valid trace link. **Reverse coverage**: % of deliverable elements justified by ≥1 clause. A completed contract needs both at 100%. |
| **Validation gate** | The mechanism that accepts/rejects a deliverable *only* on contract-grounded, mechanically checkable evidence where possible; explicitly flags clauses that could only be judged subjectively. |

## 4. Emerging design principles

From the intent and the prior design work in `designs/`, tentative principles (to be challenged):

1. **The contract is the interface.** Agents exchange artifacts, not just messages. What flows between agents is a contract + a deliverable + a trace manifest — everything else is transport.
2. **Deterministic verification > probabilistic judgment.** A clause that can be compiled, executed, type-checked, or property-tested should be. LLM judgment is a fallback of last resort and must be labeled as such in the trace.
3. **Contracts must be cheap to satisfy honestly and expensive to fake.** Anti-patterns we already know from `designs/`: trivial assertions (`assert True`), self-graded homework (producer writes its own acceptance test), coverage theater. The gate design must assume the producer is sometimes lazy or adversarial.
4. **Trace links must survive refactoring.** Identity of a clause is stable even when its wording, file layout, or symbol names change (see the identity work in PTE/ZFT: content-addressable anchors vs. UUIDv7 vs. aliases).
5. **Both directions of coverage are load-bearing.** Uncovered clause = missed requirement. Unjustified deliverable element = scope creep / hallucination. Symmetry is the point.

## 5. Prior design thinking in this repo (`designs/`)

The original four design docs (PTE, ZFT, "PTE ZFT", DEC) have been **unified into one canonical document: [`designs/ARCHITECTURE.md`](designs/ARCHITECTURE.md)**, which converts their disagreements into explicit decision records with tradeoff analysis. The originals are preserved under [`designs/archive/`](designs/archive/); where they and ARCHITECTURE.md disagree, ARCHITECTURE.md wins.

The decisions that resolve the old tensions, in brief:

- **D1 · Contract medium**: declarative clause nodes are the single source of truth; executable artifacts (typed interfaces, property suites) are *derived* from clauses by one-way codegen — DEC's compiler enforcement without giving up universality for non-code deliverables. Surfaced a new v0 blocker: invariants need a real, executable DSL (the old docs stored them as strings nothing could run).
- **D2 · Clause identity**: UUIDv7 identity + SHA-256 content hash as an *integrity field* (PTE's model). ZFT's content-addressable anchor is demoted to that integrity property — content-as-identity silently forks a clause into "two different clauses" when two agents edit it concurrently, and every typo fix would mint a new identity.
- **D3 · Trace binding**: explicit link records extracted mechanically (Tree-Sitter for code, section anchors for docs); DEC's structural/type conformance is reclassified from "alternative binding mechanism" to the strongest *evidence* tier; bi-directional coverage at the gate is what makes either mechanism trustworthy.
- **D4 · Verification gates**: the two proposals were never really rivals — they're cost/depth points on one pipeline. Tiers: L0 static integrity → L1 local verify (property execution) → L2 merge gate (mutation testing + full bi-directional coverage) → L3 signed attestation. LLM judgment is quarantined: only for clauses declared subjective at authoring, visibly excluded from "deterministic coverage" claims. Gate failures are *attributed*: surviving mutants ⇒ contract fault (back to spec agent); valid clause failing ⇒ implementation fault (back to producer, bounded retries).
- **D5 · Storage & ALM**: local-first Git + halt-on-conflict bi-directional ALM sync (was uncontested; recorded for completeness).
- **D6 · Interaction protocol** (the new layer): negotiate contract → validate it → implement → gate with bounded, typed rejections naming clause IDs and the responsible role; envelope is A2A-compatible (§6, landscape findings).

`designs/DTC.md` (empty placeholder) is now realized as the **Trace Manifest** — the acceptance payload mapping clauses to deliverable elements with evidence (ARCHITECTURE.md §5.3).

## 6. Framework landscape research

Research notes (primary-source, cited, fetched 2026-09-03):

- **Broad landscape** — orchestration frameworks, protocols, and where their verification/traceability stories stop: [`docs/research/multiagent-frameworks.md`](docs/research/multiagent-frameworks.md)
- **Requirements & contracting deep dive** — spec-driven toolkits, contract protocols (Contract Net → A2A), schema/output contracts, contract-testing tradition (Pact, DbC), requirements notations (EARS, BDD), eval-as-gate: [`docs/research/requirements-contracting-for-agents.md`](docs/research/requirements-contracting-for-agents.md)
- **Scaffold search** — which OSS to depend on / adapt / replicate per system part (strictdoc, deal/icontract, CrossHair, ast-grep, mutmut, in-toto, a2a-python, Pact): [`docs/research/scaffold-search-findings.md`](docs/research/scaffold-search-findings.md)
- **Competitor landscape** — category map, threat matrix per player, moat statement, watch-list triggers: [`docs/research/competitor-landscape.md`](docs/research/competitor-landscape.md)
- **Positioning** — the one-page verdict distilled from the above (plus ECOSYSTEM_RANKING, DSL_ROADMAP, and the ELAI-archive postmortem): mission, the acceptance layer we own, niche vs. adjacent giants, anti-scope charter: [`docs/POSITIONING.md`](docs/POSITIONING.md)
- **DeepSeek Harness integration** — dsh/Cordis plugin study + design (gates at `tools/pre-execute` and turn close, attestation into the session trajectory log, validated Config, effort + preview risks): [`docs/research/DSH_INTEGRATION.md`](docs/research/DSH_INTEGRATION.md)
- **Pi integration** — earendil-works/pi extension study + design (gates at `tool_call`, turn-close check as a bounded steering loop, EARS check as skill, attest as CLI tool per pi's "no MCP — CLI tools with READMEs" pattern, effort + risks): [`docs/research/PI_INTEGRATION.md`](docs/research/PI_INTEGRATION.md)

### What the landscape converges on (fetched 2026-09-03, all claims cited there)

- **Orchestration topologies are solved commodity.** Graph execution with shared state and checkpoints (LangGraph, Microsoft Agent Framework), orchestrator-worker fan-out (Anthropic's research system), role-based crews with sequential/hierarchical processes (CrewAI). Nothing here is a differentiator.
- **The best existing acceptance gate is CrewAI guardrails**: a per-task callable returning `(True, validated_result)` or `(False, error_message)`, with the failure fed back to the producer up to `guardrail_max_retries` (default 3), alongside `output_pydantic` schema validation and a declared `expected_output`. Closest thing to contract-first — but the gate is consumer-side code with **no persistent, agreed artifact** between the parties.
- **The cleanest typed handoff is OpenAI Agents SDK**: a handoff is literally a tool (`transfer_to_<agent>`) with a Pydantic `input_type` validated before delegation fires — a formal *delegation contract*. But guardrails bind only to the first/last agent of a run, so per-hop producer→consumer acceptance cannot be expressed natively.
- **The best message envelope is A2A v1.0.0**: `Task{id, status, artifacts, history}` with typed Parts and lifecycle states including `REJECTED` and `INPUT_REQUIRED` — consumer rejection is protocol-native. Yet there is **no acceptance-criteria object and no schema an artifact must satisfy**; extensions/metadata are the obvious carrier for a contract layer.
- **Approval-by-conversation is the anti-pattern to avoid**: AutoGen's canonical gate is "terminate when the critic replies APPROVE" — a string match, not a check. (AutoGen itself is in maintenance; Microsoft Agent Framework is the active successor.) Anthropic's multi-agent research system, despite excellent brief hygiene ("objective, output format, tools, task boundaries" per subagent), accepts via a global post-hoc LLM-as-judge rubric — judged at the end, not gated per clause.
- **Spec-driven toolkits are contract-first but human-gated**: GitHub Spec Kit (spec → plan → tasks, acceptance criteria, `/speckit.analyze` cross-artifact coverage audit, checklists as "unit tests for English") and Amazon Kiro (requirements/design/tasks in EARS notation with explicit approval gates) encode contracts for *one* agent under *human* supervision — no agent-to-agent negotiation, no stable clause IDs, no machine-resolvable requirement→implementation mapping.
- **Tracing ≠ traceability, confirmed.** LangSmith / OpenAI / OTel answer "what happened" (spans, tokens, tool calls). Regulated-industry practice (ReqIF 1.2, IBM DOORS multi-level traceability, DO-178C / ISO 26262 trace matrices) has evidence-backed bi-directional trace links as a first-class artifact — exactly what **no** agent framework reproduces. Nobody ships a deterministic clause→deliverable-element matrix.
- *(Fact-check courtesy of the research note: ChatDev's oft-cited "double verification" phrase doesn't appear in the paper — the actual mechanism is code review (static) + system testing (dynamic). Don't propagate the misquote.)*

### Design implication

The gap is precise and ours: a **contract object** (structured, versioned, clause-IDed acceptance criteria held by *both* parties before work starts) plus a **trace matrix artifact** (clause → deliverable element → machine-checked evidence) used *as* the acceptance gate. This layers cleanly onto existing infrastructure — it can standardize over CrewAI-style guardrail loops, OpenAI-style typed handoffs, and A2A's task/artifact lifecycle (as a protocol extension), and it reuses the `designs/` machinery (spec nodes, identity, property gates, executable contracts) as the evidence layer. That combination exists nowhere in the current landscape.

## 7. Open questions

1. **Contract medium**: declarative clauses, executable tests, type-level interfaces, or a mix? (See §5 tension.) What is the *minimum* contract both a human and an agent can author in one sitting?
2. **Who writes the contract?** A dedicated spec agent, the consumer agent, or negotiated (producer may push back before start — "contract negotiation" phase à la A2A)?
3. **Can contracts change mid-task?** Amendment protocol, versioning, and what happens to already-validated clauses.
4. **Lineage mechanism** per artifact type: symbol resolution (code), section IDs (docs), claim anchors (analysis)? One mechanism or pluggable ones?
5. **What does the gate do with subjective clauses?** Refuse them at contract-authoring time, or allow them but force explicit LLM-judge sign-off with recorded rationale?
6. **Human's role**: contract approval? gate escalation? final sign-off?

## 8. Next steps

- [x] Capture intent (this document)
- [x] Framework landscape research → [`docs/research/multiagent-frameworks.md`](docs/research/multiagent-frameworks.md)
- [x] Distill landscape findings into design takeaways (§6)
- [x] Unify design docs → [`designs/ARCHITECTURE.md`](designs/ARCHITECTURE.md) (decision records D1–D6; originals archived)
- [x] Research requirements/contracting frameworks → [`docs/research/requirements-contracting-for-agents.md`](docs/research/requirements-contracting-for-agents.md)
- [x] Scaffold search: what to depend on / adapt / build from scratch → [`docs/research/scaffold-search-findings.md`](docs/research/scaffold-search-findings.md)
- [x] Competitor landscape → [`docs/research/competitor-landscape.md`](docs/research/competitor-landscape.md)
- [x] **Dogfood: seed v0 contract** — 26 clause nodes in [`.zft/specs/`](.zft/specs/); P1 applied; statuses VALIDATED (consumer-authorized 2026-09-04)
- [x] **Design loop** — 9 verifications, 2 rounds: [`designs/VERIFIED-DESIGNS.md`](designs/VERIFIED-DESIGNS.md)
- [x] **Implementation plan** — [`designs/IMPLEMENTATION-PLAN.md`](designs/IMPLEMENTATION-PLAN.md) (v1.1, oracle-corrected)
- [x] **Plan executed (TDD, atomic commits)** — C-00…C-37: DSL v1, codegen (oracle-bound + Gherkin fallback), L0–L3 gates with checkpoint/resume/repro, DSSE attestation, negotiation SM + a2a adapter, self-check green (24/24 due clauses bound)
- [ ] v0.1: TR-IMPACT-QUERY (impact query), ATT-EXTERNAL-IMPORT (ReqIF import), real-corpus threshold calibration, LLM-in-the-loop negotiation
- [ ] Close the gate‑conformance gap — `check` verifies traceability, not conformance (2026‑09‑10 adversarial probe): [`docs/KNOWN-GAPS.md`](docs/KNOWN-GAPS.md) (Gap 001)
