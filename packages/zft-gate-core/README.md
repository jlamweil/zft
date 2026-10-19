# zft-gate-core

The pure, zero-dependency policy units shared by the zft JS gate
adapters (opencode-zft, pi-zft):

- `findStoreRoot` — resolve the store root from the first input path
  (`.zft/` marker, walking up)
- `inCorpus` — is this path inside the store's `.zft/` corpus?
- `parsePatchPaths` / `corpusPathsFor` — opencode `apply_patch`
  target parsing + corpus filter
- `resolveGate` / `runGate` — `ZFT_BIN` (override > memo > `zft`),
  argv shape, `spawnSync` execution, output tail
- `appendLog` / `now` — the JSONL audit writer and timestamps
- `gateUnavailableRecord` — the superset `gate_unavailable` record
  factory (every writer emits the same keys; `blocked` true iff
  enforce)

Both adapters import a **synced relative copy** (`./core/gate-core.js`)
— no bare specifiers, no node_modules, no symlinks.
`scripts/sync-zft-gates.mjs` keeps the copies byte-identical
(`pretest`; `prepublishOnly` runs it in copy+assert mode).

Record schema (superset, one across every writer — opencode, pi,
codex, zcode): every gate-decision record carries `blocked`;
meta-records carry neither `gate` nor `blocked`. See
`.opencode/plugins/README.md` for example lines.

Tests:

```sh
node --experimental-strip-types --test test/policy.test.ts
node --experimental-strip-types --test test/parity.test.ts  # cross-adapter
```
