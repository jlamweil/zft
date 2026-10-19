/**
 * zft-gate-core policy tests (C1).
 *
 * The core is the pure, harness-free L0 gate policy shared by the
 * opencode and pi adapters: store lookup, corpus membership, apply_patch
 * path parsing, binary resolution (ZFT_BIN authoritative, runnability
 * probing, memoization), the never-green exit table, and record
 * primitives. Ported verbatim from the pinned deploy behavior
 * (packages/opencode-zft/test/zft-lint-gate.test.ts is the behavior
 * oracle; this file unit-tests the relocated units directly).
 *
 * Run: bun test packages/zft-gate-core/test/policy.test.ts
 */
import { test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, readFileSync, chmodSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  CORPUS_DIR,
  LOG_REL,
  EDIT_TOOLS,
  GATE_TIMEOUT_MS,
  findStoreRoot,
  inCorpus,
  toAbsolute,
  parsePatchPaths,
  corpusPathsFor,
  resolveGate,
  resetGateMemo,
  runGate,
  gateUnavailableRecord,
} from "../lib/gate-core.js";

let tmp: string;

beforeEach(() => {
  tmp = mkdtempSync(join(tmpdir(), "zftcore-"));
  resetGateMemo();
  delete process.env.ZFT_BIN;
});

afterEach(() => {
  delete process.env.ZFT_BIN;
  rmSync(tmp, { recursive: true, force: true });
});

const makeStore = (name = "store") => {
  const root = join(tmp, name);
  mkdirSync(join(root, CORPUS_DIR), { recursive: true });
  return root;
};

const stub = (name: string, out: string, code: number) => {
  const p = join(tmp, name);
  writeFileSync(p, `#!/bin/sh\necho "${out}"\nexit ${code}\n`);
  chmodSync(p, 0o755);
  return p;
};

test("constants: corpus dir, log path, edit tools, timeout", () => {
  expect(CORPUS_DIR).toBe(".zft");
  expect(LOG_REL).toBe(join(".zft", "gates-hook", "log.jsonl"));
  expect([...EDIT_TOOLS].sort()).toEqual(["apply_patch", "edit", "write"]);
  expect(GATE_TIMEOUT_MS).toBe(60_000);
});

test("findStoreRoot: walks up to the .zft store; null when none above", () => {
  const root = makeStore();
  expect(findStoreRoot(join(root, ".zft", "specs", "x.json"))).toBe(root);
  const none = mkdtempSync(join(tmpdir(), "zftcore-nostore-"));
  try {
    expect(findStoreRoot(join(none, "a.md"))).toBeNull();
  } finally {
    rmSync(none, { recursive: true, force: true });
  }
});

test("findStoreRoot: a FILE path resolves from its parent dir", () => {
  const root = makeStore();
  const f = join(root, ".zft", "exists.md");
  writeFileSync(f, "x");
  expect(findStoreRoot(f)).toBe(root);
});

test("inCorpus: only <root>/.zft/** counts", () => {
  const root = makeStore();
  expect(inCorpus(join(root, ".zft", "specs", "x.json"), root)).toBe(true);
  expect(inCorpus(join(root, "src", "app.ts"), root)).toBe(false);
  expect(inCorpus(root, root)).toBe(false);
  const sibling = join(tmp, "sibling", "a.md");
  mkdirSync(join(tmp, "sibling"), { recursive: true });
  expect(inCorpus(sibling, root)).toBe(false);
});

test("parsePatchPaths: Add/Update/Move-to targets, Delete skipped, /dev/null skipped, deduped", () => {
  const text =
    "*** Begin Patch\n" +
    "*** Add File: .zft/a.json\n@@ -1 +1 @@\n+x\n" +
    "*** Update File: .zft/b.json\n@@ -1 +1 @@\n-x\n+y\n" +
    "*** Move to: .zft/a.json\n@@ -1 +1 @@\n" +
    "*** Delete File: .zft/c.json\n" +
    "*** Update File: /dev/null\n" +
    "*** End Patch\n";
  expect(parsePatchPaths(text)).toEqual([".zft/a.json", ".zft/b.json"]);
});

test("corpusPathsFor: edit/write carry one absolute path (relative resolved against directory)", () => {
  const root = makeStore();
  expect(corpusPathsFor("edit", { filePath: ".zft/x.json" }, root)).toEqual([join(root, ".zft", "x.json")]);
  expect(corpusPathsFor("write", { filePath: "/abs/y.md" }, root)).toEqual(["/abs/y.md"]);
  expect(corpusPathsFor("edit", {}, root)).toEqual([]);
});

test("corpusPathsFor: apply_patch carries the parsed targets, resolved, deduped", () => {
  const root = makeStore();
  const patch =
    "*** Update File: .zft/a.json\n@@ -1 +1 @@\n-x\n+y\n" +
    "*** Update File: src/app.ts\n@@ -1 +1 @@\n-x\n+y\n";
  expect(corpusPathsFor("apply_patch", { patchText: patch }, root)).toEqual([
    join(root, ".zft", "a.json"),
    join(root, "src", "app.ts"),
  ]);
  expect(corpusPathsFor("apply_patch", { patchText: "*** Delete File: .zft/c.json\n" }, root)).toEqual([]);
});

test("resolveGate: ZFT_BIN is authoritative — a missing override fails, never falls back", () => {
  process.env.ZFT_BIN = join(tmp, "does-not-exist");
  const [argv, reason] = resolveGate(makeStore());
  expect(argv).toBeNull();
  expect(reason).toContain("ZFT_BIN");
});

test("resolveGate: a runnable ZFT_BIN override is returned as-is (never memoized)", () => {
  const bin = stub("zft-bin", "ok", 0);
  process.env.ZFT_BIN = bin;
  expect(resolveGate(makeStore())[0]).toEqual([bin]);
});

test("resolveGate: .venv/bin/zft wins when runnable", () => {
  const root = makeStore();
  const venv = join(root, ".venv", "bin");
  mkdirSync(venv, { recursive: true });
  writeFileSync(join(venv, "zft"), "#!/bin/sh\necho ok\n");
  chmodSync(join(venv, "zft"), 0o755);
  const [argv, reason] = resolveGate(root);
  expect(reason).toBeNull();
  expect(argv[0]).toBe(join(venv, "zft"));
});

test("resolveGate: a broken .venv entry point is skipped (runnability probe)", () => {
  const root = makeStore();
  const venv = join(root, ".venv", "bin");
  mkdirSync(venv, { recursive: true });
  writeFileSync(join(venv, "zft"), "#!/bin/sh\necho \"Traceback (most recent call last):\" >&2\n");
  chmodSync(join(venv, "zft"), 0o755);
  const [argv, reason] = resolveGate(root);
  // falls through to PATH/python probing (outcome depends on host) — but
  // it must NOT be the broken venv binary.
  if (argv) expect(argv[0]).not.toBe(join(venv, "zft"));
  else expect(reason).toBeTruthy();
});

test("resolveGate: memoizes per store (second call does not re-probe)", () => {
  const root = makeStore();
  const venv = join(root, ".venv", "bin");
  mkdirSync(venv, { recursive: true });
  const probe = join(root, "probe-count");
  writeFileSync(join(venv, "zft"), `#!/bin/sh\necho ok >> ${probe}\n`);
  chmodSync(join(venv, "zft"), 0o755);
  resolveGate(root);
  resolveGate(root);
  const count = existsSync(probe) ? readFileSync(probe, "utf8").trim().split("\n").length : 0;
  expect(count).toBe(1); // second call served from memo
});

test("gateUnavailableRecord: the C4 superset shape", () => {
  const base = { ts: "t", event: "PostToolUse", tool: "Edit", mode: "enforce", session_id: "s", root: "/r", paths: ["/r/.zft/a"] };
  const r1 = gateUnavailableRecord(base, true, { detail_tail: "no zft executable" });
  expect(r1).toMatchObject({ decision: "gate_unavailable", blocked: true, detail_tail: "no zft executable" });
  expect(r1.gate).toBeUndefined();
  const r2 = gateUnavailableRecord(base, false, {
    gate: { name: "L0", status: "unavailable", exit: 3 },
    detail_tail: "tail",
  });
  expect(r2.blocked).toBe(false);
  expect(r2.gate).toEqual({ name: "L0", status: "unavailable", exit: 3 });
  // base keys survive, no key is invented
  expect(Object.keys(r1).sort()).toEqual(["blocked", "decision", "detail_tail", "event", "mode", "paths", "root", "session_id", "tool", "ts"]);
});

test("runGate: the never-green exit table", async () => {
  const root = makeStore();
  process.env.ZFT_BIN = stub("zft-pass", "L0 PASSED", 0);
  let r = await runGate(root);
  expect(r.kind).toBe("passed");

  process.env.ZFT_BIN = stub("zft-fail", "L0 FAILED: finding", 1);
  r = await runGate(root);
  expect(r.kind).toBe("failed");
  expect(r.detailTail).toContain("L0 FAILED");

  // exit 1 WITHOUT the marker is a broken gate, not a failure
  process.env.ZFT_BIN = stub("zft-weird", "something else", 1);
  r = await runGate(root);
  expect(r.kind).toBe("unavailable");

  // any other exit is unavailable, never green
  process.env.ZFT_BIN = stub("zft-err", "boom", 3);
  r = await runGate(root);
  expect(r.kind).toBe("unavailable");
  expect(r.exit).toBe(3);
});
