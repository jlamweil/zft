# DSL_ROADMAP — what traceagent should steal from EARS tooling, OPA/Rego, and Sigstore

> Status: proposal, 2026-09-05. Synthesized from training knowledge of the three
> ecosystems; traceagent-side claims are grounded in the tree as of this date
> (file:line refs). Mechanisms are described at the design level — external API/CLI
> details drift, so re-check primary sources before building anything that must
> interoperate with those ecosystems directly. Complements, not replaces:
> `docs/research/requirements-contracting-for-agents.md` (EARS/BDD landscape) and
> `docs/research/scaffold-search-findings.md` (depend/adapt/replicate calls).

## 0. TL;DR — ranked steals (value ÷ effort)

Value 1–5 (5 = load-bearing for the v1 trust story), Effort 1–5 (1 = hours,
2 = 1–2 days, 3 = 2–4 days). Ties broken by dependency order, not ratio.

| # | Steal | From | Value | Effort | Wave |
|---|-------|------|-------|--------|------|
| R-01 | Structured gate findings with `deny`/`warn` tiers | OPA admission conventions | 4 | 1 | 1 |
| R-02 | Ambiguity-lexicon lint for clause prose | INCOSE rules via EARS tooling | 3 | 1 | 1 |
| R-03 | Assurance levels as *negotiated* contract terms | SLSA levels, reshaped | 3 | 1 | 1 |
| R-04 | Unsafe-variable analysis in the predicate DSL | Rego compiler safety rule | 5 | 2 | 2 |
| R-05 | Consumer-side verify-policy over attestation payloads | cosign policy-controller | 5 | 2 | 2 |
| R-06 | EARS type taxonomy → verification routing | EARS patterns × Hypothesis | 4 | 2 | 2 |
| R-07 | Gate fingerprint + verification-summary attestations | OPA decision logs ∩ SLSA VSA | 4 | 2 | 2 |
| R-08 | Hash-chained ledger → Merkle heads with inclusion proofs | Rekor (serverless reading) | 4 | 2–3 | 2/3 |
| R-09 | Trust root: pinned keys, thresholds, rotation, freshness | Sigstore trust root / TUF | 5 | 3 | 3 |
| R-10 | Pure `evaluate()` gate interface + decision replay | OPA `input`/`data` purity | 3 | 2 | 3 |
| R-11 | EARS ⇒ predicate unification (compiled clause skeletons) | formal-EARS semantics | 4 | 3 | 3 |
| R-12 | Per-agent signing identities, rotation-ready | Fulcio keyless, adapted | 4 | 3 | 3 |

Sequencing principle: Wave 1 hardens what the gate *says* (findings), Wave 2
hardens what the gate *accepts* (DSL safety, attestation policy, evidence
identity), Wave 3 hardens *who can be trusted at all* (roots, identities,
tamper evidence). The end state is one pipeline:

```
EARS surface (authoring)  →  predicate DSL (formal core)  →  gates L0–L3 (policy evaluation)
  →  DSSE TraceManifest (evidence)  →  verify-policy + trust root (acceptance)
  →  signed append-only log (tamper evidence)
```

## 1. Already absorbed (don't re-steal)

The repo already implements the *core* best bits of all three domains:

- **Sigstore packaging**: DSSE envelopes, in-toto `Statement/v1`, custom
  versioned predicate URI, RFC 8785 JCS canonicalization, canonical-base64
  rejection, subject-digest verification — `src/traceagent/attest/dsse.py`,
  `attest/jcs.py`.
- **OPA admission shape**: gate tiers, default-deny (missing binding = red,
  `gates/l1.py:79`, `gates/l2.py:63`), typed rejections with fault
  attribution (`{code, clause_ids, fault, expected, actual}`, `gates/l1.py:126`,
  `gates/l2.py:77`), `judge_excluded` transparency published into the signed
  predicate (`dsse.py:111`).
- **EARS tooling practice**: frozen grammar version, layered diagnostics with
  expected-shape + fix hint (`dsl/ears.py`), caret-marked ParseErrors in the
  predicate DSL (`dsl/predicate.py:65`), golden-pinned grammars.
- **Decision-log seeds**: digest-keyed L1 verdict cache (`gates/l1.py:28`),
  event ledger (`debug/ledger.py`), `repro` command.

The steals below are the *next* mechanisms each ecosystem learned the hard way.

## 2. The steals

### Wave 1 — quick wins (≤ a day each)

#### R-01 · Structured gate findings with deny/warn tiers (OPA)

> Status: **prototyped (C-41, 2026-09-06)** — `spec/findings.py` (fixed six-key
> `Finding`, golden-pinned by `tests/golden/findings.json`), `lint_store` now
> renders denies only, `run_l0` publishes structured `warnings`, wired through
> the ledger event, `check` JSON, and `build_gate_log(l0_warnings=...)`.
> Deferred to the real landing: publishing warns as a TraceManifest *predicate*
> field (touches the signed DSSE payload shape and its golden envelopes).

**Source.** OPA admission policy convention: rules accumulate into named sets
(`deny`, `warn`) of structured objects (`{msg, detail}`); evaluation collects
*all* findings instead of stopping at the first; `deny` blocks admission,
`warn` records an advisory. `opa check --strict` is the same split for the
policy source itself.

**Today.** `lint_store` (`spec/lint.py:11`) returns flat `list[str]`, and L0
makes every finding fatal. L1/L2 already emit structured rejections — L0 is
the odd one out, and there is no severity channel at all: an advisory-quality
store (prose concerns, style) currently either passes silently or blocks.

**Proposal.** Findings become objects: `{code, alias, severity: "deny"|"warn",
msg, hint}`. `run_l0` blocks on `deny`; `warn` flows into the gate log and the
TraceManifest predicate — `judge_excluded` (`dsse.py:111`) is precedent for a
published advisory list. Aligns L0's rejection shape with L1/L2, which the
negotiation SM consumes as typed rejections.

**Done when.** A store with one schema error and one style concern: gates red
with a structured rejection; the warn visible in `check` JSON and the L3
payload, gates otherwise green.

#### R-02 · Ambiguity-lexicon lint (INCOSE rules via EARS tooling)

**Source.** INCOSE's Rules for Writing Requirements, operationalized by EARS
authoring tools: flag weak/open words ("appropriate", "adequate", "sufficient",
"fast", "user-friendly", "etc."), unbounded quantifiers, passive voice,
pronouns without antecedent, and negation in the response clause. EARS's
grammar constrains *syntax*; the lexicon extends the verifiability guarantee
to the *response text*, which no grammar can constrain.

**Today.** `parse_statement` checks shape only. "THE SYSTEM SHALL be nice."
parses, renders a green Gherkin scenario (`cli/main.py:156`), and counts as
clause coverage — the pipeline happily verifies nothing.

**Proposal.** `spec/ambiguity.py`: lexicon + rule pass over trigger/response
text of every invariant whose `statement` parses as EARS. Hard rules → `deny`
(negated modal in response, "etc."/"and so on", unbounded universal without a
declared domain); soft rules → `warn` (weak adjectives, passive voice).Clauses
that can't be made checkable should be *routed to `check.kind = "judge"` at
authoring time* — honest quarantine, per CONTEXT.md §4.2 — instead of
decorating L2's `judge_excluded` after the fact.

**Done when.** `create --statement "THE SYSTEM SHALL respond quickly."` warns;
a response with "not" denies; judge-routed clauses surface at authoring, not
at L2.

#### R-03 · Assurance levels as negotiated contract terms (SLSA, reshaped)

**Source.** SLSA's provenance *levels*: a shared vocabulary of graduated
assurance that consumers *require* and producers *claim*, so verification
strength is a negotiable, declared term rather than an implementation accident.

**Today.** Milestone deferral exists (`meta.target_milestone`, `gates/l2.py:42`)
and the check pipeline pins `tier: "fast"` (`cli/main.py:125`) — but tier and
mutation depth are runner settings, not contract terms. The negotiation SM has
nothing to say about how hard the gate will hit.

**Proposal.** Contract manifest gains `assurance: {default: "L2-fast",
clauses: {ALIAS: "L2-mutation"}}`. The gate reads required level per clause;
the producer can see and push back on it during negotiation (the negotiation
SM gets a typed objection: "assurance too expensive for clause X"). Surviving
mutants → contract-fault attribution already exists, which is the natural L2+
semantics.

**Done when.** A contract demanding `L2-mutation` on a safety-critical clause
makes `check` run the mutmut runner for it; negotiation can reject the level
as a typed, clause-IDed objection.

### Wave 2 — core hardening

#### R-04 · Unsafe-variable analysis in the predicate DSL (Rego)

**Source.** Rego's compiler safety rule: every variable must be bound by a
positive term in the rule body; an unbound reference is a *compile-time* error
("var x is unsafe"), never a runtime surprise. This is what makes OPA policies
safe to evaluate against arbitrary input.

**Today.** `compile_predicate` (`dsl/predicate.py:283`) validates the
*generated Python's syntax* (`predicate.py:302`) — not its names. A binder-less
reference compiles fine: `forall x: score > 0` →
`all_(['x'], lambda x: (score > 0))`, then NameError deep inside `all_` at gate
time, far from the authoring moment. `predicate_symbols` (`oracle.py:46`)
catches missing *oracle implementations*, but a free *variable* is invisible to
everything until execution.

**Proposal.** Scope-aware binding check during parsing: track bound names per
quantifier level (binder groups, set-builder variables) and each referenced
name's position; a reference that is neither bound nor resolvable to a
declared oracle symbol is a typed `ParseError` — "name `score` is not bound by
any `forall`/`exists`" with the caret treatment the lexer already produces
(`predicate.py:65`). Keep `compile()` as the final backstop, not the only check.

**Done when.** The typo'd predicate fails at authoring with a scoped message;
all golden fixtures still compile (no false positives — nested quantifiers and
`not` scoping are the hard part and need their own tests).

#### R-05 · Consumer-side verify-policy over attestation payloads (cosign policy-controller)

**Source.** Sigstore's policy-controller: admission-time verification where the
*consumer* declares matchers and constraints over attestation *contents*
(identity, predicate fields) and the artifact is rejected unless its
attestations satisfy them. This is where OPA and Sigstore converge: policy
evaluation *over attestation data*.

**Today.** `verify_attestation` (`dsse.py:258`) checks signature and subject
digests; predicate fields — coverage, `model_dependent`, `judge_excluded`,
`deferred` (`dsse.py:105`) — are carried but never acted on. The trust decision
is hard-coded in Python.

**Proposal.** A small, schema-checked verify-policy document (JSON,
content-addressed, referenced from contract meta):
`{min_deterministic_coverage, deny_if_model_dependent, judge_excluded_allowed_domains,
max_age_days, allowed_predicate_types}`. `traceagent verify --policy p.json`
evaluates payload fields → accept/deny with named, clause-level reasons.
Deliberately **not** Rego (see §3): six fields of fixed vocabulary beat an
embedded evaluator when the authors are LLMs and the moat is the pipeline, not
the policy engine.

**Done when.** An attestation with `model_dependent = true` is denied under a
policy forbidding it, with the reason naming the predicate field — and the same
attestation passes under a laxer policy.

#### R-06 · EARS type taxonomy → verification routing (EARS × Hypothesis)

**Source.** EARS's six-pattern taxonomy (Mavin & Wilkinson): UBIQUITOUS /
EVENT-driven (WHEN) / STATE-driven (WHILE) / UNWANTED behaviour (IF) /
OPTIONAL feature (WHERE) / COMPLEXITY. Each pattern has a known *testing
shape*. Hypothesis has exactly matching machinery: `RuleBasedStateMachine` for
state-driven clauses, boundary/fuzz-biased generation for unwanted-condition
handling, plain invariants for ubiquitous ones.

**Today.** The parser records the type (`ears.py:108`) and nothing consumes it
— a repo-wide grep shows the only reference is the definition. All property
clauses get the same binder→strategy mapping (`dsl/strategies.py`), so a
WHILE clause and a UBIQUITOUS clause are tested identically.

**Proposal.** Type-driven codegen policy in the property generator:
- `UBIQUITOUS` → invariant property (current behavior).
- `WHEN` → implication-shaped property: generator biased toward the trigger
  region *and* its complement (both branches of the guard).
- `WHILE` → `RuleBasedStateMachine` scaffold over the state variables.
- `IF` (unwanted) → negative/boundary-weighted strategies; also the natural
  home for mutant-survivor triage (a surviving mutant in a fault branch *is*
  an untested IF clause — `gates/survivors.py` can cite the clause).
- `WHERE` → paired runs with the feature present/absent.

**Done when.** Golden fixtures show a WHILE clause generating a stateful
scaffold and an IF clause generating trigger-region-negative cases; strategy
doc updated (the ordering constraints in `strategies.py` stay intact — this
layers *above* binder conventions, not inside them).

#### R-07 · Gate fingerprint + verification-summary attestations (OPA decision logs ∩ SLSA VSA)

**Source.** Two mechanisms, one lesson: OPA decision logs record *which policy
version* produced each decision (the evaluator is part of the evidence), and
SLSA's Verification Summary Attestation (VSA) lets a verifier publish "I
checked artifact X against policy P at time T, result R" so downstream
consumers don't re-verify.

**Today.** The ledger records *events* but nothing attests *which gate code*
produced a verdict; gates, oracle modules, and strategy conventions are
unversioned relative to the manifest (`dsse.py:113` carries model strings only).
And there is no "verified once, trusted downstream" artifact — every consumer
re-runs the gates.

**Proposal.** Two pieces:
1. **Gate fingerprint**: content hash of gates + oracle + strategies +
   `DSL_VERSION` (+ git rev) computed at check time, into the gate log and the
   TraceManifest predicate. A re-run of an old repro pinpoints gate drift as
   the cause of a verdict change.
2. **VerificationSummary/v1**: `traceagent verify --summary out.json` emits a
   second, signed predicate type `{subject, policy_ref, result, checked_at,
   gate_fingerprint}`. This is the artifact that makes subagent fan-out
   auditable: an orchestrator accepts a subagent's deliverable on the strength
   of a summary attestation, and R-05's policy says when a summary suffices.

**Done when.** Manifest payload carries the gate fingerprint; a downstream
`verify --policy` accepts on a summary attestation without executing gates.

#### R-08 · Hash-chained ledger → Merkle heads with inclusion proofs (Rekor, serverless)

**Source.** Rekor's actual lesson is not the service — it is *tamper evidence
for the evidence*: an append-only log, signed tree heads, and inclusion proofs
that make both rewriting history and silently dropping an entry detectable.

**Today.** `RunLedger` is plain JSONL — mutable in place; re-runs overwrite;
nothing proves a rejection ever existed. For a system whose pitch is
"auditable acceptance", the acceptance history is currently unauthenticated.

**Proposal, staged.**
- *Stage 1 (effort 2)*: each ledger event carries `prev_hash`; periodic signed
  heads (signers already exist). Flipping one historical event breaks the
  chain; `repro` validates the chain before replaying.
- *Stage 2 (effort 3)*: Merkle-ize per run; each attestation carries an
  inclusion proof against the run's signed head; heads are committed to git
  (D5 git-native — no Rekor/Trillian dependency; see §3).

**Done when.** Stage 1: editing a past event in place is detected by head
recomputation. Stage 2: `verify` checks an attestation's inclusion proof
against a head it trusts.

### Wave 3 — strategic (who can be trusted at all)

#### R-09 · Trust root: pinned keys, thresholds, rotation, freshness (Sigstore trust root / TUF)

**Source.** Sigstore's verification model: consumers pin a versioned,
self-signed *trusted root* (keys, identities, thresholds, rotation), verify
against it — never against ad-hoc keys — and enforce *freshness* (signed
timestamps + max age). DSSE natively supports signature thresholds.

**Today.** One dev key; `verify_attestation` requires the verifier to *supply*
a key with no provenance (`dsse.py:267`), threshold hard-coded to 1
(`dsse.py:281`), no expiry, no rotation story. "Which producer keys do I accept
for domain X?" has no artifact — which blocks the multiagent story it exists
for.

**Proposal.** `.traceagent/trust/root.json`:
`{version, keys: [{keyid, public_key, owner, domains}], thresholds: {default,
per-milestone}, max_age_days}`, self-signed over canonical form (JCS already
exists). `verify` resolves keys *only* from the root; attestations carry a
timestamp the verifier checks for age (with documented clock-skew caveats and
git commit time as a secondary witness). Threshold 2 for high-stakes
milestones becomes a root setting, and DSSE already handles the crypto.

**Done when.** Rotation test: old key rejected after a root bump; a
threshold-2 milestone rejects a single-signed manifest; a stale attestation
fails freshness.

#### R-10 · Pure gate evaluation interface + decision replay (OPA `input`/`data`)

**Source.** OPA's `input`/`data` separation makes policy evaluation a pure
function of (input document, data, policy version): decisions are replayable
and cacheable, and the decision log is trustworthy *because* the function is
total over declared inputs.

**Today.** The right pattern exists in exactly one gate: L1's digest-keyed
verdict cache (`l1.py:28`). L0/L2 recompute every run, and nothing *declares*
each gate's input set — purity is accidental, not contractual.

**Proposal.** One declaration site per gate: `{store_hash, contract_meta_hash,
bindings_hash, gate_fingerprint}` → cache key. All gates use it. `repro` gains
*decision replay*: re-evaluate from recorded input digests and diff the verdict
against the ledger — the OPA decision-log replay loop, which is also the
regression test for the gates themselves (complements the mutmut campaigns).

**Done when.** `check` on an unchanged store serves L0/L2 verdicts from cache;
replaying a historical run reproduces its verdicts byte-identically or names
the drift (gate fingerprint vs input digests).

#### R-11 · EARS ⇒ predicate unification (formal-EARS semantics)

**Source.** EARS has a latent formal semantics its tooling exploits: every
triggered statement is an implication (`trigger ⇒ obligation`), state-driven
adds a hold-condition, unwanted adds a negated guard. Formal-EARS variants
compile statements to guarded commands. traceagent owns both ends — a natural-
language surface (`dsl/ears.py`) and a formal core (`dsl/predicate.py`) — but
they don't talk.

**Today.** `invariant.statement` (prose) and `invariant.property` (DSL) are
authored as *independent* fields (`spec/schema.py:28-30`). Nothing checks the
property formalizes *that* statement: an LLM (or human) can write a correct
property for a different requirement and every gate stays green. This is the
quietest integrity hole in the pipeline.

**Proposal.** Template-bound derivation: `parse_statement`'s structured output
`{type, trigger, response}` seeds the property skeleton — a WHEN-clause
property must have the shape `trigger_pred => response_pred` (the `=>`
compile already exists, `predicate.py:164`); the author fills the two slots.
New optional clause field `derivation: {from_statement: true, slots: {...}}`;
L0 checks slot presence when the field is set. Opt-in first, golden-tested,
never retrofitted onto the existing 26-clause corpus by force.

**Done when.** An invariant whose property ignores its trigger is denied at L0
as "property does not formalize the statement trigger", while legacy clauses
without `derivation` pass unchanged.

#### R-12 · Per-agent signing identities, rotation-ready (Fulcio keyless, adapted)

**Source.** Fulcio keyless signing: short-lived certificates binding a
*verified identity* to a key, verified by identity *matchers* rather than key
pinning. With no OIDC fabric for agents, the transferable part is the
decomposition: identity claims travel with signatures, are verified by policy
(R-05), and keys are issued/rotated by an authority (R-09) — consumers pin the
root, never a key.

**Today.** One dev key; `producer_model`/`gate_model` are free-text strings in
the predicate (`dsse.py:113`). `model_dependent` — the flag that says "the
producer graded its own homework" — is an honor-system claim: nothing binds it
to a key, so a spoofed attestation asserts whatever it likes.

**Proposal.** Per-agent keypairs registered in the trust root with identity
`{role, model, org}`; `attest` asserts identity claims; R-05's policy matches
claims (cosign-style matchers). `model_dependent` becomes *verifiable*: the
claim "signed by gate identity G" either checks against the root or the
attestation is denied. True keyless/OIDC is deferred until an agent-identity
ecosystem exists (§3, non-goal) — the key layout should not preclude it.

**Done when.** An attestation claiming `gate = gate-dev` without the gate
key's signature fails policy, with the failing matcher named.

## 3. Anti-steals — what to deliberately *not* take

| Temptation | Why not | Revisit when |
|---|---|---|
| **Rego as a dependency** (embed OPA/rego-python for gate or verify policy) | Violates the "write the DSL from scratch — that stack is our product" call (`scaffold-search-findings.md`); unbounded evaluation is the wrong surface for LLM-authored policy; R-05's whole vocabulary is ~6 fields | Never, unless consumers demand arbitrary user policy over third-party attestations |
| **OPA bundles / REST services / decision-stream infra** | No server in the architecture; D5 is git-native; distribution = git | If a hosted registry layer (chainloop-class) is ever adopted |
| **Full Rekor / Trillian / witness quorum** | Server weight without a multi-party threat model yet; R-08's hash chain + signed heads in git delivers the tamper-evidence property | When attestations are exchanged between organizations that don't share a git history |
| **Fulcio keyless / OIDC** | No agent-identity ecosystem to federate with; ephemeral certs solve a PKI problem agents don't have yet | When a credible "OIDC for agents" exists; R-12's layout is the on-ramp |
| **SLSA build-platform provenance levels verbatim** | traceagent doesn't run build platforms; the ladder's *shape* (negotiable graduated assurance) is the transferable part → R-03 | If deliverables start including built/released artifacts |
| **EARS-CTRL / mode-machine extensions** | YAGNI until a corpus demands mode systems; the six-pattern taxonomy (R-06) carries the value | First corpus with mode-based requirements |
| **OCI referrers / Sigstore protobuf packaging** | Git-native store suffices; a second packaging format is pure overhead | When attestations must be discoverable via OCI registries |

## 4. Synergies with the existing next-steps (CONTEXT.md §8)

- **TR-IMPACT-QUERY**: R-04's binder analysis + existing `predicate_symbols`
  (`oracle.py:46`) give the symbol→clauses index for free; the OPA
  data-dependency idea is the query shape ("what breaks if oracle term X
  changes").
- **ATT-EXTERNAL-IMPORT (ReqIF)**: imported prose runs the R-02 ambiguity lint;
  EARS type taxonomy (R-06) survives import as the routing hint.
- **LLM-in-the-loop negotiation**: R-05 + R-09 are what make machine
  negotiation safe — a consumer can accept a producer's attestation
  mechanically mid-handshake instead of re-running gates (R-07 summaries).
- **Real-corpus threshold calibration**: R-02's warn rates and R-03's level
  assignments are exactly the data to calibrate.

## 5. Suggested execution order

Wave 1 (R-01 → R-02 → R-03) needs no new dependencies and touches only
`spec/`, `gates/l0.py`, and the manifest schema — each is a single checkpoint
in the C-41+ range. Wave 2 starts with R-04 (pure function, golden-tested,
zero schema impact), then R-05 → R-07 (policy consumes existing payload
fields), R-06 and R-08 stage 1 in either order. Wave 3 is ordered by
dependency: R-09 (trust root) unblocks R-12 (identities); R-10 and R-11 are
independent and can interleave anywhere after Wave 2.

The one item to pull *forward* if anything is R-04: it converts the predicate
DSL's only deferred failure class (free variables, NameError at gate time)
into an authoring-time typed error, which is the same "fail gracefully at the
authoring moment" bar the EARS and predicate parsers already meet.
