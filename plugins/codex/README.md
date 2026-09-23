# zft-codex — M0 prototype (skill + gates hook)

Codex integration for ZFT, following the same shape as
`plugins/dsh` (not built; parked): the artifact is proven by a repo-local test against
the documented host contract — **no live Codex install** anywhere in the loop.

Two pieces:

- `skills/zft-gates/SKILL.md` — Agent-Skills-shaped folder (frontmatter
  `name` + `description`, exactly the two fields Codex requires). Codex
  discovers repo skills at `$CWD/.agents/skills/**` up to the repo root and
  follows symlinks; install is one symlink
  (`ln -s ../../plugins/codex/skills/zft-gates .agents/skills/`).
  The skill carries the *workflow*: L0 after `.zft/**` edits, fast `check`
  before done, how to read typed rejections, and the never-fake-evidence rules.
- `hooks/gates_hook.py` + `hooks.json` — a PostToolUse command hook: every
  apply_patch/Edit/Write that touches the contract corpus (`<root>/.zft/**`,
  the same seed policy as [`.pre-commit-hooks.yaml`](../../.pre-commit-hooks.yaml))
  fires `zft lint <root>` (L0) and appends the outcome to
  `<root>/.zft/gates-hook/log.jsonl`.

Host contract pinned from learn.chatgpt.com `/codex/hooks` and
`/docs/build-skills` (fetched 2026-09-07): event JSON on stdin; exit 0 =
success; exit 2 + reason on stderr = blocking feedback that Codex swaps into
the tool result; skill folders = `SKILL.md` with `name`/`description`.

## Proven without a live Codex install

`pytest tests/unit/test_codex_gates_hook.py` drives the hook as a subprocess
with Codex PostToolUse events on stdin, against a one-clause store seeded in
`tmp_path`:

- **the hook fires on a sample edit**: an apply_patch touching
  `.zft/specs/**` runs the real L0 CLI (`zft lint`) and the log record
  shows `decision: allow`, `gate.exit: 0`, the edited path, session id and
  mode;
- **policy**: edits outside `.zft/**` record `passthrough` and never run the
  gate; edits outside any store record `outside_root`;
- **enforce mode** (`ZFT_HOOK_MODE=enforce`): an edit that breaks L0
  (torn `content_hash`) → exit 2 with the findings on stderr, `decision: deny`;
  observe mode records the same failure and exits 0;
- **fail closed**: a missing/broken gate (`ZFT_BIN` pointing nowhere,
  non-L0 CLI output, timeout) is a typed `GATE_UNAVAILABLE` — never green —
  blocking in enforce mode;
- **skill shape**: the folder Codex would discover parses, declares both
  required frontmatter fields, and sits next to the hook + `hooks.json`.

## Install (when a live Codex is available)

1. Skill: `mkdir -p .agents/skills && ln -s ../../plugins/codex/skills/zft-gates .agents/skills/zft-gates`.
2. Hook: copy the `[[hooks.PostToolUse]]` table from `hooks.json` into your
   `config.toml` (or `hooks.json`), with `<repo-root>` made absolute.
3. Approve the hook once via `/hooks` (Codex requires a one-time trust review
   for non-managed hooks).

## ZCode install (configured in-repo — hook waits on one client approval)

The same hook script serves ZCode: its PostToolUse events carry the fields the
hook parses (`tool_name`, `tool_input.file_path`, `cwd`, `session_id`), and
ZCode aliases `ApplyPatch` into the `Edit`/`Write` matcher. Committed here as
workspace-scope configuration, so every session in this repo runs the gate
**once the client's workspace hook review is approved** — the client blocks
project-scope hooks until that review lands, so the hook has not fired in a
live session yet:

- **Hook**: `.zcode/config.json` — `hooks.enabled: true` (configuration-file
  hooks are disabled by default) with `hooks.events.PostToolUse` matcher
  `^(Edit|Write)$` → the hook script via the repo venv interpreter
  (`.venv/bin/python3`), so the hook's own gate resolution lands where
  `zft` is importable. Without the venv the hook logs a failure and
  the session continues (observe mode never blocks).
- **Skill**: `.agents/skills/zft-gates` symlink — workspace skill
  discovery scans `.agents/skills/`. **This half is live**: sessions in this
  repo list `zft-gates` among their discovered skills.

**Deployment status, measured (2026-09-11).** Two-part artifact, two states:

| Piece | State | Evidence |
| --- | --- | --- |
| Skill (`zft-gates`) | | **live** | listed in session skill discovery (`.agents/skills/zft-gates/SKILL.md`); symlink verified → `plugins/codex/skills/zft-gates` |
| Hook (`gates_hook.py` via `.zcode/config.json`) | **blocked, pending client review** | client log `config.project_hooks.pending_trust` ("Project hooks are pending workspace trust and remain blocked") every session since 09-08; `.zft/gates-hook/log.jsonl` has no harness-fired record |

**Dogfood evidence** (`.zft/gates-hook/log.jsonl`, fed by the real
corpus edit that added CON-CRASH-RESUME): the first record is the clause-node
Write — `decision: allow`, gate L0 `passed`, exit 0; the second is the
`.zcode/config.json` Write — `decision: passthrough` (edit outside `.zft/**`
never runs the gate). Config-file hooks load at session start, so these first
records were fired by piping the same event JSON the harness sends to the
hook's stdin — the documented host contract the repo test replays. They prove
the artifact; they are **not** harness fires, and the log keeps them
distinguishable by their synthetic `session_id`
(`zcode-midwave-20260908-con-crash-resume`). The live proof that closes HB-3
is a new record with a real session `session_id`, fired by the harness on the
first `.zft/` edit of the first session after the review approval.

## Choices & deviations from the dsh plugin

| Choice | Why |
| --- | --- |
| PostToolUse, not PreToolUse | L0 is defined on the *store*, so the gate can only run after the edit lands. PreToolUse deny would have to predict L0 on a state that does not exist yet. Enforcement is therefore a feedback loop (exit 2 → the failure is swapped into the tool result), not prevention. |
| Unclassifiable events pass (logged) | dsh fails closed on unclassifiable payloads because it denies *pre*-hoc. Post-hoc, a deny cannot undo anything and would only punish unrelated edits for one malformed event — so the event is logged (`decision: unclassified`) and the residual risk stays with the skill workflow. |
| `observe` by default | PostToolUse blocking is opt-in (`ZFT_HOOK_MODE=enforce`) so a consumer can adopt the audit trail before adopting the block. |
| CLI seam (`zft lint`), not imports | the hook is stdlib-only and interpreter-agnostic (runs under whatever `python3` Codex picks); resolution: `ZFT_BIN` > `zft` on PATH > `python3 -m zft.cli.main`. An explicitly broken `ZFT_BIN` fails rather than silently falling back. |

## Stubs vs the real integration

| Prototype | Real integration |
| --- | --- |
| Stdin events replayed by the test | Codex fires the hook on real apply_patch/Edit/Write tool calls |
| Symlink install documented in this README | packaged install path (plugin/marketplace or repo-native `.agents/skills/`) |
| `log.jsonl` under `.zft/gates-hook/` | surfacing gate records in the session transcript via Codex's feedback channel + run ledger correlation |
| `matcher` regex pinned to edit tools | widen to Bash redirections (sed/echo edits bypass apply_patch) if Codex exposes a richer diff surface |
