/**
 * F8 parity pin: the PACKAGE copy of zft-gate.ts must carry the same
 * client-API shape guards as the deploy copy (87e07a0d). The deploy-side
 * behavior is pinned in tests/ts/zft-gate-shape.test.ts; this file pins
 * the package file so a stale package can never be published again
 * (publish stages from the package dir).
 *
 * Run: bun test packages/opencode-zft/test/zft-gate-package-shape.test.ts
 */
import { describe, it, expect, afterEach } from "bun:test";
import { mkdirSync, mkdtempSync, writeFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const TAG = "[zft gate]";

const loadPackageGate = async (
  dir: string,
  client: unknown,
): Promise<Record<string, (i: unknown, o: unknown) => Promise<void>>> => {
  (globalThis as Record<string, unknown>).__zftGateRegistered = false;
  const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const { ZftGate } = await import(`../zft-gate.ts?case=${id}`);
  const hooks = await ZftGate({ directory: dir, client } as never);
  return hooks as Record<string, (i: unknown, o: unknown) => Promise<void>>;
};

const captureWarn = (): { stop: () => string } => {
  let buf = "";
  const w = process.stderr as unknown as { write: (...a: unknown[]) => boolean };
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

const makeWorkdir = (): string => {
  const w = mkdtempSync(join(tmpdir(), "zftpkg-shape-"));
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

afterEach(() => {
  delete process.env.ZFT_BIN;
  delete process.env.ZFT_HOOK_MODE;
});

describe("package zft-gate client-API shape safety (F8 parity with deploy)", () => {
  it("agents() returning {} degrades with a legible diagnostic, not 'not iterable'", async () => {
    const w = makeWorkdir();
    const cap = captureWarn();
    const client = {
      app: { agents: async () => ({}), log: async () => {} },
      session: {},
      tool: { execute: {} },
    } as never;
    const reg = await loadPackageGate(w, client);
    let threw: unknown = null;
    try {
      await reg["tool.execute.before"](
        { tool: "task", callID: "call-1", sessionID: "sess-1" },
        { args: { subagent_type: "fixer", description: "d" } },
      );
    } catch (e) {
      threw = e;
    }
    const warns = cap.stop();
    if (threw) expect(String(threw)).not.toContain("is not iterable");
    else expect(warns).toContain("returned non-array");
    expect(warns).not.toContain("is not iterable");
  });

  it("agents() {data: [...]} SDK envelope is unwrapped, no fallback warning (0.4.1 fix)", async () => {
    const w = makeWorkdir();
    const cap = captureWarn();
    const client = {
      app: { agents: async () => ({ data: [{ name: "fixer", permission: [] }] }), log: async () => {} },
      session: {},
      tool: { execute: {} },
    } as never;
    const reg = await loadPackageGate(w, client);
    await reg["tool.execute.before"](
      { tool: "task", callID: "call-1", sessionID: "sess-1" },
      { args: { subagent_type: "fixer", description: "d" } },
    );
    const warns = cap.stop();
    expect(warns).not.toMatch(/non-array|lookup failed|not iterable/s);
  });
});
