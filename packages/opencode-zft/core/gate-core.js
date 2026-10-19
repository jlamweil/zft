// zft-gate-core — the pure, harness-free L0 gate policy shared by the
// opencode (opencode-zft) and pi (pi-zft) adapters.
//
// Ported verbatim from the pinned deploy behavior
// (.opencode/plugins/zft-lint-gate.js, gap-002 era). No harness APIs are
// imported here: store lookup, corpus membership, apply_patch path
// parsing, binary resolution, and the never-green exit table. Adapters
// keep their harness-specific legs (opencode: task gate; pi: settle gate)
// and build records with buildRecord.
//
// Policy: the gate acts only on the contract corpus (<root>/.zft/**).
// A broken or missing gate is never green: it is unavailable and, in
// enforce mode, blocks (adapter decides how to block).
//
// Binary resolution: ZFT_BIN > <project>/.venv/bin/zft
// > `zft` on PATH (plus ~/.local/bin) > `python3 -m zft.cli.main`. An
// explicitly set ZFT_BIN that cannot run is authoritative — it fails
// rather than silently falling back. Any other candidate must also RUN
// (runnable): a stale entry point is skipped, never spawned into a
// traceback that would block every edit.

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const CORPUS_DIR = ".zft";
export const LOG_REL = path.join(CORPUS_DIR, "gates-hook", "log.jsonl");
export const EDIT_TOOLS = new Set(["edit", "write", "apply_patch"]);
export const GATE_TIMEOUT_MS = 60_000;

const STORE_KEYS = ["ZFT_BIN"];

export function findStoreRoot(startPath) {
  let dir = startPath;
  try {
    if (fs.existsSync(dir) && fs.statSync(dir).isFile()) dir = path.dirname(dir);
  } catch {
    dir = path.dirname(dir);
  }
  while (true) {
    try {
      if (fs.statSync(path.join(dir, CORPUS_DIR)).isDirectory()) return dir;
    } catch {
      // not here — keep walking up
    }
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

export function inCorpus(absPath, root) {
  const rel = path.relative(root, absPath);
  return rel !== "" && !rel.startsWith("..") && rel.split(path.sep)[0] === CORPUS_DIR;
}

export function toAbsolute(p, directory) {
  return path.isAbsolute(p) ? p : path.resolve(directory, p);
}

/** Targets an Aider-format `apply_patch` writes — the same
 *  `*** Add/Update/Move to:` lines the task gate parses (Gap 002: the
 *  patch escaped the lint gate). `*** Delete File:` writes nothing
 *  (skipped, like /dev/null); results are deduped. */
export function parsePatchPaths(patchText) {
  const seen = new Set();
  for (const line of patchText.split("\n")) {
    const m = line.match(/^\*\*\*\s+(?:Add File|Update File|Move to):\s*(\S+)\s*$/);
    if (!m) continue;
    const p = m[1];
    if (p === "/dev/null") continue;
    seen.add(p);
  }
  return [...seen];
}

/** The absolute paths a tool call writes, per its input shape:
 *  edit/write carry a single args.filePath; apply_patch carries
 *  args.patchText (Aider *** format). Returns [] when nothing was
 *  written (adapters stay silent in that case). */
export function corpusPathsFor(tool, args, directory) {
  if (tool === "apply_patch") {
    const text = typeof args?.patchText === "string" ? args.patchText : "";
    return parsePatchPaths(text).map((p) => toAbsolute(p, directory));
  }
  const fp = args?.filePath;
  if (typeof fp !== "string" || !fp.trim()) return [];
  return [toAbsolute(fp, directory)];
}

/** Resolve the gate. Returns [argv, null] or [null, reason].
 *  ZFT_BIN is read on every call (authoritative, never memoized); the
 *  candidate search is memoized per store because runnable() probes. */
const GATE_MEMO = new Map();

export function resetGateMemo() {
  GATE_MEMO.clear();
}

export function resolveGate(directory) {
  for (const key of STORE_KEYS) {
    const override = process.env[key];
    if (!override) continue;
    const argv = override.trim().split(/\s+/).filter(Boolean);
    if (!argv.length) return [null, `${key}=${JSON.stringify(override)}: empty command`];
    // An explicit override is authoritative: verify it exists rather than
    // falling back to a different binary.
    const exe =
      path.isAbsolute(argv[0]) && fs.existsSync(argv[0]) ? argv[0] : whichOr(argv[0]);
    if (!exe) return [null, `${key}=${JSON.stringify(override)}: executable not found`];
    return [[exe, ...argv.slice(1)], null];
  }
  const memo = GATE_MEMO.get(directory);
  if (memo !== undefined) return memo;
  const out = resolveCandidates(directory);
  GATE_MEMO.set(directory, out);
  return out;
}

/** Candidate search (memoized by resolveGate). A candidate must run: a
 *  stale entry point is skipped so resolution can fall through. */
function resolveCandidates(directory) {
  const local = path.join(directory, ".venv", "bin", "zft");
  if (fs.existsSync(local) && runnable([local])) return [[local], null];
  const onPath = whichOr("zft");
  if (onPath && runnable([onPath])) return [[onPath], null];
  // Last resort: run the module directly. Both import names are probed
  // because the published 0.2.x wheel still exposes `zft.cli.main`.
  const py = whichOr("python3") || whichOr("python");
  if (py) {
    const mod = probeModule(py, "zft.cli.main");
    if (mod) return [[py, "-m", mod], null];
  }
  return [null, "no zft executable: set ZFT_BIN or install `pip install zft`"];
}

/** True when argv launches a zft: any run whose stderr carries no Python
 *  traceback. One probe per store (resolveGate memoizes); catches stale
 *  entry points and missing shebang interpreters. */
function runnable(argv) {
  try {
    const res = spawnSync(argv[0], argv.slice(1), {
      encoding: "utf8",
      timeout: 10_000,
      env: { ...process.env },
    });
    if (res.error) return false;
    const err = String(res.stderr ?? "");
    return !/Traceback \(most recent call last\)|ModuleNotFoundError|No module named|Exec format error|command not found/.test(
      err,
    );
  } catch {
    return false;
  }
}

/** Return the module name if `python -c 'import mod'` succeeds, else null. */
function probeModule(py, mod) {
  try {
    const res = spawnSync(py, ["-c", `import ${mod}`], {
      encoding: "utf8",
      timeout: 10_000,
      env: { ...process.env },
    });
    return res.status === 0 ? mod : null;
  } catch {
    return null;
  }
}

function whichOr(cmd) {
  // Minimal PATH lookup; avoids depending on a `which` binary. ~/.local/bin
  // is always consulted (uv tool / pipx / pip --user) even when the
  // server's PATH omits it.
  const dirs = [
    ...(process.env.PATH ?? "").split(path.delimiter).filter(Boolean),
    path.join(os.homedir(), ".local", "bin"),
  ];
  for (const dir of dirs) {
    const cand = path.join(dir, cmd);
    try {
      if (fs.statSync(cand).isFile()) return cand;
    } catch {
      // keep scanning
    }
  }
  return null;
}

/** Run `zft lint <root>` and classify the outcome on the never-green
 *  exit table:
 *    exit 0                      -> { kind: "passed" }
 *    exit 1 + "L0 FAILED"       -> { kind: "failed", detailTail }
 *    anything else / spawn fail -> { kind: "unavailable", ... }
 *  A gate that cannot run is reported, never treated as green. */
export async function runGate(root) {
  const [argv, reason] = resolveGate(root);
  if (!argv) return { kind: "unavailable", reason };
  let res;
  try {
    res = spawnSync(argv[0], [...argv.slice(1), "lint", root], {
      cwd: root,
      encoding: "utf8",
      timeout: GATE_TIMEOUT_MS,
      env: { ...process.env },
    });
  } catch (e) {
    return { kind: "unavailable", detailTail: String(e) };
  }
  if (res.error) {
    return { kind: "unavailable", detailTail: res.error.message ?? "spawn failed" };
  }
  const out = ((res.stdout ?? "") + (res.stderr ?? "")).trim();
  if (res.status === 0) return { kind: "passed" };
  if (res.status === 1 && out.includes("L0 FAILED")) {
    return { kind: "failed", detailTail: out.slice(-2000) };
  }
  return { kind: "unavailable", exit: res.status, detailTail: out.slice(-400) };
}

export function now() {
  return new Date().toISOString();
}

/** The superset gate_unavailable record (C4): every writer (opencode,
 *  pi, codex, zft-gates) emits the same keys, in particular `blocked`
 *  (true iff enforce — a broken gate blocks). `extra` carries the
 *  branch-specific keys (detail_tail, and `gate` only when the CLI
 *  actually ran). */
export function gateUnavailableRecord(base, enforce, extra = {}) {
  const rec = { ...base, decision: "gate_unavailable", blocked: !!enforce };
  for (const [k, v] of Object.entries(extra)) {
    if (v !== undefined) rec[k] = v;
  }
  return rec;
}

/** Append a record to <root>/.zft/gates-hook/log.jsonl. The log is an
 *  audit trail, never a reason to crash the session. */
export function appendLog(root, record) {
  try {
    const log = path.join(root, LOG_REL);
    fs.mkdirSync(path.dirname(log), { recursive: true });
    fs.appendFileSync(log, JSON.stringify(record) + "\n");
  } catch {
    // audit trail only
  }
}
