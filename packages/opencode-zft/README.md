# opencode-zft

[opencode](https://opencode.ai) gates for [zft](https://github.com/jlamweil/zft) —
the contract-first traceability framework for multi-agent deliverables.

Two gates, both enforced by the same CLI they ship with:

- **Dispatch gate** (`zft-gate.ts`) — intercepts task dispatch to an
  implementation subagent and refuses it unless the task description carries a
  `[contract: <name>]` binding. No contract, no implementation work: the
  requirement is agreed before the deliverable exists, and the refusal names
  the missing binding so the producer can fix it in one step.
- **L0 lint gate** (`zft-lint-gate.js`) — fires on every edit that touches the
  contract corpus (`<root>/.zft/**`) and runs `zft lint <root>` (structural
  integrity of the clause store), appending the outcome to
  `<root>/.zft/gates-hook/log.jsonl`.

Both fail closed: a repo without a seeded contract store never pays gate
latency, and an unseeded store is a typed deny (`STORE_MISSING`, exit 1),
never green-vacuous.

## Install

```bash
bun add -D opencode-zft        # or: npm install -D opencode-zft
pip install zft                # the CLI the gates invoke
```

Then list the package in your opencode config:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["opencode-zft"]
}
```

opencode installs the package with Bun at startup. The gates find the `zft`
executable by probing for an importable `zft.cli.main` (falling back to the
`zft` binary on PATH); the Python side is the thing that actually runs.

## Requirements

- opencode (loads TypeScript plugins directly — no build step)
- Python ≥ 3.12 with `zft` installed in the environment the gates shell out to

## Alternatives

Rather install from the source tree? The same two files live at
[`.opencode/plugins/`](https://github.com/jlamweil/zft/tree/main/.opencode/plugins)
in the repository — copy them into your project's `.opencode/plugins/` or your
global `~/.config/opencode/plugins/`. The npm package exists so that path
stays versioned and updatable.

## License

Apache-2.0, same as zft.
