# Changelog

## Unreleased

- **The gate's `--conftest` seam actually carries now.** `prepare_sandbox`
  copied the consumer conftest into the sandbox and then unconditionally
  overwrote it with the generated isolation conftest, so the documented
  `[--conftest path/to/conftest.py]` recovery seam could never deliver the
  `sys.path` setup it is named for — the sandboxed baseline died at collection
  (ModuleNotFoundError) and the verdict reported `ok:false` behind fake kill
  counts. A conftest arriving via `also_copy` is now preserved byte-exact as
  `conftest_consumer.py` and executed by the generated conftest *after* the
  isolation preamble (env scrub, cwd, sandbox-first `sys.path`), so consumer
  path setup and hooks apply while the mirrored module keeps shadowing
  whatever the consumer's own setup puts first on the path.

## 0.2.0a8 — 2026-09-28

Supersedes the unpublished a7 cut of the same day: everything it carried —
the D1–D6 quickstart dead ends fixed, gate-baseline surfacing, and
capability-based classification (the a7 section below) — ships in this
build, so PyPI consumers still installing a6 need only a8.

- **The dispatch gate finds `zft` where it used to fail.** Resolution now
  falls through project `.venv` → PATH → `~/.local/bin` (uv tool / pipx /
  `pip --user`) → a `python -m zft.cli.main` module invocation, and every
  candidate must *run*: a stale `.venv` entry point that only prints a
  `ModuleNotFoundError` traceback is skipped instead of failing the gate on
  every dispatch. Fixes the reported
  `[zft gate] internal error … Executable not found in $PATH: "zft"`
  (project with no `.venv`, `zft` installed user-wide) and the stale-.venv
  class behind `GATE_UNAVAILABLE` / fail-closed lint edits — the same
  runnability probe now guards the lint gate too.
- **The after-gate now counts only what the subagent changed.** Coverage in
  `zft task-gate after` can be scoped to the dispatch's changeset —
  `--changed <path>` (repeatable), `--since-ref <git-ish>`, or
  `--scope changeset` — and the opencode plugin fills those flags
  automatically from the child session's completed `edit`/`write` calls.
  A changeset verdict covers only the clauses bound inside those paths, so
  one subagent's gate can no longer ride on coverage produced by another
  (or on the tree before it ran); an unresolvable ref is an **error
  verdict** (exit 2), never an unscoped pass, and an empty changeset reports
  every due clause missing. Defaults are unchanged — without a scoping flag
  the verdict stays tree-wide. New clause `ENF-CHANGESET-VERDICT` pins the
  semantics; every payload/audit record carries its `scope`. The plugin
  degrades one rung at a time (child sessions → `--since-ref <dispatch
  HEAD>` → tree mode) and never blocks the report or fabricates a scope.

## 0.2.0a7 — 2026-09-27

The consumer-first-readability release: everything a fresh `pip install zft`
consumer touches between install and a signed attestation was probed with the
PyPI wheel on a clean venv, the six documented-path dead ends it found are
fixed, and the gate now tells the truth about its own sandbox. This is the cut
that closes the ship-gap — the published 0.2.0a6 artifacts still teach the
pre-fix quickstart in their METADATA, so every consumer installing from PyPI
today hits D1–D6 below; a7 is the first cut whose shipped README (and wheel
METADATA) matches the verified-working path.

- **The README quickstart now survives first contact.** A clean-venv probe
  executed it verbatim against the PyPI wheel (0.2.0a6, CPython 3.12.13,
  cold install 10 s, zero warnings — packaging itself defect-free) and
  dead-ended at six named points, each fixed in this release:
  - **D1 — lint ran before the store existed.** `zft lint` first on a fresh
    directory exits 1 by design (`no clause store found`); the documented
    path now scaffolds first (`zft create`) and names the typed refusal.
  - **D2 — the `@trace` binding idiom was documented nowhere** while
    `zft check` rejects unbound clauses with no in-README recovery; the
    `# @trace("ALIAS")` comment convention and `zft extract` are now in the
    Quickstart lead.
  - **D3 — the gate example red-baselined its own sandbox.** A module that
    exists only as a file path flattens to the sandbox root, the baseline
    dies at collection, and every mutant is fake-killed behind a bare
    `ok:false`; the importable-package requirement (`src/<pkg>/__init__.py`
    with top-package imports) is now documented with a proven-working shape.
  - **D4 — the impact example could never bind.** `zft impact` resolves
    bindings on traced test symbols; the example now targets
    `tests/test_exporter.py:<symbol>` (proven `binds: EXPORT-413`), not a
    source symbol.
  - **D5 — both task-gate examples were unrunnable as written:** no
    `[contract: …]` reference (rc 1 `ENF_WRITER_REQUIRES_CONTRACT`) and no
    stated prerequisite that `.zft/contracts/<name>.json` exists; both fixed.
  - **D6 — `zft negotiate`'s contract-manifest prerequisite was unstated;**
    it now sits on the command's comment line.
  All six are pinned by `tests/unit/test_readme_quickstart.py` (six red
  tests against the pre-fix README) plus
  `tests/e2e/test_consumer_quickstart_arc.py`, which replays the probe's
  arc end to end.
- **A red mutation baseline is no longer invisible.** `zft gate` captured
  the sandboxed baseline's own pytest verdict as `baseline_ok` in the JSON
  report and the run-ledger summary, and a red baseline prints a loud
  stderr hint naming every recovery seam (`ZFT_KEEP_SANDBOX=1` autopsy,
  `--conftest`, the `src/<pkg>/__init__.py` mirroring rule) — previously a
  baseline that could not even collect was reported as a bare `ok:false`
  with fake-looking kill counts. Open: the `--conftest` seam still cannot
  carry `sys.path` setup (the generated isolation conftest overwrites the
  consumer's; a sandbox-design decision, not yet taken).
- **Producer classification now follows capability, not the name.** The task
  gate decides who must bind a contract from what a subagent can actually do:
  when the opencode plugin can resolve its permission via `client.app.agents()`,
  an agent that can edit or run bash is a **writer** whatever it is called,
  and an agent with both catch-all denied is **exempt** whatever its name.
  The lane-name list (`researcher`, `explorer`, …) is now the *fallback* for
  dispatches the plugin cannot resolve — unknown agents still default to
  writer, so nothing silently ungates. The classification mirrors opencode's
  own `disabled()` heuristic (last matching rule wins; no rule means `ask`,
  which is still a capability) and is pinned by an executable oracle,
  `oracle_CAPABILITY-CLASSIFICATION.py`, whose ten cases are the unit tests.
  Every decision records its trace — `source`, the raw ruleset, `found` — in
  the payload and the audit log, and is replayable by hand via
  `zft task-gate before --subagent X --description "…" --capability '<json>'`
  (or `--explain` to see the classification without enforcing).
  **Behavior change** in the intended direction: a read-only-*named* agent
  with write access is now gated; a writer-named agent with everything denied
  is now exempt.

## 0.2.0a6 — 2026-09-23

Version-stamp consistency release, cut to supersede 0.2.0a5 **before either
shipped** — nothing from a5 ever reached PyPI or npm, and a5's content ships
here (its receipt, `RELEASE-0.2.0a5.json`, stays on record):

- **`zft.__version__` tells the truth again** — the in-package version had
  frozen at `0.2.0a1` across the a2–a5 cuts while the wheel METADATA moved
  on: the only test on it asserted non-emptiness, so nothing failed when the
  stamps drifted. A consumer asking the package for its version read one
  three releases older than the artifact it imported.
- **Stamps are now pinned to one source of truth** — a red-tested
  consistency check ties `zft.__version__`, `CITATION.cff`, and the npm
  `opencode-zft` version to `pyproject.toml`, so stamp drift is a failing
  test at commit time, not a release-RC finding.

## 0.2.0a5 — 2026-09-23

Colleague-readiness pass, verified by a fresh `git clone` + `pip install zft`
on two machines (HTTPS clone, no credentials, clean venv): lint reports 43
clause nodes, `zft check` exits 0 against the shipped baseline, and
attest + verify are green against the clone's own store.

- **README accuracy** — the seed contract is 43 validated clause nodes, not
  26 (the count now cites `zft lint` as the source of truth so it does not
  drift silently).
- **README install paths** — the opencode gates can be installed from npm
  (`bun add -D opencode-zft`, add `"opencode-zft"` to `opencode.json`) or
  copied from the repo; the changelog and `docs/` are now linked.

## 0.2.0a4 — 2026-09-23

Documentation and packaging completeness release. The 0.2.0a3 wheel was
functional but its PyPI page rendered empty — the `readme` key was fixed in
the cut repo only and was lost when the a3 export re-derived `pyproject.toml`
from the lab. The fix now lives in the lab, so it travels with every export:

- **PyPI page renders** — `readme = "README.md"` plus `[project.urls]`
  (homepage, repository, issues, changelog) and topic classifiers, so the
  project page carries the README and the sidebar links.
- **No shipped doc points at a non-shipped doc** — two `designs/` pages
  referenced `docs/PUBLIC_REPO.md` (internal publish machinery); the Codex
  plugin README's `HB-3` reference now names what it means. The export gate
  catches broken markdown *links*; these were unlinked prose mentions, found
  by a full-text scan of the shipped set.
- **npm package `opencode-zft`** published (`0.2.0-alpha.4`), kept version-
  aligned with the CLI.

## 0.2.0a3 — 2026-09-23

Six first-try defects found by installing the 0.2.0a2 wheel into a fresh
pipx/venv and running the README quickstart verbatim (consumer path, no repo
checkout). All fixed test-first:

- **Gate sources resolve from the installed package** — `zft attest` crashed
  under any non-checkout install: the gate-manifest hash walk assumed the
  repo's `src/` layout and looked for `<env>/lib/python3.12/src/zft/...`. The
  manifest now records package-relative keys (`gates/l1.py`, `gates/l2.py`,
  `codegen/property_gen.py`), identical in every install layout. Attestation
  envelopes produced by ≤ 0.2.0a2 carry the old checkout-relative keys and
  verify only against a ≤ 0.2.0a2 install (alpha: no cross-version compat
  promise).
- **Typed negotiate refusal** — `zft negotiate` on a store without a contract
  manifest raised a raw `FileNotFoundError` traceback at the consumer; it now
  exits 1 with `negotiation refused: ...`, like the command's other refusal
  paths.
- **README quickstart `--key-in`** — `zft verify` hard-requires `--key-in
  <public-key.json>` but the quickstart showed a bare invocation, so the first
  consumer run failed as written. `attest` now states it writes
  `.zft/attest.json` + `.zft/attest-key.pub.json`; `verify` shows the flag.
- **`zft <cmd> --help` stopped swallowing the root** — every subcommand ran
  on a directory literally named `--help`, and `baseline --help` silently
  created one. All 14 subcommands now print usage and exit 0.
- **README ships as the PyPI long description** — the `readme = "README.md"`
  key was lost in the rename squash; `twine check` warned `long_description
  missing` and the PyPI page would have rendered empty. Both 0.2.0a3
  artifacts now pass `twine check` clean.
- **Dead `securesystemslib[cryptography]` extra dropped** — securesystemslib
  1.5.1 no longer provides that extra, so every consumer install warned on
  first try; `cryptography` is already a direct dependency.

Consumer proof for this release: the 0.2.0a2 wheel was probed through a
fresh pipx install (all defects reproduced), and the 0.2.0a3 wheel passed the
same path first-try — install → attest → verify → export, plus the README
quickstart verbatim — and so did the two remaining shapes, uvx and a plain
venv from the wheel.

## 0.2.0a2 — 2026-09-22

- traceagent→zft rename completed; opencode plugin shipped with the cut.
