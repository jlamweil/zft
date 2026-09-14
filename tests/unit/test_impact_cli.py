"""v0.1 TR-IMPACT-QUERY: CLI surface for the impact query (README contract).

The file queries ITSELF: test_impact_cli_func carries the @trace marker the
extractor will see, so `zft impact tests/unit/test_impact_cli.py` has a
known binding to assert against.
"""
from __future__ import annotations

import subprocess
import sys


# @trace("TR-IMPACT-QUERY")
def test_impact_cli_func():
    """Bound element used as the known query target below."""


# @trace("TR-IMPACT-QUERY")
def _run_impact(args):
    return subprocess.run(
        [sys.executable, "-m", "zft.cli.main", "impact"] + args,
        capture_output=True,
        text=True,
    )


# @trace("TR-IMPACT-QUERY")
def test_file_path_impact():
    target = "tests/unit/test_impact_cli.py"
    r = _run_impact([target])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TR-IMPACT-QUERY" in r.stdout
    assert "test_impact_cli_func" in r.stdout


# @trace("TR-IMPACT-QUERY")
def test_symbol_narrowing():
    target = "tests/unit/test_impact_cli.py:test_impact_cli_func"
    r = _run_impact([target])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "test_impact_cli_func" in r.stdout
    # narrowed to the symbol: the other test names must NOT appear
    assert "test_file_path_impact" not in r.stdout


# @trace("TR-IMPACT-QUERY")
def test_unknown_target():
    r = _run_impact(["nonexistent.py"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no bindings" in r.stdout.lower()


# @trace("TR-IMPACT-QUERY")
def test_base_flag_honest_rejection():
    r = _run_impact(["--base", "HEAD~1", "tests"])
    assert r.returncode == 2
    assert "not supported" in (r.stdout + r.stderr).lower()
