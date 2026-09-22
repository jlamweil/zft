/**
 * zft-gate — enforce the zft task gate at the subagent-dispatch boundary.
 *
 * Wraps the built-in `task` tool:
 *  - `tool.execute.before`: runs `zft task-gate before` and BLOCKS the
 *    dispatch (throws) when the CLI exits 1 — the policy rejection, with the
 *    CLI's stdout/stderr embedded in the error message.
 *  - `tool.execute.after`: runs `zft task-gate after` and prepends the CLI's
 *    coverage verdict to the tool output as a gate report. Exit 1 from the
 *    `after` phase means the verdict found missing clauses — the report is
 *    still surfaced (non-blocking), because the subagent has already run.
 *
 * Safety: any internal failure (spawn error, timeout, unexpected exit code,
 * exception) fails OPEN with a warning on stderr. A hook exception never
 * escapes except the deliberate policy block above.
 *
 * Scope: silent unless the project has a `.zft/` store, and unless disabled
 * via env (see README.md).
 */
import type { Plugin } from "@opencode-ai/plugin";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const TAG = "[zft gate]";

/** Upper bound on a single gate invocation. A hung CLI must not freeze the
 *  dispatch: on timeout spawnSync reports an error and we fail open. */
const GATE_TIMEOUT_MS = 30_000;

/** Thrown only for the deliberate policy block (task-gate before exit 1). */
class GateBlock extends Error {}

export const ZftGate: Plugin = async ({ directory }) => {
  // Idempotency: opencode can load both the repo-local copy and the global
  // copy in the same process. Only the first registers hooks, so an enforced
  // dispatch is never double-gated or double-audited.
  const g = globalThis as Record<string, unknown>;
  if (g.__zftGateRegistered) return {};
  g.__zftGateRegistered = true;

  const warn = (msg: string): void => {
    try {
      process.stderr.write(`${TAG} ${msg}\n`);
    } catch {
      // stderr itself failing is not actionable; stay silent.
    }
  };

  /** Scope: active only in a zft workspace and unless explicitly disabled. */
  const active = (): boolean => {
    try {
      return (
        process.env.ZFT_GATE_DISABLED !== "1" &&
        existsSync(join(directory, ".zft"))
      );
    } catch {
      return false;
    }
  };

  /** Resolve the zft binary: env override > repo .venv > PATH. */
  const bin = (): string => {
    const fromEnv = process.env.ZFT_BIN;
    if (fromEnv) return fromEnv;
    const local = join(directory, ".venv", "bin", "zft");
    if (existsSync(local)) return local;
    return "zft"; // resolved against PATH by the spawn itself
  };

  /** Run the CLI; returns undefined (after warning) if it could not run. */
  const runGate = (
    phase: "before" | "after",
    subagent: string,
    description: string,
  ) => {
    try {
      return spawnSync(
        bin(),
        [
          "task-gate",
          phase,
          "--subagent",
          subagent,
          "--description",
          description,
        ],
        {
          cwd: directory,
          encoding: "utf8",
          timeout: GATE_TIMEOUT_MS,
          // Node inherits process.env by default; Bun's node:child_process
          // compat does NOT inherit process.env mutations made after process
          // start, so pass the current env explicitly (no-op on Node).
          env: { ...process.env },
        },
      );
    } catch (e) {
      warn(`internal error (${phase}): ${e instanceof Error ? e.message : String(e)} — failing open`);
      return undefined;
    }
  };

  return {
    "tool.execute.before": async (input, output) => {
      try {
        if (input.tool !== "task" || !active()) return;
        const args = (output.args ?? {}) as Record<string, unknown>;
        const res = runGate(
          "before",
          String(args.subagent_type ?? ""),
          String(args.description ?? ""),
        );
        if (!res || res.error) {
          warn(`internal error (before): ${res?.error?.message ?? "spawn failed"} — failing open`);
          return; // never block on an internal error
        }
        if (res.status === 1) {
          const detail = [res.stdout, res.stderr]
            .map((s) => s.trim())
            .filter(Boolean)
            .join("\n");
          throw new GateBlock(`${TAG} dispatch blocked by task gate:\n${detail}`);
        }
        if (res.status !== 0) {
          warn(`unexpected exit code ${res.status} (before) — failing open`);
        }
      } catch (e) {
        if (e instanceof GateBlock) throw e; // deliberate policy block
        warn(`hook error (before): ${e instanceof Error ? e.message : String(e)} — failing open`);
      }
    },

    "tool.execute.after": async (input, output) => {
      try {
        if (input.tool !== "task" || !active()) return;
        if (typeof output.output !== "string") return;
        const args = (input.args ?? {}) as Record<string, unknown>;
        const res = runGate(
          "after",
          String(args.subagent_type ?? ""),
          String(args.description ?? ""),
        );
        if (!res) return; // already warned
        if (res.error) {
          warn(`internal error (after): ${res.error.message} — ignoring`);
          return; // non-blocking
        }
        // 0 = verdict green; 1 = verdict with missing clauses (still a
        // report the orchestrator needs); 2/other = internal error.
        if (res.status !== 0 && res.status !== 1) {
          warn(`unexpected exit code ${res.status} (after) — ignoring`);
          return;
        }
        const out = (res.stdout ?? "").trim();
        if (!out) return;
        const tag =
          res.status === 1
            ? `${TAG} coverage verdict: MISSING clauses`
            : `${TAG} coverage verdict`;
        output.output = `${tag}\n${out}\n\n${output.output}`;
      } catch (e) {
        // Never escape: the subagent result must reach the caller.
        warn(`hook error (after): ${e instanceof Error ? e.message : String(e)} — ignoring`);
      }
    },
  };
};
