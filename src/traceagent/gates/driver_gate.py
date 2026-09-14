"""Driver gate (batch-driver contract): the fast, read-only L0-L3 subset.

The ZCode batch driver runs `--gate-cmd '<shell> {folder}'` before every model
send: exit 0 passes the folder, nonzero rejects it, output is capped at ~2000
chars, the driver kills at 120s, and transport errors fail OPEN on the driver
side. This module is the verdict behind `gates/driver-gate.sh`:

- EARS-spec check: every clause statement must parse (`dsl.ears`) — a clause
  the gate cannot read is not acceptable evidence (typed deny, not a warning);
- fast subset: L0 store integrity, L2-fast milestone-scoped coverage (judge
  clauses quarantined), L1 executed property evidence, L3 gate-log projection.
  The L2 mutation campaign stays a merge-gate concern, not a per-task one.

Contract discipline:

- READ-ONLY: no ledger, no verdict-cache writes (`write_cache=False`), no
  gherkin render; pytest children run under the sandbox launch policy
  (`gates.sandbox.STRIPPED_ENV_VARS` + PYTHONDONTWRITEBYTECODE) with the
  hypothesis example database pointed OUTSIDE the workspace at a temp dir that
  is removed on exit. A byte-identical workspace after a green run is pinned
  by tests/unit/test_driver_gate.py.
- FAST: per-suite timeout, bounded single-line payload; a gate that cannot
  finish inside its budget is a rejection, never a hang into the driver's kill
  window (the kill would fail open — the gate itself fails closed).
- TYPED REDS: a crashed stage is a finding (DRIVER_GATE_CRASHED), mirroring
  L0's crashed-lint discipline; an unseeded store stays a deny (never
  green-vacuous — RUNBOOK seed policy).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from traceagent.dsl.ears import EarsError, parse_statement
from traceagent.gates.l0 import run_l0
from traceagent.gates.l2 import run_l2
from traceagent.gates.l3 import build_gate_log
from traceagent.gates.sandbox import STRIPPED_ENV_VARS
from traceagent.spec.store import Store

BUDGET_CHARS = 1800  # driver sink caps at ~2000; stay under with headroom
MAX_FAILURES = 6
MAX_WARNINGS = 8
FAILURE_MAX_CHARS = 200
PRODUCER_MODEL_ENV = "TRACEAGENT_PRODUCER_MODEL"
GATE_MODEL_ENV = "TRACEAGENT_GATE_MODEL"


@dataclass
class DriverGateVerdict:
    ok: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stages: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    l1: dict = field(default_factory=dict)
    ears_checked: int = 0
    models: dict = field(default_factory=dict)
    payload: str = ""  # bounded single-line JSON — the driver-facing verdict


@contextmanager
def _readonly_child_env():
    """Launch policy for gate subprocesses without touching the workspace.

    Parent leak channels stripped (same policy as mutation sandboxes), bytecode
    writes off, hypothesis's example DB redirected to a temp dir outside the
    governed folder; everything is restored afterwards. The temp dir is the one
    deliberate write — system temp, self-removing, never inside {folder}.
    """
    watched = (*STRIPPED_ENV_VARS, "PYTHONDONTWRITEBYTECODE",
               "HYPOTHESIS_STORAGE_DIRECTORY")
    saved = {k: os.environ.get(k) for k in watched}
    db_dir = tempfile.mkdtemp(prefix="traceagent-driver-gate-")
    try:
        for k in STRIPPED_ENV_VARS:
            os.environ.pop(k, None)
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        os.environ["HYPOTHESIS_STORAGE_DIRECTORY"] = db_dir
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(db_dir, ignore_errors=True)


def _ears_findings(root: Path) -> tuple[list[tuple[str, str]], int]:
    """(alias, message) per statement the EARS grammar rejects, plus n checked.

    A corrupt store yields no EARS findings — L0 types that red; EARS only
    judges statements it can actually load.
    """
    failures: list[tuple[str, str]] = []
    checked = 0
    try:
        nodes = Store.load(root).nodes
    except Exception:  # noqa: BLE001 — typed by L0 as STORE_NODE_* denies
        return failures, checked
    for alias, node in sorted(nodes.items()):
        for inv in node.get("invariants", []):
            checked += 1
            try:
                parse_statement(inv.get("statement"))
            except (EarsError, TypeError) as e:
                first = str(e).splitlines()[0] if str(e) else "unparseable"
                failures.append(
                    (alias, f"{alias}/{inv.get('id', '?')}: {first}"))
    return failures, checked


def run_driver_gate(root: Path | str, examples_timeout_s: int = 60,
                    write_cache: bool = False,
                    budget: int = BUDGET_CHARS,
                    producer_model: str | None = None,
                    gate_model: str | None = None) -> DriverGateVerdict:
    """One read-only gate pass over `root`; never raises — reds are typed.

    (producer, gate) identity is caller-supplied: explicit arguments (the
    CLI's --producer-model/--gate-model flags) first, then the
    TRACEAGENT_*_MODEL config envs, else None — never a default name. An
    unsupplied identity stays null in the verdict and model_dependent stays
    true (GATE-MODEL-INDEPENDENCE fails closed).
    """
    root = Path(root)
    producer_model = producer_model or os.environ.get(PRODUCER_MODEL_ENV)
    gate_model = gate_model or os.environ.get(GATE_MODEL_ENV)
    failures: list[str] = []
    warnings: list[str] = []
    stages: dict[str, bool] = {}
    coverage: dict = {}
    l1_summary: dict = {}
    models: dict = {}
    ears_checked = 0
    failed_aliases: set[str] = set()
    uncovered: list[str] = []

    with _readonly_child_env():
        try:
            ears_failures, ears_checked = _ears_findings(root)
            for alias, msg in ears_failures:
                failed_aliases.add(alias)
                failures.append(msg)
            stages["ears"] = not ears_failures

            v0 = run_l0(root)
            failures.extend(v0.failures)
            warnings = [str(w.get("code")) for w in v0.warnings]
            stages["l0"] = v0.ok

            v2 = run_l2(root, tier="fast", examples_timeout_s=examples_timeout_s,
                        write_cache=write_cache)
            failures.extend(v2.failures)
            stages["l1"] = bool(v2.l1 and v2.l1.ok)
            stages["l2_fast"] = v2.ok
            l1_summary = {"executed": v2.l1.executed if v2.l1 else 0,
                          "ok": stages["l1"]}
            if v2.rejection and v2.rejection.get("fault") == "contract":
                uncovered = list(v2.rejection.get("clause_ids", []))
                failed_aliases.update(uncovered)
            coverage = {
                "deterministic": str(v2.coverage.get("coverage", "")),
                "judge_excluded": list(v2.coverage.get("judge_excluded", []))[:MAX_WARNINGS],
                "uncovered": uncovered[:MAX_WARNINGS],
            }

            events = [{"event": name, "ok": ok} for name, ok in stages.items()]
            gate_log = build_gate_log(
                events,
                producer_model=producer_model,
                gate_model=gate_model,
                judge_excluded=v2.coverage.get("judge_excluded", []),
                deterministic_coverage=str(v2.coverage.get("coverage", "")),
            )
            models = {"producer": gate_log["models"]["producer"],
                      "gate": gate_log["models"]["gate"],
                      "model_dependent": gate_log["model_dependent"]}
        except Exception as e:  # noqa: BLE001 — a crashed gate is a red, not a traceback
            stages["driver_gate"] = False
            failures.append(f"DRIVER_GATE_CRASHED: {e!r}")

    ok = not failures
    doc = {
        "stage": "DRIVER-GATE",
        "ok": ok,
        "folder": str(root),
        "stages": stages,
        "ears_checked": ears_checked,
        "coverage": coverage,
        "l1": l1_summary,
        "models": models,
        "warnings": warnings[:MAX_WARNINGS],
        "failure_count": len(failures),
        "failures": [f[:FAILURE_MAX_CHARS] for f in failures[:MAX_FAILURES]],
    }
    verdict = DriverGateVerdict(ok=ok, failures=failures, warnings=warnings,
                                stages=stages, coverage=coverage, l1=l1_summary,
                                ears_checked=ears_checked, models=models)
    verdict.payload = _render(doc, budget)
    return verdict


def _render(doc: dict, budget: int) -> str:
    """Bounded payload: shrink advisory fields before touching failure names."""
    def without(d: dict, keys: tuple[str, ...]) -> dict:
        return {k: v for k, v in d.items() if k not in keys}

    shrinks = [
        lambda d: d,
        lambda d: without(d, ("warnings",)),
        lambda d: {**without(d, ("warnings",)), "failures": d["failures"][:3]},
        lambda d: {**without(d, ("warnings",)), "failures": d["failures"][:1]},
        lambda d: without(d, ("warnings", "coverage", "models")),
    ]
    out = json.dumps(doc, separators=(",", ":"))
    for shrink in shrinks:
        out = json.dumps(shrink(dict(doc)), separators=(",", ":"))
        if len(out) <= budget:
            return out
    return out[:budget - 15] + "...[truncated]"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: python -m traceagent.gates.driver_gate <folder>")
        return 2
    verdict = run_driver_gate(argv[0])
    print(verdict.payload)
    return 0 if verdict.ok else 1


if __name__ == "__main__":
    sys.exit(main())
