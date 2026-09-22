// zft-lint-gate — run the zft L0 gate when an edit lands in the contract
// corpus.
//
// opencode port of the Codex PostToolUse hook
// (plugins/codex/hooks/gates_hook.py), minus the Python middleman: opencode
// hands us the edited path directly, so this plugin calls the `zft` CLI seam
// itself. The Python script stays the single implementation of gate *policy*
// for Codex; the decision table below mirrors it exactly.
//
// Policy: the gate acts only on the contract corpus (<root>/.zft/**), the
// same seed policy as .pre-commit-hooks.yaml. Every fired event is appended
// to <root>/.zft/gates-hook/log.jsonl. Outside a store the plugin is
// completely silent (no logs, no .zft/ litter in repos that never opted in).
//
// Modes via ZFT_HOOK_MODE: `observe` (default) records gate outcomes to
// <root>/.zft/gates-hook/log.jsonl without blocking; `enforce` throws the L0
// findings back into the session on failure — mandatory feedback, since
// PostToolUse cannot undo the edit. A broken or missing gate is never green:
// it is recorded as gate_unavailable and, in enforce mode, blocks.
//
// Binary resolution: ZFT_BIN > <project>/.venv/bin/zft
// > `zft` on PATH > `python3 -m zft.cli.main`. An explicitly set ZFT_BIN that
// cannot run is authoritative — it fails rather than silently falling back.

import { spawnSync } from "node:child_process"
import fs from "node:fs"
import path from "node:path"

const TAG = "[zft lint]"
const CORPUS_DIR = ".zft"
const LOG_REL = path.join(CORPUS_DIR, "gates-hook", "log.jsonl")
const EDIT_TOOLS = new Set(["edit", "write"])
const GATE_TIMEOUT_MS = 60_000
const STORE_KEYS = ["ZFT_BIN"]

function findStoreRoot(startPath) {
  let dir = startPath
  try {
    if (fs.existsSync(dir) && fs.statSync(dir).isFile()) dir = path.dirname(dir)
  } catch {
    dir = path.dirname(dir)
  }
  while (true) {
    try {
      if (fs.statSync(path.join(dir, CORPUS_DIR)).isDirectory()) return dir
    } catch {
      // not here — keep walking up
    }
    const parent = path.dirname(dir)
    if (parent === dir) return null
    dir = parent
  }
}

function inCorpus(absPath, root) {
  const rel = path.relative(root, absPath)
  return rel !== "" && !rel.startsWith("..") && rel.split(path.sep)[0] === CORPUS_DIR
}

/** Resolve the gate. Returns [argv, null] or [null, reason]. */
function resolveGate(directory) {
  for (const key of STORE_KEYS) {
    const override = process.env[key]
    if (!override) continue
    const argv = override.trim().split(/\s+/).filter(Boolean)
    if (!argv.length) return [null, `${key}=${JSON.stringify(override)}: empty command`]
    // An explicit override is authoritative: verify it exists rather than
    // falling back to a different binary.
    const exe = path.isAbsolute(argv[0]) && fs.existsSync(argv[0])
      ? argv[0]
      : whichOr(argv[0])
    if (!exe) return [null, `${key}=${JSON.stringify(override)}: executable not found`]
    return [[exe, ...argv.slice(1)], null]
  }
  const local = path.join(directory, ".venv", "bin", "zft")
  if (fs.existsSync(local)) return [[local], null]
  if (whichOr("zft")) return [["zft"], null]
  // Last resort: run the module directly. Both import names are probed
  // because the published 0.2.x wheel still exposes `traceagent.cli.main`.
  const py = whichOr("python3") || whichOr("python")
  if (py) {
    const mod = probeModule(py, "zft.cli.main") ?? probeModule(py, "traceagent.cli.main")
    if (mod) return [[py, "-m", mod], null]
  }
  return [null, "no zft executable: set ZFT_BIN or install `pip install zft`"]
}

/** Return the module name if `python -c 'import mod'` succeeds, else null. */
function probeModule(py, mod) {
  try {
    const res = spawnSync(py, ["-c", `import ${mod}`], {
      encoding: "utf8",
      timeout: 10_000,
      env: { ...process.env },
    })
    return res.status === 0 ? mod : null
  } catch {
    return null
  }
}

function whichOr(cmd) {
  // Minimal PATH lookup; avoids depending on a `which` binary.
  const dirs = (process.env.PATH ?? "").split(path.delimiter).filter(Boolean)
  for (const dir of dirs) {
    const cand = path.join(dir, cmd)
    try {
      if (fs.statSync(cand).isFile()) return cand
    } catch {
      // keep scanning
    }
  }
  return null
}

function now() {
  return new Date().toISOString()
}

function appendLog(root, record) {
  try {
    const log = path.join(root, LOG_REL)
    fs.mkdirSync(path.dirname(log), { recursive: true })
    fs.appendFileSync(log, JSON.stringify(record) + "\n")
  } catch {
    // the log is an audit trail, never a reason to crash the session
  }
}

export const ZftLintGate = async ({ directory, sessionID }) => {
  // opencode can load both the global copy and a project copy in one process.
  // Only the first registers; an edit is never double-gated or double-logged.
  const g = globalThis
  if (g.__zftLintGateRegistered) return {}
  g.__zftLintGateRegistered = true

  // opencode may emit tool.execute.after more than once per tool call (result
  // updates); gate the gate on the call id so one edit is one log record.
  const seen = new Set()

  const warn = (msg) => {
    try {
      process.stderr.write(`${TAG} ${msg}\n`)
    } catch {
      // not actionable
    }
  }

  return {
    "tool.execute.after": async (input) => {
      if (!EDIT_TOOLS.has(input.tool)) return
      const key = `${input.callID}:${input.tool}`
      if (seen.has(key)) return
      seen.add(key)

      const fp = input.args?.filePath
      if (typeof fp !== "string" || !fp.trim()) return
      const abs = path.isAbsolute(fp) ? fp : path.resolve(directory, fp)

      const root = findStoreRoot(abs)
      if (!root) return // outside any store: stay completely silent

      const mode = process.env.ZFT_HOOK_MODE ?? "observe"
      const enforce = mode === "enforce"
      const base = {
        ts: now(),
        event: "PostToolUse",
        tool: input.tool === "write" ? "Write" : "Edit",
        mode,
        session_id: sessionID ?? input.sessionID,
      }

      if (!inCorpus(abs, root)) {
        appendLog(root, { ...base, root, paths: [abs], decision: "passthrough" })
        return
      }

      const record = { ...base, root, paths: [abs] }
      const [gateArgv, reason] = resolveGate(root)
      if (!gateArgv) {
        appendLog(root, { ...record, decision: "gate_unavailable", detail_tail: reason })
        warn(`gate unavailable: ${reason}`)
        if (enforce) throw new Error(`${TAG} GATE_UNAVAILABLE: ${reason}`)
        return
      }

      let res
      try {
        res = spawnSync(gateArgv[0], [...gateArgv.slice(1), "lint", root], {
          cwd: root,
          encoding: "utf8",
          timeout: GATE_TIMEOUT_MS,
          env: { ...process.env },
        })
      } catch (e) {
        appendLog(root, { ...record, decision: "gate_unavailable", detail_tail: String(e) })
        warn(`gate unavailable: ${e}`)
        if (enforce) throw new Error(`${TAG} GATE_UNAVAILABLE: ${e}`)
        return
      }
      if (res.error) {
        const detail = res.error.message ?? "spawn failed"
        appendLog(root, { ...record, decision: "gate_unavailable", detail_tail: detail })
        warn(`gate unavailable: ${detail}`)
        if (enforce) throw new Error(`${TAG} GATE_UNAVAILABLE: ${detail}`)
        return
      }

      const out = ((res.stdout ?? "") + (res.stderr ?? "")).trim()
      // The CLI reserves exit 0 for `L0 PASSED` and 1 for `L0 FAILED`; any
      // other outcome is a broken gate, never a green one.
      if (res.status === 0) {
        appendLog(root, { ...record, decision: "allow",
          gate: { name: "L0", status: "passed", exit: 0 } })
        return
      }
      if (res.status === 1 && out.includes("L0 FAILED")) {
        appendLog(root, { ...record, decision: enforce ? "deny" : "allow",
          blocked: enforce,
          gate: { name: "L0", status: "failed", exit: 1 },
          detail_tail: out.slice(-2000) })
        if (enforce) {
          throw new Error(`${TAG} L0 FAILED after edit to ${abs}\n${out}`.slice(0, 4000))
        }
        warn(`L0 FAILED after edit to ${abs} (observe mode — recorded, not blocked)`)
        return
      }
      appendLog(root, { ...record, decision: "gate_unavailable",
        gate: { name: "L0", status: "unavailable", exit: res.status },
        detail_tail: out.slice(-400) })
      warn(`gate unavailable: exit ${res.status}`)
      if (enforce) throw new Error(`${TAG} GATE_UNAVAILABLE: gate exited ${res.status}; tail: ${out.slice(-400)}`)
    },
  }
}
