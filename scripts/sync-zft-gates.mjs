#!/usr/bin/env node
// Z0c/F3 SoT sync — single writer, correct arrow:
//   canonical:  packages/opencode-zft/   packages/pi-zft/   packages/zft-gate-core/
//   deployed:   .opencode/plugins/       packages/{opencode,pi}-zft/core/
//
// Usage:
//   node scripts/sync-zft-gates.mjs             (copy package -> deploy + core sites)
//   node scripts/sync-zft-gates.mjs --assert    (verify every deploy/core site
//                                                exists and is byte-identical to
//                                                its canonical source; no writes)
//
// `pretest` runs the copy mode (deploy is a build artifact, so the suite
// must never observe a stale one). `prepublishOnly` runs copy + assert, so
// a publish can never stage a package whose core is missing or stale.
import { mkdirSync, readFileSync, writeFileSync, cpSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = join(dirname(fileURLToPath(import.meta.url)), "..");

// [source, target] pairs, canonical first.
const PAIRS = [
  [join(REPO, "packages/opencode-zft/zft-lint-gate.js"),
   join(REPO, ".opencode/plugins/zft-lint-gate.js")],
  [join(REPO, "packages/opencode-zft/zft-gate.ts"),
   join(REPO, ".opencode/plugins/zft-gate.ts")],
  [join(REPO, "packages/pi-zft/index.ts"),
   join(REPO, ".opencode/plugins/pi-zft-index.ts")],
  [join(REPO, "packages/zft-gate-core/lib/gate-core.js"),
   join(REPO, "packages/opencode-zft/core/gate-core.js")],
  [join(REPO, "packages/zft-gate-core/lib/gate-core.js"),
   join(REPO, ".opencode/plugins/core/gate-core.js")],
  [join(REPO, "packages/zft-gate-core/lib/gate-core.js"),
   join(REPO, "packages/pi-zft/core/gate-core.js")],
];

const assertMode = process.argv.includes("--assert");

let wrote = false;
for (const [src, dst] of PAIRS) {
  const s = readFileSync(src);
  if (assertMode) {
    if (!existsSync(dst)) {
      console.error(`assert: MISSING ${dst.replace(REPO + "/", "")}`);
      process.exit(1);
    }
    const d = readFileSync(dst);
    if (s.byteLength !== d.byteLength || s.toString("utf8") !== d.toString("utf8")) {
      console.error(`assert: STALE ${dst.replace(REPO + "/", "")}`);
      process.exit(1);
    }
    continue;
  }
  mkdirSync(dirname(dst), { recursive: true });
  const cur = existsSync(dst) ? readFileSync(dst) : null;
  if (cur && cur.toString("utf8") === s.toString("utf8")) {
    console.log(`inert: ${dst.replace(REPO + "/", "")}`);
    continue;
  }
  writeFileSync(dst, s);
  wrote = true;
  console.log(`synced: ${dst.replace(REPO + "/", "")}`);
}

if (assertMode) console.log("assert: all core/deploy sites byte-identical to canonical");
else if (!wrote) console.log("up-to-date");
