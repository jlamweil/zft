/**
 * Regression + contract tests for the shape-safety of zft-gate.ts.
 *
 * The opencode SDK client injected into a plugin resolves to a RESPONSE
 * ENVELOPE — `{ data, error, request, response }` (responseStyle "fields") —
 * never the bare payload. Verified live against the real `@opencode-ai/sdk`.
 * So `await client.app.agents()` is `{data:[...],request,response}` and
 * `Array.isArray(x)` is always false. Treating the return as an array
 * surfaced as:
 *   [zft-gate] agent lookup failed ({} is not iterable) — falling back ...
 *   [zft gate] changeset enumeration failed. — falling back
 *
 * The gate now unwraps `.data` (accepting a bare array too) and reports a
 * failed call's server error legibly instead of a vague "non-array", so a
 * changed opencode surface is correctable from the log text alone.
 *
 * These tests import the REAL plugin module and drive the actual task-gate
 * before/after hooks with a mocked client, so they verify behavior, not the
 * fix's copy. Run:  bun test tests/ts/ (in this repo).
 */
import { describe, it, expect, afterEach } from "bun:test";
import { mkdirSync, mkdtempSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PLUGIN = join(import.meta.dir, "..", "..", ".opencode", "plugins", "zft-gate.ts");
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

/** The envelope an SDK call really resolves to (responseStyle "fields"). */
const sdkOk = (data: unknown) => ({ data, request: {}, response: {} });
const sdkErr = (name: string, message: string, ref: string) => ({
  error: { name, data: { message, ref } },
  request: {},
  response: {},
});

afterEach(() => {
  delete process.env.ZFT_BIN;
  delete process.env.ZFT_HOOK_MODE;
});

describe("zft-gate client-API shape safety", () => {
  it("agents() success envelope {data:[...]} is unwrapped — no diagnostic", async () => {
    const w = makeWorkdir();
    const cap = captureWarn();
    const client = {
      app: {
        agents: async () => sdkOk([{ name: "fixer", permission: [] }]),
        log: async () => {},
      },
      session: {},
      tool: { execute: {} },
    } as never;
    const reg = await loadGate(w, client);
    await reg["tool.execute.before"](taskInput(), taskOutput(false));
    const warns = cap.stop();
    expect(warns).not.toContain("client.app.agents()");
    expect(warns).not.toContain("lanes");
    expect(warns).not.toContain("is not iterable");
  });

  it("agents() malformed value degrades with a legible diagnostic (no 'not iterable')", async () => {
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
    expect(warns).toContain("client.app.agents() unusable");
    expect(warns).toContain("response had no data array");
    expect(warns).not.toContain("is not iterable");
    expect(warns).not.toContain("agent lookup failed");
  });

  it("session.children() error envelope names the server error (no generic crash)", async () => {
    const w = makeWorkdir();
    const cap = captureWarn();
    const client = {
      app: { agents: async () => sdkOk([{ name: "fixer", permission: [] }]), log: async () => {} },
      session: {
        children: async () => sdkErr("UnknownError", "Unexpected server error", "err_bcd9b89e"),
        messages: async () => sdkOk([]),
      },
      tool: { execute: {} },
    } as never;
    const reg = await loadGate(w, client);
    await reg["tool.execute.before"](taskInput(), taskOutput(false));
    await reg["tool.execute.after"](taskInput(), taskOutput(true));
    const warns = cap.stop();
    expect(warns).toContain("session.children() unusable");
    expect(warns).toContain("UnknownError");
    expect(warns).toContain("err_bcd9b89e");
    expect(warns).not.toContain("changeset enumeration failed");
  });

  it("children()/messages() success envelopes scope a real changeset — no diagnostic", async () => {
    const w = makeWorkdir();
    mkdirSync(join(w, "src"), { recursive: true });
    const cap = captureWarn();
    const client = {
      app: { agents: async () => sdkOk([{ name: "fixer", permission: [] }]), log: async () => {} },
      session: {
        children: async () => sdkOk([{ id: "child-9", time: { created: Date.now() } }]),
        messages: async () =>
          sdkOk([
            {
              parts: [
                {
                  type: "tool",
                  tool: "edit",
                  state: { status: "completed", input: { filePath: join(w, "src/a.ts") } },
                },
              ],
            },
          ]),
      },
      tool: { execute: {} },
    } as never;
    const reg = await loadGate(w, client);
    await reg["tool.execute.before"](taskInput(), taskOutput(false));
    await reg["tool.execute.after"](taskInput(), taskOutput(true));
    const warns = cap.stop();
    expect(warns).not.toMatch(/non-array|unavailable|not iterable|enumeration failed|unusable/s);
  });

  it("legacy bare-array surfaces still work (back-compat)", async () => {
    const w = makeWorkdir();
    mkdirSync(join(w, "src"), { recursive: true });
    const cap = captureWarn();
    const client = {
      app: { agents: async () => [{ name: "fixer", permission: [] }], log: async () => {} },
      session: {
        children: async () => [{ id: "child-1", time: { created: Date.now() } }],
        messages: async () => [
          {
            parts: [
              {
                type: "tool",
                tool: "write",
                state: { status: "completed", input: { filePath: join(w, "src/b.ts") } },
              },
            ],
          },
        ],
      },
      tool: { execute: {} },
    } as never;
    const reg = await loadGate(w, client);
    await reg["tool.execute.before"](taskInput(), taskOutput(false));
    await reg["tool.execute.after"](taskInput(), taskOutput(true));
    const warns = cap.stop();
    expect(warns).not.toMatch(/non-array|unavailable|not iterable|enumeration failed|unusable/s);
  });
});
