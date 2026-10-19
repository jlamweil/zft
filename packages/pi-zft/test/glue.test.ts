/**
 * K5 — contract tests for the zft-gates pi glue (event wiring).
 * Fake pi API + stub ZFT_BIN (lint/check both scriptable).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { makeZftGlue, makeFakePi } from "../lib/glue-pi.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "pi-zft-g-"));
const mkStore = (dir: string): string => {
  const store = join(dir, "store");
  mkdirSync(join(store, ".zft"), { recursive: true });
  return store;
};

/** Stub zft: lint -> configurable L0 result; check -> configurable JSON. */
let stubN = 0;
const installZftStub = (store: string, opts: { lintExit?: number; lintOut?: string; checkOk?: boolean; failures?: string[] } = {}): string => {
  const stub = join(store, `zft-stub-${stubN++}`);
  const lintOut = opts.lintOut ?? "L0 FAILED — stub failure in c1";
  const checkJson = JSON.stringify({ ok: opts.checkOk ?? false, failures: opts.failures ?? ["stub-check-fail"] });
  writeFileSync(stub, `#!/bin/sh\ncase "$1" in\n  lint) echo "${lintOut.replace(/"/g, '\\"')}"; exit ${opts.lintExit ?? 1};;\n  check) echo "${checkJson.replace(/"/g, '\\"')}"; exit 0;;\nesac\n`, { mode: 0o755 });
  return stub;
};

const withEnv = (env: Record<string, string>, fn: () => void) => {
  const prev: Record<string, string | undefined> = {};
  for (const k of Object.keys(env)) { prev[k] = process.env[k]; process.env[k] = env[k]; }
  try { fn(); } finally {
    for (const k of Object.keys(env)) {
      if (prev[k] === undefined) delete process.env[k]; else process.env[k] = prev[k];
    }
  }
};

const ctx = (cwd: string, session = "sess-z") =>
  ({ cwd, sessionManager: { getSessionId: () => session } } as never);

const editEvent = (fp: string, callId = "call-1") =>
  ({ toolName: "edit", toolCallId: callId, input: { filePath: fp }, content: [{ type: "text", text: "ok" }] });

test("observe: L0 FAILED after an edit -> report appended to the result + log record", () => {
  const store = mkStore(tmp());
  const spec = join(store, ".zft", "specs", "c.md");
  mkdirSync(join(store, ".zft", "specs"), { recursive: true });
  writeFileSync(spec, "clause c1\n");
  const stub = installZftStub(store);
  withEnv({ ZFT_BIN: stub, ZFT_HOOK_MODE: "observe" }, () => {
    const pi = makeFakePi();
    makeZftGlue()(pi);
    const r = pi.fire("tool_result", editEvent(spec), ctx(store));
    assert.ok(r, "should return a change");
    const texts = (r as { content: { text: string }[] }).content.map((c) => c.text).join("\n");
    assert.match(texts, /L0 FAILED/);
    assert.equal((r as { isError?: boolean }).isError, undefined, "observe mode must not block");
    const log = readFileSync(join(store, ".zft", "gates-hook", "log.jsonl"), "utf8").trim().split("\n");
    const rec = JSON.parse(log.at(-1)!);
    assert.equal(rec.decision, "allow");
    assert.equal(rec.blocked, false);
    assert.equal(rec.gate.status, "failed");
  });
  rmSync(store, { recursive: true, force: true });
});

test("enforce: L0 FAILED -> isError result (the model gets mandatory feedback)", () => {
  const store = mkStore(tmp());
  const spec = join(store, ".zft", "specs", "c.md");
  mkdirSync(join(store, ".zft", "specs"), { recursive: true });
  writeFileSync(spec, "clause c1\n");
  const stub = installZftStub(store);
  withEnv({ ZFT_BIN: stub, ZFT_HOOK_MODE: "enforce" }, () => {
    const pi = makeFakePi();
    makeZftGlue()(pi);
    const r = pi.fire("tool_result", editEvent(spec), ctx(store)) as { isError?: boolean };
    assert.equal(r.isError, true);
  });
  rmSync(store, { recursive: true, force: true });
});

test("L0 PASSED -> no change to the result, log says allow/passed", () => {
  const store = mkStore(tmp());
  const spec = join(store, ".zft", "specs", "c.md");
  mkdirSync(join(store, ".zft", "specs"), { recursive: true });
  writeFileSync(spec, "clause c1\n");
  const stub = installZftStub(store, { lintExit: 0, lintOut: "L0 PASSED — 2 clause nodes checked" });
  withEnv({ ZFT_BIN: stub, ZFT_HOOK_MODE: "observe" }, () => {
    const pi = makeFakePi();
    makeZftGlue()(pi);
    const r = pi.fire("tool_result", editEvent(spec), ctx(store));
    assert.equal(r, undefined, "pass is silent");
    const log = readFileSync(join(store, ".zft", "gates-hook", "log.jsonl"), "utf8").trim().split("\n");
    assert.equal(JSON.parse(log.at(-1)!).decision, "allow");
  });
  rmSync(store, { recursive: true, force: true });
});

test("gate unavailable (ZFT_BIN not found) + enforce -> blocked; observe -> recorded", () => {
  const store = mkStore(tmp());
  const spec = join(store, ".zft", "specs", "c.md");
  mkdirSync(join(store, ".zft", "specs"), { recursive: true });
  writeFileSync(spec, "clause c1\n");
  withEnv({ ZFT_BIN: "/nonexistent/zft", ZFT_HOOK_MODE: "enforce" }, () => {
    const piE = makeFakePi();
    makeZftGlue()(piE);
    const r = piE.fire("tool_result", editEvent(spec), ctx(store)) as { isError?: boolean };
    assert.equal(r.isError, true);
  });
  withEnv({ ZFT_BIN: "/nonexistent/zft", ZFT_HOOK_MODE: "observe" }, () => {
    const piO = makeFakePi();
    makeZftGlue()(piO);
    const r2 = piO.fire("tool_result", editEvent(spec, "call-2"), ctx(store));
    assert.equal(r2, undefined, "observe: no block");
  });
  const log = readFileSync(join(store, ".zft", "gates-hook", "log.jsonl"), "utf8").trim().split("\n");
  assert.ok(log.every((l) => JSON.parse(l).decision === "gate_unavailable"));
  rmSync(store, { recursive: true, force: true });
});

test("non-corpus path is logged as passthrough (in-store); non-edit tools: silent", () => {
  const store = mkStore(tmp());
  const outside = join(store, "src", "x.ts");
  mkdirSync(join(store, "src"));
  const stub = installZftStub(store);
  withEnv({ ZFT_BIN: stub, ZFT_HOOK_MODE: "observe" }, () => {
    const pi = makeFakePi();
    makeZftGlue()(pi);
    assert.equal(pi.fire("tool_result", editEvent(outside), ctx(store)), undefined);
    assert.equal(pi.fire("tool_result", { ...editEvent(join(store, ".zft", "specs", "c.md")), toolName: "bash" }, ctx(store)), undefined);
  });
  const log = readFileSync(join(store, ".zft", "gates-hook", "log.jsonl"), "utf8").trim().split("\n");
  assert.equal(log.length, 1, "only the in-store non-corpus passthrough is logged");
  assert.equal(JSON.parse(log[0]).decision, "passthrough");
  rmSync(store, { recursive: true, force: true });
});

test("no store anywhere: completely silent (no log, no .zft litter)", () => {
  const dir = tmp();
  const stub = installZftStub(dir);
  withEnv({ ZFT_BIN: stub, ZFT_HOOK_MODE: "observe" }, () => {
    const pi = makeFakePi();
    makeZftGlue()(pi);
    assert.equal(pi.fire("tool_result", editEvent(join(dir, "file.md")), ctx(dir)), undefined);
  });
  rmSync(dir, { recursive: true, force: true });
});

test("dedupe: same toolCallId gated+logged once", () => {
  const store = mkStore(tmp());
  const spec = join(store, ".zft", "specs", "c.md");
  mkdirSync(join(store, ".zft", "specs"), { recursive: true });
  writeFileSync(spec, "clause c1\n");
  const stub = installZftStub(store);
  withEnv({ ZFT_BIN: stub, ZFT_HOOK_MODE: "observe" }, () => {
    const pi = makeFakePi();
    makeZftGlue()(pi);
    pi.fire("tool_result", editEvent(spec, "call-9"), ctx(store));
    pi.fire("tool_result", editEvent(spec, "call-9"), ctx(store));
  });
  const log = readFileSync(join(store, ".zft", "gates-hook", "log.jsonl"), "utf8").trim().split("\n");
  assert.equal(log.length, 1);
  rmSync(store, { recursive: true, force: true });
});

// ----------------------------------------------------------------- settle gate
test("turn_end: check fails -> demand message (triggerTurn+followUp) citing run id + STOP", () => {
  const store = mkStore(tmp());
  mkdirSync(join(store, ".zft", "runs", "run-abc"), { recursive: true });
  const stub = installZftStub(store, { checkOk: false, failures: ["stub-check-fail"] });
  withEnv({ ZFT_BIN: stub }, () => {
    const pi = makeFakePi();
    makeZftGlue()(pi);
    pi.fire("turn_end", {}, ctx(store, "sess-s1"));
    assert.equal(pi.sent.length, 1);
    assert.equal(pi.sent[0].triggerTurn, true);
    assert.equal(pi.sent[0].deliverAs, "followUp");
    assert.match(pi.sent[0].text, /run-abc/);
    assert.match(pi.sent[0].text, /stub-check-fail/);
    assert.match(pi.sent[0].text, /STOP/i);
  });
  rmSync(store, { recursive: true, force: true });
});

test("turn_end: check passes -> no message, counter resets", () => {
  const store = mkStore(tmp());
  const stub = installZftStub(store, { checkOk: true, failures: [] });
  withEnv({ ZFT_BIN: stub }, () => {
    const pi = makeFakePi();
    makeZftGlue()(pi);
    // fail once (counter 0->1), then pass -> settle, counter back to 0
    const stubFail = installZftStub(store, { checkOk: false, failures: ["x"] });
    process.env.ZFT_BIN = stubFail;
    pi.fire("turn_end", {}, ctx(store, "sess-s2"));
    assert.equal(pi.sent.length, 1);
    process.env.ZFT_BIN = stub;
    pi.fire("turn_end", {}, ctx(store, "sess-s2"));
    assert.equal(pi.sent.length, 1, "pass: no demand");
    // now fail again: counter should have reset (first demand, not second)
    process.env.ZFT_BIN = stubFail;
    pi.fire("turn_end", {}, ctx(store, "sess-s2"));
    assert.equal(pi.sent.length, 2);
    assert.match(pi.sent[1].text, /attempt 1/);
  });
  rmSync(store, { recursive: true, force: true });
});

test("turn_end: cap reached -> give-up message stating the cap, then silence", () => {
  const store = mkStore(tmp());
  const stub = installZftStub(store, { checkOk: false, failures: ["x"] });
  withEnv({ ZFT_BIN: stub, ZFT_SETTLE_CAP: "2" }, () => {
    const pi = makeFakePi();
    makeZftGlue()(pi);
    pi.fire("turn_end", {}, ctx(store, "sess-s3"));
    pi.fire("turn_end", {}, ctx(store, "sess-s3"));
    assert.equal(pi.sent.length, 2);
    assert.match(pi.sent[1].text, /giving up/);
    assert.match(pi.sent[1].text, /2/);
    pi.fire("turn_end", {}, ctx(store, "sess-s3"));
    assert.equal(pi.sent.length, 2, "no repeated give-up");
  });
  rmSync(store, { recursive: true, force: true });
});

test("turn_end: no store -> no message", () => {
  const dir = tmp();
  withEnv({ ZFT_BIN: "/nonexistent/zft" }, () => {
    const pi = makeFakePi();
    makeZftGlue()(pi);
    pi.fire("turn_end", {}, ctx(dir));
    assert.equal(pi.sent.length, 0);
  });
  rmSync(dir, { recursive: true, force: true });
});
