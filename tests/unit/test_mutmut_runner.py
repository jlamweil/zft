"""C-23/C-24: mutation campaign runner (micro-mutator) + survivor taxonomy.

Decision record: mutmut's sandbox proved unstable for our layout (C-36);
the runner is implemented directly per plan C-23 terms.
"""


import json
import os
from pathlib import Path

from zft.debug.ledger import RunLedger
from zft.gates.runners.mutmut_runner import (
    generate_mutants,
    parse_results,
    run_campaign,
)
from zft.gates.sandbox import prepare_sandbox

MODULE = """def expired(t):
    return t > 100

def validate(t):
    if expired(t):
        return err("Unauthorized")
    if t < 0:
        return err("Invalid")
    return ("Ok", t)

def err(code):
    return ("Err", code)

def row_hash(rows):
    h = 0
    for r in rows:
        h ^= hash(r)
    return h

def format_row(r):
    if r is None:
        return "<empty>"
    return f"{r:>10}"
"""

TESTS = """from hypothesis import given, settings, strategies as st
from oracle import expired, err
from module import validate, row_hash, format_row

@settings(max_examples=50, deadline=None, derandomize=True)
@given(t=st.integers())
def test_expired(t):
    assert (not (expired(t))) or (validate(t) == err("Unauthorized"))

@settings(max_examples=20, deadline=None, derandomize=True)
@given(t=st.integers(min_value=95, max_value=105))
def test_boundary(t):
    if t == 100:
        assert validate(t) == ("Ok", 100)

@settings(max_examples=30, deadline=None, derandomize=True)
@given(rows=st.lists(st.integers()))
def test_row_hash(rows):
    assert row_hash(rows) == row_hash(list(reversed(rows)))

@settings(max_examples=30, deadline=None, derandomize=True)
@given(r=st.integers())
def test_format_row(r):
    assert format_row(r) is not None
"""

REPO = os.environ.get("ZFT_REPO") or str(Path(__file__).resolve().parents[2])

ORACLE = """def expired(t):
    return t > 100

def err(code):
    return ("Err", code)
"""


def _prepare(tmp_path):
    src = tmp_path / "src"
    tests = tmp_path / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "module.py").write_text(MODULE)
    (tests / "test_module.py").write_text(TESTS)
    (tests / "oracle.py").write_text(ORACLE)
    return prepare_sandbox(tmp_path / "sandbox",
                           mutate_paths=[src / "module.py"], also_copy=[tests])


def test_generate_mutants_excludes_comments_and_bad_syntax():
    mutants = generate_mutants(MODULE, "module.py")
    assert len(mutants) >= 5
    for name, src_text, fn in mutants:
        assert "::fn:" in name
        assert src_text != MODULE
        compile(src_text, name, "exec")


# GATE-MUTATION-ATTRIBUTION: triage T-2 — generate_mutants mapped only
# top-level FunctionDefs, so every mutant inside a class body attributed to
# fn:<module> and could never match --scope (the whole predicate parser P was
# invisible to attribution and scoping).
CLASS_MODULE = '''\
MAX = 2

class Pile:
    def allow(self, n):
        return n == MAX

    def deny(self, n):
        if n < 0:
            return True
        return False
'''


# @trace("GATE-MUTATION-ATTRIBUTION")
def test_campaign_kills_and_classifies(tmp_path):
    sandbox = _prepare(tmp_path)
    result = run_campaign(
        sandbox, test_paths=["tests/test_module.py"],
        scope_functions={"expired", "validate", "err"},
    )
    assert result.ok, "restored module must pass the suite again (reverse check)"
    assert result.total_mutants > 0
    # Wave C / WP-C1: scope filters execution. Out-of-scope mutants (here
    # format_row's) are still attributed to the total but never run, so only
    # in-scope mutants can be executed or survive.
    assert result.in_scope_total == 2
    assert result.total_mutants > result.in_scope_total
    assert result.executed == result.in_scope_total
    assert result.in_scope_killed == 2
    assert result.survivors == []


def test_resume_skips_prior_verdicts(tmp_path):
    sandbox = _prepare(tmp_path)
    led = RunLedger.start(tmp_path / "runs", manifest={"stage": "L2"}, repo=tmp_path)
    r1 = run_campaign(sandbox, test_paths=["tests/test_module.py"],
                      scope_functions={"expired", "validate", "err"}, ledger=led,
                      repo_root=REPO)
    led.close()
    led2 = RunLedger.start(tmp_path / "runs", manifest={"stage": "L2", "resume": True},
                           repo=tmp_path)
    r2 = run_campaign(sandbox, test_paths=["tests/test_module.py"],
                      scope_functions={"expired", "validate", "err"}, ledger=led2,
                      resume=True, repo_root=REPO)
    led2.close()
    assert r1.total_mutants == r2.total_mutants
    # Wave C / WP-C1: only in-scope mutants are executed, so only their
    # prior verdicts can be resumed — out-of-scope ones are filtered first.
    assert r2.resumed == r2.in_scope_total
    assert r2.executed == 0
    assert r1.survivor_names == r2.survivor_names
    assert r1.in_scope_killed > 0, "fixture must actually kill in-scope mutants"
    assert r2.in_scope_killed == r1.in_scope_killed


# wave2 risk #1 (zft lineage): a hung mutant run is not evidence of a caught
# mutant — it must be excluded from `killed` and reported as its own class.
HANG_MODULE = """def bounded(n):
    i = 0
    while i < n:
        i = i + 1
    return i
"""

HANG_TESTS = """from module import bounded

def test_bounded():
    assert bounded(3) == 3
"""


def _prepare_hang(tmp_path):
    src = tmp_path / "src"
    tests = tmp_path / "tests"
    src.mkdir()
    tests.mkdir()
    (src / "module.py").write_text(HANG_MODULE)
    (tests / "test_module.py").write_text(HANG_TESTS)
    return prepare_sandbox(tmp_path / "sandbox",
                           mutate_paths=[src / "module.py"], also_copy=[tests])


def test_timed_out_mutant_is_its_own_class(tmp_path):
    # `while i < n` -> `>=` fails fast (killed); `i = i + 1` -> `-` hangs.
    sandbox = _prepare_hang(tmp_path)
    result = run_campaign(sandbox, test_paths=["tests/test_module.py"], timeout_s=3)
    assert result.ok, "restored module must pass the suite again (reverse check)"
    assert result.total_mutants == 2
    assert result.executed == 2
    assert len(result.timed_out) == 1, "exactly the `+`->`-` mutant hangs"
    hanger = result.timed_out[0]
    assert "::line:4::" in hanger
    assert hanger not in result.survivor_names
    assert result.killed == 1
    cache = json.loads((sandbox / ".zft" / "cache" / "mutants.json").read_text())
    assert cache[hanger]["outcome"] == "timeout"  # C4: entries are {outcome, in_scope}


def test_resume_restores_timeout_class_without_rerun(tmp_path):
    sandbox = _prepare_hang(tmp_path)
    names = [n for n, _, _ in generate_mutants(HANG_MODULE, "module.py")]
    cache_dir = sandbox / ".zft" / "cache"
    cache_dir.mkdir(parents=True)
    # legacy checkpoints store booleans: False meant killed
    (cache_dir / "mutants.json").write_text(json.dumps(
        {names[1]: "timeout", names[0]: False}, sort_keys=True))
    result = run_campaign(sandbox, test_paths=["tests/test_module.py"],
                          resume=True, timeout_s=3)
    assert result.resumed == 2
    assert result.executed == 0
    assert result.timed_out == [names[1]]
    assert result.killed == 1
    assert result.survivor_names == []


# --- parse_results pins (2026-09-19 sitting): the campaign-checkpoint
# recovery surface had no direct tests — all 27 of its mutants classed
# "no tests" in the 09-18 fresh generation (jobs/results-mut-gates);
# A/B'd 27/27 killed via mutmut's own trampoline before landing.


def test_parse_results_absent_checkpoint_is_all_zeros(tmp_path):
    """No campaign checkpoint in the sandbox: exactly ([], 0, 0) — the
    absent-ledger shape run_campaign's resume path keys on."""
    survivors, total, killed = parse_results(tmp_path)
    assert survivors == []
    assert total == 0
    assert killed == 0


def test_parse_results_classifies_checkpoint_entries_by_outcome(tmp_path):
    """Per-entry classification: dict entries by their 'outcome' field,
    legacy boolean checkpoints (False = killed, True = survived); a
    'timeout' entry counts in total only — a hang is attributable, not a
    kill — and lands in neither survivors nor killed."""
    checkpoint = tmp_path / ".zft" / "cache" / "mutants.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(json.dumps({
        "m_survived_a": {"outcome": "survived"},
        "m_survived_b": {"outcome": "survived"},
        "m_killed": {"outcome": "killed"},
        "m_hang": {"outcome": "timeout"},
        "m_legacy_killed": False,
        "m_legacy_survived": True,
    }))
    survivors, total, killed = parse_results(tmp_path)
    assert sorted(survivors) == [
        "m_legacy_survived",
        "m_survived_a",
        "m_survived_b",
    ]
    assert total == 6
    assert killed == 2
