# zft-gates — ZCode integration (skill + gates hook + stop gate)

ZCode counterpart of `plugins/codex`: the artifact is proven by a repo-local
test against the documented host contract — **no live ZCode install** in the
loop (`pytest tests/unit/test_zcode_gates_hook.py`, 13 tests; the codex twin's
6 run beside them so the two hook files cannot drift).

Three pieces:

- `skills/zft-gates/SKILL.md` — the workflow: L0 after `.zft/**` edits, fast
  `check` before done, how to read typed rejections, the never-fake-evidence
  rules. Install source-side via `<repo>/.zcode/skills/zft-gates` (symlink),
  or through the plugin (below; workspace scope shadows the plugin copy).
- `hooks/gates_hook.py` + `hooks/hooks.json` (PostToolUse, matcher
  `^(Edit|Write)$`) — every Edit/Write touching the contract corpus
  (`<root>/.zft/**`) fires `zft lint <root>` (L0) and appends the outcome to
  `<root>/.zft/gates-hook/log.jsonl`. Byte-for-byte the codex twin modulo its
  docstring.
- `hooks/stop_gate.py` + the `Stop` entry in `hooks.json` — before a session
  may stop, `zft check <root>` runs; the event fires for **every session in
  the workspace, main or subagent**, so a red store holds a subagent
  completion exactly like a main-session one. No store above the session cwd
  means nothing to enforce (silent exit 0).

## Requirements (prerequisites for practical use)

1. **Python 3.12+** and the CLI: `pip install zft` (stable, on PyPI).
2. **A resolvable `zft` executable**: `ZFT_BIN` (authoritative) > `zft` on
   `PATH` > `python3 -m zft.cli.main`. A broken gate is a typed
   `GATE_UNAVAILABLE` — never green.
3. **A seeded contract store** (`zft create` + a contract manifest under
   `.zft/contracts/`). Fail-closed by design
   (`CON-VALIDATED-OR-NO-START`): no store, nothing enforced — silently or
   otherwise.
4. **Workspace trust for the hook half**: configuration-file hooks stay
   blocked until the client's workspace hook review approves them (the
   skill half is live the moment the symlink exists). The plugin route via
   the marketplace carries the same review.
5. **No subagent configuration is required.** This integration has no
   dispatch gate; enforcement is edit-time L0 plus the Stop gate — and the
   Stop event fires for subagent completions exactly like main-session
   ones, so a subagent cannot land a red store. For dispatch-boundary
   enforcement (contract-binding work *before* it spawns), use the opencode
   integration or call `zft task-gate before/after` manually around
   delegated work.

## Modes (fail closed)

Both hooks log every fired event; a missing or broken gate is a typed
GATE_UNAVAILABLE and never passes green. `observe` (default) records and
allows; `enforce` blocks: PostToolUse exits 2 with the L0 findings on stderr
(feeding straight back into the editing session), Stop exits 2 with the
failures list as the work list. Knobs: `ZFT_HOOK_MODE`, `ZFT_STOP_MODE`,
`ZFT_BIN` (authoritative gate binary) > `zft` on PATH >
`python3 -m zft.cli.main`; `ZFT_ROOT` overrides store discovery. App-wide
enforcement ships via `~/.config/environment.d/zft.conf`.

## Install (plugin route)

Marketplace root is this directory's parent: `plugins/marketplace.json`
declares dev market `dev-traceagent-zcode` → plugin `zft-gates@dev-traceagent-zcode`.
In ZCode: Plugin Marketplace → Add → Add Plugin Marketplace → paste the
`plugins/` directory → install **ZFT Gates**. Plugin hooks append to any
config-file hooks; hand the workspace `.zcode/config.json` hook block over
to the plugin (empty it) to avoid double-firing.

## Proven without a live ZCode install

The test drives both hooks as subprocesses with ZCode events on stdin
(PostToolUse Edit/Write with `tool_input.file_path`; Stop with
`session_id`/`cwd`) against a one-clause store seeded in `tmp_path`:
L0 fires on a sample contract edit; edits outside the corpus pass through
un-gated; enforce blocks an L0-breaking edit with findings on stderr while
observe records and allows; the stop gate allows-and-records a red store in
observe, blocks red in enforce, holds a broken gate fail-closed, and is
silent where no store exists. Plugin shape (manifest name/dir agreement,
`${CLAUDE_PLUGIN_ROOT}` wiring, skill frontmatter, marketplace entry) is
asserted too.
