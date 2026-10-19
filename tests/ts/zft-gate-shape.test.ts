/**
 * Regression + contract tests for the shape-safety of zft-gate.ts.
 *
 * Two real incidents (2026-10-19) were the SAME bug class: the opencode client
 * API is assumed to return arrays, and `x ?? []` does NOT guard against a
 * non-array truthy value like `{}` — `for (const a of {} ?? [])` throws
 * "{} is not iterable". That surfaced as:
 *   [zft-gate] agent lookup failed ({} is not iterable) — falling back ...
 *   [zft gate] changeset enumeration failed. — falling back
 *
 * Fixed by Array.isArray guards; every degraded path now emits a legible
 * shape diagnostic (which call + what came back via describe()) so a changed
 * opencode surface is correctable from the log text alone.
 *
 * These tests import the REAL plugin module and drive the actual task-gate
 * before/after hooks with a mocked client, so they verify behavior, not the
 * fix's copy. Run:  bun test tests/ts/ (in this repo).
 */
import { describe, it, expect, afterEach } from "bun:test";
import { mkdirSync, mkdtempSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PLUGIN = new URL("../../.opencode/plugins/zft-gate.ts", import.meta.url).pathname;
const TAG = "[zft gate]";

/** Fresh plugin instance: reset the idempotency guard and re-import the module
 *  under a unique specifier so each scenario gets its own closure. */
const loadGate = async (
  dir: string,
  client: unknown,
): Promise<Record<string, (i: unknown, o: unknown) => Promise<void>>> => {
  (globalThis as Record<string, unknown>).__zftGateRegistered = false;
  const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const { ZftGate } = await import(`${PLUGIN}?case=${id}`);
  const hooks = await ZftGate({ directory: dir, client } as never);
  return hooks as Record<string, (i: unknown, o: unknown) => Promise<void>>;
};

const makeWorkdir = (): string => {
  const w = mkdtempSync(join(tmpdir(), "zft-test-"));
  mkdirSync(join(w, ".zft"), { recursive: true });
  const fake = join(w, "fake-zft");
  writeFileSync(
    fake,
    "#!/usr/bin/env node\nconst a=process.argv.slice(2);" +
      "if(a[0]==='task-gate'&&a[1]==='before'){process.stdout.write(JSON.stringify({allow:true,gated:false,contract:null,reason:'test'}));process.exit(0);}" +
      "process.stdout.write(JSON.stringify({verdict:'ok',missing:[]}));process.exit(0);\n",
  );
  chmodSync(fake, 0o755);
  process.env.ZFT_BIN = fake;
  process.env.ZFT_HOOK_MODE = "observe";
  return w;
};

/** Capture [zft gate] stderr warnings; restores original writer on return of
 *  the returned fn. */
const captureWarn = (): { stop: () => string } => {
  let buf = "";
  const w = process.stderr as unknown as {
    write: (...a: unknown[]) => boolean;
  };
  const orig = w.write.bind(process.stderr);
  w.write = ((chunk: unknown) => {
    const s = String(chunk);
    if (s.includes(TAG)) buf += s;
    return true;
  }) as typeof w.write;
  return {
    stop: () => {
      (process.stderr as unknown as { write: typeof w.write }).write = orig as never;
      return buf;
    },
  };
};

const taskInput = (callID = "call-1") => ({ tool: "task", callID, sessionID: "sess-1" });
const taskOutput = (withResult: boolean) =>
  withResult
    ? { args: { subagent_type: "fixer", description: "d" }, output: '{"verdict":"ok"}' }
    : { args: { subagent_type: "fixer", description: "d" } };

afterEach(() => {
  delete process.env.ZFT_BIN;
  delete process.env.ZFT_HOOK_MODE;
});

describe("zft-gate client-API shape safety", () => {
  it("agents(){...} degrades to lane-name classification with a legible diagnostic (no 'not iterable')", async () => {
    const w = makeWorkdir();
    const cap = captureWarn();
    const client = {
      app: { agents: async () => ({}), log: async () => {} },
      session: {}, // unused on this path
      tool: { execute: {} },
    } as never;
    const reg = await loadGate(w, client);
    await reg["tool.execute.before"](taskInput(), taskOutput(false));
    const warns = cap.stop();
    expect(warns).toContain("agent lookup: client.app.agents() returned non-array {}");
    expect(warns).not.toContain("is not iterable");
    expect(warns).not.toContain("agent lookup failed");
  });

  it("session.children(){...} degrades changeset scoping with a legible diagnostic (no generic crash)", async () => {
    const w = makeWorkdir();
    const cap = captureWarn();
    const client = {
      app: { agents: async () => [{ name: "fixer", permission: [] }], log: async () => {} },
      session: { children: async () => ({}), messages: async () => ([]) },
      tool: { execute: {} },
    } as never;
    const reg = await loadGate(w, client);
    await reg["tool.execute.before"](taskInput(), taskOutput(false));
    await reg["tool.execute.after"](taskInput(), taskOutput(true));
    const warns = cap.stop();
    expect(warns).toContain("session.children() returned non-array {}");
    // the specific shape diagnostic replaces the generic catch-all crash
    expect(warns).toContain("returned non-array");
    expect(warns).not.toContain("changeset enumeration failed");
  });

  it("correct array shapes produce NO shape diagnostic and scope a real changeset", async () => {
    const w = makeWorkdir();
    mkdirSync(join(w, "src"), { recursive: true });
    const cap = captureWarn();
    const client = {
      app: { agents: async () => [{ name: "fixer", permission: [] }], log: async () => {} },
      session: {
        children: async () => [{ id: "child-9", time: { created: Date.now() } }],
        messages: async () => [
          { parts: [{ type: "tool", tool: "edit", state: { status: "completed", input: { filePath: join(w, "src/a.ts") } } }] },
        ],
      },
      tool: { execute: {} },
    } as never;
    const reg = await loadGate(w, client);
    await reg["tool.execute.before"](taskInput(), taskOutput(false));
    await reg["tool.execute.after"](taskInput(), taskOutput(true));
    const warns = cap.stop();
    expect(warns).not.toMatch(/non-array|unavailable|not iterable|enumeration failed/s);
  });
});
