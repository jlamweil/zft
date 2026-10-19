/**
 * L0 lint-gate record-contract pins (gap-002 era, SoT = the deploy file).
 *
 * These pin the deployed behavior VERBATIM — including the apply_patch
 * record semantics (tool enum value, corpus-filtered multi-path `paths`,
 * silent no-corpus patch, root resolved from the FIRST input path) — so
 * the later gate-core extraction (C1) and the canonical-record change
 * (C4) each have a green baseline to prove "no behavior change" /
 * "exactly this change" against.
 *
 * Run: bun test packages/opencode-zft/test/zft-lint-gate.test.ts
 */
import { test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync, chmodSync, readFileSync, existsSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ZftLintGate } from "../../../.opencode/plugins/zft-lint-gate.js";

let root: string;

const logPath = () => join(root, ".zft", "gates-hook", "log.jsonl");
const records = (): Array<Record<string, unknown>> =>
  existsSync(logPath())
    ? readFileSync(logPath(), "utf8").trim().split("\n").map((l) => JSON.parse(l))
    : [];

/** Stub zft: emits `out`, exits `code`. */
const stubZft = (name: string, out: string, code: number): string => {
  const p = join(root, name);
  writeFileSync(p, `#!/bin/sh\necho "${out}"\nexit ${code}\n`);
  chmodSync(p, 0o755);
  return p;
};

const hooks = async () => {
  (globalThis as Record<string, unknown>).__zftLintGateRegistered = false;
  return (await ZftLintGate({ directory: root, sessionID: "ses-pins" } as never)) as Record<
    string,
    (i: unknown) => Promise<unknown>
  >;
};

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "zftlint-pins-"));
  mkdirSync(join(root, ".zft"), { recursive: true });
  delete process.env.ZFT_HOOK_MODE;
});

afterEach(() => {
  delete process.env.ZFT_BIN;
  delete process.env.ZFT_HOOK_MODE;
  rmSync(root, { recursive: true, force: true });
});

test("L1: edit in the corpus, gate pass -> allow record, tool Edit, single path", async () => {
  process.env.ZFT_BIN = stubZft("zft-pass", "L0 PASSED", 0);
  const h = await hooks();
  await h["tool.execute.after"]({
    tool: "edit",
    callID: "e1",
    sessionID: "ses-pins",
    args: { filePath: join(root, ".zft", "specs", "x.json") },
  });
  const rec = records()[0];
  expect(rec.tool).toBe("Edit");
  expect(rec.decision).toBe("allow");
  expect(rec.mode).toBe("observe");
  expect(rec.paths).toEqual([join(root, ".zft", "specs", "x.json")]);
  expect(rec.gate).toEqual({ name: "L0", status: "passed", exit: 0 });
});

test("L2: edit in the store but outside the corpus -> passthrough, no spawn", async () => {
  process.env.ZFT_BIN = stubZft("zft-pass", "L0 PASSED", 0);
  const h = await hooks();
  await h["tool.execute.after"]({
    tool: "edit",
    callID: "e2",
    sessionID: "ses-pins",
    args: { filePath: join(root, "src", "app.ts") },
  });
  const rec = records()[0];
  expect(rec.decision).toBe("passthrough");
  expect(rec.paths).toEqual([join(root, "src", "app.ts")]);
  expect("gate" in rec).toBe(false);
});

test("L3: write in the corpus -> tool Write", async () => {
  process.env.ZFT_BIN = stubZft("zft-pass", "L0 PASSED", 0);
  const h = await hooks();
  await h["tool.execute.after"]({
    tool: "write",
    callID: "w1",
    sessionID: "ses-pins",
    args: { filePath: join(root, ".zft", "contracts", "c.json") },
  });
  expect(records()[0].tool).toBe("Write");
});

test("L4: apply_patch with TWO corpus targets + one deliverable -> paths = both corpus paths, in patch order", async () => {
  process.env.ZFT_BIN = stubZft("zft-pass", "L0 PASSED", 0);
  const h = await hooks();
  const patch =
    "*** Begin Patch\n" +
    "*** Update File: .zft/specs/a.json\n@@ -1 +1 @@\n-x\n+y\n" +
    "*** Update File: src/app.ts\n@@ -1 +1 @@\n-x\n+y\n" +
    "*** Update File: .zft/specs/b.json\n@@ -1 +1 @@\n-x\n+y\n" +
    "*** End Patch\n";
  await h["tool.execute.after"]({
    tool: "apply_patch",
    callID: "ap-1",
    sessionID: "ses-pins",
    args: { patchText: patch },
  });
  const rec = records()[0];
  expect(rec.tool).toBe("apply_patch");
  expect(rec.decision).toBe("allow");
  expect(rec.paths).toEqual([
    join(root, ".zft", "specs", "a.json"),
    join(root, ".zft", "specs", "b.json"),
  ]);
});

test("L5: apply_patch whose FIRST target has no store above it -> silent (root resolved from first input path)", async () => {
  const elseDir = mkdtempSync(join(tmpdir(), "zftlint-nostore-"));
  try {
    process.env.ZFT_BIN = stubZft("zft-pass", "L0 PASSED", 0);
    const h = await hooks();
    const patch =
      "*** Begin Patch\n" +
      `*** Update File: ${join(elseDir, "orphan.ts")}\n@@ -1 +1 @@\n-x\n+y\n` +
      "*** Update File: .zft/specs/x.json\n@@ -1 +1 @@\n-x\n+y\n" +
      "*** End Patch\n";
    await h["tool.execute.after"]({
      tool: "apply_patch",
      callID: "ap-2",
      sessionID: "ses-pins",
      args: { patchText: patch },
    });
    expect(records()).toEqual([]); // no record at all — deployed behavior, pinned
  } finally {
    rmSync(elseDir, { recursive: true, force: true });
  }
});

test("L6: gate exits 7 (neither 0 nor 1) -> gate_unavailable record, superset blocked:false", async () => {
  process.env.ZFT_BIN = stubZft("zft-bad", "boom: weird crash", 7);
  const h = await hooks();
  await h["tool.execute.after"]({
    tool: "edit",
    callID: "e3",
    sessionID: "ses-pins",
    args: { filePath: join(root, ".zft", "specs", "x.json") },
  });
  const rec = records()[0];
  expect(rec.decision).toBe("gate_unavailable");
  expect(rec.gate).toEqual({ name: "L0", status: "unavailable", exit: 7 });
  expect(rec.blocked).toBe(false); // C4 superset: key always present, false in observe
});

test("L7: enforce + gate exits 7 -> throws GATE_UNAVAILABLE and still records", async () => {
  process.env.ZFT_HOOK_MODE = "enforce";
  process.env.ZFT_BIN = stubZft("zft-bad", "boom", 7);
  const h = await hooks();
  await expect(
    h["tool.execute.after"]({
      tool: "edit",
      callID: "e4",
      sessionID: "ses-pins",
      args: { filePath: join(root, ".zft", "specs", "x.json") },
    }),
  ).rejects.toThrow("GATE_UNAVAILABLE");
  expect(records()[0].decision).toBe("gate_unavailable");
  expect(records()[0].blocked).toBe(true); // C4 superset: broken gate blocks in enforce
});

test("L8: enforce + L0 FAILED -> throws L0 FAILED, record decision deny, blocked true", async () => {
  process.env.ZFT_HOOK_MODE = "enforce";
  process.env.ZFT_BIN = stubZft("zft-fail", "L0 FAILED: synthetic finding", 1);
  const h = await hooks();
  await expect(
    h["tool.execute.after"]({
      tool: "edit",
      callID: "e5",
      sessionID: "ses-pins",
      args: { filePath: join(root, ".zft", "specs", "x.json") },
    }),
  ).rejects.toThrow("L0 FAILED");
  const rec = records()[0];
  expect(rec.decision).toBe("deny");
  expect(rec.blocked).toBe(true);
});

test("L9: observe + L0 FAILED -> no throw, record decision allow, blocked false", async () => {
  process.env.ZFT_BIN = stubZft("zft-fail", "L0 FAILED: synthetic finding", 1);
  const h = await hooks();
  await expect(
    h["tool.execute.after"]({
      tool: "edit",
      callID: "e6",
      sessionID: "ses-pins",
      args: { filePath: join(root, ".zft", "specs", "x.json") },
    }),
  ).resolves.toBeUndefined();
  const rec = records()[0];
  expect(rec.decision).toBe("allow");
  expect(rec.blocked).toBe(false);
});

test("L10: file outside any store -> completely silent (no record, no spawn)", async () => {
  const elseDir = mkdtempSync(join(tmpdir(), "zftlint-outside-"));
  try {
    process.env.ZFT_BIN = stubZft("zft-pass", "L0 PASSED", 0);
    const h = await hooks();
    await h["tool.execute.after"]({
      tool: "edit",
      callID: "e7",
      sessionID: "ses-pins",
      args: { filePath: join(elseDir, "loose.md") },
    });
    expect(records()).toEqual([]);
  } finally {
    rmSync(elseDir, { recursive: true, force: true });
  }
});
