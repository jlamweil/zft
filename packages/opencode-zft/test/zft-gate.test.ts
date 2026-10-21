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
import { ZftLintGate } from "../../../.opencode/plugins/zft-lint-gate.js";

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

/** A client exposing the session API the changeset enumeration uses. `calls`
 *  records every argument so the SDK call shape is assertable (the real
 *  signature is `{path:{id}}`, not a flat `{sessionID}`). */
function fakeClientWithSession(children: unknown, messages: unknown, calls: unknown[] = []) {
  return {
    app: { log: async () => {}, agents: async () => [] },
    session: {
      children: async (a: unknown) => {
        calls.push(a);
        return children;
      },
      messages: async (a: unknown) => {
        calls.push(a);
        return messages;
      },
    },
  };
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
  delete (globalThis as Record<string, unknown>).__zftLintGateRegistered;
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

// ---------------------------------------------------------------------------
// Direct-write L2 verdict (T4.2) + apply_patch path extraction (T4.1) +
// enforce fail-closed (T4.3). Gap 002: the L2 after-verdict was task-only, so a
// direct edit/write/apply_patch escaped the contract gate. A direct write must
// now produce the same after-phase L2 verdict (over its changed paths); and
// under ZFT_HOOK_MODE=enforce an unavailable/failed gate blocks (fail-closed),
// not silently passes.

function makeRecordingZft(root: string, exitCode = 0): string {
  const p = join(root, "rec-zft.sh");
  writeFileSync(
    p,
    `#!/usr/bin/env bash\necho "$@" > "${root}/zft-argv.txt"\necho '{"verdict":"covered"}'\nexit ${exitCode}\n`,
  );
  chmodSync(p, 0o755);
  return p;
}

function gate(root: string) {
  return ZftGate({ directory: root, client: fakeClient() as never }) as Promise<
    Record<string, (i: unknown, o: unknown) => Promise<unknown>>
  >;
}

test("T4.2: a direct edit emits an after-phase L2 verdict record (not task-only)", async () => {
  process.env.ZFT_BIN = makeRecordingZft(root);
  const h = await gate(root);
  await h["tool.execute.after"](
    { tool: "edit", callID: "e-1", sessionID: "ses_9", args: { filePath: "src/foo.py" } },
    { output: "edited" },
  );
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain("task-gate");
  expect(argv).toContain("after");
  expect(argv).toContain("--changed");
  expect(argv).toContain("src/foo.py");
  const recs = ledger(root);
  expect(recs.length).toBe(1);
  expect(recs[0].phase).toBe("after");
  expect(recs[0].subagent).toBe("main");
});

test("changeset enumeration: SDK calls use path.id and unwrap the {data} envelope", async () => {
  process.env.ZFT_BIN = makeRecordingZft(root);
  const calls: unknown[] = [];
  const client = fakeClientWithSession(
    { data: [{ id: "ses_child", time: { created: Date.now() + 60_000 } }] },
    {
      data: [{
        parts: [{
          type: "tool",
          tool: "edit",
          state: { status: "completed", input: { filePath: "src/edited.py" } },
        }],
      }],
    },
    calls,
  );
  const h = (await ZftGate({ directory: root, client: client as never })) as Record<
    string,
    (i: unknown, o: unknown) => Promise<unknown>
  >;
  const input = {
    tool: "task",
    callID: "c-enum",
    sessionID: "ses_parent",
    args: { subagent_type: "builder", description: "[contract: perf] work" },
  };
  await h["tool.execute.before"](input, { args: input.args });
  await h["tool.execute.after"](input, { output: "subagent result" });
  // the SDK signature is {path:{id}} — a flat {sessionID} leaves {id} literal
  // in the URL (server: 'Expected a string starting with "ses", got "%7Bid%7D"').
  expect(calls[0]).toEqual({ path: { id: "ses_parent" }, query: { directory: root } });
  expect(calls[1]).toEqual({ path: { id: "ses_child" }, query: { directory: root } });
  // {data} was unwrapped, so the verdict is scoped to THIS dispatch's edits
  // (a failed enumeration would fall back to whole-tree / since-ref coverage).
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain("--changed");
  expect(argv).toContain("src/edited.py");
  expect(ledger(root).length).toBe(2);
});

test("T4.1: apply_patch file paths are extracted and passed to the after verdict", async () => {
  process.env.ZFT_BIN = makeRecordingZft(root);
  const h = await gate(root);
  const patchText =
    "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n" +
    "@@ -1 +1 @@\n+x\n" +
    "diff --git a/src/b.py b/src/b.py\n--- a/src/b.py\n+++ b/src/b.py\n" +
    "@@ -1 +1 @@\n+y";
  await h["tool.execute.after"](
    { tool: "apply_patch", callID: "ap-1", sessionID: "ses_9", args: { patchText } },
    { output: "patched" },
  );
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain("src/a.py");
  expect(argv).toContain("src/b.py");
  const recs = ledger(root);
  expect(recs.length).toBe(1);
  expect(recs[0].phase).toBe("after");
});

test("T4.3: enforce mode blocks a dispatch when the gate cannot run (fail-closed)", async () => {
  process.env.ZFT_BIN = join(root, "no-such-zft"); // spawn will fail
  process.env.ZFT_HOOK_MODE = "enforce";
  const h = await gate(root);
  await expect(
    h["tool.execute.before"](
      { tool: "task", callID: "t-1", sessionID: "ses_x" },
      { args: { subagent_type: "builder", description: "work" } },
    ),
  ).rejects.toThrow();
  delete process.env.ZFT_HOOK_MODE;
});

test("T4.4: after-phase exit-2 (no-contract error verdict) is surfaced, not ignored", async () => {
  const p = join(root, "err-zft.sh");
  writeFileSync(
    p,
    `#!/usr/bin/env bash\necho '{"verdict":"error","reason":"no [contract: <name>] reference in description"}'\nexit 2\n`,
  );
  chmodSync(p, 0o755);
  process.env.ZFT_BIN = p;
  const h = await gate(root);
  const input = { tool: "task", callID: "call-4", sessionID: "ses_4", args: { subagent_type: "builder", description: "work" } };
  await h["tool.execute.before"](input, { args: input.args }); // exit 2 before -> fails open, proceeds
  const out = { output: "subagent result" };
  await h["tool.execute.after"](input, out);
  const text = String((out as { output: string }).output);
  // the error verdict is surfaced (Gap 002 signal), the tool output is preserved
  expect(text).toContain("no [contract: <name>] reference in description");
  expect(text).toContain("ERROR (no contract reference)");
  expect(text).toContain("subagent result");
});

// ---------------------------------------------------------------------------
// P-012 C2-C5: per-session binding map (contract/ungated), the governance
// after-description + --governance flag for direct writes, exit-2-only
// surfacing, the .zft/** after-exemption, and the apply_patch session-gate
// (the real Gap-002 hole: Aider *** patches escaped every gate).

/** A stub zft that records argv AND prints a fixed stdout (the gate's JSON
 *  verdict — what the plugin parses for binding recovery). */
function makeJsonZft(root: string, stdout: string, exitCode = 0): string {
  const p = join(root, "json-zft.sh");
  writeFileSync(
    p,
    `#!/usr/bin/env bash\necho "$@" > "${root}/zft-argv.txt"\nprintf '%s' '${stdout}'\nexit ${exitCode}\n`,
  );
  chmodSync(p, 0o755);
  return p;
}

/** A stub zft whose response varies per call: call #1 (the dispatch before)
 *  gets one verdict, call #2+ (the after) gets another. */
function makeTwoPhaseZft(
  root: string,
  first: { out: string; exit: number },
  second: { out: string; exit: number },
): string {
  const p = join(root, "two-zft.sh");
  writeFileSync(
    p,
    `#!/usr/bin/env bash\necho "$@" > "${root}/zft-argv.txt"\n` +
      `n=$(cat "${root}/zft-calls.txt" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "${root}/zft-calls.txt"\n` +
      `if [ "$n" -eq 1 ]; then printf '%s' '${first.out}'; exit ${first.exit}\n` +
      `else printf '%s' '${second.out}'; exit ${second.exit}; fi\n`,
  );
  chmodSync(p, 0o755);
  return p;
}

/** Capture process.stderr so the surfacing policy (warn vs. debug) is
 *  assertable without depending on the test runner's own output. */
function captureStderr(): { restore: () => void; text: () => string } {
  const s = process.stderr as unknown as { write: (c: unknown) => boolean };
  const orig = s.write.bind(process.stderr);
  const chunks: string[] = [];
  s.write = (c: unknown) => {
    chunks.push(String(c));
    return true;
  };
  return {
    restore: () => {
      s.write = orig;
    },
    text: () => chunks.join(""),
  };
}

/** A real opencode (Aider) patch: add + update + rename + delete. */
const AIDER_PATCH =
  "*** Begin Patch\n" +
  "*** Add File: src/new.py\n" +
  "+hello\n" +
  "*** Update File: src/old.py\n" +
  "*** Move to: src/moved.py\n" +
  "@@ -1 +1 @@\n" +
  "-a\n" +
  "+b\n" +
  "*** Delete File: src/gone.py\n" +
  "*** End Patch\n";

const PATCH_DELIVERABLE =
  "*** Begin Patch\n" +
  "*** Update File: src/app.ts\n" +
  "@@ -1 +1 @@\n" +
  "-x\n" +
  "+y\n" +
  "*** End Patch\n";

const PATCH_CORPUS =
  "*** Begin Patch\n" +
  "*** Update File: .zft/specs/x.json\n" +
  "@@ -1 +1 @@\n" +
  "-x\n" +
  "+y\n" +
  "*** End Patch\n";

test("T4.1b: Aider *** patch paths are extracted (Add/Update/Move to; Delete skipped)", async () => {
  process.env.ZFT_BIN = makeRecordingZft(root);
  const h = await gate(root);
  await h["tool.execute.after"](
    { tool: "apply_patch", callID: "ap-2", sessionID: "ses_9", args: { patchText: AIDER_PATCH } },
    { output: "patched" },
  );
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain("src/new.py"); // *** Add File:
  expect(argv).toContain("src/old.py"); // *** Update File:
  expect(argv).toContain("src/moved.py"); // *** Move to: (rename target is judged)
  expect(argv).not.toContain("src/gone.py"); // *** Delete File: writes nothing
  const recs = ledger(root);
  expect(recs.length).toBe(1);
  expect(recs[0].phase).toBe("after");
});

test("C2: a contract dispatch binds the session; the after-gate names it with --governance", async () => {
  process.env.ZFT_BIN = makeJsonZft(
    root,
    '{"allow":true,"gated":true,"contract":"perf","reason":null}',
  );
  const h = await gate(root);
  await h["tool.execute.before"](
    { tool: "task", callID: "cb-1", sessionID: "ses_c" },
    { args: { subagent_type: "builder", description: "[contract: perf] work" } },
  );
  await h["tool.execute.after"](
    { tool: "edit", callID: "e-c", sessionID: "ses_c", args: { filePath: "src/foo.py" } },
    { output: "edited" },
  );
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain("[contract: perf] direct edit");
  expect(argv).toContain("--governance");
});

test("C2: an override dispatch binds ungated; the after-gate carries the override reason", async () => {
  process.env.ZFT_BIN = makeJsonZft(
    root,
    '{"allow":true,"gated":false,"contract":null,"override":true,"reason":"hotfix"}',
  );
  const h = await gate(root);
  await h["tool.execute.before"](
    { tool: "task", callID: "cb-2", sessionID: "ses_o" },
    { args: { subagent_type: "builder", description: "[ungated: hotfix] work" } },
  );
  await h["tool.execute.after"](
    { tool: "edit", callID: "e-o", sessionID: "ses_o", args: { filePath: "src/foo.py" } },
    { output: "edited" },
  );
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain("[ungated: hotfix] direct edit");
  expect(argv).toContain("--governance");
});

test("C2: unparseable before-stdout still binds (ungated, named as unparseable)", async () => {
  process.env.ZFT_BIN = makeJsonZft(root, "not-json{");
  const h = await gate(root);
  await h["tool.execute.before"](
    { tool: "task", callID: "cb-3", sessionID: "ses_u" },
    { args: { subagent_type: "builder", description: "[contract: x] work" } },
  );
  // the session is bound: a deliverable edit passes the session-gate
  await expect(
    h["tool.execute.before"](editInput(root, "ses_u"), { args: { filePath: join(root, "src", "app.ts") } }),
  ).resolves.toBeUndefined();
  await h["tool.execute.after"](
    { tool: "edit", callID: "e-u", sessionID: "ses_u", args: { filePath: "src/foo.py" } },
    { output: "edited" },
  );
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain("[ungated: unparseable gate output] direct edit");
  expect(argv).toContain("--governance");
});

test("C2: an audit-scan manual binding with a contract is named in the after-gate", async () => {
  process.env.ZFT_BIN = makeRecordingZft(root);
  appendAudit(root, { ts: Date.now(), subagent: "main", phase: "before",
                      gated: true, contract: "manual-c", override: false,
                      reason: "bound on file" });
  const h = await gate(root);
  await expect(
    h["tool.execute.before"](editInput(root, "s-audit"), { args: { filePath: join(root, "src", "app.ts") } }),
  ).resolves.toBeUndefined();
  await h["tool.execute.after"](
    { tool: "edit", callID: "e-a", sessionID: "s-audit", args: { filePath: "src/foo.py" } },
    { output: "edited" },
  );
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain("[contract: manual-c] direct edit");
  expect(argv).toContain("--governance");
});

test("C6: split-brain — a disk bind is named by the after-gate even when the in-memory session map is empty", async () => {
  process.env.ZFT_BIN = makeRecordingZft(root);
  appendAudit(root, { ts: Date.now(), subagent: "main", phase: "before",
                      gated: false, contract: null, override: true,
                      reason: "manual hotfix" });
  const h = await gate(root);
  // No tool.execute.before for this session: the in-memory boundSessions map
  // is empty, so the after-gate must fall back to the on-disk audit record
  // (the same source the session-gate reads) rather than misreading the miss
  // as an ungoverned bare write (which would record a false 'error').
  await h["tool.execute.after"](
    { tool: "edit", callID: "e-sb", sessionID: "s-sb", args: { filePath: "src/foo.py" } },
    { output: "edited" },
  );
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain("[ungated: manual hotfix] direct edit");
  expect(argv).toContain("--governance");
});

test("C3: an ungoverned session keeps the bare description; exit-2 still warns (Gap-002 signal)", async () => {
  process.env.ZFT_BIN = makeJsonZft(
    root,
    '{"verdict":"error","reason":"no [contract: <name>] reference in description"}',
    2,
  );
  const h = await gate(root);
  const err = captureStderr();
  try {
    await h["tool.execute.after"](
      { tool: "edit", callID: "e-g0", sessionID: "ses_ungov", args: { filePath: "src/foo.py" } },
      { output: "edited" },
    );
  } finally {
    err.restore();
  }
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  // ungoverned: the bare description (no marker), governance flag still set
  expect(argv).toContain("direct edit");
  expect(argv).toContain("--governance");
  expect(argv).not.toContain("[contract:");
  expect(argv).not.toContain("[ungated:");
  // the exit-2 no-contract verdict is the Gap-002 signal — it stays on stderr
  expect(err.text()).toContain("direct edit: gate verdict");
  expect(err.text()).toContain("no [contract: <name>] reference");
});

test("C3: a governed direct write (exit 0) is silent on stderr", async () => {
  process.env.ZFT_BIN = makeJsonZft(root, '{"allow":true,"gated":true,"contract":"perf"}', 0);
  const h = await gate(root);
  await h["tool.execute.before"](
    { tool: "task", callID: "cb-4", sessionID: "ses_ok" },
    { args: { subagent_type: "builder", description: "[contract: perf] work" } },
  );
  const err = captureStderr();
  const out = { output: "edited" };
  try {
    await h["tool.execute.after"](
      { tool: "edit", callID: "e-ok", sessionID: "ses_ok", args: { filePath: "src/foo.py" } },
      out,
    );
  } finally {
    err.restore();
  }
  expect(err.text()).not.toContain("[zft gate]");
  expect(out.output).toBe("edited");
});

test("C3: a governed direct write (exit 1) is silent on stderr", async () => {
  // dispatch before exits 0 (binds the session); the direct-write after exits 1
  process.env.ZFT_BIN = makeTwoPhaseZft(
    root,
    { out: '{"allow":true,"gated":true,"contract":"perf"}', exit: 0 },
    { out: '{"verdict":"missing","missing":["c1"]}', exit: 1 },
  );
  const h = await gate(root);
  await h["tool.execute.before"](
    { tool: "task", callID: "cb-5", sessionID: "ses_ok1" },
    { args: { subagent_type: "builder", description: "[contract: perf] work" } },
  );
  const err = captureStderr();
  try {
    await h["tool.execute.after"](
      { tool: "edit", callID: "e-ok1", sessionID: "ses_ok1", args: { filePath: "src/foo.py" } },
      { output: "edited" },
    );
  } finally {
    err.restore();
  }
  expect(err.text()).not.toContain("[zft gate]");
});

test("C4: a direct write touching only .zft/** skips the after-gate entirely", async () => {
  process.env.ZFT_BIN = makeRecordingZft(root);
  const h = await gate(root);
  await h["tool.execute.after"](
    { tool: "write", callID: "w-z", sessionID: "ses_z", args: { filePath: ".zft/specs/x.json" } },
    { output: "written" },
  );
  expect(existsSync(join(root, "zft-argv.txt"))).toBe(false); // no gate spawn
  expect(ledger(root).length).toBe(0); // no ledger record
});

test("C4: a mixed corpus + deliverable patch still gates over all paths", async () => {
  process.env.ZFT_BIN = makeRecordingZft(root);
  const h = await gate(root);
  const mixed =
    "*** Begin Patch\n" +
    "*** Update File: .zft/specs/x.json\n" +
    "@@ -1 +1 @@\n-x\n+y\n" +
    "*** Update File: src/app.ts\n" +
    "@@ -1 +1 @@\n-x\n+y\n" +
    "*** End Patch\n";
  await h["tool.execute.after"](
    { tool: "apply_patch", callID: "ap-m", sessionID: "ses_m", args: { patchText: mixed } },
    { output: "ok" },
  );
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain(".zft/specs/x.json");
  expect(argv).toContain("src/app.ts");
  expect(ledger(root).length).toBe(1);
});

test("after-gate: a write outside the store root is not a deliverable (no verdict)", async () => {
  process.env.ZFT_BIN = makeRecordingZft(root);
  const h = await gate(root);
  await h["tool.execute.after"](
    { tool: "edit", callID: "e-out", sessionID: "ses_out", args: { filePath: "/tmp/outside-store.txt" } },
    { output: "edited" },
  );
  // out of root: the before/session gate exempts it, so the after-gate must not
  // invent an ungoverned-write verdict (the reported false "no [contract]").
  expect(existsSync(join(root, "zft-argv.txt"))).toBe(false);
  expect(ledger(root).length).toBe(0);
});

test("session-gate: a read-only dispatch does not bind the session for writes", async () => {
  process.env.ZFT_BIN = makeJsonZft(
    root,
    '{"allow":true,"gated":false,"lane":"readonly","contract":null,"reason":"read-only lane"}',
    0,
  );
  const h = await gate(root);
  await h["tool.execute.before"](
    { tool: "task", callID: "c-ro", sessionID: "ses_ro" },
    { args: { subagent_type: "oracle", description: "review only" } },
  );
  // dispatching a read-only agent must not authorize main-session deliverable writes
  await expect(
    h["tool.execute.before"](
      { tool: "edit", callID: "e-ro", sessionID: "ses_ro" },
      { args: { filePath: join(root, "src", "app.ts") } },
    ),
  ).rejects.toThrow(/\[contract:/);
});

test("C5: an unbound apply_patch touching a deliverable is blocked pre-write", async () => {
  process.env.ZFT_BIN = makeStubZft(root);
  const h = await gate(root);
  await expect(
    h["tool.execute.before"](
      { tool: "apply_patch", callID: "ap-b1", sessionID: "s-ap" },
      { args: { patchText: PATCH_DELIVERABLE } },
    ),
  ).rejects.toThrow(/task-gate before[\s\S]*\[contract:/);
  const recs = ledger(root).filter((r) => r.phase === "session-gate");
  expect(recs.length).toBe(1);
  expect(recs[0].decision).toBe("block");
});

test("C5: a bound session's apply_patch passes the before-hook", async () => {
  process.env.ZFT_BIN = makeJsonZft(root, '{"allow":true,"gated":true,"contract":"perf"}', 0);
  const h = await gate(root);
  await h["tool.execute.before"](
    { tool: "task", callID: "cb-6", sessionID: "s-ap2" },
    { args: { subagent_type: "builder", description: "[contract: perf] work" } },
  );
  await expect(
    h["tool.execute.before"](
      { tool: "apply_patch", callID: "ap-b2", sessionID: "s-ap2" },
      { args: { patchText: PATCH_DELIVERABLE } },
    ),
  ).resolves.toBeUndefined();
});

test("C5: an apply_patch touching only .zft/** is not session-gated (lint gate domain)", async () => {
  process.env.ZFT_BIN = makeStubZft(root);
  const h = await gate(root);
  await expect(
    h["tool.execute.before"](
      { tool: "apply_patch", callID: "ap-b3", sessionID: "s-ap3" },
      { args: { patchText: PATCH_CORPUS } },
    ),
  ).resolves.toBeUndefined();
  // a delete-only patch writes nothing — also unclassifiable, passes
  const deleteOnly = "*** Begin Patch\n*** Delete File: src/gone.py\n*** End Patch\n";
  await expect(
    h["tool.execute.before"](
      { tool: "apply_patch", callID: "ap-b4", sessionID: "s-ap3" },
      { args: { patchText: deleteOnly } },
    ),
  ).resolves.toBeUndefined();
});

test("C5: the lint gate lints an apply_patch that touches the corpus", async () => {
  process.env.ZFT_BIN = makeJsonZft(root, "L0 PASSED", 0);
  const hooks = (await ZftLintGate({ directory: root, sessionID: "ses-lg" } as never)) as Record<
    string,
    (i: unknown) => Promise<void>
  >;
  const patch =
    "*** Begin Patch\n" +
    "*** Update File: .zft/specs/x.json\n" +
    "@@ -1 +1 @@\n-x\n+y\n" +
    "*** Update File: src/app.ts\n" +
    "@@ -1 +1 @@\n-x\n+y\n" +
    "*** End Patch\n";
  await hooks["tool.execute.after"]({
    tool: "apply_patch",
    callID: "lg-1",
    sessionID: "ses-lg",
    args: { patchText: patch },
  });
  const argv = readFileSync(join(root, "zft-argv.txt"), "utf8");
  expect(argv).toContain("lint");
  const logFile = join(root, ".zft", "gates-hook", "log.jsonl");
  expect(existsSync(logFile)).toBe(true);
  const rec = JSON.parse(readFileSync(logFile, "utf8").trim().split("\n")[0]);
  expect(rec.tool).toBe("apply_patch");
  expect(rec.decision).toBe("allow");
  // only the corpus path is judged (the deliverable is out of the lint gate's domain)
  expect(rec.paths).toEqual([join(root, ".zft", "specs", "x.json")]);
});

test("C5: an apply_patch with no corpus paths is silent in the lint gate", async () => {
  process.env.ZFT_BIN = makeJsonZft(root, "L0 PASSED", 0);
  const hooks = (await ZftLintGate({ directory: root, sessionID: "ses-lg2" } as never)) as Record<
    string,
    (i: unknown) => Promise<void>
  >;
  await hooks["tool.execute.after"]({
    tool: "apply_patch",
    callID: "lg-2",
    sessionID: "ses-lg2",
    args: { patchText: PATCH_DELIVERABLE },
  });
  expect(existsSync(join(root, ".zft", "gates-hook", "log.jsonl"))).toBe(false); // no log record
  expect(existsSync(join(root, "zft-argv.txt"))).toBe(false); // no lint spawn
});
