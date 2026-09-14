"""C-19/C-19b: extraction CLI determinism + performance budget guard (plan §0)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("TRACEAGENT_REPO")
            or Path(__file__).resolve().parents[2])


def test_extract_cli_wires_and_reports():
    """Entrypoint seam: zft extract <root> → JSON bindings to stdout."""
    r = subprocess.run([sys.executable, "-m", "traceagent.cli.main", "extract", str(REPO)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    bindings = json.loads(r.stdout.strip().splitlines()[-1])
    assert isinstance(bindings, list) and len(bindings) >= 1


def test_bench_budgets_smoke():
    """C-19b: core stages complete within budget ceilings (seconds, not minutes).

    Budgets are assertions, tuned to measured lab constants (plan §0):
      parse+codegen of 26 clauses and extraction of a small tree are sub-second.
    """
    from traceagent.dsl.ears import parse_statement
    from traceagent.dsl.predicate import compile_predicate

    corpus = sorted((REPO / ".zft" / "specs").rglob("*.json"))
    t0 = time.perf_counter()
    for path in corpus:
        node = json.loads(path.read_text())
        compile_predicate(node["invariants"][0]["property"])
        parse_statement(node["invariants"][0]["statement"])
    dt = time.perf_counter() - t0
    assert dt < 1.0, f"parse stage budget blown: {dt:.2f}s for 26 clauses"
