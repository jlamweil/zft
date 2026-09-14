# Scaffold Search — What We Can Rely On, Per Part

> Searched 2026-09-04 via `gh search repos` (20+ queries, deduplicated, filter: archived → license → activity) + deep evaluation of 20 finalists (contents probe, README, releases, contributors, score formula from the scaffold-search skill).
> Design context: [`designs/ARCHITECTURE.md`](../../designs/ARCHITECTURE.md) (D1–D6), research notes in this directory.
> Scores are scaffold-ability (license/maintenance/maturity/docs/production/community/vitality). "est." = forks/contributors estimated, not fetched.

## Reliance map (the one-paragraph answer)

We **depend on** six mature libraries — Hypothesis, ast-grep (+ tree-sitter underneath), mutmut, in-toto, pytest-bdd, and the official A2A + MCP Python SDKs — none of which we should ever fork. We **adapt** three codebases' innards: strictdoc (clause store + ReqIF compliance export, the single biggest win), deal/icontract (the DbC contract surface for D1), and — as a direct competitor to study — rtmx, which already does requirements-traceability-as-CSV-in-git with MCP access for agents. We **use patterns** from Pact's broker/matrix/can-i-deploy (our registry semantics), spec-kit (clause-ID conventions, NEEDS-CLARIFICATION state), OpenSpec (delta/archive amendment protocol), sem (entity-level element anchoring), and SCIP (symbol-stable bindings). We **write from scratch**: the invariant DSL grammar, the L0–L3 gate orchestration, the coverage engine, the trace-manifest predicate, and the negotiation protocol — that stack is our product.

| Component | Rely on | Recommendation | Score | License |
| --- | --- | --- | --- | --- |
| 1 Contract store | [strictdoc](https://github.com/strictdoc-project/strictdoc) | **ADAPT** | 90 | Apache-2.0 |
| 1 | [OpenSpec](https://github.com/Fission-AI/OpenSpec) | USE PATTERN (deltas, stores) | 87 | MIT |
| 1 | [spec-kit](https://github.com/github/spec-kit) | USE PATTERN (IDs, states, audit) | 87 | MIT |
| 1 | [rtmx](https://github.com/rtmx-ai/rtmx) | STUDY / run alongside — competitor | 81 | Apache-2.0 |
| 1 | [doorstop](https://github.com/doorstop-dev/doorstop) | SKIP for fork (LGPL) | 83 | LGPL-3.0 |
| 2 Invariant DSL | [deal](https://github.com/life4/deal) | ADAPT | 85 | MIT |
| 2 | [icontract](https://github.com/Parquery/icontract) | ADAPT (alt.) | 85 | MIT |
| 2 | [CrossHair](https://github.com/pschanely/CrossHair) | DEPEND (symbolic gate tier) | 90 | MIT/Apache/PSF |
| 3 Codegen | [pytest-bdd](https://github.com/pytest-dev/pytest-bdd) | DEPEND | 90 | MIT |
| 3 | [icontract-hypothesis](https://github.com/Parquery/icontract-hypothesis) | USE PATTERN only — dead (2020) | n/a | none |
| 4 Gates | [HypothesisWorks/hypothesis](https://github.com/HypothesisWorks/hypothesis) | DEPEND | n/a | MPL-2.0 |
| 4 | [mutmut](https://github.com/boxed/mutmut) | DEPEND | 90 | BSD-3-Clause |
| 4 | [stryker-js](https://github.com/stryker-mutator/stryker-js) | DEFER (TS deliverables later) | 83 | Apache-2.0 |
| 5 Lineage | [ast-grep](https://github.com/ast-grep/ast-grep) | DEPEND (build D3 on it) | 83 | MIT |
| 5 | [Ataraxy-Labs/sem](https://github.com/Ataraxy-Labs/sem) | USE PATTERN (element anchoring) | 83 | Apache-2.0 |
| 5 | [sourcegraph/scip](https://github.com/sourcegraph/scip) | USE PATTERN (symbol identity) | n/a | Apache-2.0 |
| 6 Attestation | [in-toto/in-toto](https://github.com/in-toto/in-toto) | DEPEND | 90 | Apache-2.0 |
| 6 | [chainloop](https://github.com/chainloop-dev/chainloop) | Optional infra (evidence store) | 87 | Apache-2.0 |
| 7 Agent protocol | [a2aproject/a2a-python](https://github.com/a2aproject/a2a-python) | DEPEND | 87 est. | Apache-2.0 |
| 7 | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | DEPEND | 87 est. | MIT |
| 8 Registry | [pact-foundation/pact_broker](https://github.com/pact-foundation/pact_broker) | USE PATTERN (+pact-python if API deliverables) | 90 | MIT |

---

## 1. Contract store (clause nodes, identity, ReqIF export)

### [strictdoc](https://github.com/strictdoc-project/strictdoc) — **ADAPT** · 90/100 · Apache-2.0 · active (2026-09)
Python requirements-management tool; textual/SDOC + JSON requirement nodes with UIDs and fields, bi-directional links, HTML/Sphinx publishing — and a **full ReqIF backend** (`strictdoc/backend/reqif/`, both sdoc→reqif and reqif→sdoc converters, verified in tree).
**This is PTE/ZFT's spec-node store + compliance export, already productionized.**
- Reuse: requirement object model, link model, ReqIF export backend (`strictdoc/backend/reqif/reqif_export.py`).
- Modify: identity (we add UUIDv7 + content-hash per D2 — strictdoc uses section-path UIDs); statuses to our lifecycle; clause schema as its requirement fields.
- Discard: none needed to start — its document/section grammar is a superset of our clause nodes.
- Score: 90 (License 15 · Maintenance 15 · Maturity 10 · Docs 10 · Production 20 · Community capped 20 · Vitality 10).

### [OpenSpec](https://github.com/Fission-AI/OpenSpec) — USE PATTERN · 87/100 · MIT · very active
Git-native spec store + **delta format** (`ADDED/MODIFIED/REMOVED Requirements` against stable heading slugs, merged on archive) + "Stores" (read-only spec repos consumed by other teams' agents).
- Steal: delta protocol = ARCHITECTURE §7.3 amendment answer; store-per-consumer model = our contract registry topology.

### [github/spec-kit](https://github.com/github/spec-kit) — USE PATTERN · 87/100 · MIT · very active
Prompt/workflow assets more than embeddable code. Steal: `FR-001`/`SC-001` ID conventions, `[NEEDS CLARIFICATION]` clause state, analyze-style coverage audit as gate artifact.

### [rtmx](https://github.com/rtmx-ai/rtmx) — STUDY / run alongside · 81/100 · Apache-2.0 · active, small (31★, 28 contrib.)
"Requirements traceability as a CSV file in git. Every requirement has an ID, a spec, and linked tests. Status derived from test results. AI agents query your requirements via MCP."
**Direct competitor to our trace-matrix layer** — same-kind rule says don't fork; study and differentiate. Our differentiators over rtmx: negotiated contracts (not human-authored CSVs), clause→evidence tiers, bi-directional coverage, attestation. Worth running early traceagent pilots against rtmx as a baseline.

### [doorstop](https://github.com/doorstop-dev/doorstop) — SKIP for fork · 83/100 · **LGPL-3.0** ⚠️
Same YAML-in-git idea, actively maintained. LGPL rules out fork-into-our-framework; acceptable only as an external tool.

## 2. Invariant DSL (D1's blocking item)

### [deal](https://github.com/life4/deal) — **ADAPT** · 85/100 · MIT · stable, slowed (2025-11)
DbC decorators (`@deal.pre/@deal.post/@deal.inv/@deal.ensure`) plus a large library of ready-made contract predicates (`deal.dispatch`, `deal.has`, …). The contract *vocabulary* is exactly our predicate core; license and purity make it safe to vendor.
### [icontract](https://github.com/Parquery/icontract) — ADAPT (alternative) · 85/100 · MIT
Better inheritance-aware violation messages (useful for D4's typed rejections); more recent activity than deal.
- Choose: icontract if violation-message quality matters first (it does, per D4); deal for its predicate zoo. Possible: icontract surface, deal predicates ported.
### [CrossHair](https://github.com/pschanely/CrossHair) — DEPEND · 90/100 · MIT/Apache/PSF
Symbolic execution of contracts/properties — checks without random sampling. Perfect as an optional *stronger gate tier* between L1 (sampling) and L2 (mutation) for pure-function clauses.
- Negative result: **no maintained EARS parser exists** (searched). The EARS grammar is tiny — we write it ourselves (~a day), which is fine: it's the surface syntax layer of our DSL, feeding icontract/deal predicates and pytest-bdd scenarios.

## 3. Codegen (clause → artifacts)

### [pytest-bdd](https://github.com/pytest-dev/pytest-bdd) — DEPEND · 90/100 · MIT
Executes Gherkin scenarios as pytest. Our codegen rule "every clause minimally compiles to a Gherkin scenario" (so no clause is un-checkable) executes on pytest-bdd out of the box.
### [icontract-hypothesis](https://github.com/Parquery/icontract-hypothesis) — USE PATTERN only · dead (0★, untouched since 2020, no license)
Was exactly D1's codegen shape: DbC contracts → Hypothesis-generated test cases. We reimplement that integration (thin: icontract decorators are introspectable) — flagged in ARCHITECTURE §7.2.

## 4. Verification gates (L1–L2)

### [HypothesisWorks/hypothesis](https://github.com/HypothesisWorks/hypothesis) — DEPEND · MPL-2.0
The property engine (L1). Nothing else in Python is competitive.
### [mutmut](https://github.com/boxed/mutmut) — DEPEND · 90/100 · BSD-3-Clause · very active
Python mutation testing for L2. Fast-enough for clause-targeted mutation if we mutate only the module scopes a clause binds to (its selected-test support helps). Score partial (contributors API unavailable).
### [stryker-mutator/stryker-js](https://github.com/stryker-mutator/stryker-js) — DEFER · 83/100 · Apache-2.0
The equivalent for JS/TS deliverables; not v0 (Python-first), keep on the list.

## 5. Lineage / traceability extraction (D3)

### [ast-grep](https://github.com/ast-grep/ast-grep) — DEPEND · 83/100 (tests-in-crates: score partial) · MIT · very active
Structural search/rewrite across many languages via YAML rule files, Rust-fast, has an MCP server (`ast-grep/ast-grep-mcp`) — so agents can run our extraction queries directly.
**Recommendation: build D3 extraction on ast-grep YAML rules instead of hand-written Tree-Sitter S-expressions per language** — the PTE/ZFT approach's maintenance burden becomes a directory of declarative rule files, and `@trace("ALIAS")` becomes one rule.
### [Ataraxy-Labs/sem](https://github.com/Ataraxy-Labs/sem) — USE PATTERN · 83/100 · Apache-2.0 · new (2026-02), hot
Entity-level diffs (functions/classes as addressable units) on tree-sitter, MCP-first. Exactly the element-anchoring semantics our §7.4 needs; replicate its entity-identity model, don't depend on it (young, VC-stack).
### [sourcegraph/scip](https://github.com/sourcegraph/scip) — USE PATTERN · Apache-2.0 · active
SCIP index = symbol-stable identity across languages. DEC-style structural evidence ("implements AuthContract") should be recorded as SCIP symbols so bindings survive renames (D3 evidence tier).

## 6. Attestation (L3)

### [in-toto/in-toto](https://github.com/in-toto/in-toto) — DEPEND · 90/100 · Apache-2.0
Supply-chain attestation framework: DSSE-signed statements binding subject hashes to evidence — our L3 attestation manifest *is* an in-toto statement with a custom predicate. Verifies with existing tooling.
### [in-toto/attestation](https://github.com/in-toto/attestation) — SPEC to reuse
Define a `TraceManifest` predicate (clause hashes, coverage totals, gate log) in their predicate registry format.
### [chainloop](https://github.com/chainloop-dev/chainloop) — Optional infra · 87/100 · Apache-2.0
Hosted-style evidence store + policy engine for attestations. If we don't want to build registry storage at all, this holds our manifests with signatures verified. Decision later (infra dependency vs. git-native store per D5).

## 7. Agent protocol envelope (D6)

### [a2aproject/a2a-python](https://github.com/a2aproject/a2a-python) — DEPEND · 87 est. · Apache-2.0 · very active
Official Linux-Foundation A2A SDK: Tasks, artifacts, typed Parts, lifecycle states including `REJECTED`/`INPUT_REQUIRED` — our contract/deliverable/manifest ride as artifacts (research note's D6 extension point).
### [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) — DEPEND · 87 est. · MIT
Tool/context plumbing; also the channel through which rtmx-style tools and ast-grep-mcp expose themselves to producer agents.
### agi-inc/agent-protocol — SKIP · stale (2025-04), effectively archived (research note concurrs).

## 8. Contract registry (verification matrix, acceptance gate)

### [pact-foundation/pact_broker](https://github.com/pact-foundation/pact_broker) — USE PATTERN · 90/100 · MIT · active
The semantics we replicate in our registry: published contracts + accumulated **verification results per version-pair**, and `can-i-deploy` = a gate reading "is there a valid verification row for exactly these versions" — structurally identical to our acceptance gate ("is there a valid evidence row for every clause at contract version N"). Whether we run the Ruby broker for API-flavored deliverables (via [pact-python](https://github.com/pact-foundation/pact-python), 90/100, MIT) or implement the matrix in our own store: decide at §7.7.

---

## Method notes & caveats

- License resolution: GitHub's search API returned `license: none` for many repos; all licenses above were verified from repo LICENSE files (strictdoc/in-toto/CrossHair are permissive despite `NOASSERTION` in the API; doorstop is genuinely LGPL-3.0).
- Scores use the scaffold-search formula; `pytest-bdd` and `mutmut` are partial (contributors API returned empty); `a2a-python` and `mcp-python-sdk` forks/contributors estimated.
- Negative searches (recorded to avoid re-searching): "requirements bdd gherkin" and "requirements code as" → `[]`; "property testing python" → junk (2-word miss — Hypothesis found by name); "crosshair" name searches are polluted by game-cheat repos (GitHub search limitation); no maintained EARS parser found.
- Earlier research (multiagent-frameworks.md) already covers framework-level candidates (LangGraph, CrewAI, AutoGen/MAF): those are *orchestration peers*, not scaffold targets — traceagent layers on top of any of them via A2A/MCP, so none is adopted wholesale.
