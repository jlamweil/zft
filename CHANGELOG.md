# Changelog

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
