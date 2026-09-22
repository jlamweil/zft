# TraceAgent — Unified System Architecture

> **Canonical design document.** Supersedes `designs/PTE.md`, `designs/ZFT.md`, `designs/PTE ZFT.md`, and `designs/DEC.md` (preserved under [`designs/archive/`](archive/)). Project intent and vocabulary: [`CONTEXT.md`](../CONTEXT.md). Framework landscape evidence: [`docs/research/multiagent-frameworks.md`](../docs/research/multiagent-frameworks.md).
>
> Rule of the road: when this doc and any archived doc disagree, this doc wins. Changing a decision here means writing a new decision record that supersedes the old one — not silently editing it.

---

## 0. What this document unifies

Four prior documents describe overlapping slices of the same system. This doc merges them and converts their disagreements into explicit decision records (§3).

| Source doc | Lineage | Disposition in this doc |
| --- | --- | --- |
| `PTE.md` | First full engine: UUIDv7 identity, Tree-Sitter `@trace` lineage, property gate, ALM sync, ReqIF export | Absorbed: identity model (D2), lineage extraction (D3), storage & ALM (D5), export (§6) |
| `ZFT.md` | Refinement of PTE swapping identity for pure content-addressable SHA-256 anchors | Absorbed: content-hash integrity + normalization rules (D2); its identity model **superseded** by D2 |
| `PTE ZFT.md` | Merge draft of PTE + ZFT | Superseded by this doc; the stray appended generic design-template text was unrelated material and is excluded |
| `DEC.md` | Counter-proposal: executable contracts, symbol-resolution lineage, mutation gate | Absorbed: derived executable bindings (D1), mutation gate (D4/L2), attestation manifest (L3), fault-attribution rule (§4) |
| `DTC.md` | Empty placeholder | Reserved for the deliverable-to-contract trace matrix — realized as the Trace Manifest (§5.3) |

---

## 1. The system in one page

TraceAgent is a **contract-first traceability layer for multiagent work**. Agents exchange *contracts* (structured, clause-IDed acceptance criteria) and *deliverables*; a deterministic engine extracts which deliverable element satisfies which clause, verifies claims with mechanical evidence, and only then accepts the work. Compliance artifacts (trace matrices, ReqIF, ALM updates) are compiled outputs of that same graph — never hand-maintained.

```
                ┌──────────────────────────────────────────────────────────┐
                │                    CONTRACT STORE                        │
                │   Clause nodes (.zft/specs/**) : identity + invariants   │
                └───────┬───────────────────────────────▲──────────────────┘
                        │ contract (clause set)         │ amendments / new clauses
                        ▼                               │
   ┌────────────────────────┐   binding + evidence  ┌────┴───────────────────┐
   │  PRODUCER AGENT        │──────────────────────▶│ CONSUMER / GATE        │
   │  fills the contract    │   deliverable         │ validates per clause   │
   └────────────────────────┘                       └────┬───────────────────┘
                                                            │ reject → bounded retry loop
                                                            ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │                    TRACEABILITY ENGINE (this system)                    │
   │  L0 static integrity → L1 local verify → L2 merge gates → L3 attest     │
   │  Lineage extraction · property + mutation campaigns · signed manifests  │
   └───────┬──────────────────────┬───────────────────────┬─────────────────┘
           ▼                      ▼                       ▼
   Trace Manifest         Compliance Export        Bi-directional ALM Sync
   (clause ↔ element)     (ReqIF, ISO matrices)    (Jira / DOORS / Polarion)
```

Two roles, not two products: **producer** and **consumer** are roles any agent takes in a given interaction (CONTEXT.md §3). The engine is role-agnostic infrastructure.

> **Open/enterprise split.** The trace manifest is the public acceptance payload. The
> *Compliance Export* and *Bi-directional ALM Sync* outputs (ReqIF bundles,
> Jira / DOORS / Polarion sync) are **proprietary enterprise** features,
> implemented in `private/enterprise/` and not shipped in the open-source
> `zft` package — see §6 and `docs/PUBLIC_REPO.md`.

---

## 2. Domain model

| Entity | Definition | Identity |
| --- | --- | --- |
| **Contract** | A versioned set of clauses agreed before validation begins | Contract ID + version |
| **Clause** | One atomic, individually verifiable obligation, with ≥1 invariant | UUIDv7, alias, content hash (D2) |
| **Deliverable** | Work product: code, tests, docs, analysis | Git tree hash |
| **Element** | Addressable piece of a deliverable: function, type, test case, doc section, claim | Language-specific anchor (symbol, line range, section slug + hash) |
| **Binding** | The recorded *claim* "element E was produced for clause C" | Trace-link record |
| **Evidence** | Mechanical proof attached to a binding: compile-symbol, passing property test, mutation survival, judge sign-off | Evidence record with kind + result + reference |
| **Trace Manifest** | The complete clause↔element graph with coverage totals and evidence — the acceptance payload (fills `DTC.md`'s reserved slot) | Signed artifact |
| **Gate** | Any checkpoint that accepts/rejects using only contract-grounded evidence (tiers in §4) | — |
| **Attestation** | Signed statement binding clause hashes + deliverable tree hash + gate results | Cryptographic manifest |

Key semantic rule: a **binding is a claim; evidence is what makes the claim trustworthy; coverage is what makes the contract complete.** The engine's job is to make claims cheap to record, evidence hard to fake, and coverage impossible to fake.

---

## 3. Decision records

Format: Context → Options → Trade-off → Decision → Consequences. Status of all: **Accepted for v0** — this document is the arbiter going forward.

### D1 — Contract artifact medium: declarative, executable, or layered?

**Context.** Clauses must be authored by a spec agent, implemented by a producer, validated by a gate, synced to ALMs, and exported to ReqIF. The source docs propose two different contract media.

**Option A — declarative nodes only (PTE/ZFT).** Clauses are structured JSON files; invariants are algebraic property strings; code links back via `@trace` annotations.
*For:* tool-independent (no compiler needed to read a contract); uniform across artifact kinds (docs and code alike); maps 1:1 onto ALM/ReqIF objects; cheap to diff and review; polyglot-neutral.
*Against:* nothing forces an invariant to be checkable — agents can author vacuous ones; annotations are a second hand-maintained artifact that drifts; verification of the *string* is form-only.

**Option B — executable contracts only (DEC).** The spec agent emits compiled interfaces + property test suites; the producer makes them pass; lineage is type/symbol resolution.
*For:* the compiler enforces contract structure for free; verification is real execution; the producer works in its native code loop; no string tags to rot.
*Against:* needs a per-language toolchain; only covers code (a contract for a design doc has no compiler); humans/regulators review code harder than structured nodes; requirement→code sync for ALM/ReqIF means reverse-engineering prose from tests; contract identity gets entangled with code layout.

| Dimension | A: Declarative | B: Executable |
| --- | --- | --- |
| Universality (non-code deliverables) | ✔ | ✗ |
| Enforcement strength | form-only | compiler + runtime |
| Human/ALM/review friendliness | ✔ | weaker |
| Polyglot cost | one parser set | per-language toolchain |
| Drift risk | annotations drift | none if generated; high if hand-written |
| Authoring friction for agents | low | medium (language-bound) |

**Decision: layered, with one-way derivation.** The **declarative clause is the single source of truth**. Executable artifacts (interface stubs, property skeletons) are **derived** from clauses by codegen — for code-targeted clauses, where a toolchain exists. The derivation is one-way (clause → binding, never hand-edited binding → clause), so drift is eliminated by construction: don't synchronize, regenerate. Where codegen is impossible (non-code deliverables, unsupported languages), annotations and generic evidence apply.

**Consequences.**
1. Invariants must be written in a **constrained, machine-executable invariant DSL** — not free text. This is the biggest *new* work item unification exposes: every source doc stores `algebraic_property` as a string nothing can run. The DSL grammar is a v0 blocking task (§7).
2. A clause declares its own verification kind(s): `property`, `type`, `judge` (§4 L3 rule) — so the gate knows what evidence it may accept.
3. DEC's enforcement insight is preserved where it matters (code), without sacrificing PTE's universality (everything else).
4. *(Amendment, 2026-09-04, from seeding the v0 contract)*: check kinds extended to **`property`, `type`, `test`, `judge`, `process`** — `test` = integration-test evidence, `process` = manual/processual check. First applied by `tools/contract_seed.py` / enforced by `tools/contract_lint.py` (both deleted since — enforcement now lives in `src/traceagent/spec/lint.py`, exposed as `traceagent lint`).

### D2 — Clause identity: minted UUID vs. content-addressable hash?

**Context.** The docs disagree: PTE mints a UUIDv7 and carries a SHA-256 content hash *alongside*; ZFT derives the primary ID *from* the content hash. This is the sharpest fork in the source material.

**Option A — UUIDv7 identity + content-hash state (PTE).** Identity is minted once and immutable; edits bump version and change the content hash, never the ID.
**Option B — content-addressable anchor (ZFT).** Identity *is* `SHA256(normalized content)`; any edit mints a new identity.

| Concern | A: UUIDv7 + hash | B: content address |
| --- | --- | --- |
| Identity survives edits (typo fixes, clarifications) | ✔ | ✗ — every edit = "new clause" |
| External links (Jira, DOORS, history) stable | ✔ | only via alias indirection — i.e., reinventing A with worse ergonomics |
| Concurrent edits by two agents | same clause diverges → version conflict, haltable | divergent content = two *different* clauses → **silent spec fork** |
| Authority-free derivation | ✗ (needs minting — trivial, `uuid7()` anywhere) | ✔ |
| Tamper-evidence | via the accompanying content hash | ✔ inherent |
| Exact-duplicate detection | via a content-hash index (cheap) | ✔ inherent |

**Decision: Option A** — UUIDv7 primary identity + SHA-256 content hash as an *integrity field* + mutable human alias. ZFT's virtues are retained as properties, not as identity: the content hash is mandatory and verified at every gate (L0); a hash index detects exact duplicates; alias uniqueness is enforced.

**Consequences.** The content hash must be defined precisely, and the two docs actually differ here too (PTE hashes `version`; ZFT doesn't). Canonical rule: **the hash covers meaning, not revision state** — `domain`, `title`, `invariants` (normalized), and *excludes* `version`, `status`, `external_links`, and all metadata. The version counter answers "which revision"; the hash answers "did the meaning change". Full normalization algorithm: §5.2.

### D3 — Trace binding: annotation tags vs. structural/type resolution?

**Context.** How does a deliverable element get *bound* to a clause, such that the binding can be found again deterministically?

**Option A — explicit `@trace("ALIAS")` annotations extracted by Tree-Sitter (PTE/ZFT).** One query grammar per language family; exact line ranges; 30+ languages without per-language AST plugins.
**Option B — structural resolution (DEC).** The producer implements a generated interface (`class TokenValidator implements AuthContract`); lineage comes from symbol/type resolution and call graphs (e.g., SCIP).

| Concern | A: annotations | B: structural |
| --- | --- | --- |
| Polyglot reach | ✔ broad | per-language toolchain needed |
| Enforcement at authoring | gate-time only (resolvable-alias check) | ✔ compile-time — won't build unbound |
| Granularity | any: file, function, line range, doc section | coarse: type/module level — "implements" ≠ "satisfies invariant" |
| Refactor resilience | tag travels with code; deleting code silently drops the tag (caught by coverage at the gate) | ✔ rename-safe via symbol identity |
| Non-code deliverables | ✔ (comments, frontmatter, section anchors) | ✗ |

**Decision: reclassify rather than choose.** The *binding* mechanism is uniform — an explicit link record, extracted mechanically (Tree-Sitter for code, section anchors for docs). **Structural conformance is demoted from "alternative binding" to the strongest tier of *evidence*** (§2): where a generated interface exists, `implements` gives the binding its top evidence tier; where it doesn't, annotations still bind, with weaker evidence. What makes either trustworthy is the **bi-directional coverage gate**: every clause ≥1 valid inbound binding, every element ≥1 justifying clause — so missing or silent tags fail loudly at the gate instead of rotting quietly.

### D4 — Verification gates: property enforcement vs. mutation testing?

**Context.** PTE/ZFT gate on test *form* (property-based generators present, trivial-assertion ratio capped). DEC gates on test *bite* (mutants injected; if the suite doesn't fail, the contract is under-specified or the suite fraudulent). Written as rivals; they are actually different cost/depth points on one pipeline.

**Decision: tiered gates**, cheap-and-always first, deep-and-expensive at the boundary:

| Tier | When | Checks | Cost |
| --- | --- | --- | --- |
| **L0 static integrity** | every write | schema validation, alias resolution, content-hash verify, duplicate-hash check, annotation syntax | ms |
| **L1 local verify** | producer's inner loop | compile/typecheck of derived bindings; property suite (small N); property-ratio + trivial-assertion checks | seconds |
| **L2 merge gate** | acceptance/merge | full property campaign; **mutation testing of the contract suite**; coverage in both directions | 5–15s+ |
| **L3 attestation** | post-acceptance | signed manifest binding clause hashes + tree hash + gate results (D2 hashes + DEC's ledger) | ms |
| **Judge** | only clauses declared `kind: judge` at authoring | LLM-judged with recorded rationale; excluded from "deterministic coverage" claims | API call |

Thresholds are gate configuration, not dogma — the source docs themselves disagree (trivial-assertion cap 15% in PTE.md vs. property-ratio ≥50% in `PTE ZFT.md`). Defaults: trivial ≤15% **and** property ratio ≥50%; tunable per repo.

**Fault attribution rule (from DEC, kept).** An L2 failure classifies before it retries: if mutants *survive* the suite, the **contract** is under-specified → back to the spec agent; if the suite is fine but code fails it, the **implementation** is at fault → back to the producer. The retry loop never bounces work without naming the responsible role (CONTEXT.md's producer/consumer vocabulary).

### D5 — Storage, concurrency, and ALM sync

Not contested between source docs; recorded for completeness. **Local-first Git** (`.zft/specs/**` in the working tree) is authoritative; enterprise ALMs (Jira, DOORS, Polarion) synchronize bi-directionally and asynchronously. Sync conflicts halt the pipeline with a structured resolution diff — never a silent CRDT overwrite. Clause `status` lifecycle (`DRAFT → PROPOSED → VALIDATED → IMPLEMENTED → DEPRECATED`) maps onto the A2A task lifecycle (`INPUT_REQUIRED`, `REJECTED`, …) so the same graph drives both agent interactions and enterprise reporting.

### D6 — Interaction protocol (the new layer)

The engine above is the substrate; the *framework* is the protocol wrapped around it. Design follows directly from CONTEXT.md and the landscape gap analysis:

1. **Contract negotiation precedes work.** Consumer drafts clauses (`PROPOSED`); producer may push back before `VALIDATED`. No validation without a `VALIDATED` contract — the contract is the acceptance criteria, versioned and clause-IDed (the piece Spec Kit/Kiro lack between agents).
2. **Acceptance payload = Trace Manifest.** The producer returns deliverable + bindings; the gate runs L0–L2 and answers per-clause, not per-vibe.
3. **Rejection is bounded and typed.** Gate rejection names failed clause IDs and the attributed fault (D4), fed back in a guardrail-style retry loop with a bounded retry count (landscape: CrewAI's `guardrail_max_retries` is the right shape).
4. **Transport-agnostic, A2A-shaped.** Contract, deliverable, and manifest ride as artifacts on the existing Task/envelope model (A2A extension point) or the in-process equivalent; nothing in the engine assumes a wire protocol.

---

## 4. End-to-end pipeline

```
 1. CONSUMER drafts contract          clauses minted, invariants in DSL, status PROPOSED
 2. NEGOTIATION                       producer reviews; amendments bump contract version
 3. VALIDATION GATE (L0)              contract itself gated: schema, DSL, duplicates, hashes
 4. STATUS → VALIDATED                contract frozen; codegen emits interface stubs + property skeletons
 5. PRODUCER implements               code + tests; bindings recorded; L1 runs in-loop
 6. ACCEPTANCE GATE (L2)              coverage both ways + property campaign + mutation
        ├─ contract-fault  → clauses under-specified → back to consumer/spec agent (step 1)
        └─ impl-fault      → code fails valid clauses → back to producer (step 5, bounded retries)
 7. ATTESTATION (L3)                  signed manifest: clause hashes + tree hash + gate log
 8. EXPORT                            trace matrix, ReqIF bundle, ALM state updates
```

---

## 5. Schemas & algorithms (canonical)

### 5.1 Clause node (`.zft/specs/<domain>/<alias>.json`)

Field provenance marked: **[P]** = PTE, **[Z]** = ZFT, **[D]** = DEC, **[N]** = new in unification.

```json
{
  "node_id":     "018f3a2b-9e41-7100-8000-000000000001",   // [P] identity, UUIDv7, immutable (D2)
  "alias":       "AUTH-OAUTH-JWT-VALIDATE",                 // [P/Z] unique human handle, mutable
  "domain":      "auth",                                    // [P/Z]
  "title":       "Reject expired JWT tokens with 401",      // [P/Z]
  "status":      "PROPOSED",                                // [P/Z] DRAFT|PROPOSED|VALIDATED|IMPLEMENTED|DEPRECATED
  "version":     2,                                          // [P/Z] revision counter
  "content_hash":"e3b0c44298fc1c149afbf4c8996fb92427ae4…",  // [Z] integrity field, §5.2, verified at L0
  "invariants": [                                            // [P/Z], now constrained (D1)
    {
      "id":        "INV-01",
      "statement": "System SHALL reject expired tokens with HTTP 401.",
      "property":  "forall t: expired(t) => validate(t) == Err(Unauthorized)",  // invariant DSL (§7)
      "check":     { "kind": "property", "generator": "jwt.tokens" }            // [N] what evidence L1/L2 may accept
    }
  ],
  "external_links": [ { "system": "JIRA", "external_id": "SEC-8492" } ]       // [P/Z] excluded from hash
}
```

### 5.2 Content-hash normalization (canon; resolves the PTE/ZFT divergence)

```
content_hash = SHA256( canonical_json({
    "domain":     lowercase(strip(domain)),
    "title":      lowercase(strip(title)),
    "invariants": sort_by_id([{id, statement, property, check}…])   // strings stripped
}))
```
Excluded deliberately: `version`, `status`, `external_links`, `node_id`, `alias` — metadata and revision state, not meaning. Serialization: sorted keys, no whitespace (matching ZFT's `separators=(',',':')` rule).

### 5.3 Trace manifest (acceptance payload; realizes the reserved `DTC.md`)

```json
{
  "contract":     { "id": "…", "version": 3 },
  "deliverable":  { "tree_hash": "sha256:…" },
  "bindings": [
    {
      "clause":    "018f3a2b-…",
      "elements":  [ { "kind": "function", "ref": "src/auth/jwt.py#validate", "lines": "40-72" } ],
      "evidence":  [ { "kind": "implements-generated-interface", "result": "pass" },
                     { "kind": "property-test", "ref": "tests/test_jwt.py::INV-01", "result": "pass", "cases": 10000 },
                     { "kind": "mutation-survival", "killed": 41, "total": 41 } ]
    }
  ],
  "coverage":     { "clauses_covered": "12/12", "elements_justified": "87/87", "judge_gated": [] },
  "gate_log":     { "L0": "pass", "L1": "pass", "L2": "pass" },
  "signature":    "…"
}
```

### 5.4 Attestation manifest

Signed statement binding: contract content hashes, deliverable tree hash, gate log, tool versions, timestamp — DEC's "cryptographic trace manifest" and PTE's commit-hash binding, merged. It is the sole input to compliance export (§6): if it isn't attested, it isn't exported.

---

## 6. Compliance & ALM export

> **Enterprise scope note (2026-09-11):** the ReqIF and ALM implementation
> described here lives in the proprietary tree (`private/enterprise/zft/reqif/`,
> `private/enterprise/zft/alm/`) — it is **not** part of the open-source
> `zft` package. The public package ships the attested trace matrix / DSSE /
> summary exports only.

Unchanged in substance from PTE/ZFT, now fed exclusively by attested manifests: deterministic trace matrices (clause ↔ element ↔ evidence), ReqIF XML bundles for ALM interchange, ISO 26262 / IEC 62304 / DO-178C-style matrices, and bi-directional ALM state sync (D5). Regulatory framing note: deterministic, evidence-backed links are what make this auditor-defensible — probabilistic (LLM-judged) links exist only in `judge_gated` clauses and are visibly quarantined in every export.

---

## 7. Open questions (blocking v0 implementation)

> Research input: [`docs/research/requirements-contracting-for-agents.md`](../docs/research/requirements-contracting-for-agents.md) §"What traceagent should adopt" proposes concrete, cited candidate answers for each question below (AgentSpec grammar + EARS + DbC for the DSL; Contract Net + OpenSpec deltas + FIPA typed acts for negotiation; Pact's broker/matrix for the registry). Treat them as inputs to decide, not decisions made. It also adds one evidence-backed requirement for D4: the gate (and its judge fallback) must be **independent of the producer's model** — same-model two-agent handoffs co-fail on 90% of failed missions (ABC II, arXiv:2608.12895).

1. **Invariant DSL grammar** (D1) — the top blocking item. Which subset of algebraic property notation is both expressive enough for real clauses and mechanically compilable into Hypothesis/fast-check/QuickCheck generators?
2. **Codegen coverage** — which `(clause shape → artifact kind)` pairs does v0 generate (e.g., property suite only? typed interfaces? test scaffolds?), and what is the graceful fallback when none apply?
3. **Negotiation protocol details** (D6) — amendment format, what freezes at `VALIDATED`, escalation when producer and consumer dead-lock.
4. **Element anchoring for non-code deliverables** — stable slugs + section content hashes (§5.2 rules extended to prose) need a concrete spec.
5. **Mutation budget policy** — which clauses get mutation-checked at L2 and with what operator set, given cost (DEC's own trade-off note: deep gates at merge only).
6. **Threshold defaults** — validate trivial ≤15% / property ≥50% against real corpora before freezing.
7. **Concurrent clause minting** — two agents minting overlapping clauses: hash-index detection exists (D2), but the merge/dedupe workflow is unspecified.

---

## 8. Source index (traceability of this document itself)

| This doc | Derived from | Supersedes |
| --- | --- | --- |
| §1, §2, §5.2, §6 | PTE.md, ZFT.md | both |
| D1, D4 (L2, L3), §4 fault rule | DEC.md vs. PTE/ZFT | the rivalry |
| D2 | PTE.md vs. ZFT.md | ZFT's identity model |
| D3 | PTE/ZFT vs. DEC | both as sole mechanisms |
| D5, §5.1 | PTE.md (§4, schema), ZFT.md (§3) | both |
| D6, §1 framing | CONTEXT.md, docs/research/multiagent-frameworks.md | — |
| §5.3 | `DTC.md` (reserved slot) | — |
