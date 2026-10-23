# Publishing the public cut — runbook

This is the owner's step-by-step for shipping a release of the public repo
(`zft-public`). It is the companion to `tools/export-cut-check.sh` — that
gate's allowlist is the **single source of truth** for what may ship, and
this runbook must stay in sync with it. A mismatch fails loudly by design.

Dated: 2026-10-20.

## 0. Ground rules

- **Public = leakage-free.** Nothing in the cut may name a private host,
  machine path, internal ticket, or the pre-rename package. Two independent
  guards enforce this (see §3): the export-cut gate and the unit leak test.
- **Owner-gated steps** (bump, tag, publish) are acts only the owner may take;
  this runbook records the procedure, not permission.
- Ship **by allowlist**, never `git add -A`. A blanket add can scoop up an
  internal doc that slipped in.

## 1. Before every push (the gate)

From the cut root, run the gate:

```sh
bash tools/export-cut-check.sh
```

- **Exit 0** (PASS) → safe to commit and push.
- **Exit 1** (FAIL) → a leak, a broken link, or an out-of-set path is present.
  Do **not** push until it is resolved.

Fixing categories:

| Failure                            | Fix |
| ---                                | --- |
| `outside the public set: <path>`   | It is a tracked file the allowlist does not admit. Either it is legitimate new content → **add it to the ALLOWLIST array** in `tools/export-cut-check.sh` (and note it here), or it is internal → remove/move it. |
| `path names the pre-rename package`| Rename the file so no pre-rename token appears in its path. |
| `… still referenced` / credential / machine-path | The cut (or the gate itself) carries a private literal. Scrub or neutralize it (assemble the token at runtime, mirroring §3). |
| `broken or non-public link`        | A relative markdown link dangles or targets a non-shipped path. Fix the link or ship the target. |
| `baseline enumerates an internal tree` | Re-seed the baseline on the cut (`zft baseline .`); never copy one from the private side. |

`--fix` untracks (index-only) every path outside the allowlist and re-runs:

```sh
bash tools/export-cut-check.sh --fix
```

Use `--fix` after pruning a stray doc; it does not delete the file from disk.

## 2. Self-check when no `zft` binary is installed

The gate's final step runs `zft lint .` and `zft check .` to confirm
lint + reverse-coverage are green. If no `zft` executable is on `PATH`, it
falls back to `.venv/bin/python -m zft.cli.main` when the venv has `zft`.

Wheel-unzip fallback (a host without either): unzip a released `zft` wheel
and run the CLI module from it, or point `ZFT_BIN` at any working install:

```sh
ZFT_BIN='venv/bin/python -m zft.cli.main' bash tools/export-cut-check.sh
```

## 3. Leak guard

`tests/unit/test_no_private_leaks.py` scans **every tracked file** (now
including `tools/export-cut-check.sh`) for private tokens — the pre-rename
package name, the old driver name, private hosts, `$HOME`-style paths, an
internal redaction token, and internal `INT-`/`WQ-` ticket ids. A private
identifier belongs only in the **private archive**, never here. If an
internal artifact must be preserved, move it to the private side rather than
scrubbing it into meaninglessness.

Run it in the suite:

```sh
pytest tests/unit/test_no_private_leaks.py -q
```

## 4. Release steps (owner-gated)

1. **Gate**: `bash tools/export-cut-check.sh` green, full suite green
   (`pytest`, `ruff`, the package test runners).
2. **Version bump**: `pyproject.toml` + `src/zft/__init__.py` + `CITATION.cff`
   + `packages/opencode-zft/package.json` + `packages/pi-zft/package.json`
   (all five are pinned together by `tests/unit/test_package.py`; the two
   `package.json`s are the part this runbook used to omit) + the README
   version line and publishing table.
3. **Tag**: create `vX.Y.Z` on the cut's main.
4. **Publish**:
   - PyPI: `zft` (build + `twine upload`).
   - npm: `opencode-zft` (and sibling packages under `packages/`), stage
     promotion first (stage-only token is owner-gated).
   - GitHub: open a release for the tag; attach the changelog section.
5. **Record**: append the release to `CHANGELOG.md` and note the ship list
   drift, if any, in the ALLOWLIST + this runbook together.

## 5. Keeping this runbook honest

- The allowlist array and this section must stay in lock-step; the gate does
  not read this file, but a reviewer cross-checks them.
- Every new public path gets added to **both** the ALLOWLIST in
  `tools/export-cut-check.sh` (section S1 of that file) and the ship list
  documented here.
