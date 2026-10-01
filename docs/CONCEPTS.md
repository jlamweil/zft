# ZFT concepts — the one-page mental model

What flows between agents is three artifacts: a **contract**, a
**deliverable**, and a **trace manifest**. Everything else is transport.
This page defines each concept in one paragraph, threads them through one
worked example, and ends with the glossary. Wording follows
[`designs/ARCHITECTURE.md`](../designs/ARCHITECTURE.md) (decision records
D1–D6); for agent-facing usage rules the zft-gates skill
([`.opencode/skills/zft/SKILL.md`](../.opencode/skills/zft/SKILL.md)) is
authoritative.

## Contract

A versioned set of clauses agreed between producer and consumer *before*
validation begins (D6: negotiation precedes work). Contracts live under
`.zft/contracts/<name>.json` as a `clause_ids` list with a status and
version; work is only gated against a VALIDATED contract. No contract, no
validation — acceptance runs against the artifact the parties agreed on,
not against anyone's recollection of a prompt.

## Clause

One atomic, individually verifiable obligation — the unit of acceptance
("the export endpoint rejects payloads > 10 MB with a 413 status"). A clause
carries at least one invariant (a statement plus a machine-checkable
property) and a `check` kind — `property`, `type`, `test`, `judge`, or
`process` — declaring what evidence its gate may accept (D1). Clauses move
through a lifecycle: `DRAFT → PROPOSED → VALIDATED → IMPLEMENTED →
DEPRECATED`.

## Clause-ID (and the content hash)

Identity is a minted UUIDv7 `node_id`, immutable for the clause's life (D2)
— edits bump the version, they do not mint a new clause. Alongside it, a
SHA-256 `content_hash` is the integrity field: it covers *meaning* (domain,
title, invariants) and deliberately excludes revision state (version,
status, external links), so "did the meaning change" and "which revision is
this" stay separate questions. The hash is re-verified at every L0 gate,
and its index is how exact duplicates are caught. Never hand-edit it.

## Alias

The clause's mutable human handle, uppercase `[A-Z0-9-]+`: `EXPORT-413`,
not a UUID. Aliases are unique across the `.zft/specs/` store, and it is
aliases that tests, task descriptions, and prose refer to. Renaming an
alias changes what the clause is *called*; the node-id underneath — which
clause it *is* — does not move.

## @trace marker

The binding seam. A comment on the line directly above the test or function
that exercises the clause links that element to it:

```python
# @trace("EXPORT-413")
def test_oversize_payload_rejected_413(): ...
```

(`// @trace("...")` in other languages.) The marker is an explicit link
record, not an inference from names (D3) — and it cuts both ways: code that
loses its marker (or never had one) silently drops its binding, which is
exactly what the coverage gate exists to catch.

## Extraction

`zft extract` reads the markers mechanically and prints the element →
clause binding list as JSON — precisely what the gates will count, with no
judgment pass in between. Coverage is checked in **both** directions and
both are load-bearing: every due clause needs ≥ 1 binding (no missed
requirements), and every deliverable element needs ≥ 1 justifying clause
(no scope creep, no hallucinated work).

## The gate tiers (L0–L3)

Cheap and always-on first, deep at the acceptance boundary (D4):

| Tier | When | What it checks | Cost |
| --- | --- | --- | --- |
| **L0 · static integrity** | every write | schema validity, content-hash verification, duplicate/alias detection (`zft lint`) | ms |
| **L1 · local verification** | producer's inner loop | bound suites execute for clauses declaring executable evidence; `zft check` = L0 + coverage + L1 + L2-fast, JSON report | seconds |
| **L2 · merge gate** | acceptance/merge | sandboxed mutation campaign over module + tests, full bi-directional coverage (`zft gate`) | 5–15 s+ |
| **L3 · attestation** | post-acceptance | DSSE-signed manifest binding clause hashes + tree hash + gate results (`zft attest` / `zft verify`) | ms |

L2 failures are *attributed*, not just red: surviving mutants mean the
**contract** is under-specified (back to the spec author); a valid clause
failing means the **implementation** is at fault (back to the producer,
bounded retries). LLM judgment is quarantined, not banned — it may
adjudicate only clauses declared `kind: judge` at authoring, and it is
excluded from deterministic coverage claims.

## Run ledger

Every verification run is recorded under `.zft/runs/<run_id>/` — what
executed, against which store state, with what outcome. `zft repro
<run_id>` re-executes a recorded run's failed units. The ledger is why "the
gate was green" is a claim with receipts rather than a memory: the evidence
behind any verdict can be re-derived after the fact.

## Prereg discipline

Freeze the design of a check before you run it. Contracts are negotiated to
VALIDATED *before* implementation starts — the same discipline governs
evaluations of the gates themselves: the research program that bench-tested
zft ran its windows under a preregistered, frozen-before-execution design
and computed verdicts from the ledger, not by reshaping criteria
afterward. Prereg is the temporal half of trust: evidence exists before the
verdict that cites it.

## Worked example (one thread through every concept)

```bash
# 1. Author a clause (alias EXPORT-413, node-id + content hash minted)
zft create --alias EXPORT-413 --domain protocol \
  --title "Export size limit" \
  --statement "The export endpoint rejects payloads > 10 MB with 413" \
  --property "size > 10MB -> status == 413" --kind test

# 2. Contract: list the alias in .zft/contracts/release-1.json clause_ids

# 3. Bind the deliverable element with a @trace marker, then extract
#   (in tests/test_exporter.py, above the test:)
#     # @trace("EXPORT-413")
zft extract            # the binding list, exactly as the gates see it

# 4. Gate it: L0 integrity + coverage + bound-suite execution
zft lint && zft check

# 5. Acceptance: sandboxed mutation campaign over module + tests
zft gate --module src/exports/exporter.py --tests tests/test_exporter.py

# 6. Sign and export: DSSE attestation, then the trace matrix
zft attest && zft verify --key-in .zft/attest-key.pub.json
zft export --format matrix
```

A handoff now carries its own proof: the contract said what "done" means,
the marker said which element fills which clause, the gates said the
evidence is real, and the attestation says it in writing.

## Glossary

| Term | One-line definition |
| --- | --- |
| **Contract** | Versioned set of clauses agreed before validation; the acceptance criteria. |
| **Clause** | One atomic, individually verifiable obligation; the unit of acceptance. |
| **Clause-ID** | The clause's immutable UUIDv7 identity (D2); its content hash is the verified integrity field. |
| **Alias** | The clause's mutable human handle (`[A-Z0-9-]+`), unique in the store. |
| **Invariant** | A clause's statement plus machine-checkable property, with the `check` kinds its gate may accept. |
| **@trace marker** | The comment binding a deliverable element to a clause alias — the explicit link record. |
| **Extraction** | Mechanical read of the markers (`zft extract`): the bindings exactly as the gates count them. |
| **Coverage** | Bi-directional: clauses covered by elements *and* elements justified by clauses — both must be complete. |
| **Gate** | Any checkpoint accepting/rejecting on contract-grounded mechanical evidence only (tiers L0–L3). |
| **Fault attribution** | Surviving mutants ⇒ contract fault (spec author); valid clause failing ⇒ implementation fault (producer). |
| **Trace manifest** | The complete clause ↔ element graph with evidence and coverage — the acceptance payload. |
| **Attestation** | The DSSE-signed manifest binding clause hashes, tree hash, and gate results; export requires it. |
| **Run ledger** | The `.zft/runs/<run_id>/` record of every verification run; `zft repro` replays its failures. |
| **Producer / Consumer** | The agent obligated to fill the contract and the one entitled to validate against it — roles, not identities. |
