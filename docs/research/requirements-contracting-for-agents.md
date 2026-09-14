# Requirements & Contracting for Agents — Deep Research

**TL;DR.** "Contracts" for agent work exist, on six layers that never talk to each other. (1) **Spec-driven gating** (Spec Kit, Kiro, OpenSpec, BMAD, Tessl) has stable requirement IDs, acceptance criteria, even a coverage audit — but the counterparty is a human, agreement is an *approval*, coverage LLM-inferred at audit time. (2) **Inter-agent task contracting** (Contract Net, FIPA ACL, WS-Agreement) solved *negotiation* — producer counter-terms, binding acceptance, deadlines, typed rejections — but has no deliverable or evidence concept. (3) **Output schema contracts** (Instructor, PydanticAI, Guardrails, BAML, Outlines) contribute the best retry-budget semantics. (4) **Contract testing** (Pact, OpenAPI/gRPC) is the most mature negotiation-and-verification machine in software: versioned artifact, broker holding a verification matrix, and `can-i-deploy` — a gate that reads that matrix. (5) **Requirements notations** (EARS, Gherkin, ISO 29148/ReqIF) make clauses bounded, LLM-authorable, auditor-exchangeable. (6) **Eval-as-acceptance-gate** (promptfoo, DeepEval, OpenAI Evals) already implements per-clause assertions with thresholds and "flaky" (judge-gated) metrics that record but never block. New in 2025–26: a seventh layer, **runtime behavioral contracts for agents** (Agent Behavioral Contracts, AgentSpec, TraceGrant). No system combines these; the strongest transfer is Pact's broker/matrix/gate architecture; the strongest new science is ABC II's finding that two agents sharing a model co-fail on 90% of missions where either fails — evidence for gate independence.

*All facts from primary sources (official docs, GitHub repos, protocol specs, arXiv), accessed 2026-09-03 unless noted. Inferences are marked.*

---

## A taxonomy of contract layers

1. **Spec → coding-agent gating** — a human co-authors a spec; an agent implements under it. Agreement = approval gate. (Spec Kit, Kiro, OpenSpec, BMAD, Tessl.)
2. **Inter-agent task contracting** — two parties negotiate an obligation before work: announce→bid→award (Contract Net), offer→accept (WS-Agreement). Agreement = a *binding exchange*.
3. **Output schema contracts** — one LLM call constrained to a typed shape, bounded retry on violation.
4. **API/service contract testing** — consumer and provider teams share a versioned contract; verification results accumulate in a registry and gate deployments.
5. **Requirements notations** — bounded grammars (EARS, Gherkin) and quality standards (ISO 29148, ReqIF) that make a clause authorable and checkable.
6. **Eval-as-acceptance-gate** — assertions per test case/requirement, deterministic and model-graded tiers, thresholds, CI gating.
7. **Runtime behavioral contracts (new 2025–26)** — contracts as runtime-enforced primitives of the agent loop (ABC, AgentSpec, TraceGrant).

---

## 1. Spec-driven development gating coding agents

### GitHub Spec Kit

- **Contract artifact.** Markdown artifacts: constitution, spec, plan, tasks, checklists. The spec template mandates **numbered, stable requirement IDs**: `FR-001…` (`System MUST …`, with `[NEEDS CLARIFICATION: …]` as a first-class clause state), `SC-001…` measurable success criteria, and prioritized user stories whose acceptance scenarios are **Given/When/Then**, each "INDEPENDENTLY TESTABLE" ([spec-template.md](https://github.com/github/spec-kit/blob/main/templates/spec-template.md)). Tasks are `T001…` with parallel markers and a **task→story tag** ("e.g., US1, US2") ([tasks-template.md](https://github.com/github/spec-kit/blob/main/templates/tasks-template.md)). Checklists are `CHK001…`, "reviewer-owned requirements-quality review artifact[s]"; "`__SPECKIT_COMMAND_IMPLEMENT__` reads checklist checkbox state as a gate" ([checklist-template.md](https://github.com/github/spec-kit/blob/main/templates/checklist-template.md)).
- **Authors & negotiation moment.** Human + agent co-write per slash-command (`specify`→`clarify`→`plan`→`tasks`→`analyze`→`checklist`→`implement`, `/speckit.converge` looping until converged); human approves each phase ([README](https://github.com/github/spec-kit), v1.0.4, 2026-09-02).
- **Conformance mechanism.** `/speckit.analyze` is a **read-only cross-artifact audit**: duplication; ambiguity ("vague adjectives (fast, scalable, secure…) lacking measurable criteria"); constitution alignment ("Constitution conflicts are automatically CRITICAL"); **coverage gaps** ("Requirements with zero associated tasks" AND "Tasks with no mapped requirement/story") ([analyze.md](https://github.com/github/spec-kit/blob/main/templates/commands/analyze.md)). Output: a **Coverage Summary Table** (`Requirement Key | Has Task? | Task IDs`) plus "Coverage %". But the task→requirement map is built "by keyword / explicit reference patterns" — **LLM inference, not mechanical extraction**.
- **Traceability.** FR-/SC-/T-/CHK-/US- IDs make links writable and audit-checkable, but no persistent machine-resolved matrix is stored.
- **What traceagent should steal.** (a) The ID families are the de-facto clause-ID convention of 2026 — adopt; (b) `[NEEDS CLARIFICATION]` as a first-class clause state between draft and validated; (c) the **constitution** as a meta-contract whose violations are unwaivable CRITICAL; (d) the analyze coverage table as a **gate artifact**, computed from explicit trace links instead of keyword inference; (e) checklists as pre-flight "unit tests for English" required before implementation.

### Amazon Kiro

- **Contract artifact.** Per feature: `requirements.md` ("user stories, acceptance criteria… in structured notation"), `design.md`, `tasks.md`; `bugfix.md` variant; **agent hooks** ("hooks refresh README files" on API changes; committed to Git they "enforce the coding standard across my entire team") ([docs](https://kiro.dev/docs/specs/), [launch blog](https://kiro.dev/blog/introducing-kiro)).
- **Authors & negotiation moment.** Kiro generates; human approves between phases (design "analyz[es] your codebase and **approved** spec requirements"; only "Quick Spec" skips "approval gates").
- **Conformance mechanism.** "Each user story includes **EARS**… notation acceptance criteria," which "make your prompt assumptions explicit" ([launch blog](https://kiro.dev/blog/introducing-kiro)). Tasks run as dependency waves ("Wave 1 - all tasks with no dependencies… run concurrently"). Audit is "viewing code diffs and agent execution history" — evidence exists but is unbound to criteria.
- **Traceability.** Kiro "links each [task] to requirements so nothing falls through the cracks" — document-level, convention-based ([launch blog](https://kiro.dev/blog/introducing-kiro)).
- **What traceagent should steal.** EARS as clause surface syntax (§5); the approval gate as the **freeze point** where draft clauses become validated; hooks as post-deliverable enforcement; its diff/history audit names the evidence problem traceagent solves by binding evidence to clause IDs at gate time.

### OpenSpec

- **Contract artifact.** Git-native spec store: `openspec/specs/` (canonical) plus `openspec/changes/<change>/` holding a **delta** (`proposal.md`, `specs/`, `design.md`, `tasks.md`), written as `## ADDED Requirements` / `### Requirement: X` / `#### Scenario:` with WHEN/THEN bullets ([README](https://github.com/Fission-AI/OpenSpec)). OPSX workflow is "actions, not phases" (`propose/apply/update/sync/archive` anytime) ([opsx.md](https://github.com/Fission-AI/OpenSpec/blob/main/docs/opsx.md)).
- **Authors & negotiation moment.** AI writes deltas; human reviews "before any code is written"; `archive` merges the delta into canonical specs.
- **Conformance.** Human review of the delta; no automated clause checking documented. **Traceability.** Requirement headings act as stable slugs; archive history gives lineage.
- **What traceagent should steal.** Two high-value things. (a) The **delta protocol** is the best existing answer to mid-task amendment (§7.3 of ARCHITECTURE.md): changes as ADDED/MODIFIED/REMOVED blocks against named slugs, then merged. (b) **Stores** (beta): specs in their own repo "owned by one team and consumed by others… read-only, right where their coding agent can read them" — a working model for a contract registry with read-only consumer agents.

### BMAD-METHOD

- **Contract artifact.** Planning artifacts (brief→PRD→architecture→epics→**stories**), where "each story carr[ies] acceptance criteria a developer can implement against"; tracking in `stories.yaml`/`sprint-status.yaml` ([stories doc](https://docs.bmad-method.org/plan/break-work-into-stories-and-track-it/); [README](https://github.com/bmad-code-org/BMAD-METHOD), v6-era).
- **Authors & negotiation moment.** Specialist agents draft under human collaboration. The notable moment is **`bmad-sprint-planning`, a readiness gate**: it "judges the plan like a skeptical senior developer reading a handoff… could a developer implement these epics **without inventing decisions nothing records**?" Verdict PASS/CONCERNS/FAIL; a fail "stops with findings ordered by severity, each naming the skill that fixes it."
- **Conformance/traceability.** Build skills implement against story acceptance criteria; review moves stories through states; **`bmad-correct-course`** "assess[es] the impact, and produces a sprint change proposal — what changes, what stays." Statuses live as files with drift repair ("infers the true state first — from epic files, story files, and git history").
- **What traceagent should steal.** (a) The **readiness-gate question** is the best contract-validation prompt found anywhere — adopt nearly verbatim as the contract-validation agent's charter; (b) correct-course = **amendment with impact analysis**; (c) findings that "nam[e] the skill that fixes it" = typed rejections naming the responsible role (D6).

### Tessl

- **Status.** Pivoted: its CLI is now an "Agent Enablement Platform" whose "Spec Registry" distributes usage documentation for libraries to agents ([README](https://github.com/tesslio/cli)); the spec-driven methodology ships as an installable "tile" making the agent (1) ask clarifying questions, (2) "write specs first," (3) "**wait for your approval** — pause for confirmation that the specs capture your intent," (4) "implement with guardrails — build against the approved specs, then verify the work" ([tile repo](https://github.com/tesslio/spec-driven-development-tile)). Conformance/traceability not mechanically specified. Inference: not a competing contract system as of 2026-09.
- **Steal.** The **hard approval pause as a UX primitive**; and the distribution insight — contract methodology can ship as an installable profile for existing agents (protocol-as-skill before any framework exists).

---

## 2. Inter-agent task contracting — the classics

### Contract Net Protocol (Smith 1980; FIPA CNP, SC00029H)

- **Contract artifact.** No persistent artifact — the contract is the message sequence. The manager's **cfp** "specifies the task, as well [as] any conditions the Initiator is placing upon the execution"; participants' **propose** "includes the **preconditions that the Participant is setting out** for the task." Award via **accept-proposal**/**reject-proposal**; "The proposals are **binding** on the Participant, so that once the Initiator accepts the proposal, the Participant **acquires a commitment to perform the task**." Completion: `inform-done`/`inform-result`; failure: `failure` ([FIPA CNP, SC00029H, 2002](https://web.archive.org/web/2019/https://fipa.org/specs/fipa00029/SC00029H.html); fipa.org no longer serves the specs — accessed via Internet Archive; original: [Smith, IEEE Trans. Computers C-29(12), 1980](https://doi.org/10.1109/TC.1980.1675516)).
- **Authors & negotiation moment.** Genuinely bidirectional and pre-work: the producer negotiates its preconditions before binding. `reply-by` deadlines bound it; `conversation-id` threads it; `not-understood` is protocol-native.
- **Conformance/traceability.** None — CNP contracts on task execution, never verifies the work product; provenance is conversation-id only.
- **What traceagent should steal.** The **two-phase agreement with producer counter-terms**: clause drafting must include a producer counter-offer step *before* the contract binds — the binding transition D6 currently lacks. Plus **binding as a state transition** (accepted⇒committed), per-negotiation conversation IDs, and deadlines. The 45-year hole — task contracting without an acceptance artifact — is exactly the space traceagent fills.

### FIPA ACL / speech-act performatives

- **Contract artifact.** ACL messages typed by ~22 performatives (`cfp`, `propose`, `accept-proposal`, `reject-proposal`, `refuse`, `agree`, `failure`, `not-understood`, …) — a message-contract vocabulary ([FIPA ACL, SC00061G, 2002](https://web.archive.org/web/2019/https://fipa.org/specs/fipa00061/SC00061G.html)).
- **Relevance.** It standardizes the speech acts typed rejections need: **`refuse` before committing vs `reject-proposal` of the other's offer vs `failure` after commitment** — three distinct, typable failure points mapping 1:1 onto D4's fault attribution. (Modern framing: protocol dimensions incl. "capability negotiation" ([survey, arXiv:2504.16736](https://arxiv.org/abs/2504.16736)); Agent Network Protocol lets agents negotiate protocols dynamically ([ANP spec](https://agentnetworkprotocol.com/en/specs/06-anp-agent-communication-meta-protocol-specification/)) — protocol negotiation, not task-acceptance negotiation.)

### WS-Agreement (OGF)

- **Contract artifact.** A structured XML agreement: context (parties, lifetime, template reference) + terms, including **guarantee terms** pairing a service level objective with **business values** — obligation plus consequence ([GFD.107, 2007](https://ogf.org/documents/GFD.107.pdf); v1.1 [GFD.192](https://ogf.org/documents/GFD.192.pdf)). Creation is **template→offer→acceptance**, templates carrying "agreement creation constraints" restricting what the offerer may change; the spec covers "monitoring agreement compliance at runtime" and per-term states; multi-round negotiation is standardized separately ([GFD.193, 2011](https://ogf.org/documents/GFD.193.pdf)).
- **Authors & negotiation moment.** Provider advertises templates; consumer offers within constraints; provider accepts/rejects — a constrained bid, extendable to rounds.
- **Conformance mechanism.** Runtime compliance monitoring against guarantee-term SLOs; agreement/term state machine. **Traceability.** Term IDs and states; no deliverable mapping.
- **What traceagent should steal.** (a) **Guarantee terms = clause + SLO + consequence**: traceagent clauses could carry an optional consequence (mutation-checked at L2, blocks merge); (b) **templates + creation constraints** = a producer-facing schema for contract drafts (the "minimum contract" question becomes a template); (c) the term-level state machine (template→offer→accepted→monitoring→violated) is the cleanest prior art for clause lifecycle; (d) GFD.193's existence shows the amendment/negotiation protocol should be a separate small spec (D6).

### Agent Protocol (AI Engineer Foundation) — negative result

Agent Protocol (OpenAPI-style `/task`/`/runs` spec) is dead: the SDK repos are **archived** (last pushes Nov–Dec 2023) ([agent-protocol-sdk-python](https://github.com/AI-Engineer-Foundation/agent-protocol-sdk-python)); agentprotocol.ai is now a third-party explainer. It never defined acceptance criteria. **Lesson:** an agent protocol without a work-product contract layer had no durable reason to exist once A2A landed — traceagent must supply the layer A2A *lacks*, not another run-API.

---

## 3. Output/schema contracts for LLM calls

### Instructor

- **Artifact.** A Pydantic `response_model` attached to a chat call ([README](https://github.com/567-labs/instructor)). **Authors.** Developer, pre-call; the only "negotiation" is the retry loop.
- **Conformance.** Pydantic validation with bounded re-asking (`max_retries`); a `token_budget` is "checked after a response fails validation and before Instructor prepares another request" — a **retry budget in tokens**, not just attempts ([retrying docs](https://python.useinstructor.com/concepts/retrying/)). **Traceability.** None.
- **Steal.** The **retry budget as a two-dimensional quota** (attempts × tokens); the machine-checked failure text is the payload fed back to the producer — D6 rejections should carry it verbatim, counted against a declared budget.

### PydanticAI

- **Artifact.** `output_type` plus registered **output validators** ([output docs](https://pydantic.dev/docs/ai/core-concepts/output/)).
- **Conformance.** Three output modes (tool schema / native constrained / prompted); validators raise **`ModelRetry`** ("tell the model to try again if validation fails"); a **retry budget**: "Each `ModelRetry` raised here consumes one unit of the run's output retry budget," default `1`, configurable per agent/run/tool.
- **Steal.** **Output validators as consumer-authored clause checkers** that can do IO (their example: `EXPLAIN` the generated SQL) — the shape of traceagent's deterministic clause checks; per-role budgets as the standard bound on a producer.

### Guardrails AI

- **Artifact/conformance.** Composable named **validators** (a Hub of reusable checks) combined into Input/Output Guards that "detect, quantify and mitigate" risks and help "generate structured data" ([README](https://github.com/guardrails-ai/guardrails); validators moving to plain PyPI, hosted inference discontinued 2026-08-25). **Steal:** validators as **named, versioned, reusable clause-check packages**; guard composition as surface syntax for clause→checker binding.

### BAML

- Now "the programming language for agents": "Types persist at runtime. There is no `any`," typed errors, a "built-in tests / eval framework" ([README](https://github.com/BoundaryML/baml), active 2026-09-03). **Steal:** evidence that a contract language survives only when it **compiles into both prompts and validators** — D1's codegen should emit to the prompt *and* the checker from one clause source.

### Outlines

- Constrained decoding: "Outlines **guarantees** structured outputs **during generation**" — violation impossible by construction ([README](https://github.com/dottxt-ai/outlines)). **Steal:** name this the strongest evidence tier ("satisfied by construction"), but only expressible for syntactic clauses — the D4 tier ladder should read: generation-constrained > schema-validated > tested > mutation-certified > judged.

### Provider-native structured outputs (brief)

OpenAI Structured Outputs ties generation to a JSON Schema (schema-adherence guarantee via constrained decoding) ([platform docs](https://platform.openai.com/docs/guides/structured-outputs)); Anthropic offers tool-based structured output. **Steal:** schema clauses are *natively checkable* — never spend an LLM judge on one.

---

## 4. Contract-testing tradition (pre-agent, highly transferable)

### Pact — the mature contract-negotiation-and-verification machine

- **Contract artifact.** The **pact file**: "a collection of interactions," each an expected request plus a "**minimal expected response** — describing **the parts of the response the consumer wants**"; generated by running consumer tests against a mock provider ([how Pact works](https://docs.pact.io/getting_started/how_pact_works)). Contract tests assert that "inter-application messages conform to a shared understanding that is documented in a contract" ([introduction](https://docs.pact.io/)).
- **Authors & negotiation moment.** **The consumer authors the contract from its actual usage** (only what is actually used gets tested); the provider accepts or rejects later by verifying — an asynchronous offer/verify protocol with the broker as intermediary, not a sit-down negotiation.
- **Conformance mechanism.** **Provider verification**: each request is replayed and "the actual response it generates is compared" to the minimal expected response, with provider states for preconditions. Results are **published to the Pact Broker**, accumulating the **Pact Matrix** (consumer-version × provider-version × success).
- **Traceability.** The matrix *is* traceability: every (contract version, provider version, evidence result) triple persisted and queryable. **`can-i-deploy`** turns it into a gate: deploy is safe only if "there is a successful verification result between the version that is about to be deployed, and all the versions of the integrated applications… in that environment"; `record-deployment` closes the loop ([can-i-deploy doc](https://github.com/pact-foundation/docs.pact.io/blob/master/website/docs/pact_broker/can_i_deploy.md)).
- **Steal.** Pact is the closest existing system to traceagent's gate: (a) **contract scoped to actual consumer usage** — kills aspirational clauses; (b) the **broker as persistent evidence registry** — the trace manifest needs a home and a queryable matrix (clause-version × deliverable-version × evidence); (c) **`can-i-deploy` semantics as the gate**: acceptance = "a valid evidence row exists for every clause at these versions," nothing more; (d) minimal-expected-response = clause minimality.

### OpenAPI / gRPC (brief)

OAS "defines a standard, language-agnostic interface to HTTP APIs" ([v3.1.1](https://spec.openapis.org/oas/v3.1.1)); gRPC uses protocol buffers "as both its Interface Definition Language (IDL) and as its underlying message interchange format," with `protoc` generating client and server code ([gRPC intro](https://grpc.io/docs/what-is-grpc/introduction/)). **Steal:** the IDL pattern — one contract source compiled into both the producer's obligations and the consumer's checks; BAML's insight at industrial maturity.

### Design by Contract and the LLM-era spec-generation revival

- **DbC.** Meyer's preconditions/postconditions/invariants attached to interfaces, checked at runtime, with **client co-obligation** — the client must satisfy preconditions ([Meyer, IEEE Computer, 1992](https://doi.org/10.1109/2.139706)). **Steal:** a clause implies a consumer duty too (fixture state, inputs); contracts should carry consumer-side obligations (Pact's provider states encode the same idea).
- **SpecGen (ISSTA 2024).** LLM-generated formal pre/postconditions validated by **mutation testing** (conversational generation + "mutation-based validation to refine and verify"); verifiable specs for 279/385 programs ([arXiv:2401.08807](https://arxiv.org/abs/2401.08807)). **Steal:** **mutation-validate the contract itself, once** — a clause counts as mechanically checkable only if its checker demonstrably kills mutants of violating code (feeds §7.5).
- **SpecRover (AutoCodeRover-v2).** Repair via "iterative specification inference within an LLM agent"; the inferred intent "is examined by a reviewer agent with the goal of vetting the patches as well as providing a measure of confidence" ([arXiv:2408.02232](https://arxiv.org/abs/2408.02232)). **Steal:** reviewer-with-confidence = gate returning per-clause confidence; inferred specs as bootstrap when no contract exists.

---

## 5. Requirements notations & RE practice

### EARS (Easy Approach to Requirements Syntax)

- **The pattern.** A restricted grammar: `THE <system> SHALL <response>`, prefixed by condition class — event-driven `WHEN <trigger>…`, unwanted `IF <trigger>…`, state-driven `WHILE <state>…`, optional-feature `WHERE <feature is included>…` ([Mavin et al., IEEE RE 2009](https://doi.org/10.1109/RE.2009.39)).
- **Current state.** Production-validated by Kiro: "Each user story includes EARS… notation acceptance criteria" that "make your prompt assumptions explicit" ([launch blog](https://kiro.dev/blog/introducing-kiro)) — LLMs author it reliably at scale.
- **Steal.** EARS is the strongest candidate for the **clause surface grammar** (§7.1): bounded NL that (a) an LLM drafts, (b) a human approves fast, (c) a parser classifies into clause *kind* — each kind mapping to a different test-generation strategy. The prefix keyword is a **clause-kind tag for free**.

### Gherkin / BDD

- **The artifact.** "Gherkin uses a set of special keywords to give structure and meaning to **executable specifications**"; each step "is matched to a code block, called a **step definition**" ([Cucumber Gherkin reference](https://cucumber.io/docs/gherkin/reference/)). Spec Kit already uses Given/When/Then as non-executable prose.
- **Steal.** Gherkin is the **non-code anchoring** precedent (§7.4): a scenario is a stable, hashable section with executable *sibling* code. Scenario clauses should store as Gherkin with step-definition bindings recorded as trace evidence; unbound prose steps are exactly where judge-gating gets declared.

### ISO/IEC/IEEE 29148 and ReqIF (brief)

ISO/IEC/IEEE 29148:2018 codifies requirement quality — singular, unambiguous, feasible, **verifiable** ([ISO catalog](https://www.iso.org/standard/72089.html)); ReqIF 1.2 standardizes exchanging requirements *with trace hierarchies* between tools ([OMG ReqIF](https://www.omg.org/spec/REQIF/)). **Steal:** make **"verifiable" an authoring-time validation** — a clause that cannot name its checker at draft time is auto-tagged subjective (quarantined per D4); ReqIF as the compliance-export target.

---

## 6. Eval-as-acceptance-gate

### promptfoo

- **Contract artifact.** YAML test cases, each with its own `vars` **and `assert` list** — "compare the LLM output against expected values or conditions" ([expected-outputs docs](https://www.promptfoo.dev/docs/configuration/expected-outputs/); repo active 2026-09-03).
- **Conformance mechanism.** **Deterministic** tier (`equals`, `contains`, `regex`, `is-json`, `javascript` — "provided Javascript function validates the output") and **model-assisted** tier (`llm-rubric` — "LLM output matches a given rubric, using a Language Model to grade output"); every type negatable; scores combine as "the weighted average of the scores of all assertions"; pass/fail by threshold; **`metric` tags group assertions**; `assert-set` passes only if all members pass.
- **Traceability.** Assertion→result rows in the eval table, but no requirement object to trace *to* — assertions are unnamed requirements.
- **Steal.** promptfoo's config is a **trace manifest without the contract object**: add clause IDs and it is one. Adopt per-clause assertion lists (type + weight + threshold), `metric`-style tags as clause-ID grouping on evidence rows, and the deterministic/model-assisted split as D4's judge-quarantine encoding.

### DeepEval

- **Artifact/conformance.** `LLMTestCase(input, actual_output, expected_output, …)` + 30+ metrics, "most of which are evaluated using LLMs" — including G-Eval-style rubric metrics ([chain-of-thought LLM grading, arXiv:2303.16634](https://arxiv.org/abs/2303.16634)) ([docs](https://deepeval.com/docs/evaluation-introduction), v4.2.1). Thresholded pass/fail: "each evaluation requires at least one non-flaky metric with a threshold"; crucially, **`flaky=True` metrics** "have their results recorded and reported as normal, but their failures don't block anything" — pytest-native.
- **Steal.** The **flaky/non-flaky distinction is the correct encoding for judge-gated clauses**: subjective clauses record a judge score and rationale but never deterministically block — a proven answer to the subjective-clause question. Thresholds must be declared at metric definition.

### OpenAI Evals (brief)

"An open-source registry of benchmarks" plus a framework matching completion samples against eval criteria ([repo](https://github.com/openai/evals); active, pushed 2026-04-14). **Steal:** the registry idiom — clause checkers as publishable, versioned artifacts.

---

## 7. Contract-like artifacts inside agent systems (2024–26)

### Magentic-One's Task Ledger / Progress Ledger

- **The artifacts.** Orchestrator-private state. **Task ledger**: "given or verified facts, facts to look up…, facts to derive…, and **educated guesses**," plus an NL plan that "serves more as a hint" no agent must follow exactly. **Progress ledger**: per iteration the Orchestrator answers five questions ("Is the request fully satisfied…?", "Which agent should speak next?") with a stuck counter (≤2) triggering replanning ([arXiv:2411.04468](https://arxiv.org/html/2411.04468v1)).
- **Conformance/traceability.** None — acceptance is the orchestrator's own judgment; the ledger binds no one.
- **Steal.** Mostly a negative example (private, hint-like, unverifiable). But steal the **facts-vs-guesses epistemic labeling**: clause records should carry provenance (user-stated / negotiated / inferred / assumed) to bound the cost of being wrong.

### Agent Behavioral Contracts (ABC) — the 2026 arrival

- **The artifact.** "An ABC contract **C = (P, I, G, R)** specifies **Preconditions, Invariants, Governance policies, and Recovery mechanisms** as first-class, runtime-enforceable components"; compliance is **(p, δ, k)-satisfaction** — "a probabilistic notion of contract compliance that accounts for LLM non-determinism and recovery"; a **Drift Bounds Theorem**: contracts with recovery rate γ > drift rate α "bound behavioral drift to D* = α/γ." Implemented in **AgentAssert** (<10 ms/action); "88–100% hard constraint compliance" on AgentContract-Bench ([arXiv:2602.22302, 2026-02-25](https://arxiv.org/abs/2602.22302)).
- **Authors & negotiation moment.** System builders pre-deployment; enforcement per-action at runtime — not a negotiating producer/consumer pair.
- **The sequel that matters.** ABC II (Aug 2026) tests the independence assumption behind compositional reliability: "Two instances of one model, in a two-agent handoff, **co-fail on 90.0% of the missions on which either fails**," scored "by deterministic code with **no LLM judge**" ([arXiv:2608.12895](https://arxiv.org/abs/2608.12895)).
- **Steal.** (a) **(p, δ, k)-satisfaction** as clause-acceptance semantics for non-deterministic deliverables (passes if it holds on ≥k of p independent runs within δ) — a principled upgrade from binary pass/fail; (b) the **γ > α theorem** as a design rule: retries + re-validation must out-pace producer drift or the contract is decorative; (c) ABC II is **empirical proof the gate must not share the producer's model** — write into D4 as a named gate-independence requirement, cited.

### AgentSpec

- **The artifact.** "A lightweight **domain-specific language** for specifying and enforcing **runtime constraints** on LLM agents… structured rules that incorporate **triggers, predicates, and enforcement mechanisms**"; LLM-authored rules hit "precision of 95.56% and recall of 70.96%" in one domain, at ms overhead ([arXiv:2503.18666](https://arxiv.org/abs/2503.18666)).
- **Steal.** **Trigger / predicate / enforcement** is the best minimal grammar found for the invariant DSL (§7.1): it separates *when the clause binds* (on artifact, on tool call, on merge) from *what must hold* (the executable invariant) from *what violation triggers* (reject producer / back to spec agent). Its LLM-authoring precision/recall numbers calibrate how much mechanical validation LLM-drafted clauses need.

### TraceGrant

- **The artifact.** A security contract governing an agent task's lifecycle: "**Before execution**, TraceGrant establishes a task-effect boundary from the trusted user request. During execution, admitted evidence can instantiate only **authority already established by the Contract**. After execution, **task completion is verified against actual tool results**" — zero attack successes across 1,349 injection cases ([arXiv:2608.21126, 2026-08-21](https://arxiv.org/abs/2608.21126)).
- **Steal.** Its three phases are traceagent's validate→implement→gate (D6) independently reinvented for security, confirming the shape: **contract before action, evidence only under contract authority, completion checked against actuals**. Its *authority* concept suggests a missing clause kind: **authorization clauses** (tool/scope/cost bounds), mechanically enforced.

### Negative results (searched, not found, Sept 2026)

No mainstream framework or protocol ships a **negotiated, clause-IDed acceptance contract between agents**: A2A has rejection states but no acceptance-criteria object; CrewAI guardrails are consumer-side code with no artifact; searches for "agent handshake", "task specification protocol", "agent SLA" surface only A2A/MCP/ANP material and blog commentary. The only real 2025–26 inter-agent contract systems are ABC, AgentSpec, and TraceGrant — runtime-safety-motivated, none doing deliverable-level traceability, none negotiating at task granularity between producer and consumer agents. The niche is still empty.

---

## Synthesis

| System | Contract artifact | Negotiation moment | Conformance mechanism | Traceability |
|---|---|---|---|---|
| Spec Kit | Spec w/ FR-/SC- IDs, GWT scenarios, CHK checklists | Human approves each phase | `/speckit.analyze` audit; checklist gates `implement` | ID conventions; ad-hoc audit, no stored matrix |
| Kiro | requirements/design/tasks, EARS criteria | Human approval gates | Approval gates; hooks; diff audit | Task→requirement links by convention |
| OpenSpec | Spec deltas over slug-named requirements | Human reviews delta pre-code | Human review; archive/merge lifecycle | Stable slugs + archive history |
| BMAD | PRD→epics→stories w/ ACs; sprint-status.yaml | **Readiness gate** (PASS/CONCERNS/FAIL) | Gate + build/review skills; correct-course | Story/epic hierarchy; status files |
| Tessl (tile) | specs/ dir, human-approved | Hard approval pause | "Verify the work" (unspecified) | None documented |
| Contract Net / FIPA CNP | Message sequence (cfp→propose→accept) | **Bidirectional, pre-binding** | None (delivery signalled, unverified) | conversation-id |
| FIPA ACL | Performative-typed messages | Per-message | refuse vs reject-proposal vs failure | None |
| WS-Agreement | XML agreement; **guarantee terms** (SLO + business value) | Template→offer→accept; multi-round (GFD.193) | Runtime compliance monitoring; term states | Term IDs + states |
| Agent Protocol | REST run-API | — | — | — (archived 2023) |
| Instructor | Pydantic `response_model` | Retry loop only | Bounded re-ask; token retry budget | None |
| PydanticAI | `output_type` + validators | Retry loop only | `ModelRetry`; per-role retry budget | None |
| Guardrails AI | Named composable validators | None | Guards w/ on-fail policies | None |
| BAML | Typed language → prompts + validators | Compile time | Runtime-persistent types; typed errors | Type-level |
| Outlines | Grammar/schema | None | Constrained decoding (**by construction**) | None |
| Pact | Pact file (minimal expected responses) | Consumer authors from usage; provider verifies | Provider verification vs provider states | **Pact Matrix**; `can-i-deploy` gate |
| OpenAPI / gRPC | IDL | Design-first | Generated checks both sides | Symbol-level |
| DbC | Pre/postconditions, invariants | Design time | Runtime assertion checks | Method-level |
| SpecGen | LLM-generated formal specs | — | **Mutation-validation of the spec** | Spec→program unit |
| SpecRover | Inferred intent specs | — | Reviewer agent + confidence | Patch→spec |
| EARS | Restricted clause grammar | Authoring | Enables parse→test generation | Clause-level by construction |
| Gherkin | Executable specification files | Authoring | Step definitions run as tests | Step↔code binding |
| ISO 29148 / ReqIF | Quality standard / trace-exchange XML | Authoring | Human review per characteristics | ReqIF trace links |
| promptfoo | Per-test-case typed `assert` lists | None | Deterministic + model-graded; weights, thresholds | Assertion→result rows |
| DeepEval | Test cases + thresholded metrics | None | Threshold pass/fail; **flaky = record, never block** | Case→metric scores |
| OpenAI Evals | Eval files + registry | None | Sample-matching criteria | None |
| Magentic-One | Task/Progress ledgers (private) | None | Orchestrator self-judgment | None (hint-like) |
| ABC (2026) | C=(P,I,G,R) runtime contract | Pre-deployment authoring | **(p,δ,k)-satisfaction**; drift bounds | Contract→session metrics |
| AgentSpec (2025) | Trigger/predicate/enforcement DSL | — | Runtime enforcement (ms) | Rule→violation events |
| TraceGrant (2026) | Task-effect Contract | Pre-execution (from user intent) | Evidence admitted per contract; completion vs actuals | Intent→evidence→effect chain |

**Strongest patterns.** (1) Mature systems separate the contract artifact from verification results and put a **registry** between them — Pact's broker/matrix, OpenSpec's archive, BMAD's sprint-status, WS-Agreement's term states; without accumulated verification data, every gate is amnesiac. (2) The best agreement moments are **bidirectional and constrained**: CNP's producer counter-terms, WS-Agreement's creation constraints, Pact's usage-scoped authoring; approval-only contracts (Spec Kit, Kiro, Tessl) get force from being hard stops, not from negotiation. (3) Conformance strength is a **spectrum** — constrained decoding > schema validation > executed tests > mutation-certified specs > LLM judgment — and mature tools label each check's tier (promptfoo's split; DeepEval's flaky flag). (4) The 2025–26 academic layer independently converges on traceagent's shape — contract before action, evidence only under contract authority, completion vs actuals — adding probabilistic satisfaction (ABC) and DSL rules (AgentSpec). (5) **Nobody has both negotiation and traceability**: the classics negotiate without evidence, Pact evidences without in-the-moment negotiation, the 2026 papers enforce without producer/consumer agreement.

---

## What traceagent should adopt

Mapped to ARCHITECTURE.md §7's open questions:

1. **Invariant DSL grammar.** Compose three prior arts rather than invent: **AgentSpec's rule shape** (trigger / predicate / enforcement) as the clause skeleton — when the clause binds, what must hold, what violation triggers; **EARS as surface syntax** for behavioral clauses (the prefix keyword is a free clause-kind tag: WHEN=event, IF=unwanted, WHILE=state, each mapping to a different test strategy); **DbC pre/post + algebraic properties** as the predicate core compiling to Hypothesis/fast-check generators. Schema clauses delegate wholesale to JSON Schema/Pydantic. Semantic residue = rubric clauses, authored as promptfoo-style typed assertions with weight and threshold. Acceptance semantics for any non-deterministically checked clause: ABC's **(p, δ, k)-satisfaction**.
2. **Codegen coverage.** Clause-kind → artifact: event/unwanted EARS clauses → Gherkin scenario + pytest scaffolds; state clauses → property suites; schema clauses → Pydantic models wired via native structured outputs where available; authorization clauses → policy checks (TraceGrant); rubric clauses → no codegen, judge tier, `flaky=True`. Graceful fallback: every clause minimally compiles to a Gherkin scenario, so no clause is ever un-checkable — only un-checked-yet.
3. **Negotiation protocol.** Take CNP's **binding transition**: draft (cfp) → producer counter-offer carrying **preconditions and consumer-side obligations** (propose; Pact provider-states and DbC client-duties as content) → **accept ⇒ committed** (clause IDs frozen; Kiro's approval gate as UX). Amendments ride **OpenSpec's delta format** (ADDED/MODIFIED/REMOVED against stable slugs) after BMAD-style impact analysis. Deadlocks resolve with FIPA's typed acts — `refuse` (pre-commitment), `reject-proposal` (counter-terms), `failure` (post-commitment, attributed per D4) — plus `reply-by` deadlines.
4. **Non-code element anchoring.** OpenSpec's `### Requirement:` heading slugs and Gherkin scenario headings are the field-tested conventions; keep D2's UUIDv7 identity, with slug + content-hash as the integrity/alias layer — two production precedents for exactly the D2 compromise.
5. **Mutation budget.** Follow **SpecGen**: spend mutations **once, at contract-validation time**, to certify a clause's checkers kill violating mutants (a clause that can't kill its own mutants is mis-authored — likely subjective). At L2/merge, mutate only clauses marked high-consequence via a WS-Agreement-style **consequence field**, not all clauses.
6. **Thresholds.** Deterministic clauses binary; judge-gated clauses **flaky=True** (DeepEval) with recorded score/rationale, never blocking; weighted clause scores with a contract-level threshold (promptfoo); subjective clauses checked p times, requiring k passes (ABC). Calibrate on real corpora before freezing.
7. **Concurrent clause minting.** Use a **registry, not pairwise reconciliation**: the Pact broker pattern — one store where contract versions are published, deltas merged (OpenSpec archive), verification results accumulated (the Pact Matrix is the direct precedent for the trace manifest's queryable form). D2's hash-index detects overlap; the registry's delta/merge with BMAD-style drift repair resolves it.

**One new hard requirement, evidence-backed:** ABC II's co-failure result (90% for same-model handoffs) means **the gate — and its LLM-judge fallback — must be independent of the producer's model**; where the same model must be reused, discount coverage claims. Write this into D4: it is the first empirical justification for traceagent's "validation is gated on the contract, not on another agent's vibes."
