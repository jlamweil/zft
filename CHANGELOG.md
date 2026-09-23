# Changelog

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
