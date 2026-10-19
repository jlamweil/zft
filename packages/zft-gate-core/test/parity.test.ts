/**
 * C5 repo parity harness — the two gate adapters (opencode-zft, pi-zft)
 * must emit IDENTICAL L0 gate records for the same event, same stub
 * binary, and same mode. This is the permanent debug artifact promoted
 * from the throwaway /tmp/parity harness: if either adapter drifts, this
 * test fails with both full records printed.
 *
 * Asymmetries are pinned, not hidden:
 *  - opencode has an `apply_patch` tool (pi does not): the oc
 *    apply_patch record shape is asserted against a golden, and pi's
 *    EDIT_TOOLS subset guard is asserted to stay silent.
 *  - the settle gate is pi-only: out of scope for cross-adapter parity.
 *
 * Run (bare node, zero dependencies, no node_modules):
 *   node --experimental-strip-types --test test/parity.test.ts
 * (bun test works too: bun test test/parity.test.ts)
 */
import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import {
  mkdtempSync, rmSync, writeFileSync, chmodSync,
  readFileSync, existsSync, mkdirSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const { ZftLintGate } = await import(join(REPO, "packages/opencode-zft/zft-lint-gate.js"));
// the .ts glue needs --experimental-strip-types on node 22; bun strips
// types natively.
const { makeZftGlue, makeFakePi } = await import(join(REPO, "packages/pi-zft/lib/glue-pi.ts"));
const P = await import(join(REPO, "packages/pi-zft/lib/policy.ts"));

let base: string;
let ocHooks: Record<string, (input: unknown) => Promise<unknown>>;

beforeEach(async () => {
  base = mkdtempSync(join(tmpdir(), "zftparity-"));
  if (!ocHooks) {
    // the opencode factory registers once per process (globalThis guard)
    ocHooks = (await ZftLintGate({ directory: base, sessionID: "ses-parity" })) as
      Record<string, (input: unknown) => Promise<unknown>>;
  }
});

afterEach(() => {
  delete process.env.ZFT_BIN;
  delete process.env.ZFT_HOOK_MODE;
  rmSync(base, { recursive: true, force: true });
});

const makeStore = (name: string) => {
  const root = join(base, name);
  mkdirSync(join(root, ".zft"), { recursive: true });
  return root;
};

const stubZft = (name: string, out: string, code: number) => {
  const p = join(base, name);
  writeFileSync(p, `#!/bin/sh\necho "${out}"\nexit ${code}\n`);
  chmodSync(p, 0o755);
  return p;
};

// the oc handler awaits (microtask) before appending the record; the pi
// handler is sync. A tick flushes both before the log is read.
const fireOc = (input: Record<string, unknown>) =>
  Promise.resolve(ocHooks["tool.execute.after"](input));

const firePi = (input: Record<string, unknown>, cwd: string) => {
  const pi = makeFakePi();
  makeZftGlue()(pi);
  return pi.fire("tool_result", input, {
    cwd,
    sessionManager: { getSessionId: () => "ses-parity" },
  });
};

const tick = () => new Promise((r) => setTimeout(r, 0));

const norm = (rec: Record<string, unknown>, root: string): Record<string, unknown> => {
  const { ts, session_id, ...rest } = rec;
  // session_id is harness-specific by design (LV9: each adapter takes it
  // from its own session context) — the parity assertion covers everything
  // the gate derives, not the caller's session.
  return JSON.parse(JSON.stringify(rest).replaceAll(root, "<ROOT>"));
};

const logOf = (root: string): Record<string, unknown>[] =>
  readFileSync(join(root, ".zft", "gates-hook", "log.jsonl"), "utf8")
    .trim().split("\n")
    .map((l) => JSON.parse(l));

const assertParity = (label: string, rootOc: string, rootPi: string) => {
  const a = logOf(rootOc);
  const b = logOf(rootPi);
  assert.equal(a.length, b.length, `${label}: record count oc=${a.length} pi=${b.length}`);
  const na = a.map((r) => norm(r, rootOc));
  const nb = b.map((r) => norm(r, rootPi));
  if (JSON.stringify(na) !== JSON.stringify(nb)) {
    throw new Error(
      `${label}: record mismatch\n--- oc ---\n${JSON.stringify(na, null, 2)}\n--- pi ---\n${JSON.stringify(nb, null, 2)}`);
  }
};

const EDIT = ".zft/specs/x.json";

const ocEdit = (root: string, callID: string, tool = "write") => ({
  tool, callID, sessionID: "ses-parity",
  args: { filePath: join(root, EDIT) },
});

const piEdit = (root: string, toolCallId: string, toolName = "write") => ({
  toolName, toolCallId,
  input: { path: join(root, EDIT) },  // pi real param name (not filePath)
  content: [],
});

test("parity: L0 PASSED -> identical allow records (observe)", async () => {
  const rOc = makeStore("oc-pass");
  const rPi = makeStore("pi-pass");
  process.env.ZFT_BIN = stubZft("zft-pass", "L0 PASSED", 0);
  await fireOc(ocEdit(rOc, "p1"));
  firePi(piEdit(rPi, "p1"), rPi);
  await tick();
  assertParity("allow", rOc, rPi);
  assert.equal(logOf(rOc)[0].decision, "allow");
  assert.equal(logOf(rOc)[0].blocked, false);
  assert.deepEqual(logOf(rOc)[0].gate, { name: "L0", status: "passed", exit: 0 });
});

test("parity: L0 FAILED, observe -> identical allow/blocked:false records", async () => {
  const rOc = makeStore("oc-fail");
  const rPi = makeStore("pi-fail");
  process.env.ZFT_BIN = stubZft("zft-fail", "L0 FAILED: synthetic finding", 1);
  await fireOc(ocEdit(rOc, "f1"));
  firePi(piEdit(rPi, "f1"), rPi);
  await tick();
  assertParity("failed-observe", rOc, rPi);
  assert.equal(logOf(rOc)[0].blocked, false);
});

test("parity: L0 FAILED, enforce -> both block; identical deny records", async () => {
  const rOc = makeStore("oc-fe");
  const rPi = makeStore("pi-fe");
  process.env.ZFT_HOOK_MODE = "enforce";
  process.env.ZFT_BIN = stubZft("zft-fail", "L0 FAILED: synthetic finding", 1);
  await assert.rejects(fireOc(ocEdit(rOc, "fe1")), /L0 FAILED/);
  const piRes = firePi(piEdit(rPi, "fe1"), rPi);
  await tick();
  assert.equal((piRes as { isError?: boolean }).isError, true);
  assertParity("failed-enforce", rOc, rPi);
  assert.equal(logOf(rOc)[0].decision, "deny");
  assert.equal(logOf(rOc)[0].blocked, true);
});

test("parity: gate exits 7 -> identical gate_unavailable records (observe)", async () => {
  const rOc = makeStore("oc-u7");
  const rPi = makeStore("pi-u7");
  process.env.ZFT_BIN = stubZft("zft-bad", "boom: weird crash", 7);
  await fireOc(ocEdit(rOc, "u1"));
  firePi(piEdit(rPi, "u1"), rPi);
  await tick();
  assertParity("unavailable-exit7", rOc, rPi);
  assert.equal(logOf(rOc)[0].decision, "gate_unavailable");
  assert.equal(logOf(rOc)[0].blocked, false);
});

test("parity: gate exits 7, enforce -> both block; identical gate_unavailable records", async () => {
  const rOc = makeStore("oc-ue");
  const rPi = makeStore("pi-ue");
  process.env.ZFT_HOOK_MODE = "enforce";
  process.env.ZFT_BIN = stubZft("zft-bad", "boom", 7);
  await assert.rejects(fireOc(ocEdit(rOc, "ue1")), /GATE_UNAVAILABLE/);
  const piRes = firePi(piEdit(rPi, "ue1"), rPi);
  await tick();
  assert.equal((piRes as { isError?: boolean }).isError, true);
  assertParity("unavailable-exit7-enforce", rOc, rPi);
  assert.equal(logOf(rOc)[0].blocked, true);
});

test("parity: unrunnable ZFT_BIN -> identical gate_unavailable records (no argv)", async () => {
  const rOc = makeStore("oc-na");
  const rPi = makeStore("pi-na");
  process.env.ZFT_BIN = "/nonexistent/zft-bin";
  await fireOc(ocEdit(rOc, "na1"));
  firePi(piEdit(rPi, "na1"), rPi);
  await tick();
  assertParity("no-argv", rOc, rPi);
  assert.match(String(logOf(rOc)[0].detail_tail), /ZFT_BIN/);
});

test("parity: out-of-corpus edit -> identical passthrough records (no gate, no blocked)", async () => {
  const rOc = makeStore("oc-pt");
  const rPi = makeStore("pi-pt");
  process.env.ZFT_BIN = stubZft("zft-pass", "L0 PASSED", 0);
  await fireOc({ ...ocEdit(rOc, "pt1"), args: { filePath: join(rOc, "src", "app.ts") } });
  firePi({ ...piEdit(rPi, "pt1"), input: { path: join(rPi, "src", "app.ts") } }, rPi);
  await tick();
  assertParity("passthrough", rOc, rPi);
  assert.equal(logOf(rOc)[0].decision, "passthrough");
  assert.ok(!("gate" in logOf(rOc)[0]));
  assert.ok(!("blocked" in logOf(rOc)[0]));
});

test("oc-only golden: apply_patch record carries parsed corpus paths; pi stays silent", async () => {
  const rOc = makeStore("oc-ap");
  const rPi = makeStore("pi-ap");
  process.env.ZFT_BIN = stubZft("zft-pass", "L0 PASSED", 0);
  const patch =
    "*** Begin Patch\n" +
    `*** Update File: ${join(rOc, ".zft", "specs", "a.json")}\n@@ -1 +1 @@\n-x\n+y\n` +
    "*** Update File: src/app.ts\n@@ -1 +1 @@\n-x\n+y\n" +
    `*** Update File: ${join(rOc, ".zft", "specs", "b.json")}\n@@ -1 +1 @@\n-x\n+y\n` +
    "*** End Patch\n";
  await fireOc({ tool: "apply_patch", callID: "ap1", sessionID: "ses-parity", args: { patchText: patch } });
  await tick();
  const rec = logOf(rOc)[0];
  assert.equal(rec.tool, "apply_patch");
  assert.equal(rec.decision, "allow");
  assert.deepEqual(rec.paths, [
    join(rOc, ".zft", "specs", "a.json"),
    join(rOc, ".zft", "specs", "b.json"),
  ]);
  // asymmetry pinned: pi's EDIT_TOOLS subset has no apply_patch tool, so
  // the same (unrepresentable-in-pi) event writes nothing.
  assert.ok(!P.EDIT_TOOLS.has("apply_patch"));
  const res = firePi(
    { toolName: "apply_patch", toolCallId: "ap1", input: { patchText: patch }, content: [] },
    rPi);
  assert.equal(res, undefined);
  assert.ok(!existsSync(join(rPi, ".zft", "gates-hook", "log.jsonl")));
});
