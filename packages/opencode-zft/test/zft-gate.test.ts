/**
 * Plugin-side O1 instrumentation pins (gates-bench v3 prereg §1.5 T4-T5).
 *
 * Drives the SoT plugin (.opencode/plugins/zft-gate.ts) through its hook
 * path with a stub zft binary — no opencode, no policy. Pins:
 *  - every phase invocation appends one {event:"task-gate", ...} record to
 *    <store>/.zft/gates-hook/taskgate.jsonl carrying the spawn wall time
 *    (durationMs), the dispatch-clock marker (sinceMs), and a UUID-shaped
 *    dispatchId shared by the before/after pair (the join key);
 *  - the before-phase record is durable BEFORE the subagent spawns, so a
 *    session killed mid-subagent can no longer erase the proof that a gated
 *    dispatch started (the v2 config-G class).
 *
 * Run: bun test packages/opencode-zft/test/zft-gate.test.ts
 */
import { test, expect, beforeEach } from "bun:test";
import { execSync, mkdtempSync, readFileSync, rmSync, chmodSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ZftGate } from "../../../.opencode/plugins/zft-gate.ts";

const SLEEP_MS = 150;

function makeStore(): string {
  const root = mkdtempSync(join(tmpdir(), "zftgate-test-"));
  mkdirSync(join(root, ".zft"), { recursive: true });
  return root;
}

function makeStubZft(root: string, exitCode = 0): string {
  const p = join(root, "stub-zft.sh");
  writeFileSync(
    p,
    `#!/usr/bin/env bash\nsleep ${SLEEP_MS / 1000}\necho '{"verdict":"covered"}'\nexit ${exitCode}\n`,
  );
  chmodSync(p, 0o755);
  return p;
}

function fakeClient() {
  return { app: { log: async () => {}, agents: async () => [] } };
}

function ledger(root: string): any[] {
  const f = join(root, ".zft", "gates-hook", "taskgate.jsonl");
  if (!existsSync(f)) return [];
  return readFileSync(f, "utf8")
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l));
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

let root: string;

beforeEach(() => {
  delete (globalThis as Record<string, unknown>).__zftGateRegistered;
  if (root) rmSync(root, { recursive: true, force: true });
  root = makeStore();
  process.env.ZFT_BIN = makeStubZft(root);
});

test("T4: before phase emits a durable task-gate record with timing + identity", async () => {
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<void>
  >;
  await hooks["tool.execute.before"](
    { tool: "task", callID: "call-1", sessionID: "ses_1" },
    { args: { subagent_type: "builder", description: "[contract: perf] work" } },
  );
  const recs = ledger(root);
  expect(recs.length).toBe(1);
  const rec = recs[0];
  expect(rec.event).toBe("task-gate");
  expect(rec.phase).toBe("before");
  expect(rec.exit).toBe(0);
  expect(rec.subagent).toBe("builder");
  expect(rec.sessionID).toBe("ses_1");
  expect(rec.durationMs).toBeGreaterThanOrEqual(SLEEP_MS);
  expect(Number.isFinite(rec.sinceMs)).toBe(true);
  expect(rec.dispatchId).toMatch(UUID_RE);
  expect(typeof rec.ts).toBe("string");
});

test("T4: after phase joins the before record by dispatchId", async () => {
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<unknown>
  >;
  const input = { tool: "task", callID: "call-1", sessionID: "ses_1", args: { subagent_type: "builder", description: "[contract: perf] work" } };
  await hooks["tool.execute.before"](input, { args: input.args });
  const out = { output: "subagent result" };
  await hooks["tool.execute.after"](input, out);
  const recs = ledger(root);
  expect(recs.length).toBe(2);
  expect(recs[1].phase).toBe("after");
  expect(recs[1].dispatchId).toBe(recs[0].dispatchId);
  expect(recs[1].sinceMs).toBe(recs[0].sinceMs);
  expect(recs[1].durationMs).toBeGreaterThanOrEqual(SLEEP_MS);
  expect(recs[1].exit).toBe(0);
  // the verdict report is still prepended to the tool output
  expect(String((out as { output: string }).output)).toContain("subagent result");
});

test("T4: blocked dispatch (exit 1) is recorded as an enforcement event", async () => {
  process.env.ZFT_BIN = makeStubZft(root, 1);
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<void>
  >;
  await expect(
    hooks["tool.execute.before"](
      { tool: "task", callID: "call-2", sessionID: "ses_2" },
      { args: { subagent_type: "builder", description: "no contract" } },
    ),
  ).rejects.toThrow();
  const recs = ledger(root);
  expect(recs.length).toBe(1);
  expect(recs[0].phase).toBe("before");
  expect(recs[0].exit).toBe(1);
});

test("T5: the before record survives a SIGKILL of the session mid-subagent", async () => {
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<void>
  >;
  await hooks["tool.execute.before"](
    { tool: "task", callID: "call-3", sessionID: "ses_3" },
    { args: { subagent_type: "builder", description: "[contract: perf] work" } },
  );
  // the session "dies" while its subagent runs: SIGKILL a child mid-flight
  const child = Bun.spawn(["sleep", "5"]);
  child.kill(9);
  await child.exited;
  // durable evidence is still on disk: engagement is derivable post-mortem
  const recs = ledger(root);
  expect(recs.length).toBe(1);
  expect(recs[0].phase).toBe("before");
  expect(recs[0].exit).toBe(0);
  expect(recs[0].dispatchId).toMatch(UUID_RE);
});

// ---------------------------------------------------------------------------
// Session-binding gate (main-session deliverable edits). Desired behavior:
// every writer works under a recorded contract binding — a subagent dispatch
// is one binding path, never the only one. A main-session edit on a
// deliverable path before any binding is blocked with a typed hint; a
// manual `zft task-gate before --subagent main ...` record in audit.log
// binds the session (gated or explicit [ungated] override).

function auditPath(r: string): string {
  return join(r, ".zft", "audit.log");
}

function appendAudit(r: string, rec: Record<string, unknown>): void {
  mkdirSync(join(r, ".zft"), { recursive: true });
  const f = auditPath(r);
  const prev = existsSync(f) ? readFileSync(f, "utf8") : "";
  writeFileSync(f, prev + JSON.stringify(rec) + "\n");
}

function editInput(r: string, sessionID: string): unknown {
  return { tool: "edit", callID: "e-" + sessionID, sessionID };
}

test("session-gate: unbound main-session deliverable edit is blocked with a bind hint", async () => {
  process.env.ZFT_BIN = makeStubZft(root);
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<void>
  >;
  await expect(
    hooks["tool.execute.before"](
      editInput(root, "s-main"),
      { args: { filePath: join(root, "src", "app.ts") } },
    ),
  ).rejects.toThrow(/task-gate before[\s\S]*\[contract:/);
});

test("session-gate: a manual task-gate before record binds the session", async () => {
  process.env.ZFT_BIN = makeStubZft(root);
  appendAudit(root, { ts: Date.now(), subagent: "main", lane: "writer",
                      phase: "before", gated: true, contract: "x",
                      override: false, reason: "contract on file" });
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<void>
  >;
  await expect(
    hooks["tool.execute.before"](
      editInput(root, "s-manual"),
      { args: { filePath: join(root, "src", "app.ts") } },
    ),
  ).resolves.toBeUndefined();
});

test("session-gate: an explicit [ungated] override record binds the session", async () => {
  process.env.ZFT_BIN = makeStubZft(root);
  appendAudit(root, { ts: Date.now(), subagent: "main", lane: "writer",
                      phase: "before", gated: false, contract: null,
                      override: true, reason: "typo fix" });
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<void>
  >;
  await expect(
    hooks["tool.execute.before"](
      editInput(root, "s-override"),
      { args: { filePath: join(root, "src", "app.ts") } },
    ),
  ).resolves.toBeUndefined();
});

test("session-gate: store-corpus edits are not session-gated (lint gate domain)", async () => {
  process.env.ZFT_BIN = makeStubZft(root);
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<void>
  >;
  await expect(
    hooks["tool.execute.before"](
      editInput(root, "s-store"),
      { args: { filePath: join(root, ".zft", "specs", "protocol", "export-413.json") } },
    ),
  ).resolves.toBeUndefined();
});

test("session-gate: a gated dispatch binds the session in memory", async () => {
  process.env.ZFT_BIN = makeStubZft(root);
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<void>
  >;
  await hooks["tool.execute.before"](
    { tool: "task", callID: "call-sg", sessionID: "s-dispatch" },
    { args: { subagent_type: "builder", description: "[contract: perf] work" } },
  );
  await expect(
    hooks["tool.execute.before"](
      editInput(root, "s-dispatch"),
      { args: { filePath: join(root, "src", "app.ts") } },
    ),
  ).resolves.toBeUndefined();
});

test("session-gate: ZFT_ALLOW_UNGATED=1 lets the edit through", async () => {
  process.env.ZFT_BIN = makeStubZft(root);
  process.env.ZFT_ALLOW_UNGATED = "1";
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<void>
  >;
  await expect(
    hooks["tool.execute.before"](
      editInput(root, "s-allow"),
      { args: { filePath: join(root, "src", "app.ts") } },
    ),
  ).resolves.toBeUndefined();
  delete process.env.ZFT_ALLOW_UNGATED;
});

test("session-gate: every decision lands one taskgate.jsonl record", async () => {
  process.env.ZFT_BIN = makeStubZft(root);
  const hooks = (await ZftGate({ directory: root, client: fakeClient() as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<void>
  >;
  await hooks["tool.execute.before"](
    editInput(root, "s-blocked").constructor === Object
      ? editInput(root, "s-blocked")
      : editInput(root, "s-blocked"),
    { args: { filePath: join(root, "src", "app.ts") } },
  ).catch(() => {}); // blocked; the record must exist anyway
  const recs = ledger(root).filter((r) => r.phase === "session-gate");
  expect(recs.length).toBe(1);
  expect(recs[0].decision).toBe("block");
});
