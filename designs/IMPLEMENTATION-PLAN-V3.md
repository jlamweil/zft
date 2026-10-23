# Implementation plan: ship `opencode-zft` & `pi-zft` to npm (0.3.1)

Dated: 2026-10-21. Status: **EXECUTED — C1–C4 all landed; registries are at 0.3.1. Post-0.3.1 content now needs a new version.**

> **State re-check 2026-10-23.** Upstream `main` moved past the tagged tree:
> `c7169cf` lands C1 (`test_pi_zft_version_aligned`), `ce4a332` lands C4
> (history leak gate), and `586c02a` adds the taskgate `[root: PATH]` marker
> (now `3e00678` after a metadata-only rewrite that dropped a leaked private
> author email; tree identical). §0.5.1, C1 and C4 are historical — treat
> them as done.
>
> **Correction 2026-10-23:** C2/C3 are done too — PyPI `zft@0.3.1` (09:21Z)
> and `opencode-zft@0.3.1` / `pi-zft@0.3.1` (14:49Z) were published on
> 2026-10-21. The "npm live" table below is draft-time state, minutes before
> that publish, not current. Nothing in this plan remains open; the open
> question is now a **new version** for the post-tag commits.
>
> **Superseded 2026-10-23:** `0.4.0` was cut for that post-tag content
> (PyPI published; npm staged, awaiting interactive 2FA approval). This file
> stays as the 0.3.1 publish record.

## 0. Objective

Complete the JS-adapter release. The tagged tree is already `v0.3.1`
(commit `2d4a688`; HEAD has since moved on without changing the 0.3.1
adapter content), and it carries the governance fix `82a1936`
(reader/writer lane binding, `boundSessions` `Map` logic) **plus** the other
three gate-correctness fixes from the 0.3.1 patch. But the npm registry is
stale relative to that tree:

> Draft-time snapshot — superseded 2026-10-21; verified live 2026-10-23: all three at 0.3.1.

| Artifact | In-tree / tagged | npm live (draft time) | Gap |
| --- | --- | --- | --- |
| `opencode-zft` | 0.3.1 | **0.2.1** | missing 0.3.x (incl. governance fix) |
| `pi-zft` | 0.3.1 | **0.0.0-stage** | never had a real release |
| `zft-gate-core` | 0.1.0 (`private:true`) | not published (by design) | shipped as `core/` copies inside the two above |

So the work is **not a new code change** — it is *completing the publish* of
the already-0.3.1 tree (tree/tag/README/CHANGELOG all already state 0.3.1).
A version bump to 0.3.2 is **only** required if we also want to fold in any
new content; the default for this plan is to publish the existing 0.3.1 as-is.
Decision recorded at §9.

## 0.5 Oracle corrections (from CLI interrogation — supersede any earlier claim)

These are facts measured against the real CLI/registry/tests that *contradict
or sharpen* the drafting assumptions. Treat as authoritative.

1. **The npm alignment test pins ONLY `opencode-zft`, not `pi-zft`.**
   `tests/unit/test_package.py::test_npm_package_version_aligned` reads
   `packages/opencode-zft/package.json` only (line 59). `grep pi-zft tests/
   tools/` → **zero matches**: there is **no** CI oracle for pi-zft's version.
   My draft's "both pinned" claim was wrong. pi-zft's 0.3.1 is convention-only.
   → If pi-zft must be version-guarded, that guard does not exist today.
   Recommendation: add a parallel `test_pi_zft_version_aligned` (own atomic
   commit) OR accept convention-only and record it.
   → **RESOLVED 2026-10-23 (`c7169cf`):** `test_pi_zft_version_aligned` landed
   in `tests/unit/test_package.py:77`; pi-zft is now version-guarded by CI.

2. **`npm stage publish` DOES run `prepublishOnly` (opencode-zft).** Confirmed
   with `--dry-run`: it runs `sync-zft-gates.mjs && sync-zft-gates.mjs --assert`
   before staging; tarball includes `core/gate-core.js` (9.0kB) + `zft-gate.ts`
   (40.8kB). The stale-deploy safety net **is real** for opencode-zft.

3. **`pi-zft` has NO `prepublishOnly`.** So pi-zft publish has **no inherent
   stale/core guard**. The sync+assert protection applies to opencode-zft
   only. → Run `node scripts/sync-zft-gates.mjs --assert` manually in Phase A
   (already planned) before pi-zft publish; do not assume pi-zft self-checks.

4. **A live npm auth token is present** in `~/.npmrc`
   (`//registry.npmjs.org/:_authToken=…`, registry = live, not a stage
   namespace). Implication: `npm stage publish` may be **fully automatable**
   (no browser OTP) if the token carries publish rights — the "owner must
   approve" blocker is **not guaranteed**. Conversely, `npm stage approve`
   may still demand 2FA. → Treat the owner-gate as *conditional*: attempt the
   pipeline, and only hand off if approve actually demands a browser OTP.

5. **Gate operates on the index, not untracked files.**
   `export-cut-check.sh` enumerates `git ls-files` + staged (`--cached`) only.
   The untracked `tests/unit/test_no_private_leaks_in_history.py` is **not**
   seen by the gate until staged. So landing it (C4) requires an explicit
   `git add` before the gate can bless it — it is under the `tests` allowlist
   entry, so a normal stage is safe.

6. **`zft-gate-core` is `private:true`** → correctly absent from npm; never
   publish; confirmed not a gap. (Unchanged from draft.)

## 1. Verified facts (pre-flight, already measured)

- `node scripts/sync-zft-gates.mjs` → **up-to-date**, all 6 deploy/`core/`
  sites byte-identical to canonical. `--assert` idle. (0.08s)
- `.opencode/plugins/zft-gate.ts` ≡ `packages/opencode-zft/zft-gate.ts`
  (identical), has the **new** `Map`-based binding logic.
- `bun test packages/opencode-zft/test/` → **51 pass, 0 fail** (~2.0s).
- `bun test packages/pi-zft/test/` → **32 pass, 0 fail** (~0.1s).
- `bash tools/export-cut-check.sh` → **PASS** (G1–G8 green, lint+check green).
  (~2.3s)
- Python full suite (the long pole) **1523 passed, 1 skipped** (≈3 min).
- `zft-gate-core` is `private:true` → correctly absent from npm; never
  publish it standalone.
- npm `v12.2.0` (≥12 ✓) with the real `stage` subcommand (`stage publish/list/
  view/approve/reject/download`) — **verified**, not assumed.
- House convention: `test_npm_package_version_aligned` pins **opencode-zft**
  version == `pyproject.toml` (see correction §0.5.1 — pi-zft un-pinned).
  opencode-zft already `0.3.1`; no drift. pi-zft 0.3.1 is convention-only.
- Working tree: only untracked `tests/unit/test_no_private_leaks_in_history.py`
  (new TDD history gate). Nothing else dirty.

## 2. Run-duration budget & checkpointing

The only long run is the **Python full suite (~3 min)**; every other step is
seconds. Checkpointing is therefore cheap and applied on the long run.

| Step | Wall time | Checkpoint? |
| --- | --- | --- |
| sync (`node scripts/sync-zft-gates.mjs [--assert]`) | 0.1s | no |
| opencode-zft tests (`bun test packages/opencode-zft/test/`) | 2.0s | no |
| pi-zft tests (`bun test packages/pi-zft/test/`) | 0.1s | no |
| export-cut-check (`bash tools/export-cut-check.sh`) | 2.3s | no |
| **Python full suite** | **~3 min** | **yes — see §2.1** |
| `npm stage publish` x2 (each) | ~10–30s (network) | no (idempotent re-stage) |
| `npm stage approve` ("<id>" x2) | **manual, interactive OTP** | n/a — owner-only |

### 2.1 Checkpointing the 3-minute Python suite

- It is `pytest` over `tests/`; use `pytest -x --timeout=…`-style flags only
  if already configured — otherwise rely on pytest's own per-test reporting
  plus `--lf` (last-failed) to resume.
- **Lead with the 3 pinned files that gate the release**, fail fast before
  the long tail:
  1. `tests/unit/test_package.py` (version alignment)
  2. `tests/unit/test_md_anchor.py` (binding baseline)
  3. `tests/unit/test_taskgate.py` (governance behavior)
  ```sh
  .venv/bin/python -m pytest tests/unit/test_package.py \
      tests/unit/test_md_anchor.py tests/unit/test_taskgate.py -q
  ```
  (~1 min; if these pass, the release-critical surface is sound.)
- Then run the full suite; on any failure use `pytest --lf -q` to resume
  from the first failure without re-running the green block.
- Every pytest invocation writes a JSON report for auditability (README §150
  notes the `JSON report` stage exists): keep the latest JSON under
  `artifacts/` or the run ledger so a judge can point at evidence.

## 3. Atomic-commit map

Each step is one self-contained, revertable commit. **Ship by allowlist,
never `git add -A`** (PUBLISH-RUNBOOK §ground rules).

| # | Commit | Contents |
| --- | --- | --- |
| ~~C1~~ | ~~`ci(publish): pin pi-zft version alongside opencode-zft`~~ — **DONE upstream `c7169cf`** (`test_pi_zft_version_aligned`, §0.5.1 resolved) | landed 2026-10-23 |
| ~~C2~~ | ~~`release(adapter): publish opencode-zft 0.3.1 to npm`~~ — **DONE 2026-10-21 14:49Z** | registry `latest` = 0.3.1 |
| ~~C3~~ | ~~`release(adapter): publish pi-zft 0.3.1 to npm`~~ — **DONE 2026-10-21 14:49Z** | registry `latest` = 0.3.1 |
| ~~C4~~ | ~~`test(leaks): land history leak gate`~~ — **DONE upstream `ce4a332`** | landed 2026-10-23 |

Default: **C2 + C3 are the two atomic release commits**; C4 is the
history-gate test that is already written and untracked — land it either as
its own atomic commit (recommended, it currently gates on the rewritten
history) or defer. C1 only if we add tooling.

## 4. Steps (dry-run through, live only at the owner's OK)

### Phase A — verify (no writes, checkpoint at the 3-min suite)
1. `bash tools/export-cut-check.sh` → PASS.
2. `node scripts/sync-zft-gates.mjs --assert` → "all core/deploy sites byte-identical".
3. `bun test packages/opencode-zft/test/` → 51 pass.
4. `bun test packages/pi-zft/test/` → 32 pass.
5. Python pinned-3 + full suite (§2.1) → green (1523 pass / 1 skip).
6. **Checkpoint A** once green: record package JSON report path + git status
   in the run ledger.

### Phase B — publish opencode-zft (C2)
1. `cd packages/opencode-zft`
2. `npm stage publish` (confirmed: fires `prepublishOnly` sync+assert → stale
   deploy or stale `core/` **fails** the publish; dry-run tar verified to ship
   `core/gate-core.js` + `zft-gate.ts`).
3. Capture the `<stage-id>` it returns.
4. Attempt `npm stage approve "<stage-id>"`. **If the present auth token
   (correction §0.5.4) lets it pass without a browser OTP, the pipeline is
   fully automatable — proceed.** If it demands a one-time browser password
   the owner cannot delegate, hand the stage-id to the owner for the single
   manual approve.
5. On success, verify `npm view opencode-zft version` == `0.3.1`.

### Phase C — publish pi-zft (C3)
1. `cd packages/pi-zft` — **no prepublishOnly here** (correction §0.5.3);
   the sync/assert guard from Phase A is the only clock on this package.
2. `npm stage publish`.
3. Capture stage-id; approve as in Phase B. On success verify
   `npm view pi-zft version` == `0.3.1`.

### Phase D — land (C4 optional test commit)
- Commit C2 / C3 / C4 atomically per §3 by allowlist; `git add` the C4 test
  **before** running export-cut-check (§0.5.5 — gate only sees the index).
- push.

## 5. Debuggability

- **Every gate decision is one JSONL line** in `<root>/.zft/gates-hook/log.jsonl`
  and taskgate records; any gate regression is traceable to a record, not a
  silent drift.
- The sync script already **fails loudly** (MISSING / STALE + exit 1) rather
  than shipping a stale deploy — rely on it: it is the canary for a
  publish-time mismatch.
- `prepublishOnly` on `opencode-zft` runs copy **and** assert, so a broken
  `core/` copy aborts the package stage at the source.
- Test failures are self-describing (bun prints file + assertion; pytest
  prints stage). Keep the JSON reports for the judge.

## 6. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| `npm stage approve` demands a browser OTP the agent cannot enter | Token may already automate it (§0.5.4). Only if approve truly needs 2FA does it become owner-only; everything before/after stays automated |
| pi-zft version is unpinned by CI (§0.5.1) | **Resolved:** `c7169cf` landed `test_pi_zft_version_aligned` |
| pi-zft has no `prepublishOnly` stale-guard (§0.5.3) | Manual sync/assert already in Phase A; do not assume self-check |
| Adding `prepublishOnly` to pi-zft changes publish behavior | Do it as a **separate** atomic commit, never entangle with the release commits |
| History-leak test is untracked & gate only sees the index (§0.5.5) | **Resolved:** `ce4a332` landed it (C4). It then caught a real leak — `586c02a`'s private author email — fixed by a metadata-only rewrite (now `3e00678`) |

## 7. Definition of done

- `npm view opencode-zft version` == `0.3.1`
- `npm view pi-zft version` == `0.3.1`
- `node scripts/sync-zft-gates.mjs --assert` clean at HEAD
- `bash tools/export-cut-check.sh` PASS
- Python full suite green (1523 pass / 1 skip)
- C2/C3 (and C4/C1 if scoped) landed as atomic commits, allowlisted, `git add`ed, pushed
- Registry carries the governance fix `82a1936` semantics (inspect published
  tarball via `npm stage view`/`npm pack`: `boundSessions` is a `Map`,
  `j.lane === "readonly"` exemption present).

## 8. Backups / safety

- Keep `/tmp/opencode/zft-pre-rewrite.bundle` and `/tmp/opencode/sync/*`
  untouched until the release is confirmed live.
- Ship by allowlist only (PUBLISH-RUNBOOK).

## 9. Open decisions (need owner)

**A. Publish existing `0.3.1`, or bump to `0.3.2`?**
- Default (no new content): publish the current `0.3.1` tree — tag, README,
  CHANGELOG, package.json, pyproject all already say 0.3.1. Zero code
  changes; the release is purely registry completion. **(Recommended.)**
- If any fix/change is added during this effort, bump **both** npm packages
  *and* `pyproject.toml` together (CI-enforced alignment) to `0.3.2`.

**B. Do we add the pi-zft version pin (C1)?**
- Today pi-zft's 0.3.1 is convention-only (`test_package.py` ignores it,
  §0.5.1). If pi-zft must be oracle-guarded, land C1 as its own atomic
  commit. Recommended if a pi release matters; otherwise record the gap.

**C. Is the npm token approved for scripting?**
- A live `_authToken` sits in `~/.npmrc` (§0.5.4). Confirm whether using it
  for `npm stage publish/approve` is sanctioned before any real publish.

**D. Is the untracked history-leak test (`tests/unit/test_no_private_leaks_in_history.py`) in scope for C4?**
- It is already written and green; land it as C4 alone (this decision only
  controls whether it is included in this release commit set or deferred).
