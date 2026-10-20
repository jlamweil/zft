/**
 * pi-zft core-delegation tests (C3).
 *
 * policy.ts must RE-EXPORT the shared zft-gate-core policy units (same
 * function identities, not copies) so opencode-zft and pi-zft can never
 * diverge on corpus logic.
 *
 * Run: node --test 'packages/pi-zft/test/*.test.ts'
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import * as policy from "../lib/policy.ts";
import * as core from "../core/gate-core.js";

test("policy re-exports the core policy units by identity", () => {
  for (const name of [
    "findStoreRoot",
    "inCorpus",
    "corpusPathsFor",
    "parsePatchPaths",
    "resolveGate",
    "runGate",
    "appendLog",
    "now",
    "resetGateMemo",
    "LOG_REL",
    "CORPUS_DIR",
    "GATE_TIMEOUT_MS",
    "toAbsolute",
  ] as const) {
    assert.equal(policy[name], core[name], `policy.${name} should be the core export`);
  }
});

test("pi EDIT_TOOLS is the documented subset of core EDIT_TOOLS", () => {
  const piTools = [...policy.EDIT_TOOLS];
  for (const t of piTools) assert.ok(core.EDIT_TOOLS.has(t), `core must accept ${t}`);
  assert.deepEqual(piTools.sort(), ["edit", "write"]); // pi has no apply_patch
});
