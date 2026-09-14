# ZFT (Zero-Friction Traceability)

Contract-grounded verification for multi-agent work.

## What ZFT is

ZFT is a contract-first traceability and verification layer for multiagent
software development. Instead of accepting handoffs on vibes, agents exchange
structured artifacts:

1. **A contract** — a versioned, clause-IDed set of obligations agreed between
   producer and consumer *before* validation. Each **clause** is one atomic,
   individually verifiable statement ("the export endpoint rejects payloads
   greater than 10 MB with a 413 status").
2. **A deliverable** — the work product, composed of **elements** (a function,
   a section, a test case, a claim).
3. **A trace manifest** — a deterministic, bi-directional mapping showing which
   deliverable element fulfills which contract clause, with machine-checked
   evidence (test run, type check, hash) attached to each link.

Both directions of coverage are load-bearing: every clause must be covered by
at least one element (no missed requirements), and every element must be
justified by at least one clause (no scope creep or hallucinated work).
LLM judgment is quarantined — it may only adjudicate clauses explicitly
declared subjective at authoring time, and it is excluded from deterministic
coverage claims.

ZFT is the product and repository name (decision 2026-09-13, supersedes the 2026-09-12 note that kept `traceagent` canonical). The Python import package remains `traceagent`, and a deprecated `traceagent` console alias is installed for continuity; dated logs and the paper retain the research codename.

## The L0–L3 verification gate

`zft gate` enforces four sequential tiers:

- **L0 · Static integrity** — schema validity, clause content hashes,
  duplicate-clause detection across the `.zft/specs/` store.
- **L1 · Local verification** — executable property suites (code-generated
  from clause invariants, with a Gherkin fallback renderer) executed per
  clause.
- **L2 · Merge gate** — sandboxed mutation testing plus full bi-directional
  coverage. Failures are *attributed*: surviving mutants indicate a contract
  fault (back to the spec agent); a valid clause failing indicates an
  implementation fault (back to the producer, bounded retries).
- **L3 · Signed attestation** — DSSE-enveloped attestation over the clause
  subjects, verifiable against the live store.

## Install

```bash
pip install zft
```

(A deprecated `traceagent` console alias is installed too, command-for-command
identical to `zft`; it exists for continuity with the pre-rename history.)

Requires Python 3.12+.

## Quickstart

All commands take an optional trailing `[root]` (defaults to the current
directory) and exit non-zero on gate failure.

```bash
# L0: lint every clause node in .zft/specs/ (schema, hashes, duplicates)
zft lint [root]

# Scaffold a new DRAFT clause node
zft create --alias EXPORT-413 --domain protocol \
  --title "Export size limit" \
  --statement "The export endpoint rejects payloads > 10 MB with 413" \
  --property "size > 10MB -> status == 413" --kind test

# Fast verification stage: L0 + L2-fast + Gherkin fallback, JSON report
zft check [root]

# L2 merge gate: sandboxed mutation-testing campaign over a module + its tests
zft gate --module src/exports/exporter.py --tests tests/test_exporter.py \
  [--scope f1,f2] [--oracle path/to/oracle.py] [--conftest path/to/conftest.py] \
  [--sandbox .zft/sandbox] [--resume] [root]

# L3: produce a DSSE attestation over the clause subjects
zft attest [root]
# Verify the attestation against the live store (re-derives clause digests)
zft verify [root]

# Export the attestation / trace matrix (e.g. --format matrix)
zft export --format matrix [root]

# Replay a recorded run from .zft/runs by run id
zft repro <run_id> [root]

# Run the contract negotiation state machine (CFP -> counter -> accept -> validate)
zft negotiate [root]

# Lineage: mechanically extract element -> clause bindings (JSON)
zft extract [root]
# Impact query: which clauses are affected by changed path[:symbol]
zft impact src/exports/exporter.py:handle_export

# Pre/post subagent task gates
zft task-gate before --subagent producer --description "implement export endpoint"
zft task-gate after  --subagent producer --description "implement export endpoint"
```

## Repository layout

```
.zft/
  specs/          # Clause nodes, one JSON file per domain/<alias>.json.
                  # UUIDv7 node identity + SHA-256 content integrity hash.
  contracts/      # Contract versions binding clause sets to milestones.
.traceagent/  # Generated runtime artifacts (run ledgers, sandboxes,
                  # gherkin renders, attestation envelopes) — local only,
                  # never committed.
designs/          # Architecture decision records and implementation plans.
```

The seed contract (26 validated clause nodes) lives in
[`.zft/specs/`](.zft/specs/) and is the working dogfood example for every
gate tier above.

## Design

Full architecture, decision records (D1–D6), and the verification pipeline
specification live in [`designs/ARCHITECTURE.md`](designs/ARCHITECTURE.md).

## License

Apache-2.0 — see [LICENSE](LICENSE).

---

## Enterprise (proprietary) features

ReqIF certification export/import and enterprise ALM connectors (store sync,
DOORS / Polarion integrations) are commercial, **proprietary** add-ons — they
are not part of the open-source `zft` package.

For enterprise ALM connectors, compliance export pipelines, or bespoke
integration engineering, contact **contact@keyrie.eu**.
