"""C-23/C-24: mutation campaign runner (micro-mutator) + survivor taxonomy.

Decision record: mutmut's sandbox proved unstable for our layout (C-36);
the runner is implemented directly per plan C-23 terms.
"""


import json
import os
from pathlib import Path

from zft.debug.ledger import RunLedger
from zft.gates.runners import mutmut_runner as mm
from zft.gates.runners.mutmut_runner import (
    _outcome,
    generate_mutants,
    parse_results,
    run_campaign,
)
from zft.gates.runners.pytest_runner import RunnerResult
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


# ---------------------------------------------------------------------------
# kill-shard pins (0920 runners cut): direct, deterministic pins over the
# campaign runner's own seams — run_pytest/gate_env faked so every call,
# ledger event, checkpoint write, and verdict field is observed by full
# equality. Preregistered waiver candidates live in
# scratch/runners-shard/suspects.md.
# ---------------------------------------------------------------------------

PIN_MODULE = """def f1(a):
    return a > 0

def f2(a):
    return a < 0

def f3(a):
    return a + 1

def f4(a):
    return True
"""

PIN_NAMES = [
    "mod.py::fn:f1::line:2::>-><",
    "mod.py::fn:f2::line:5::<->>=",
    r"mod.py::fn:f3::line:8::\+->-",
    r"mod.py::fn:f4::line:11::return True\b->return False",
]


def _pin_sandbox(tmp_path, source=PIN_MODULE):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "mod.py").write_text(source)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.mutmut]\npaths_to_mutate = ["mod.py"]\n')
    return tmp_path


class _FakeLedger:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


def _install_fakes(monkeypatch, results, gate_envs):
    """Fake run_pytest (pops `results`) and gate_env (records `extra`)."""
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return results.pop(0)

    def fake_gate_env(extra):
        gate_envs.append(extra)
        return {"G": extra is None}

    monkeypatch.setattr(mm, "run_pytest", fake_run)
    monkeypatch.setattr(mm, "gate_env", fake_gate_env)
    return calls


def _res(*specs):
    return [RunnerResult(ok=ok, duration_ms=1234, timed_out=to, tail="")
            for ok, to in specs]


def test_campaign_execution_contract_end_to_end(tmp_path, monkeypatch):
    """One deterministic campaign: 2 kills + 1 survivor + 1 timeout, then the
    final reverse check. Pins the exact call shape, ledger events, checkpoint
    bytes, verdict fields, counters, and module restore."""
    sb = _pin_sandbox(tmp_path)
    results = _res((False, False), (False, False), (True, False), (False, True),
                   (True, False))  # m1 killed, m2 killed, m3 survived, m4 timeout, final ok
    gate_envs = []
    calls = _install_fakes(monkeypatch, results, gate_envs)
    led = _FakeLedger()
    repo = tmp_path / "repo"
    # Scripted clock: duration_ms must equal the scripted delta exactly. The
    # old wall-clock `> 0` assert was a machine-timing flake — in a warm
    # stats-subset process the faked campaign truncates to 0 ms, and the
    # flake manufactured three false mutation kills (the 09-21 merged
    # regen's _41/_46/_48; control-proven mutant-independent 2026-09-22).
    times = iter([10.0, 12.0])
    monkeypatch.setattr(mm.time, "perf_counter", lambda: next(times))
    r = run_campaign(sb, test_paths=["t_x.py"], timeout_s=9, ledger=led,
                     repo_root=repo)
    assert r.total_mutants == 4
    assert r.executed == 4
    assert r.resumed == 0
    assert r.killed == 2
    assert r.in_scope_killed == 2
    assert r.in_scope_total == 4
    assert r.survivors == [PIN_NAMES[2]]
    assert r.survivor_names == [PIN_NAMES[2]]
    assert r.timed_out == [PIN_NAMES[3]]
    assert r.ok is False
    assert r.duration_ms == 2000
    # the mutated module is restored byte-exact after the loop
    assert (sb / "mod.py").read_text() == PIN_MODULE
    # every run_pytest call: exact positional args, timeout, gate env. The
    # loop passes repo_root through (env {"G": False}); so does the final call.
    for args, kwargs in calls:
        assert args == (sb, ["t_x.py"])
        assert kwargs["timeout_s"] == 9
        assert kwargs["env"] == {"G": False}
    assert len(calls) == 5
    assert gate_envs == [{"ZFT_REPO": str(repo)}] * 5
    # ledger events, full equality per entry
    expect = [
        {"event": "mutant_verdict", "name": PIN_NAMES[0], "ok": False,
         "function": "f1", "in_scope": True, "timed_out": False,
         "duration_ms": 1234},
        {"event": "mutant_verdict", "name": PIN_NAMES[1], "ok": False,
         "function": "f2", "in_scope": True, "timed_out": False,
         "duration_ms": 1234},
        {"event": "mutant_verdict", "name": PIN_NAMES[2], "ok": True,
         "function": "f3", "in_scope": True, "timed_out": False,
         "duration_ms": 1234},
        {"event": "mutant_verdict", "name": PIN_NAMES[3], "ok": False,
         "function": "f4", "in_scope": True, "timed_out": True,
         "duration_ms": 1234},
    ]
    assert led.events == expect
    # checkpoint: C4 {outcome, in_scope} entries, written with sort_keys=True
    cache_file = sb / ".zft" / "cache" / "mutants.json"
    expect_state = {
        PIN_NAMES[0]: {"in_scope": True, "outcome": "killed"},
        PIN_NAMES[1]: {"in_scope": True, "outcome": "killed"},
        PIN_NAMES[2]: {"in_scope": True, "outcome": "survived"},
        PIN_NAMES[3]: {"in_scope": True, "outcome": "timeout"},
    }
    assert cache_file.read_text() == json.dumps(expect_state, sort_keys=True)


def test_campaign_resume_matrix_and_defaults(tmp_path, monkeypatch):
    # resumed verdicts keep their classes and counters (2 resumed kills)
    sb = _pin_sandbox(tmp_path)
    cache_dir = sb / ".zft" / "cache"
    cache_dir.mkdir(parents=True)
    prior = {
        PIN_NAMES[0]: {"outcome": "killed", "in_scope": True},
        PIN_NAMES[1]: {"outcome": "timeout", "in_scope": True},
        PIN_NAMES[2]: {"outcome": "killed", "in_scope": True},
        PIN_NAMES[3]: {"outcome": "survived", "in_scope": True},
    }
    (cache_dir / "mutants.json").write_text(json.dumps(prior))
    gate_envs = []
    calls = _install_fakes(monkeypatch, [RunnerResult(ok=True, duration_ms=1)],
                           gate_envs)
    r = run_campaign(sb, test_paths=["t_x.py"], resume=True)
    assert r.resumed == 4
    assert r.executed == 0
    assert r.killed == 2
    assert r.in_scope_killed == 2
    assert r.timed_out == [PIN_NAMES[1]]
    assert r.survivors == [PIN_NAMES[3]]
    assert r.ok is False
    # the only real execution is the final reverse check, default timeout
    assert len(calls) == 1
    assert calls[0][1]["timeout_s"] == 300

    # resume=True with NO checkpoint: prior must stay {} (not None) and run
    sb2 = _pin_sandbox(tmp_path / "d2")
    results = _res((False, False), (False, False), (False, False), (False, False),
                   (True, False))
    _install_fakes(monkeypatch, results, gate_envs)
    r2 = run_campaign(sb2, test_paths=["t_x.py"], resume=True)
    assert r2.resumed == 0
    assert r2.executed == 4
    assert r2.killed == 4

    # checkpoint present but resume=False: every mutant re-executes
    sb3 = _pin_sandbox(tmp_path / "d3")
    (sb3 / ".zft" / "cache").mkdir(parents=True)
    (sb3 / ".zft" / "cache" / "mutants.json").write_text(
        json.dumps({PIN_NAMES[0]: {"outcome": "survived", "in_scope": True}}))
    results = _res((False, False), (False, False), (False, False), (False, False),
                   (True, False))
    _install_fakes(monkeypatch, results, gate_envs)
    r3 = run_campaign(sb3, test_paths=["t_x.py"])
    assert r3.resumed == 0
    assert r3.executed == 4

    # NOTE (waiver preregistration, _28/_60): a corrupt checkpoint is NOT a
    # discriminator for the resume gates — the loop's own cache write-back
    # re-reads the file after the first verdict regardless of `resume`, so
    # both original and mutant fail identically; the resume term in each gate
    # is redundant on every reachable state.


def test_campaign_no_fail_fast_by_default_runs_all(tmp_path, monkeypatch):
    source = "def f1(a):\n    return a > 0\n\ndef f2(a):\n    return a < 0\n"
    sb = _pin_sandbox(tmp_path, source)
    names = [n for n, _, _ in generate_mutants(source, "mod.py")]
    results = _res((True, False), (True, False), (True, False))
    calls = _install_fakes(monkeypatch, results, [])
    r = run_campaign(sb, test_paths=["t_x.py"])
    # default fail_fast=False: an all-survive campaign still executes every
    # mutant (a default-True would stop after the first survivor)
    assert r.executed == 2
    assert r.survivors == names
    assert r.ok is False
    assert r.killed == 0
    assert len(calls) == 3


def test_campaign_scope_filter_and_budget_semantics(tmp_path, monkeypatch):
    classy = ("class K:\n"
              "    def m(self, a):\n"
              "        return a > 0\n"
              "\n"
              "def top(a):\n"
              "    return a < 0\n")
    sb = _pin_sandbox(tmp_path, classy)
    # bare-name scope matches the qualified class method (rsplit seam)
    results = _res((True, False), (True, False), (True, False))
    _install_fakes(monkeypatch, results, [])
    r = run_campaign(sb, test_paths=["t_x.py"], scope_functions={"m"})
    assert r.total_mutants == 2
    assert r.in_scope_total == 1
    assert r.executed == 1
    assert r.survivors == ["mod.py::fn:K.m::line:3::>-><"]
    # scope={"top"}: the K.m mutant is skipped (never executed) and the loop
    # must CONTINUE to the in-scope mutant after it
    results = _res((True, False), (True, False))
    _install_fakes(monkeypatch, results, [])
    r2 = run_campaign(sb, test_paths=["t_x.py"], scope_functions={"top"})
    assert r2.total_mutants == 2
    assert r2.in_scope_total == 1
    assert r2.in_scope_killed == 0
    assert r2.executed == 1
    assert r2.survivors == ["mod.py::fn:top::line:6::<->>="]
    assert r2.ok is False


def test_campaign_duration_ms_pin(tmp_path, monkeypatch):
    times = iter([10.0, 12.0])
    monkeypatch.setattr(mm.time, "perf_counter", lambda: next(times))
    sb = _pin_sandbox(tmp_path, "def f1(a):\n    return a > 0\n")
    results = _res((False, False), (True, False))
    _install_fakes(monkeypatch, results, [])
    r = run_campaign(sb, test_paths=["t_x.py"])
    assert r.duration_ms == 2000


def test_run_pytest_env_passes_gate_env_extra(tmp_path, monkeypatch):
    runs, gates = [], []

    def fake_run(*args, **kwargs):
        runs.append((args, kwargs))
        return "RAN"

    def fake_gate_env(extra):
        gates.append(extra)
        return {"FAKE": extra is not None}

    monkeypatch.setattr(mm, "run_pytest", fake_run)
    monkeypatch.setattr(mm, "gate_env", fake_gate_env)
    sb = tmp_path / "sb"
    mm._run_pytest_env(sb, ["t_x.py"], 9, None)
    args, kwargs = runs[-1]
    assert args == (sb, ["t_x.py"])
    assert kwargs == {"timeout_s": 9, "env": {"FAKE": False}}
    assert gates[-1] is None
    mm._run_pytest_env(sb, None, 9, tmp_path)
    args, kwargs = runs[-1]
    assert args == (sb, [])
    assert kwargs == {"timeout_s": 9, "env": {"FAKE": True}}
    assert gates[-1] == {"ZFT_REPO": str(tmp_path)}
    # test_paths=None normalizes to [] for the runner; a populated list passes
    # through list()
    mm._run_pytest_env(sb, ("a.py", "b.py"), 9, None)
    assert runs[-1][0] == (sb, ["a.py", "b.py"])


def test_outcome_classifies_legacy_entries():
    assert _outcome({"outcome": "killed"}) == "killed"
    assert _outcome({"outcome": "timeout"}) == "timeout"
    assert _outcome({"outcome": "survived"}) == "survived"
    assert _outcome(False) == "killed"
    assert _outcome("killed") == "killed"
    # legacy booleans: True survived; anything unrecognized survives
    assert _outcome(True) == "survived"
    assert _outcome("junk") == "survived"
    assert _outcome({}) == "survived"
    assert _outcome({"outcome": "other"}) == "survived"


def test_parse_results_reads_checkpoint_exactly(tmp_path):
    # missing file: empty verdict triple
    assert parse_results(tmp_path) == ([], 0, 0)
    cache_dir = tmp_path / ".zft" / "cache"
    cache_dir.mkdir(parents=True)
    led_file = cache_dir / "mutants.json"
    state = {
        "m_a": {"outcome": "survived", "in_scope": True},
        "m_b": {"outcome": "killed", "in_scope": True},
        "m_c": {"outcome": "killed", "in_scope": True},
        "m_d": {"outcome": "killed", "in_scope": True},
        "m_e": {"outcome": "timeout", "in_scope": True},
        "m_f": True,   # legacy: survived
        "m_g": False,  # legacy: killed
    }
    led_file.write_text(json.dumps(state))
    survivors, total, killed = parse_results(tmp_path)
    assert survivors == ["m_a", "m_f"]
    # timeouts count in total only — a hang is attributable, not a kill
    assert total == 7
    assert killed == 4


def test_generate_mutants_name_format_and_default_filename():
    name, src, fn = generate_mutants("def f(a):\n    return a > 0\n")[0]
    assert name == "module.py::fn:f::line:2::>-><"
    assert fn == "f"
    assert src == "def f(a):\n    return a < 0\n"
    name2, _, _ = generate_mutants("def f(a):\n    return a > 0\n",
                                   "mod.py")[0]
    assert name2 == "mod.py::fn:f::line:2::>-><"


def test_generate_mutants_ops_each_fire_once():
    source = (
        "def f1(a):\n    return a == 1\n"
        "def f2(a):\n    return a != 2\n"
        "def f3(a):\n    return a > 3\n"
        "def f4(a):\n    return a < 4\n"
        "def f5(a):\n    return a + 5\n"
        "def f6(a):\n    return True\n"
        "def f7(a):\n    return False\n")
    mutants = generate_mutants(source, "mod.py")
    assert len(mutants) == 7
    bodies = {}
    for m_name, m_src, _ in mutants:
        line_no = int(m_name.split("::line:")[1].split("::")[0])
        bodies[m_name.split("::fn:")[1].split("::")[0]] = \
            m_src.splitlines()[line_no - 1]
    assert bodies == {
        "f1": "    return a != 1",
        "f2": "    return a == 2",
        "f3": "    return a < 3",
        "f4": "    return a >= 4",
        "f5": "    return a - 5",
        "f6": "    return False",
        "f7": "    return True",
    }


def test_generate_mutants_class_and_module_attribution():
    source = ("LIMIT = 3 > 2\n"
              "class K:\n"
              "    def m(self, a):\n"
              "        return a > 0\n"
              "\n"
              "def top(a):\n"
              "    return a < 0\n"
              "def one(a): return a == 1\n")
    mutants = generate_mutants(source, "mod.py")
    by_fn = {fn: name for name, _, fn in mutants}
    # module-level op outside any def attributes to the exact "<module>" name
    assert by_fn.get("<module>") == "mod.py::fn:<module>::line:1::>-><"
    # class-body method attributes to Class.method ...
    assert by_fn.get("K.m") == "mod.py::fn:K.m::line:4::>-><"
    # ... module functions to their bare names
    assert by_fn.get("top") == "mod.py::fn:top::line:7::<->>="
    # one-line def: the op sits ON the def line and still attributes to it
    assert by_fn.get("one") == "mod.py::fn:one::line:8::==->!="


def test_generate_mutants_skips_comments_without_stopping():
    source = ("# a == comment ==\n"
              "def f(a):\n"
              "    return a > 0\n"
              "    # inner < comment\n")
    mutants = generate_mutants(source, "mod.py")
    assert len(mutants) == 1
    assert mutants[0][0] == "mod.py::fn:f::line:3::>-><"


def test_generate_mutants_one_op_per_mutant():
    source = "def f(a):\n    return a == 1 == 2\n"
    mutants = generate_mutants(source, "mod.py")
    assert len(mutants) == 1
    assert mutants[0][1] == "def f(a):\n    return a != 1 == 2\n"


def test_generate_mutants_syntax_error_skips_without_stopping():
    source = ("def g(a):\n"
              "    return a > 0\n"
              "    x = a <= b + 1\n")
    mutants = generate_mutants(source, "mod.py")
    # line 3: the earlier `<` pattern yields `>==` (SyntaxError) and is
    # dropped; the pattern loop must CONTINUE so the later `+` pattern still
    # yields that line's valid mutant
    assert [m[0] for m in mutants] == [
        "mod.py::fn:g::line:2::>-><",
        r"mod.py::fn:g::line:3::\+->-",
    ]
