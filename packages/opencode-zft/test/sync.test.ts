/**
 * SoT sync contract (Z0c / audit F3): the PACKAGE dir is canonical; the
 * .opencode/plugins deploy dir is a synced copy. `scripts/sync-opencode-zft.mjs`
 * is the single writer of the deploy dir, and it runs as `pretest`, so no
 * test can ever exercise a stale deploy copy.
 *
 * Run: bun test packages/opencode-zft/test/sync.test.ts
 */
import { test, expect, afterEach } from "bun:test";
import { execSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(import.meta.dir, "..", "..", "..");
const PKG = join(ROOT, "packages", "opencode-zft");
const DEPLOY = join(ROOT, ".opencode", "plugins");
const SCRIPT = join(ROOT, "scripts", "sync-zft-gates.mjs");

const md5 = (p: string) => createHash("md5").update(readFileSync(p)).digest("hex");

const FILES = ["zft-gate.ts", "zft-lint-gate.js"];
const CORE_SITES = [
  join(PKG, "core", "gate-core.js"),
  join(DEPLOY, "core", "gate-core.js"),
  join(ROOT, "packages", "pi-zft", "core", "gate-core.js"),
];
const CORE_SRC = join(ROOT, "packages", "zft-gate-core", "lib", "gate-core.js");

test("sync script exists, fixes drift, and is idempotent", () => {
  const target = join(DEPLOY, "zft-gate.ts");
  const saved = readFileSync(target, "utf8");
  try {
    writeFileSync(target, "// DRIFTED DEPLOY\n");
    const first = execSync(`node ${JSON.stringify(SCRIPT)}`, { encoding: "utf8" });
    expect(first).not.toContain("up-to-date"); // first run repaired the drift
    const second = execSync(`node ${JSON.stringify(SCRIPT)}`, { encoding: "utf8" });
    expect(second).toContain("up-to-date"); // second run is a no-op
    for (const f of FILES) {
      expect(md5(join(DEPLOY, f))).toBe(md5(join(PKG, f)));
    }
  } finally {
    writeFileSync(target, saved);
  }
});

test("sync is package->deploy: a deploy edit is overwritten by the package content", () => {
  const target = join(DEPLOY, "zft-lint-gate.js");
  const saved = readFileSync(target, "utf8");
  try {
    writeFileSync(target, "// TAMPERED DEPLOY COPY\n");
    execSync(`node ${JSON.stringify(SCRIPT)}`, { encoding: "utf8" });
    expect(md5(target)).toBe(md5(join(PKG, "zft-lint-gate.js")));
  } finally {
    writeFileSync(target, saved);
  }
});

test("core is synced fresh to both adapter sites", () => {
  execSync(`node ${JSON.stringify(SCRIPT)}`, { encoding: "utf8" });
  for (const site of CORE_SITES) {
    expect(md5(site)).toBe(md5(CORE_SRC));
  }
});

test("pretest is wired: 'bun test' in the package runs the sync first", () => {
  const pkgJson = JSON.parse(readFileSync(join(PKG, "package.json"), "utf8"));
  expect(pkgJson.scripts?.pretest).toContain("sync-zft-gates");
});
