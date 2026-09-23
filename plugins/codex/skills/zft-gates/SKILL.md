---
name: zft-gates
description: Use when working in a repo with a zft contract store (a .zft/ directory) — after editing .zft/ contract clauses run the L0 lint gate, before claiming work done run the fast check tier, and interpret typed gate rejections and run ledgers. Not for repos without a .zft/ contract corpus.
---

# ZFT gates

ZFT validates work against a versioned contract store: `.zft/specs/**`
holds clause nodes whose `content_hash` is checked, and gates accept or reject
on mechanically checkable evidence. There is no green without a gate run —
"the change is small" is not an exemption.

## Which gate, when

| Command | Tier | When |
| --- | --- | --- |
| `zft lint <root>` | L0 | after **any** edit under `.zft/` |
| `zft check <root>` | fast (L0 + L2-fast + gherkin) | before claiming a task done |

Both exit non-zero on failure. `check` journals its run under
`.zft/runs/<run_id>/` — cite the run id in your final answer, do not
paraphrase what the JSON said.

## After editing a contract clause

1. Run `zft lint .` from the repo root.
2. On `L0 FAILED`, every `✗` line names the file and the reason, and a `hint:`
   names the fix seam (e.g. recompute `content_hash` with
   `zft.spec.canon.canonical_hash`). Fix the node.
3. Never weaken, delete, or rewrite a clause to make the gate green — that is
   a contract change and needs renegotiation, not a lint dodge.
4. Re-run until `L0 PASSED`.

## Before claiming done

Run `zft check .` and require `"ok": true` in the JSON with every due
clause bound. If `"ok"` is false, the `failures` list is your work list.

## Never

- Hand-edit anything under `.zft/` (run ledgers, attestations, this
  hook's own log). It is generated evidence; faking it is fabrication.
- Report a gate as green without a run id or command output from this session.
- Proceed on a red gate — the hook may only warn (observe mode), but the gate
  result binds either way; CI runs the same one.

## Hook companion

`plugins/codex/hooks/gates_hook.py` (registered via `plugins/codex/hooks.json`)
runs L0 automatically after every apply_patch/Edit/Write that touches
`.zft/**` and logs to `.zft/gates-hook/log.jsonl`. In its default
`observe` mode it records failures without blocking; set
`ZFT_HOOK_MODE=enforce` to make an L0 regression feed straight back
into the session. The hook is a backstop — the workflow above still binds.
