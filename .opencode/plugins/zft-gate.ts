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

const hookMode = (): "observe" | "enforce" =>
  process.env.ZFT_HOOK_MODE === "enforce" ? "enforce" : "observe";

/** Compact, safe description of an API-returned value for diagnostics — the
 *  shape of what came back, so a changed opencode client surface is correctable
 *  from the warning text alone. Never throws (JSON.stringify can on cycles). */
const describe = (v: unknown): string => {
  if (v === null || v === undefined) return String(v);
  if (Array.isArray(v)) return `Array(${v.length})`;
  if (typeof v === "object") {
    try {
      const s = JSON.stringify(v);
      if (!s || s.length <= 200) return s ?? "Object";
      return `${s.slice(0, 200)}…(+${s.length - 200})`;
    } catch {
      return `Object{${Object.keys(v as Record<string, unknown>).join(",")}}`;
    }
  }
  return `${typeof v}(${JSON.stringify(String(v).slice(0, 100))})`;
};

/** Unwrap an opencode SDK result envelope. SDK methods return `{data}` on
 *  success and `{error}` on failure (RequestResult, "fields" style); a bare
 *  payload (older hosts) passes through. An error envelope is thrown so the
 *  caller's catch reports the server's message instead of a generic
 *  non-array warning. */
const unwrapSdk = (res: unknown): unknown => {
  if (res && typeof res === "object" && !Array.isArray(res)) {
    const r = res as Record<string, unknown>;
    if ("data" in r && r.data === undefined && r.error !== undefined) {
      throw new Error(`SDK call failed: ${describe(r.error)}`);
    }
    if ("data" in r) return r.data;
  }
  return res;
};

/** Paths an Aider-format opencode `apply_patch` writes (Gap 002 — the real
 *  patch format is `*** Add File: <path>` / `*** Update File: <path>` /
 *  `*** Move to: <path>`; the latter is a rename TARGET that must be judged).
 *  `*** Delete File:` lines write nothing — skipped, like /dev/null — and
 *  results are deduped. */
const parsePatchPaths = (patchText: string): string[] => {
  const seen = new Set<string>();
  for (const line of patchText.split("\n")) {
    const m = line.match(/^\*\*\*\s+(?:Add File|Update File|Move to):\s*(\S+)\s*$/);
    if (!m) continue;
    const p = m[1];
    if (p === "/dev/null") continue;
    seen.add(p);
  }
  return [...seen];
};

/** Changed file paths for a write tool (edit/write/apply_patch) — the set the
 *  after-phase L2 verdict gates. apply_patch carries no filePath, so its paths
 *  are parsed from the patch (Gap 002: it escaped the gate entirely). Real
 *  opencode patches are Aider `***` format (parsePatchPaths); the unified-diff
 *  parse stays as a fallback for non-opencode patch text. */
const changedPathsFor = (tool: string, args: unknown): string[] => {
  const a = (args ?? {}) as Record<string, unknown>;
  if (tool === "edit" || tool === "write") {
    const fp = a.filePath;
    return typeof fp === "string" && fp.trim() ? [fp] : [];
  }
  if (tool === "apply_patch") {
    const text = typeof a.patchText === "string" ? a.patchText : "";
    const aider = parsePatchPaths(text);
    if (aider.length) return aider;
    const seen = new Set<string>();
    for (const line of text.split("\n")) {
      const m = line.match(/^(?:diff --git a\/(\S+) b\/\S+|--- a\/(\S+)|\+\+\+ b\/(\S+))/);
      const p = m ? (m[1] ?? m[2] ?? m[3]) : undefined;
      if (p && p !== "/dev/null") seen.add(p);
    }
    return [...seen];
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
        // unwrapSdk like the 0.3.1 changeset-enumeration fix: the SDK returns
        // a {data: [...]}/error envelope, not a bare list (parity with
        // session.children/messages below).
        const agents = unwrapSdk(await client.app.agents());
        if (!Array.isArray(agents)) {
          // A changed opencode surface (e.g. {} when it used to be a list) must
          // be legible from the log, not just swallowed as a generic fallback.
          warn(
            `agent lookup: client.app.agents() returned non-array ` +
              `${describe(agents)} — falling back to lane-name classification`,
          );
        }
        const rules = new Map<string, Rule[]>();
        for (const a of (Array.isArray(agents)
          ? agents
          : []) as Array<{ name?: string; permission?: unknown }>) {
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
    // Last resort: run the module directly.
    const py = whichOr("python3") || whichOr("python");
    if (py) {
      const mod = probeModule(py, "zft.cli.main");
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
  /** Sessions bound in memory: a task dispatch this gate allowed, or a
   *  manual `zft task-gate before --subagent main` record the audit scan
   *  found. The binding kind + contract/reason are retained so the
   *  direct-write after-gate can name them in its governance description
   *  (P-012 C2): `[contract: X]` / `[ungated: r]`. */
  const boundSessions = new Map<string, { kind: "contract" | "ungated"; contract?: string; reason?: string }>();
  /** Negative-scan throttle: audit.log is rescanned at most every 2 s per
   *  session so the bind-then-retry loop stays instant but cheap. */
  const lastScan = new Map<string, number>();
  let overrideWarned = false;

  /** A main-session binding record: phase before + subagent main, since the
   *  plugin epoch (with a 2 s grace: a record written in the load race —
   *  same wall-clock millisecond region as this module's init — is still
   *  this session's binding, not a stale one). gated or explicitly
   *  overridden; read-only/blocked records never bind. The binding kind and
   *  contract/reason (r.contract / r.override / r.reason) are returned so
   *  the after-gate can name them. Scans the JSONL tail only (bounded work
   *  per edit); a scan error fails open as bound. */
  const mainBindingInAudit = (): {
    found: boolean;
    contract: string | null;
    override: boolean;
    reason?: string;
  } => {
    try {
      const f = join(directory, ".zft", "audit.log");
      if (!existsSync(f)) return { found: false, contract: null, override: false };
      const lines = readFileSync(f, "utf8").split("\n").filter(Boolean);
      for (let i = lines.length - 1; i >= 0 && i >= lines.length - 200; i--) {
        try {
          const r = JSON.parse(lines[i]) as Record<string, unknown>;
          if (r.phase !== "before" || r.subagent !== "main") continue;
          const ts = typeof r.ts === "number" ? r.ts : Date.parse(String(r.ts));
          if (!Number.isFinite(ts) || ts < sessionEpoch - 2000) continue;
          if (r.gated === true || r.override === true) {
            return {
              found: true,
              contract: typeof r.contract === "string" ? r.contract : null,
              override: r.override === true,
              reason: typeof r.reason === "string" ? r.reason : undefined,
            };
          }
        } catch { /* one torn line never gates */ }
      }
      return { found: false, contract: null, override: false };
    } catch (e) {
      warn(`session-gate audit scan failed (${e instanceof Error ? e.message : String(e)}) — failing open`);
      return { found: true, contract: null, override: false };
    }
  };

  /** Session-binding check for ONE deliverable path. edit/write pass
   *  output.args.filePath; apply_patch passes each parsed patch path, so an
   *  unbound multi-file patch is blocked on its first deliverable path.
   *  Returns normally when the path is out of scope (store corpus / outside
   *  root / unclassifiable) or the session is bound; throws GateBlock
   *  otherwise. */
  const sessionGatePath = (input: unknown, fp: string): void => {
    if (!active()) return;
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
      const binding = mainBindingInAudit();
      if (binding.found) {
        if (sessionID) {
          // audit records carry contract/override/reason; a scan that
          // failed open has none — still a binding, named as such
          boundSessions.set(sessionID, binding.contract
            ? { kind: "contract", contract: binding.contract }
            : { kind: "ungated", reason: binding.reason ?? "bound via manual binding" });
        }
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
          // The SDK's generated methods take the URL template's path params
          // under `path` (SessionChildrenData = {path:{id}, query:{directory}}).
          // A flat `{sessionID}` leaves `{id}` literal in the URL and the
          // server answers "Expected a string starting with \"ses\", got
          // \"%7Bid%7D\"".
          children?: (a: {
            path: { id: string };
            query?: { directory?: string };
          }) => Promise<unknown>;
          messages?: (a: {
            path: { id: string };
            query?: { directory?: string };
          }) => Promise<unknown>;
        };
      }).session;
      if (!sessionID || !sess?.children || !sess?.messages) {
        const missing = [
          !sess ? "session" : null,
          sess && !sess.children ? "children" : null,
          sess && !sess.messages ? "messages" : null,
        ].filter(Boolean);
        warn(
          `changeset enumeration: session API unavailable (missing: ` +
            `${missing.join(",")}) — falling back`,
        );
        return null;
      }
      const children = unwrapSdk(await sess.children({
        path: { id: sessionID },
        query: { directory },
      }));
      if (!Array.isArray(children)) {
        warn(
          `changeset enumeration: session.children() returned non-array ` +
            `${describe(children)} — falling back`,
        );
        return null;
      }
      const inWindow = (children as Array<{
        id?: string;
        time?: { created?: number };
      }>).filter((c) => epochMs(c?.time?.created) >= sinceMs);
      if (inWindow.length === 0) return null; // dispatch not visible → fallback
      const out = new Set<string>();
      for (const child of inWindow) {
        if (!child?.id) continue;
        const msgs = unwrapSdk(await sess.messages({
          path: { id: child.id },
          query: { directory },
        }));
        if (!Array.isArray(msgs)) {
          warn(
            `changeset enumeration: session.messages() returned non-array ` +
              `${describe(msgs)} — falling back`,
          );
          return null;
        }
        for (const msg of msgs as Array<{ parts?: Array<Record<string, unknown>> }>) {
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
        if (hookMode() === "enforce") {
          throw new GateBlock(
            `${TAG} gate unavailable — enforcing (fail-closed); set ZFT_BIN or install zft`);
        }
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
      if (e instanceof GateBlock) throw e; // deliberate enforce block (fail-closed)
      warn(`internal error (${phase}): ${e instanceof Error ? e.message : String(e)} — failing open`);
      return undefined;
    }
  };

  return {
    "tool.execute.before": async (input, output) => {
      try {
        const tool = input.tool;
        if (!active()) return;
        if (tool === "edit" || tool === "write" || tool === "apply_patch") {
          // session-binding boundary: deliverable writes need a recorded
          // contract binding (dispatch, manual task-gate, or override).
          // apply_patch carries patchText, not filePath — one check per
          // parsed path (Gap 002: the patch bypassed the gate entirely).
          const oargs = ((output as Record<string, unknown>)?.args ?? {}) as Record<string, unknown>;
          const paths =
            tool === "apply_patch" && typeof oargs.patchText === "string"
              ? parsePatchPaths(oargs.patchText)
              : [typeof oargs.filePath === "string" ? oargs.filePath : ""];
          try {
            for (const fp of paths) sessionGatePath(input, fp);
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
          if (hookMode() === "enforce") {
            throw new GateBlock(
              `${TAG} gate failed to run (before) — enforcing (fail-closed): ` +
              `${run?.res.error?.message ?? "spawn failed"}`);
          }
          warn(`internal error (before): ${run?.res.error?.message ?? "spawn failed"} — failing open`);
          return; // never block on an internal error (observe mode)
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
        // deliverable edits then pass the session-binding gate. The before
        // stdout is a JSON verdict ({allow, gated, contract, reason, ...})
        // — the binding kind is retained for the after-gate's governance
        // description (P-012 C2).
        if (run.res.status === 0 && sessionID) {
          let binding: { kind: "contract" | "ungated"; contract?: string; reason?: string } | undefined;
          try {
            const j = JSON.parse(String(run.res.stdout ?? "").trim()) as Record<string, unknown>;
            // A read-only lane dispatch is not an authorization for the main
            // session to write: only a writer-lane dispatch (gated by a
            // contract, or explicitly ungated) binds the session. Binding on
            // a read-only dispatch let oracle/explorer grant ungated
            // deliverable writes.
            if (j.lane === "readonly") {
              binding = undefined;
            } else {
              const contract = typeof j.contract === "string" && j.contract ? j.contract : null;
              const reason = typeof j.reason === "string" && j.reason ? j.reason : null;
              binding = contract
                ? { kind: "contract", contract }
                : { kind: "ungated", reason: reason ?? "bound via dispatch" };
            }
          } catch {
            binding = { kind: "ungated", reason: "unparseable gate output" };
          }
          if (binding) boundSessions.set(sessionID, binding);
        }
      } catch (e) {
        if (e instanceof GateBlock) throw e; // deliberate policy block
        warn(`hook error (before): ${e instanceof Error ? e.message : String(e)} — failing open`);
      }
    },

    "tool.execute.after": async (input, output) => {
      try {
        if (!active()) return;
        const tool = input.tool;
        const direct = tool === "edit" || tool === "write" || tool === "apply_patch";
        if (tool !== "task" && !direct) return;
        const args = (input.args ?? {}) as Record<string, unknown>;
        let subagent: string;
        let description: string;
        let rules: Rule[] | undefined;
        let scopeArgs: string[];
        let dispatchId: string;
        let sinceMs: number;
        if (tool === "task") {
          if (typeof output.output !== "string") return;
          subagent = String(args.subagent_type ?? "");
          description = String(args.description ?? "");
          rules = await resolveRules(subagent);
          const scope = await scopeArgsFor(markerKey(input));
          scopeArgs = scope.args;
          dispatchId = scope.marker?.dispatchId ?? randomUUID();
          sinceMs = scope.marker?.sinceMs ?? Date.now();
        } else {
          // direct write (edit/write/apply_patch): a governance verdict
          // (P-012 C1/C2) — is this write under a recorded binding? No
          // dispatch marker; a fresh dispatchId stands alone as the record's
          // identity. (Gap 002 — the after-verdict was task-only until
          // C5; apply_patch paths come from parsePatchPaths.)
          const changed = changedPathsFor(tool, args);
          if (!changed.length) return;
          // store corpus (.zft/**): the lint gate is the judge — every
          // changed path under .zft/ skips the after-gate entirely (no
          // spawn, no ledger record). Mixed corpus + deliverable still
          // gates over all paths.
          const rels = changed.map((p) => rootRelative(p)).filter((r): r is string => r !== null);
          // Nothing inside this store's root: a write outside the workspace is
          // not a deliverable. The session gate already exempts it
          // (rootRelative === null), so the after-gate must not invent an
          // ungoverned-write verdict for it.
          if (rels.length === 0) return;
          if (rels.every((r) => r.startsWith(".zft/") || r === ".zft")) return;
          subagent = "main";
          // the description carries the binding marker so `--governance`
          // can name it: [contract: X] / [ungated: r] / bare (ungoverned
          // session → the CLI's exit-2 no-contract error stays live, the
          // Gap-002 signal)
          const directSessionID = sessionOf(input);
          let binding = directSessionID ? boundSessions.get(directSessionID) : undefined;
          if (!binding) {
            // Disk fallback — the SAME source of truth the session-gate used to
            // allow this write. The in-memory map is keyed by sessionOf(input);
            // when that key is absent for a direct write (a manual/CLI binding
            // the session-gate allowed from disk, or a PostToolUse input not
            // carrying the same session identity), the miss must not be read
            // as "ungoverned" — that records a false 'error' after-verdict
            // instead of the binding's own contract/ungated verdict.
            const onDisk = mainBindingInAudit();
            if (onDisk.found) {
              binding = onDisk.contract
                ? { kind: "contract", contract: onDisk.contract }
                : { kind: "ungated", reason: onDisk.reason ?? "bound via manual binding" };
              if (directSessionID) boundSessions.set(directSessionID, binding);
            }
          }
          const sanitize = (s: string): string =>
            s.replace(/[\r\n]+/g, " ").trim().slice(0, 200);
          description = !binding
            ? `direct ${tool}`
            : binding.kind === "contract"
              ? `[contract: ${sanitize(binding.contract ?? "")}] direct ${tool}`
              : `[ungated: ${sanitize(binding.reason ?? "bound via dispatch")}] direct ${tool}`;
          scopeArgs = changed.flatMap((p) => ["--changed", p]);
          dispatchId = randomUUID();
          sinceMs = Date.now();
        }
        const run = runGate("after", subagent, description, rules, [
          ...scopeArgs,
          ...(tool === "task" ? [] : ["--governance"]), // direct writes only: governance, not coverage
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
        // 0 = green; 1 = missing clauses; 2 = error verdict (no contract
        // reference — the Gap 002 signal); other = internal. Task verdicts
        // are all prepended to the output; direct writes surface exit 2
        // only (the ungoverned-write signal) — exit 0/1 go to the debug
        // log (P-012 C3). Unknown codes are ignored.
        if (run.res.status !== 0 && run.res.status !== 1 && run.res.status !== 2) {
          warn(`unexpected exit code ${run.res.status} (after) — ignoring`);
          return;
        }
        const out = (run.res.stdout ?? "").trim();
        if (!out) return;
        if (tool === "task" && typeof output.output === "string") {
          const tag =
            run.res.status === 1
              ? `${TAG} coverage verdict: MISSING clauses`
              : run.res.status === 2
                ? `${TAG} coverage verdict: ERROR (no contract reference)`
                : `${TAG} coverage verdict`;
          output.output = `${tag}\n${out}\n\n${output.output}`;
        } else if (run.res.status === 2) {
          // direct write: the exit-2 no-contract verdict is the Gap-002
          // signal that the write is not under any binding — it stays
          // surfaced (it can't rewrite the tool result, so it warns).
          // warn() itself prefixes the tag — no double prefix (PoW S3 finding).
          warn(`direct ${tool}: gate verdict\n${out}`);
        } else {
          // direct write: exit 0/1 governance verdicts (bound / ungated)
          // are silent to the TUI (P-012 C3) — the ledger record above is
          // the audit trail; a debug log keeps them recoverable.
          await debug(`direct ${tool}: gate verdict (exit ${run.res.status})\n${out}`);
        }
      } catch (e) {
        // Never escape: the tool result must reach the caller.
        warn(`hook error (after): ${e instanceof Error ? e.message : String(e)} — ignoring`);
      }
    },
  };
};
