"""L3 attestation projection (plan C-27): gate log, judge quarantine, model labeling.

Pure projection over ledger events: malformed events (missing keys, non-dicts)
are skipped, never a KeyError — the log may carry events from any producer.
"""
from __future__ import annotations


def build_gate_log(events: list[dict], producer_model: str | None,
                   gate_model: str | None, judge_excluded: list[str],
                   deterministic_coverage: str,
                   l0_warnings: list | None = None) -> dict:
    stages: dict[str, bool] = {}
    for e in events:
        if not isinstance(e, dict):
            continue
        name = e.get("event")
        if isinstance(name, str) and name.startswith("l") and "ok" in e:
            stages[name] = e["ok"]
    log = {
        "stages": stages,
        "judge_excluded": judge_excluded,
        "deterministic_coverage": deterministic_coverage,
        "models": {"producer": producer_model, "gate": gate_model},
        "model_dependent": producer_model == gate_model,
    }
    if l0_warnings is not None:  # published only when the caller passes them
        log["l0_warnings"] = l0_warnings
    return log
