"""WP-C4: CLI `gate-campaign --resume` is wired and actually resumes."""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _run(resume: bool):
    args = [sys.executable, "-m", "traceagent.cli.main", "gate-campaign",
            "--module", "src/traceagent/spec/lint.py",
            "--tests", "tests/unit/test_lint_store.py",
            "--scope", "lint_store"]
    if resume:
        args.append("--resume")
    args.append(str(REPO))
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True)


def test_gate_campaign_resume_flag():
    r1 = _run(resume=False)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    out1 = json.loads(r1.stdout)
    assert out1["in_scope_total"] >= 1
    assert out1["resumed"] == 0

    r2 = _run(resume=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    out2 = json.loads(r2.stdout)
    assert out2["total"] == out1["total"]
    assert out2["resumed"] == out1["in_scope_total"]

    ckpt = REPO / ".traceagent" / "sandbox" / ".traceagent" / "cache" / "mutants.json"
    state = json.loads(ckpt.read_text())
    assert all(isinstance(v, dict) and "in_scope" in v for v in state.values())
