/**
 * K4 — contract tests for the zft-gates pi policy module (pure tables).
 *
 * The decision tables port verbatim from packages/opencode-zft/zft-lint-gate.js
 * (L0 gate) plus the settle-gate tables from the verified pi design
 * (LV4/LV7/LV8: turn_end demand mechanism, run id from .zft/runs/, stop
 * instructions in demand text).
 *
 * Run: node --test 'packages/pi-zft/test/*.test.ts'
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  findStoreRoot, inCorpus, EDIT_TOOLS,
  isEnforce, gateDecision,
  parseCheckResult, latestRunId,
  settleDecision, buildDemandText, buildGiveUpText,
  LOG_REL,
} from "../lib/policy.ts";

const tmp = () => mkdtempSync(join(tmpdir(), "pi-zft-"));
const mkStore = (dir: string, depth = 0): string => {
  const store = join(dir, "store");
  mkdirSync(join(store, ".zft"), { recursive: true });
  let p = store;
  for (let i = 0; i < depth; i++) { p = join(p, `d${i}`); mkdirSync(p); }
  return p;
};

// ------------------------------------------------------------------- triggers
test("EDIT_TOOLS is exactly edit+write (opencode parity; no bash)", () => {
  assert.deepEqual([...EDIT_TOOLS].sort(), ["edit", "write"]);
});

test("findStoreRoot: walks up from a nested file/dir", () => {
  const store = mkStore(tmp(), 2);
  const file = join(store, ".zft", "specs", "c.md");
  mkdirSync(join(store, ".zft", "specs"), { recursive: true });
  writeFileSync(file, "x");
  assert.equal(findStoreRoot(file), store);
  assert.equal(findStoreRoot(join(store, ".zft", "specs")), store);
  assert.equal(findStoreRoot(store), store);
});

test("findStoreRoot: no store anywhere -> null (walks to root)", () => {
  const d = tmp();
  mkdirSync(join(d, "a", "b"), { recursive: true });
  assert.equal(findStoreRoot(join(d, "a", "b")), null);
});

test("inCorpus: only .zft/** of the store root", () => {
  const store = mkStore(tmp());
  const spec = join(store, ".zft", "specs", "c.md");
  const other = join(store, "src", "x.ts");
  const sibling = join(tmp(), "c.md");
  assert.equal(inCorpus(spec, store), true);
  assert.equal(inCorpus(other, store), false);
  assert.equal(inCorpus(sibling, store), false);
  // a path merely CONTAINING '.zft' in a deeper repo must not match
  const nested = join(store, ".zft", "runs", "1", ".zft", "fake");
  assert.equal(inCorpus(nested, store), true); // still under the store's .zft/**
});

// ---------------------------------------------------------------------- modes
test("isEnforce: only the exact string 'enforce'", () => {
  assert.equal(isEnforce("enforce"), true);
  assert.equal(isEnforce("observe"), false);
  assert.equal(isEnforce(undefined), false);
  assert.equal(isEnforce("ENFORCE"), false); // exact, like the opencode port
  assert.equal(isEnforce(""), false);
});

// ------------------------------------------------------------ gate decision table
test("gateDecision: exit 0 -> allow/passed", () => {
  const d = gateDecision(0, "L0 PASSED — 3 clause nodes checked");
  assert.equal(d.decision, "allow");
  assert.deepEqual(d.gate, { name: "L0", status: "passed", exit: 0 });
});

test("gateDecision: exit 1 with 'L0 FAILED' -> failed (deny iff enforce)", () => {
  const out = "L0 FAILED — clause c1: malformed hash\n";
  assert.equal(gateDecision(1, out, false).decision, "allow"); // observe: recorded, not blocked
  assert.equal(gateDecision(1, out, false).blocked, false);
  const e = gateDecision(1, out, true);
  assert.equal(e.decision, "deny");
  assert.equal(e.blocked, true);
  assert.ok(e.detail_tail?.includes("malformed hash"));
});

test("gateDecision: exit 1 WITHOUT 'L0 FAILED' -> gate_unavailable (honest, never green)", () => {
  const d = gateDecision(1, "random error", false);
  assert.equal(d.decision, "gate_unavailable");
});

test("gateDecision: any other exit -> gate_unavailable", () => {
  assert.equal(gateDecision(2, "L0 FAILED", false).decision, "gate_unavailable");
  assert.equal(gateDecision(124, "L0 FAILED", true).decision, "gate_unavailable"); // timeout
});

test("enforce + gate_unavailable -> blocked (a broken gate is never green)", () => {
  const d = gateDecision(3, "weird", true);
  assert.equal(d.decision, "gate_unavailable");
  assert.equal(d.blocked, true);
});

// ------------------------------------------------------------- settle gate tables
test("parseCheckResult: ok + failures from the check JSON (LV7: no run_id field)", () => {
  assert.deepEqual(parseCheckResult(JSON.stringify({ ok: true, failures: [] })),
    { ok: true, failures: [] });
  assert.deepEqual(parseCheckResult(JSON.stringify({ ok: false, failures: ["a", "b"] })),
    { ok: false, failures: ["a", "b"] });
  assert.deepEqual(parseCheckResult("not json"), { ok: false, failures: ["<unparseable check output>"] });
  assert.deepEqual(parseCheckResult(""), { ok: false, failures: ["<empty check output>"] });
});

test("latestRunId: newest .zft/runs/<id>/ by mtime (LV7: the id is NOT in the JSON)", () => {
  const store = mkStore(tmp());
  const runs = join(store, ".zft", "runs");
  for (const id of ["aaa", "bbb", "ccc"]) mkdirSync(join(runs, id), { recursive: true });
  for (const id of ["aaa", "bbb", "ccc"]) writeFileSync(join(runs, id, "x"), id);
  assert.equal(typeof latestRunId(runs), "string");
  assert.ok(["aaa", "bbb", "ccc"].includes(latestRunId(runs)!));
  assert.equal(latestRunId(join(store, "nope")), null);
});

test("settleDecision: ok -> settle (counter resets)", () => {
  assert.deepEqual(settleDecision(0, true, 3), { action: "settle", nextCounter: 0 });
  assert.deepEqual(settleDecision(2, true, 3), { action: "settle", nextCounter: 0 }); // reset, not carry
});

test("settleDecision: fail under cap -> demand, counter+1; on the cap-th failure -> give_up", () => {
  assert.deepEqual(settleDecision(0, false, 3), { action: "demand", nextCounter: 1 });
  assert.deepEqual(settleDecision(1, false, 3), { action: "demand", nextCounter: 2 });
  assert.deepEqual(settleDecision(2, false, 3), { action: "give_up", nextCounter: 3 }); // cap=3: give up on failure 3
});

test("settleDecision: after give-up -> silent (never repeated)", () => {
  assert.deepEqual(settleDecision(3, false, 3), { action: "silent", nextCounter: 3 });
});

test("buildDemandText: cites run id + failures + EXPLICIT stop instruction (LV8)", () => {
  const t = buildDemandText("run-123", ["clause c1 bad"], 1);
  assert.ok(t.includes("run-123"));
  assert.ok(t.includes("clause c1 bad"));
  assert.match(t, /STOP/i);
  assert.match(t, /settle/i);
});

test("buildGiveUpText: states the cap and tells the model to stop (LV8)", () => {
  const t = buildGiveUpText("run-123", ["x"], 3);
  assert.ok(t.includes("run-123"));
  assert.ok(t.includes("3"));
  assert.match(t, /STOP|stop/i);
});

test("LOG_REL keeps the opencode schema path (no new log invented)", () => {
  assert.equal(LOG_REL, ".zft/gates-hook/log.jsonl");
});
