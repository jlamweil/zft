/**
 * zft-gates pi extension — the file pi loads.
 *
 * THIN: one guarded factory. Tables in lib/policy.ts (contract-tested),
 * event wiring in lib/glue-pi.ts (fake-pi tested).
 *
 * Outside a store (.zft/ not found up the tree) the extension is
 * completely silent. Modes via ZFT_HOOK_MODE (observe default, enforce
 * blocks). Settle gate: ZFT_SETTLE_CAP consecutive failures before
 * giving up (default 3).
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { makeZftGlue } from "./lib/glue-pi.ts";

const GUARD = "__zft_pi_glue_loaded__";

export default function zftPiExtension(pi: ExtensionAPI): void {
  const g = globalThis as Record<string, unknown>;
  if (g[GUARD]) return; // pi may load repo-local + global copies: load once
  g[GUARD] = true;
  makeZftGlue()(pi);
}
