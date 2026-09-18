# Runbook — zft v0

Operational guide for the implemented gates (plan C-37). All commands run from the repo root.

## Daily loop (CI runs the same thing)

```bash
pip install -e .[dev]
zft lint            # L0: schema + §5.2 hashes + alias/duplicate detection
zft check .         # L0 → coverage (milestone-scoped) → L1 property evidence
zft negotiate       # CFP → counter → validate (ledger-recorded)
zft attest          # sign TraceManifest (writes .zft/attest.json + dev key)
zft export          # trace matrix — refuses without attestation
```

Exit codes: `0` green, `1` typed rejection (JSON printed), `2` usage error.

## Wiring the gate into CI and pre-commit (adoption recipe)

CI: run the daily loop's first two commands on every push — `zft lint`
+ `zft check .` (5-minute budget per kill criterion K-CI-1; measured
~3.4 s on the 26-clause seed corpus).
A red clause fails the build with a typed JSON rejection naming the clause node
(exit-code contract pinned in `tests/unit/test_check_cli.py`).

Pre-commit: consumers add this repo to `.pre-commit-config.yaml` —
`traceagent-lint` at pre-commit weight (L0 only),
`traceagent-check` at pre-push weight. **Seed policy:** both hooks trigger only
on `.zft/` (the contract corpus). A repo that has not seeded a contract never
pays gate latency, and an unseeded store fails closed — `STORE_MISSING` is a
typed deny (exit 1), never green-vacuous.

## Batch-driver gate (per-task, read-only)

The ZCode batch driver can gate every model send against the workspace it is
about to touch (`{folder}` is substituted by the driver):

```bash
--gate-cmd './gates/driver-gate.sh {folder}' --gate-hook shadow    # verdicts logged only
--gate-cmd './gates/driver-gate.sh {folder}' --gate-hook enforce   # red blocks the send
```

- Contract: exit 0 pass, nonzero reject; output is one bounded JSON line sized
  for the driver's ~2000-char sink; the driver kills at 120 s, so the script
  self-limits to a 100 s budget (`DRIVER_GATE_BUDGET_S`) and rejects on
  overrun — the driver-side kill/transport path would fail open, the gate
  itself fails closed (unseeded store = typed deny, never green-vacuous).
- Stages: EARS conformance (`dsl.ears` over every clause statement) + the fast
  L0-L3 subset (L0 integrity, L2-fast coverage, L1 executed evidence, L3
  projection). The mutation campaign stays a merge-gate concern.
- Strictly read-only over `{folder}`: no ledger, no verdict-cache writes, no
  gherkin render, no bytecode; hypothesis's example DB goes to a self-removing
  temp dir. A byte-identical workspace after a green run is pinned in
  `tests/unit/test_driver_gate.py`. Verdict logging is the driver's job.
- Same verdict without the driver: `zft driver-gate <folder>`
  (or `python -m traceagent.gates.driver_gate <folder>`).

### Pre-send seam for a batcher's send path

`gates/send-gate.sh <folder>` is the hook a batcher calls immediately before
every model send — the executable form of the flags above, as env vars so any
shell or subprocess dispatcher can set them:

```bash
TRACEAGENT_GATE_CMD='./gates/driver-gate.sh {folder}' \
TRACEAGENT_GATE_HOOK=shadow \
gates/send-gate.sh "$REPO_DIR" || exit 1
```

- `off` (default) is a full no-op — **rollback is that one flag**: no gate
  run, no log write, exit 0, nothing else changes. Proven by a rollback
  rehearsal on a scratch session.
- `shadow` appends one JSONL verdict per send — `allow`, `would-block`, or
  `gate-unavailable` — to `TRACEAGENT_SEND_GATE_LOG`
  (default `<folder>/.traceagent/send-gate/log.jsonl`) and **always exits 0**:
  shadow logs would-blocks, it never blocks a send.
- `enforce` blocks only a gate red (exit 1). A gate that cannot answer —
  template without `{folder}`, missing binary, budget kill at
  `TRACEAGENT_SEND_GATE_TIMEOUT` (default 120 s) — is a transport error and
  fails OPEN like the documented driver contract, loudly logged for triage.
- Rehearsed on a scratch session against pre-registered human expectations:
  6/6 agreement, shadow blocked nothing. Do not flip live lanes to `enforce`
  without a human call at triage reading the rehearsal evidence first.
## What `check` does and does not verify

A green `zft check .` proves **traceability, not conformance**:

- **Does prove:** L0 integrity (schema + content hashes, alias/duplicate detection), forward coverage (every **due** clause has ≥ 1 binding), gherkin render/collect, and bound‑suite execution for `kind: property` clauses.
- **Does not prove:** that the implementation satisfies the clause's declared `property` — the property string is never compiled or executed, and `kind: test` clauses (the default) get no execution evidence at all. Correctness requires executing the clause's semantics (property/oracle). See [`docs/KNOWN-GAPS.md`](KNOWN-GAPS.md) (Gap 001).

## Dispatch gate (`task-gate`)

The `task-gate` commands enforce contract‑binding at the subagent‑dispatch boundary.

- **Commands**
  - `zft task-gate before --subagent <type> --description <text>` – runs before a subagent is spawned.
    - Exit 0: dispatch allowed (recorded).
    - Exit 1: policy rejection (blocked).
    - Exit 2 or other: internal/usage error – the plugin fails open (dispatch proceeds). Emits a JSON object on stdout.
  - `zft task-gate after --subagent <type> --description <text>` – runs after the subagent finishes, prepending a coverage verdict to the tool output.

- **Audit log** – each decision appends a JSONL line to `<repo>/.zft/audit.log` (timestamp, subagent, lane, phase, verdict, etc.).

- **Markers & overrides**
  - Writer lanes must include `[contract: <name>]` in the task description; the name resolves to `.zft/contracts/<name>.json`.
  - Read‑only lanes (`explorer`, `explore`, `code‑explorer`, `librarian`, `oracle`, `analyst`, `councillor`, `vision`, `vision‑consultant`, `researcher`) are exempt.
  - Override with `[ungated: <reason>]` or `TRACEAGENT_ALLOW_UNGATED=1`; logged as `override: true`.
  - Kill switches: `TRACEAGENT_GATE_DISABLED=1` (disable gate) and `OPENCODE_PURE=1` (disable all plugins).

- **Scope** – this is **traceability** enforcement only; it does **not** verify that the subagent’s output satisfies the contract (see [`docs/KNOWN-GAPS.md`](KNOWN-GAPS.md), Gap 001).

## Mutation campaigns (L2)

```bash
python -m zft.cli.main gate-campaign \
    --module src/traceagent/spec/canon.py \
    --tests tests/unit/test_canon.py \
    --scope canonical_hash,canonical_payload
```

- One mutant per operator/constant per line; comments skipped; syntax-invalid mutants dropped.
- Scope = predicate-referenced functions: out-of-scope survivors are `other-clause`, not failures.
- Survivor taxonomy in verdict: `refinement-signal` (in-scope, survived → route to consumer), `other-clause`, `equivalent-suspect` (excluded from kill-rate denominators).

## Checkpoint / resume

- Campaign verdicts checkpoint per mutant to `.zft/cache/mutants.json`.
- Resume after crash: re-run the same `gate-campaign` command (same inputs ⇒ same cache key); executed mutants skip.
- Cache invalidation is automatic: any change to module, tests, oracle, or seed changes the digest key.

### Negotiation resumption (kill-9 proof)

Every `negotiate` transition is flushed to its run ledger as it happens, so a
killed process leaves a durable protocol prefix; the next plain invocation
finds the unfinished run, replays it through the state machine (typed
`IllegalTransition` on any forged/torn history), and finishes the same run.

```bash
# deterministic kill -9 mid-negotiation (demo seam; the kill is a real SIGKILL):
TRACEAGENT_NEGOTIATE_KILL_AFTER=counter zft negotiate .
zft negotiate .        # → "resuming negotiation run <id> from COUNTERED"
```

Terminal runs (`validated`/`refuse` in the ledger) are never resumed; a torn
tail line is truncated and the recovery ledgered as `resumed_torn_tail`.
Pinned end-to-end in `tests/e2e/test_negotiate_resumption.py`.

## Debuggability

```bash
TRACEAGENT_LOG=debug zft check .      # per-decision logging
zft repro <run_id>                     # re-execute only failed units
TRACEAGENT_KEEP_SANDBOX=1 ...                 # retain gate sandbox for autopsy
```

- Run ledgers: `.zft/runs/<run_id>/` — `manifest.json` (git commit, dirty, seeds, tool versions) + `events.jsonl` (fsync every 50 events; torn tail lines ignored on load).
- Every failure is a typed rejection: `{code, clause_ids, fault, expected, actual, evidence_refs, repro}`.

## Mutating source under a due clause (for maintainers)

1. Create/extend a test in `tests/unit/` exercising the behavior.
2. Bind it with a `# @trace("ALIAS")` comment directly above the test.
3. `zft check .` — the clause stays covered or CI goes red.

Deferred clauses (`target_milestone` = v0.1: TR-IMPACT-QUERY, ATT-EXTERNAL-IMPORT) are listed in the attestation under `deferred` and do not block CI.
