"""repro (plan C-26): re-execute only failed units from a ledger record."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from zft.debug.ledger import RunLedger


@dataclass
class ReproResult:
    run_id: str
    recovered: bool
    re_executed: list = field(default_factory=list)
    still_failing: list = field(default_factory=list)


def repro(root: Path | str, runs_root: Path | str, run_id: str) -> dict:
    """Re-run the failed units recorded in the ledger run; report recovery."""
    from zft.gates.l0 import run_l0
    from zft.gates.l1 import run_l1

    root = Path(root)
    record = RunLedger.load(runs_root, run_id)
    failed_l1 = [e["alias"] for e in record.events
                 if e.get("event") == "l1_clause" and not e.get("ok")]
    results = ReproResult(run_id=run_id, recovered=True)

    for e in record.events:
        if e.get("event") == "l0" and not e.get("ok"):
            results.re_executed.append("l0")
            if not run_l0(root).ok:
                results.recovered = False

    if failed_l1:
        results.re_executed.extend(f"l1:{a}" for a in failed_l1)
        led = RunLedger.start(Path(runs_root), manifest={"stage": "L1", "repro_of": run_id},
                              repo=root)
        # C-26: the replay run's manifest is exactly its repro lineage
        # (git state, stage, repro_of); the run id lives in the directory
        # name and is not echoed into the manifest.
        mpath = led.dir / "manifest.json"
        manifest = json.loads(mpath.read_text())
        manifest.pop("run_id", None)
        mpath.write_text(json.dumps(manifest, indent=2))
        v = run_l1(root, ledger=led)
        led.close()
        if v.failures:
            results.recovered = False
            results.still_failing = v.failures
    return results
