// C6 — publish staging: npm pack --dry-run must stage the core.
// The package ships the relative-synced copy of zft-gate-core; a
// broken publish (missing core/, stale files list) is caught here,
// pre-publish, without touching the npm registry.
import { test, expect } from "bun:test";
import { execSync } from "node:child_process";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const PKG = join(dirname(fileURLToPath(import.meta.url)), "..");

const packFiles = () => {
  // npm prints the listing on STDERR; merge both streams.
  const out = execSync("npm pack --dry-run 2>&1", { cwd: PKG, encoding: "utf8" });
  const lines = out.split("\n");
  const start = lines.findIndex((l) => l.includes("Tarball Contents"));
  const end = lines.findIndex((l) => l.includes("Tarball Details"));
  return lines.slice(start + 1, end).map((l) => l.replace(/^npm notice\s*/, "").trim().split(/\s+/).pop()!);
};

test("pack listing includes every core file and the original surface", () => {
  const files = packFiles();
  for (const f of [
    "package.json",
    "README.md",
    "zft-lint-gate.js",
    "zft-gate.ts",
    "index.ts",
    "core/gate-core.js",
  ]) {
    expect(files.includes(f), true, `missing from pack listing: ${f}\n${files.join("\n")}`);
  }
});

test("pack listing excludes tests and repo scripts", () => {
  const files = packFiles();
  for (const bad of ["test/", "parity.test.ts", "sync-zft-gates"]) {
    expect(files.some((f) => f.includes(bad)), false, `must not ship: ${bad}\n${files.join("\n")}`);
  }
});
