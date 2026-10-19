/**
 * zft-gates pi policy — the pure decision tables (NO pi imports).
 *
 * The shared L0 policy units (store lookup, corpus membership,
 * apply_patch parsing, binary resolution, never-green exit runner,
 * logging) are RE-EXPORTED from zft-gate-core (synced to
 * ../core/gate-core.js) so the opencode and pi adapters can never
 * diverge on corpus logic. This file adds only the pi-specific tables:
 * the pi edit-tool subset, the GateDecision mapping with the superset
 * `blocked` key, and the verified pi settle-gate tables (LV4/LV7/LV8).
 */
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import {
  findStoreRoot,
  inCorpus,
  toAbsolute,
  parsePatchPaths,
  corpusPathsFor,
  resolveGate,
  runGate,
  appendLog,
  now,
  resetGateMemo,
  CORPUS_DIR,
  LOG_REL,
  GATE_TIMEOUT_MS,
  gateUnavailableRecord,
} from "../core/gate-core.js";

export {
  findStoreRoot,
  inCorpus,
  toAbsolute,
  parsePatchPaths,
  corpusPathsFor,
  resolveGate,
  runGate,
  appendLog,
  now,
  resetGateMemo,
  CORPUS_DIR,
  LOG_REL,
  GATE_TIMEOUT_MS,
  gateUnavailableRecord,
};

/** The pi edit-tool subset of the core EDIT_TOOLS: pi has no
 *  apply_patch tool (its editor tools are edit/write), so the gate
 *  fires on that subset. core.test.ts asserts the subset relation. */
export const EDIT_TOOLS: ReadonlySet<string> = new Set(["edit", "write"]);

// --------------------------------------------------------------------- modes
export const isEnforce = (mode: string | undefined): boolean => mode === "enforce";

// -------------------------------------------------------------- gate decision
export interface GateDecision {
  decision: "allow" | "deny" | "gate_unavailable";
  blocked: boolean;
  gate: { name: "L0"; status: "passed" | "failed" | "unavailable"; exit: number };
  detail_tail?: string;
}

/** The L0 gate table: the CLI reserves exit 0 for L0 PASSED and 1 for
 *  L0 FAILED; anything else is a broken gate. The `blocked` key is the
 *  superset record field (C4): every record carries it, true in enforce. */
export function gateDecision(status: number, out: string, enforce: boolean): GateDecision {
  if (status === 0) {
    return { decision: "allow", blocked: false, gate: { name: "L0", status: "passed", exit: 0 } };
  }
  if (status === 1 && out.includes("L0 FAILED")) {
    return {
      decision: enforce ? "deny" : "allow",
      blocked: enforce,
      gate: { name: "L0", status: "failed", exit: 1 },
      detail_tail: out.slice(-2000),
    };
  }
  return {
    decision: "gate_unavailable",
    blocked: enforce, // enforce: a broken gate blocks (never green)
    gate: { name: "L0", status: "unavailable", exit: status },
    detail_tail: out.slice(-400),
  };
}

// --------------------------------------------------------------- settle gate
/** Parse `zft check --json` output (LV7: the JSON has NO run_id field). */
export function parseCheckResult(stdout: string): { ok: boolean; failures: string[] } {
  try {
    const j = JSON.parse(stdout) as { ok?: unknown; failures?: unknown };
    return {
      ok: j.ok === true,
      failures: Array.isArray(j.failures) ? j.failures.map(String) : [],
    };
  } catch {
    return { ok: false, failures: [stdout.trim() ? "<unparseable check output>" : "<empty check output>"] };
  }
}

/** Newest <runs>/<id>/ by mtime — the run id source of truth (LV7). */
export function latestRunId(runsDir: string): string | null {
  let ids: string[] = [];
  try {
    ids = readdirSync(runsDir).filter((id) => {
      try { return statSync(join(runsDir, id)).isDirectory(); } catch { return false; }
    });
  } catch {
    return null;
  }
  if (!ids.length) return null;
  const mt = (p: string): number => { try { return statSync(p).mtimeMs; } catch { return 0; } };
  ids.sort((a, b) => mt(join(runsDir, b)) - mt(join(runsDir, a)));
  return ids[0];
}

/** The LV4 table, cap = the number of consecutive failures that trigger
 *  give-up (cap=3 default: demand on failures 1–2, give up on failure 3).
 *  "silent": give-up was already delivered — never repeated. */
export function settleDecision(counter: number, ok: boolean, cap: number):
  { action: "settle" | "demand" | "give_up" | "silent"; nextCounter: number } {
  if (ok) return { action: "settle", nextCounter: 0 };
  if (counter + 1 < cap) return { action: "demand", nextCounter: counter + 1 };
  if (counter + 1 === cap) return { action: "give_up", nextCounter: counter + 1 };
  return { action: "silent", nextCounter: counter };
}

/** Demand text — MUST cite the run id, the failures, and an explicit
 *  STOP-or-fix instruction (LV8: without it the model reworks forever). */
export function buildDemandText(runId: string | null, failures: string[], attempt: number): string {
  const list = failures.length ? failures.map((f) => `- ${f}`).join("\n") : "- (no structured failures reported)";
  return [
    "zft-gates: the settle gate ran `zft check` in this store and it FAILED.",
    `run: ${runId ?? "(no .zft/runs entry)"} — see .zft/runs/ for the full record.`,
    `Failures (attempt ${attempt}):`,
    list,
    "",
    "Fix the listed failures, then STOP working and end the turn so the gate can re-run. Do not start new work.",
  ].join("\n");
}

/** Give-up text — states the cap and tells the model to STOP (LV8). */
export function buildGiveUpText(runId: string | null, failures: string[], cap: number): string {
  const list = failures.length ? failures.map((f) => `- ${f}`).join("\n") : "- (none reported)";
  return [
    `zft-gates: the settle gate has failed ${cap} consecutive times and is giving up.`,
    `Last run: ${runId ?? "(no .zft/runs entry)"}.`,
    "Outstanding failures:",
    list,
    "",
    "STOP now. Do not attempt further fixes in this session; report the failures to the user.",
  ].join("\n");
}
