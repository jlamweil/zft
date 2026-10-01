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
 *    The verdict is scoped to this dispatch's changeset when the marker and
 *    the session API allow it (see changeset scoping below), so a subagent
 *    never inherits coverage it did not produce.
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
import { appendFileSync, existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { homedir } from "node:os";
import { delimiter, isAbsolute, join, relative, sep } from "node:path";

const TAG = "[zft gate]";

/** Upper bound on a single gate invocation. A hung CLI must not freeze the
 *  dispatch: on timeout spawnSync reports an error and we fail open. */
const GATE_TIMEOUT_MS = 30_000;

/** The resolved agent list is cached briefly: config changes mid-session are
 *  rare, and a lookup on every dispatch would be needless traffic. A hot
 *  reload still wins within this window. */
const AGENT_TTL_MS = 30_000;

/** Thrown only for the deliberate policy block (task-gate before exit 1). */
class GateBlock extends Error {}

/** opencode PermissionRule — the v2 API's merged ruleset shape. */
interface Rule {
  permission: string;
  pattern: string;
  action: string;
}

/**
 * Accept either API surface:
 *  - v2: PermissionRule[] (what client.app.agents() returns today)
 *  - v1 / config: { edit: "allow"|..., bash: { pattern: action } } — flattened
 *    with the same mapping opencode's fromConfig() uses.
 * The classification itself happens in the Python core (one implementation,
 * pinned by oracle_CAPABILITY-CLASSIFICATION.py); the plugin only forwards.
 */
const normalizeRules = (perm: unknown): Rule[] => {
  if (Array.isArray(perm)) {
    return perm.filter(
      (r): r is Rule =>
        typeof r === "object" && r !== null &&
        typeof r.permission === "string" &&
        typeof r.pattern === "string" &&
        typeof r.action === "string",
    );
  }
  if (perm && typeof perm === "object") {
    const rules: Rule[] = [];
    for (const [permission, spec] of Object.entries(perm as Record<string, unknown>)) {
      if (typeof spec === "string") {
        rules.push({ permission, pattern: "*", action: spec });
      } else if (spec && typeof spec === "object") {
        for (const [pattern, action] of Object.entries(spec as Record<string, unknown>)) {
          if (typeof action === "string") rules.push({ permission, pattern, action });
        }
      }
    }
    return rules;
  }
  return [];
};

export const ZftGate: Plugin = async ({ directory, client }) => {
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

  const debug = async (msg: string): Promise<void> => {
    try {
      await client?.app?.log?.({ level: "debug", message: `${TAG} ${msg}` });
    } catch {
      // logging must never break a dispatch
    }
  };

  /** Cached {name -> ruleset} view of client.app.agents(). */
  let agentCache: { rules: Map<string, Rule[]>; expiry: number } | null = null;

  /** Resolve a subagent's merged permission ruleset; undefined on any miss,
   *  which degrades to the lane-name fallback in the CLI (fail-safe). */
  const resolveRules = async (subagent: string): Promise<Rule[] | undefined> => {
    if (!subagent) return undefined;
    try {
      if (!client?.app?.agents) return undefined;
      const now = Date.now();
      if (!agentCache || now > agentCache.expiry) {
        const agents = (await client.app.agents()) as Array<{ name?: string; permission?: unknown }>;
        const rules = new Map<string, Rule[]>();
        for (const a of agents ?? []) {
          if (a?.name) rules.set(a.name, normalizeRules(a.permission));
        }
        agentCache = { rules, expiry: now + AGENT_TTL_MS };
      }
      return agentCache.rules.get(subagent);
    } catch (e) {
      warn(`agent lookup failed (${e instanceof Error ? e.message : String(e)}) — ` +
           "falling back to lane-name classification");
      return undefined;
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

  /** Resolve the zft invocation. Mirrors the lint gate's strategy:
   *  ZFT_BIN > <project>/.venv/bin/zft > `zft` on PATH (including
   *  ~/.local/bin, where uv tool / pipx land and which the server's PATH
   *  does not always include) > `python3 -m zft.cli.main` module fallback.
   *  A candidate must also RUN (see runnable): a stale .venv entry point
   *  (ModuleNotFoundError after the package rename) is skipped rather than
   *  spawned into a traceback that would fail the gate open on every call.
   *  Returns null when nothing resolves — the caller fails open. */
  let resolvedGate: string[] | null | undefined;
  const resolveGate = (): string[] | null => {
    const fromEnv = process.env.ZFT_BIN;
    if (fromEnv) {
      // An explicit override is authoritative; a bad path surfaces as the
      // spawn's own error rather than a silent fallback.
      return fromEnv.trim().split(/\s+/).filter(Boolean);
    }
    if (resolvedGate !== undefined) return resolvedGate;
    const local = join(directory, ".venv", "bin", "zft");
    if (existsSync(local) && runnable([local])) return (resolvedGate = [local]);
    const onPath = whichOr("zft");
    if (onPath && runnable([onPath])) return (resolvedGate = [onPath]);
    // Last resort: run the module directly. Both import names are probed
    // because the published 0.2.x wheel still exposes `traceagent.cli.main`.
    const py = whichOr("python3") || whichOr("python");
    if (py) {
      const mod =
        probeModule(py, "zft.cli.main") ?? probeModule(py, "traceagent.cli.main");
      if (mod) return (resolvedGate = [py, "-m", mod]);
    }
    return (resolvedGate = null);
  };

  /** True when argv launches a zft: any run whose stderr carries no Python
   *  traceback. One probe per process (resolveGate memoizes); catches stale
   *  entry points and missing shebang interpreters. */
  const runnable = (argv: string[]): boolean => {
    try {
      const res = spawnSync(argv[0], argv.slice(1), {
        encoding: "utf8",
        timeout: 10_000,
        env: { ...process.env },
      });
      if (res.error) return false;
      const err = String(res.stderr ?? "");
      return !/Traceback \(most recent call last\)|ModuleNotFoundError|No module named|Exec format error|command not found/.test(err);
    } catch {
      return false;
    }
  };

  /** Minimal PATH lookup; avoids depending on a `which` binary. ~/.local/bin
   *  is always consulted (uv tool / pipx / pip --user) even when the server's
   *  PATH omits it. */
  const whichOr = (cmd: string): string | null => {
    const dirs = [
      ...(process.env.PATH ?? "").split(delimiter).filter(Boolean),
      join(homedir(), ".local", "bin"),
    ];
    for (const dir of dirs) {
      const cand = join(dir, cmd);
      try {
        if (statSync(cand).isFile()) return cand;
      } catch {
        // keep scanning
      }
    }
    return null;
  };

  /** Return the module name if `python -c 'import mod'` succeeds, else null. */
  const probeModule = (py: string, mod: string): string | null => {
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
  };

  // --- changeset scoping (ENF-CHANGESET-VERDICT) --------------------------
  // The after-gate must count only what THIS dispatch changed, not the whole
  // tree. The before-hook records a marker (clock + HEAD + session); the
  // after-hook resolves it against the subagent's child sessions:
  //   children found in window → their completed edit/write filePaths
  //     (--changed ...; a child with no edits → trusted-empty --scope)
  //   children/messages unusable → --since-ref <dispatch HEAD> (coarser,
  //     still attributable)
  //   no marker, no git → no scope flags (today's tree verdict)
  // Failures never block the report: worst case degrades to tree mode.

  /** callID (or sessionID) → dispatch-time marker. Deleted by the after-hook
   *  or on a blocked dispatch; the cap bounds leaks from crashed hooks.
   *  dispatchId is the join key across the before/after pair, the CLI's
   *  --dispatch-id stamp, and the durable ledger record (O1, v3 §1). */
  const markers = new Map<string, { sinceMs: number; head: string | null; sessionID: string; dispatchId: string }>();

  /** Durable O1 engagement record: one synchronous append per task-gate
   *  phase invocation, written to <store>/.zft/gates-hook/taskgate.jsonl
   *  BEFORE the subagent spawns (before phase), so a router-400 or an
   *  externally killed session can no longer erase the proof that a gated
   *  dispatch started (the v2 config-G class). exit 1 is an enforcement
   *  event, never engagement. A ledger write failure warns and fails open —
   *  it must never break a dispatch. */
  const emitTaskgate = (rec: {
    phase: "before" | "after" | "session-gate";
    dispatchId?: string;
    sinceMs?: number;
    durationMs?: number;
    exit?: number;
    decision?: string;
    subagent?: string;
    sessionID?: string;
  }): void => {
    try {
      const dir = join(directory, ".zft", "gates-hook");
      mkdirSync(dir, { recursive: true });
      const line = JSON.stringify({ ts: new Date().toISOString(), event: "task-gate", ...rec });
      appendFileSync(join(dir, "taskgate.jsonl"), `${line}\n`);
    } catch (e) {
      warn(`taskgate ledger write failed (${e instanceof Error ? e.message : String(e)})`);
    }
  };

  const markerKey = (input: unknown): string => {
    const i = (input ?? {}) as Record<string, unknown>;
    const call = i.callID != null && i.callID !== "" ? String(i.callID) : "";
    const sess = sessionOf(input);
    return call ? `c:${call}` : sess ? `s:${sess}` : "";
  };

  // --- session-binding gate -------------------------------------------------
  // Desired behavior: every writer works under a recorded contract binding —
  // a subagent dispatch is one binding path, never the only one. A main-
  // session edit on a deliverable path (anything outside .zft/**) before any
  // binding is blocked with a typed hint; the agent binds via
  // `zft task-gate before --subagent main --description "[contract: n] ..."`
  // (or "[ungated: reason]") and retries. Binding evidence: the CLI's own
  // audit.log record (phase before, subagent main, gated or override) or a
  // gated dispatch in this process. Only exit-1-style policy blocks; fs
  // faults fail open — a plugin error must never take the session down.

  const sessionEpoch = Date.now();
  /** Sessions bound in memory: a task dispatch this gate allowed. */
  const boundSessions = new Set<string>();
  /** Negative-scan throttle: audit.log is rescanned at most every 2 s per
   *  session so the bind-then-retry loop stays instant but cheap. */
  const lastScan = new Map<string, number>();
  let overrideWarned = false;

  /** A main-session binding record: phase before + subagent main, since the
   *  plugin epoch (with a 2 s grace: a record written in the load race —
   *  same wall-clock millisecond region as this module's init — is still
   *  this session's binding, not a stale one). gated or explicitly
   *  overridden; read-only/blocked records never bind. Scans the JSONL tail
   *  only (bounded work per edit). */
  const mainBindingInAudit = (): boolean => {
    try {
      const f = join(directory, ".zft", "audit.log");
      if (!existsSync(f)) return false;
      const lines = readFileSync(f, "utf8").split("\n").filter(Boolean);
      for (let i = lines.length - 1; i >= 0 && i >= lines.length - 200; i--) {
        try {
          const r = JSON.parse(lines[i]) as Record<string, unknown>;
          if (r.phase !== "before" || r.subagent !== "main") continue;
          const ts = typeof r.ts === "number" ? r.ts : Date.parse(String(r.ts));
          if (!Number.isFinite(ts) || ts < sessionEpoch - 2000) continue;
          if (r.gated === true || r.override === true) return true;
        } catch { /* one torn line never gates */ }
      }
      return false;
    } catch (e) {
      warn(`session-gate audit scan failed (${e instanceof Error ? e.message : String(e)}) — failing open`);
      return true;
    }
  };

  const sessionGate = (input: unknown, output: unknown): void => {
    if (!active()) return;
    const args = ((output as Record<string, unknown>)?.args ?? {}) as Record<string, unknown>;
    const fp = typeof args.filePath === "string" ? args.filePath : "";
    if (!fp) return; // unclassifiable: the lint gate judges post-hoc
    const rel = rootRelative(fp);
    if (rel === null) return; // outside this store root
    if (rel.startsWith(".zft/") || rel === ".zft") return; // store corpus: lint gate domain
    if (process.env.ZFT_ALLOW_UNGATED === "1") {
      if (!overrideWarned) {
        overrideWarned = true;
        warn("ZFT_ALLOW_UNGATED=1 — main-session deliverable edits pass ungated (audited by policy, not here)");
      }
      return;
    }
    const sessionID = sessionOf(input);
    if (sessionID && boundSessions.has(sessionID)) return;
    const now = Date.now();
    const last = lastScan.get(sessionID) ?? 0;
    if (now - last >= 2000) {
      lastScan.set(sessionID, now);
      if (mainBindingInAudit()) {
        if (sessionID) boundSessions.add(sessionID);
        emitTaskgate({ phase: "session-gate", decision: "allow",
                       subagent: "main", sessionID });
        return;
      }
    } else if (lastScan.has(sessionID)) {
      // within the throttle window after a failed scan: still unbound
      throw new GateBlock(sessionGateHint());
    }
    throw new GateBlock(sessionGateHint());
  };

  const sessionGateHint = (): string =>
    `${TAG} session-gate: deliverable edit before any contract binding.\n` +
    `Bind this session's work, then retry the edit:\n` +
    `  zft task-gate before --subagent main --description "[contract: <name>] <what>"\n` +
    `or mark it deliberately ungated:\n` +
    `  zft task-gate before --subagent main --description "[ungated: <reason>]"\n` +
    `(dispatching a subagent with [contract: <name>] also binds the session)`;


  const sessionOf = (input: unknown): string => {
    const i = (input ?? {}) as Record<string, unknown>;
    return i.sessionID != null && i.sessionID !== "" ? String(i.sessionID) : "";
  };

  /** HEAD at dispatch time; null outside a git repo (unusable as a ref). */
  const gitHead = (): string | null => {
    try {
      const res = spawnSync("git", ["rev-parse", "HEAD"], {
        cwd: directory,
        encoding: "utf8",
        timeout: 5_000,
        env: { ...process.env },
      });
      if (res.error || res.status !== 0) return null;
      const sha = (res.stdout ?? "").trim();
      return /^[0-9a-f]{7,64}$/.test(sha) ? sha : null;
    } catch {
      return null;
    }
  };

  /** opencode stamps time.created in ms; older paths used seconds — the
   *  unit is inferred so a seconds clock cannot silently empty the window. */
  const epochMs = (n: unknown): number => {
    if (typeof n !== "number" || !Number.isFinite(n) || n <= 0) return 0;
    return n < 1e12 ? n * 1000 : n;
  };

  /** Workspace-relative posix path, or null when the path leaves the root. */
  const rootRelative = (p: string): string | null => {
    try {
      const abs = isAbsolute(p) ? p : join(directory, p);
      const rel = relative(directory, abs);
      if (!rel || rel.startsWith("..") || isAbsolute(rel)) return null;
      return rel.split(sep).join("/");
    } catch {
      return null;
    }
  };

  /** Files edited by the subagent's sessions since dispatch; null = unknown
   *  (enumeration failed or nothing found — caller falls back). A child that
   *  ran but edited nothing is a TRUSTED empty changeset ([]), not unknown. */
  const changedSince = async (
    sessionID: string,
    sinceMs: number,
  ): Promise<string[] | null> => {
    try {
      const sess = (client as {
        session?: {
          children?: (a: { sessionID: string }) => Promise<unknown>;
          messages?: (a: { sessionID: string }) => Promise<unknown>;
        };
      }).session;
      if (!sessionID || !sess?.children || !sess?.messages) return null;
      const children = ((await sess.children({ sessionID })) ?? []) as Array<{
        id?: string;
        time?: { created?: number };
      }>;
      const inWindow = children.filter((c) => epochMs(c?.time?.created) >= sinceMs);
      if (inWindow.length === 0) return null; // dispatch not visible → fallback
      const out = new Set<string>();
      for (const child of inWindow) {
        if (!child?.id) continue;
        const msgs = ((await sess.messages({ sessionID: child.id })) ?? []) as Array<{
          parts?: Array<Record<string, unknown>>;
        }>;
        for (const msg of msgs) {
          for (const part of msg?.parts ?? []) {
            if (part?.type !== "tool") continue;
            const tool = String(part.tool ?? "");
            // apply_patch carries patchText, not filePath — it escapes this
            // scope (conservative: under-scoped → clauses stay missing).
            if (tool !== "edit" && tool !== "write") continue;
            const state = part.state as
              | { status?: string; input?: Record<string, unknown> }
              | undefined;
            if (state?.status !== "completed") continue;
            const fp = state.input?.filePath;
            if (typeof fp !== "string" || !fp) continue;
            const rel = rootRelative(fp);
            if (rel) out.add(rel);
          }
        }
      }
      return [...out].sort();
    } catch (e) {
      warn(
        `changeset enumeration failed (${e instanceof Error ? e.message : String(e)}) — ` +
          "falling back",
      );
      return null;
    }
  };

  /** Marker → task-gate scope flags; consumes the marker and returns it so
   *  the after-hook can stamp the ledger record with the same dispatch
   *  identity the before phase recorded. */
  const scopeArgsFor = async (
    key: string,
  ): Promise<{ marker: { sinceMs: number; head: string | null; sessionID: string; dispatchId: string } | null; args: string[] }> => {
    const marker = markers.get(key) ?? null;
    markers.delete(key);
    if (!marker) return { marker: null, args: [] };
    try {
      const paths = await changedSince(marker.sessionID, marker.sinceMs);
      if (paths === null)
        return { marker, args: marker.head ? ["--since-ref", marker.head] : [] };
      if (paths.length === 0) return { marker, args: ["--scope", "changeset"] };
      return { marker, args: paths.flatMap((p) => ["--changed", p]) };
    } catch {
      return { marker, args: marker.head ? ["--since-ref", marker.head] : [] };
    }
  };

  /** Run the CLI once, timing the spawn; returns undefined (after warning)
   *  if it could not run. durationMs is exactly what the harness imposes on
   *  the dispatch: the synchronous wall time the orchestrator waits on the
   *  gate (O1, v3 §1). */
  const runGate = (
    phase: "before" | "after",
    subagent: string,
    description: string,
    rules?: Rule[],
    extra: string[] = [],
  ) => {
    try {
      const gate = resolveGate();
      if (!gate) {
        warn(`no zft executable (${phase}): set ZFT_BIN or install it ` +
             "(`uv tool install zft` / `pipx install zft` / `pip install zft`) — failing open");
        return undefined;
      }
      const argv = [
        ...gate,
        "task-gate",
        phase,
        "--subagent",
        subagent,
        "--description",
        description,
      ];
      if (rules) argv.push("--capability", JSON.stringify(rules));
      argv.push(...extra);
      const t0 = Date.now();
      const res = spawnSync(argv[0], argv.slice(1), {
        cwd: directory,
        encoding: "utf8",
        timeout: GATE_TIMEOUT_MS,
        // Node inherits process.env by default; Bun's node:child_process
        // compat does NOT inherit process.env mutations made after process
        // start, so pass the current env explicitly (no-op on Node).
        env: { ...process.env },
      });
      return { res, durationMs: Date.now() - t0 };
    } catch (e) {
      warn(`internal error (${phase}): ${e instanceof Error ? e.message : String(e)} — failing open`);
      return undefined;
    }
  };

  return {
    "tool.execute.before": async (input, output) => {
      try {
        const tool = input.tool;
        if (!active()) return;
        if (tool === "edit" || tool === "write") {
          // session-binding boundary: deliverable edits need a recorded
          // contract binding (dispatch, manual task-gate, or override)
          try {
            sessionGate(input, output);
          } catch (e) {
            if (e instanceof GateBlock) {
              emitTaskgate({ phase: "session-gate", decision: "block",
                             subagent: "main", sessionID: sessionOf(input) });
            }
            throw e;
          }
          return;
        }
        if (tool !== "task") return;
        const args = (output.args ?? {}) as Record<string, unknown>;
        const subagent = String(args.subagent_type ?? "");
        const description = String(args.description ?? "");
        const rules = await resolveRules(subagent);
        await debug(`dispatch ${subagent}: rules=${JSON.stringify(rules ?? null)}`);
        const key = markerKey(input);
        const sessionID = sessionOf(input);
        const dispatchId = randomUUID();
        let sinceMs = Date.now();
        if (key) {
          if (markers.size > 128) markers.clear();
          markers.set(key, { sinceMs, head: gitHead(), sessionID, dispatchId });
        }
        const run = runGate("before", subagent, description, rules,
                            ["--dispatch-id", dispatchId]);
        if (!run || run.res.error) {
          warn(`internal error (before): ${run?.res.error?.message ?? "spawn failed"} — failing open`);
          return; // never block on an internal error
        }
        // durable engagement/enforcement evidence, on disk before any
        // subagent spawns (a blocked exit 1 is an enforcement event)
        emitTaskgate({ phase: "before", dispatchId, sinceMs,
                       durationMs: run.durationMs, exit: run.res.status,
                       subagent, sessionID });
        if (run.res.status === 1) {
          markers.delete(key); // dispatch aborted; no after-hook will consume it
          const detail = [run.res.stdout, run.res.stderr]
            .map((s) => s.trim())
            .filter(Boolean)
            .join("\n");
          throw new GateBlock(`${TAG} dispatch blocked by task gate:\n${detail}`);
        }
        if (run.res.status !== 0) {
          warn(`unexpected exit code ${run.res.status} (before) — failing open`);
        }
        // an allowed dispatch binds the orchestrating session: its own
        // deliverable edits then pass the session-binding gate
        if (run.res.status === 0 && sessionID) boundSessions.add(sessionID);
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
        const subagent = String(args.subagent_type ?? "");
        const description = String(args.description ?? "");
        const rules = await resolveRules(subagent);
        const { marker, args: scopeArgs } = await scopeArgsFor(markerKey(input));
        const dispatchId = marker?.dispatchId ?? randomUUID();
        const sinceMs = marker?.sinceMs ?? Date.now();
        const run = runGate("after", subagent, description, rules, [
          ...scopeArgs,
          "--dispatch-id", dispatchId,
          "--since-ms", String(sinceMs),
        ]);
        if (!run) return; // already warned
        if (run.res.error) {
          warn(`internal error (after): ${run.res.error.message} — ignoring`);
          return; // non-blocking
        }
        emitTaskgate({ phase: "after", dispatchId, sinceMs,
                       durationMs: run.durationMs, exit: run.res.status,
                       subagent, sessionID: sessionOf(input) });
        // 0 = verdict green; 1 = verdict with missing clauses (still a
        // report the orchestrator needs); 2/other = internal error.
        if (run.res.status !== 0 && run.res.status !== 1) {
          warn(`unexpected exit code ${run.res.status} (after) — ignoring`);
          return;
        }
        const out = (run.res.stdout ?? "").trim();
        if (!out) return;
        const tag =
          run.res.status === 1
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
