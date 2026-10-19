/**
 * zft-gates pi glue (event wiring only; tables from lib/policy.ts).
 *
 * opencode parity (zft-lint-gate.js): the gate acts only on the contract
 * corpus (<root>/.zft/**); outside a store it is completely silent; a
 * broken gate is never green (gate_unavailable, blocked in enforce).
 *
 * pi settle gate (verified LV4/LV7/LV8): turn_end runs `zft check`, demands
 * a fix-turn while failing under the cap, gives up at the cap. Demand text
 * always carries an explicit STOP instruction.
 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import * as P from "./policy.ts";

// Policy units (gate binary resolution, logging, timeouts) come from
// lib/policy.ts, which re-exports zft-gate-core — the shared L0 policy.
// This file keeps only the pi harness wiring: events, records, blocking.

const now = P.now;
const appendLog = P.appendLog;
const resolveGate = P.resolveGate;
const GATE_TIMEOUT_MS = P.GATE_TIMEOUT_MS;

// ------------------------------------------------------------------- glue
export const makeZftGlue = (): ((pi: ExtensionAPI) => void) => (pi: ExtensionAPI) => {
  const seen = new Set<string>();
  const counters = new Map<string, number>(); // root|session -> consecutive failures

  const sessionId = (ctx: ExtensionContext): string => {
    try { return ctx.sessionManager.getSessionId(); } catch { return ""; }
  };

  // ------------------------------------------------- L0 edit gate (tool_result)
  pi.on("tool_result", (event, ctx) => {
    try {
      if (!P.EDIT_TOOLS.has(event.toolName)) return undefined;
      const key = `${event.toolCallId ?? ""}:${event.toolName}`;
      if (seen.has(key)) return undefined;
      seen.add(key);

      // pi's write/edit tools take `path` (opencode's name is `filePath` —
      // kept as a fallback). Reading only one of the two made the gate
      // silently skip every real edit (live Z2 finding, 2026-10-19).
      const inp = event.input as { path?: unknown; filePath?: unknown };
      const fpRaw = typeof inp?.path === "string" ? inp.path : inp?.filePath;
      if (typeof fpRaw !== "string" || !fpRaw.trim()) return undefined;
      const fp = fpRaw;
      const abs = P.toAbsolute(fp, ctx.cwd);
      const root = P.findStoreRoot(abs);
      if (!root) return undefined; // outside any store: completely silent

      const mode = process.env.ZFT_HOOK_MODE ?? "observe";
      const enforce = P.isEnforce(mode);
      const base: Record<string, unknown> = {
        ts: now(),
        event: "PostToolUse",
        tool: event.toolName === "write" ? "Write" : "Edit",
        mode,
        session_id: sessionId(ctx),
        root,
        paths: [abs],
      };

      if (!P.inCorpus(abs, root)) {
        appendLog(root, { ...base, decision: "passthrough" });
        return undefined;
      }

      const [argv, reason] = resolveGate(root);
      const carry = { structuredContent: (event as { structuredContent?: unknown }).structuredContent };
      if (!argv) {
        appendLog(root, P.gateUnavailableRecord(base, enforce, { detail_tail: reason }));
        return enforce
          ? { isError: true, content: [{ type: "text", text: `[zft lint] GATE_UNAVAILABLE: ${reason}` }], ...carry }
          : undefined;
      }

      let res: ReturnType<typeof spawnSync>;
      try {
        res = spawnSync(argv[0], [...argv.slice(1), "lint", root], {
          cwd: root, encoding: "utf8", timeout: GATE_TIMEOUT_MS,
        });
      } catch (e) {
        appendLog(root, P.gateUnavailableRecord(base, enforce, { detail_tail: String(e) }));
        return enforce
          ? { isError: true, content: [{ type: "text", text: `[zft lint] GATE_UNAVAILABLE: ${String(e)}` }], ...carry }
          : undefined;
      }
      if (res.error) {
        const detail = res.error.message ?? "spawn failed";
        appendLog(root, P.gateUnavailableRecord(base, enforce, { detail_tail: detail }));
        return enforce
          ? { isError: true, content: [{ type: "text", text: `[zft lint] GATE_UNAVAILABLE: ${detail}` }], ...carry }
          : undefined;
      }

      const out = ((res.stdout ?? "") + (res.stderr ?? "")).trim();
      const d = P.gateDecision(res.status, out, enforce);
      appendLog(root, { ...base, decision: d.decision, blocked: d.blocked, gate: d.gate, detail_tail: d.detail_tail });

      if (d.blocked) {
        return { isError: true, content: [{ type: "text", text: `[zft lint] ${d.gate.status.toUpperCase()} after edit to ${abs}\n${out}`.slice(0, 4000) }], ...carry };
      }
      if (d.gate.status === "failed") {
        // observe mode: report appended, not blocked
        const existing = Array.isArray(event.content) ? event.content : [];
        return { content: [...existing, { type: "text", text: `[zft lint] L0 FAILED (observe — recorded, not blocked)\n${d.detail_tail ?? out.slice(-2000)}` }], ...carry };
      }
      return undefined;
    } catch (e) {
      // fail-safe: a gate bug must never break the session
      try { appendLog(ctx.cwd, { ts: now(), event: "glue_error", error: String(e) }); } catch { /* ignore */ }
      return undefined;
    }
  });

  // ------------------------------------------------- settle gate (turn_end)
  pi.on("turn_end", (_e, ctx) => {
    try {
      const root = P.findStoreRoot(ctx.cwd);
      if (!root) return;
      const enforce = P.isEnforce(process.env.ZFT_HOOK_MODE ?? "observe");
      const [argv, reason] = resolveGate(root);
      if (!argv) {
        appendLog(root, { ts: now(), event: "turn_end", decision: "gate_unavailable", blocked: enforce, detail_tail: reason });
        return;
      }
      let res: ReturnType<typeof spawnSync>;
      try {
        res = spawnSync(argv[0], [...argv.slice(1), "check", root], {
          cwd: root, encoding: "utf8", timeout: GATE_TIMEOUT_MS,
        });
      } catch (e) {
        appendLog(root, { ts: now(), event: "turn_end", decision: "gate_unavailable", blocked: enforce, detail_tail: String(e) });
        return;
      }
      const out = ((res.stdout ?? "") + (res.stderr ?? "")).trim();
      const check = P.parseCheckResult(out);
      const runId = P.latestRunId(join(root, ".zft", "runs"));
      const cap = parseInt(process.env.ZFT_SETTLE_CAP ?? "3", 10) || 3;
      const counter = counters.get(`${root}|${sessionId(ctx)}`) ?? 0;
      const d = P.settleDecision(counter, check.ok, cap);
      counters.set(`${root}|${sessionId(ctx)}`, d.nextCounter);

      appendLog(root, {
        ts: now(), event: "turn_end", decision: d.action,
        ok: check.ok, counter: d.nextCounter, cap, run: runId,
        session_id: sessionId(ctx),
      });

      if (d.action === "demand") {
        pi.sendMessage(
          { customType: "zft-settle-gate", content: P.buildDemandText(runId, check.failures, d.nextCounter), display: true },
          { triggerTurn: true, deliverAs: "followUp" });
      } else if (d.action === "give_up") {
        pi.sendMessage(
          { customType: "zft-settle-gate", content: P.buildGiveUpText(runId, check.failures, cap), display: true },
          { triggerTurn: true, deliverAs: "followUp" });
      }
    } catch (e) {
      // fail-safe
    }
  });
};

// ---------------------------------------------------------------- fake pi
export const makeFakePi = (): {
  fire: (event: string, eventObj: unknown, ctx: unknown) => unknown;
  sent: { text: string; triggerTurn?: boolean; deliverAs?: string }[];
} => {
  const handlers = new Map<string, ((e: unknown, c: unknown) => unknown)[]>();
  const api = {
    sent: [] as { text: string; triggerTurn?: boolean; deliverAs?: string }[],
    on(event: string, handler: (e: unknown, c: unknown) => unknown) {
      const list = handlers.get(event) ?? [];
      list.push(handler);
      handlers.set(event, list);
    },
    sendMessage(msg: { customType: string; content: unknown; display?: boolean }, opts: { triggerTurn?: boolean; deliverAs?: string }) {
      api.sent.push({ text: typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content), triggerTurn: opts.triggerTurn, deliverAs: opts.deliverAs });
    },
    fire(event: string, eventObj: unknown, ctx: unknown): unknown {
      let out: unknown;
      let n = 0;
      for (const h of handlers.get(event) ?? []) { out = h(eventObj, ctx); n += 1; }
      return n === 1 ? out : undefined;
    },
  };
  return api;
};
