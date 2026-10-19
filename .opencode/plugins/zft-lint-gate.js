// zft-lint-gate — run the zft L0 gate when an edit lands in the contract
// corpus.
//
// opencode port of the Codex PostToolUse hook
// (plugins/codex/hooks/gates_hook.py), minus the Python middleman: opencode
// hands us the edited path directly, so this plugin calls the `zft` CLI seam
// itself. The Python script stays the single implementation of gate *policy*
// for Codex; the shared L0 policy (store lookup, corpus membership,
// apply_patch parsing, binary resolution, never-green exit table) now lives
// in zft-gate-core (synced to ./core/gate-core.js); this file keeps the
// opencode harness legs: registration, call-ID dedup, records, and the
// observe/enforce blocking semantics.
//
// Policy: the gate acts only on the contract corpus (<root>/.zft/**), the
// same seed policy as .pre-commit-hooks.yaml. Every fired event is appended
// to <root>/.zft/gates-hook/log.jsonl. Outside a store the plugin is
// completely silent (no logs, no .zft/ litter in repos that never opted in).
//
// Modes via ZFT_HOOK_MODE: `observe` (default) records gate outcomes to
// <root>/.zft/gates-hook/log.jsonl without blocking; `enforce` throws the L0
// findings back into the session on failure — mandatory feedback, since
// PostToolUse cannot undo the edit. A broken or missing gate is never green:
// it is recorded as gate_unavailable and, in enforce mode, blocks.

import {
  EDIT_TOOLS,
  findStoreRoot,
  inCorpus,
  corpusPathsFor,
  runGate,
  gateUnavailableRecord,
  appendLog,
  now,
} from "./core/gate-core.js";

const TAG = "[zft lint]";

export const ZftLintGate = async ({ directory, sessionID }) => {
  // opencode can load both the global copy and a project copy in one process.
  // Only the first registers; an edit is never double-gated or double-logged.
  const g = globalThis;
  // opencode loads a plugin once per process; a re-entry (e.g. a second
  // test file importing the factory in the same bun process) must get the
  // SAME hooks, not an empty object — empty hooks silently disable the
  // gate for every later consumer.
  if (g.__zftLintGateRegistered) return g.__zftLintGateHooks;
  g.__zftLintGateRegistered = true;

  // opencode may emit tool.execute.after more than once per tool call (result
  // updates); gate the gate on the call id so one edit is one log record.
  const seen = new Set();

  const warn = (msg) => {
    try {
      process.stderr.write(`${TAG} ${msg}\n`);
    } catch {
      // not actionable
    }
  };

  const hooks = {
    "tool.execute.after": async (input) => {
      if (!EDIT_TOOLS.has(input.tool)) return;
      const key = `${input.callID}:${input.tool}`;
      if (seen.has(key)) return;
      seen.add(key);

      // Resolve the changed absolute paths (core): edit/write carry a
      // single args.filePath; apply_patch carries args.patchText (Aider
      // *** format). The gate acts on the contract corpus (.zft/**) only.
      const tool = input.tool;
      const absPaths = corpusPathsFor(tool, input.args, directory);
      if (!absPaths.length) return; // nothing written: silent

      const root = findStoreRoot(absPaths[0]);
      if (!root) return; // outside any store: stay completely silent

      const mode = process.env.ZFT_HOOK_MODE ?? "observe";
      const enforce = mode === "enforce";
      const base = {
        ts: now(),
        event: "PostToolUse",
        tool: tool === "write" ? "Write" : tool === "edit" ? "Edit" : "apply_patch",
        mode,
        session_id: sessionID ?? input.sessionID,
      };

      const corpus = absPaths.filter((p) => inCorpus(p, root));
      if (!corpus.length) {
        // edit/write outside the corpus are logged as passthrough (unchanged);
        // an apply_patch with no corpus targets stays silent (nothing to lint).
        if (tool !== "apply_patch") {
          appendLog(root, { ...base, root, paths: absPaths, decision: "passthrough" });
        }
        return;
      }

      const primary = corpus[0]; // representative path for messages
      const record = { ...base, root, paths: corpus };
      const res = await runGate(root);

      if (res.kind === "unavailable" && res.reason !== undefined) {
        // no gate argv at all (e.g. unrunnable ZFT_BIN override)
        appendLog(root, gateUnavailableRecord(record, enforce, { detail_tail: res.reason }));
        warn(`gate unavailable: ${res.reason}`);
        if (enforce) throw new Error(`${TAG} GATE_UNAVAILABLE: ${res.reason}`);
        return;
      }
      if (res.kind === "unavailable" && res.exit === undefined) {
        const detail = res.detailTail ?? "spawn failed";
        appendLog(root, gateUnavailableRecord(record, enforce, { detail_tail: detail }));
        warn(`gate unavailable: ${detail}`);
        if (enforce) throw new Error(`${TAG} GATE_UNAVAILABLE: ${detail}`);
        return;
      }
      if (res.kind === "unavailable") {
        // the CLI ran but exited neither 0 nor 1+"L0 FAILED": broken gate
        appendLog(root, gateUnavailableRecord(record, enforce, {
          gate: { name: "L0", status: "unavailable", exit: res.exit },
          detail_tail: res.detailTail,
        }));
        warn(`gate unavailable: exit ${res.exit}`);
        if (enforce) throw new Error(`${TAG} GATE_UNAVAILABLE: gate exited ${res.exit}; tail: ${res.detailTail}`);
        return;
      }
      if (res.kind === "passed") {
        appendLog(root, { ...record, decision: "allow", blocked: false,
          gate: { name: "L0", status: "passed", exit: 0 } });
        return;
      }
      // failed
      appendLog(root, { ...record, decision: enforce ? "deny" : "allow",
        blocked: enforce,
        gate: { name: "L0", status: "failed", exit: 1 },
        detail_tail: res.detailTail });
      if (enforce) {
        throw new Error(`${TAG} L0 FAILED after edit to ${primary}\n${res.detailTail}`.slice(0, 4000));
      }
      warn(`L0 FAILED after edit to ${primary} (observe mode — recorded, not blocked)`);
    },
  };
  g.__zftLintGateHooks = hooks;
  return hooks;
};
