"""Driver gate (batch-driver contract): EARS + fast read-only L0-L3 subset.

Pins the driver contract: exit-code verdicts, read-only workspace (no ledger,
no verdict cache, no bytecode, no hypothesis DB inside {folder}), bounded
payload for the ~2000-char sink, and the shell entrypoint's behavior.
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from zft.dsl.ears import EarsError, parse_statement
from zft.gates.driver_gate import (
    BUDGET_CHARS,
    _ears_findings,
    _render,
    main,
    run_driver_gate,
)
from zft.gates.l1 import run_l1
from zft.spec.canon import canonical_hash

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "gates" / "driver-gate.sh"

EARS_STATEMENT = "WHEN a work order is expired, THE SYSTEM SHALL reject it."


def _node(alias: str, inv_id: str, statement: str, title: str = "expired -> err") -> dict:
    inv = {
        "id": inv_id,
        "statement": statement,
        "property": "forall t: expired(t) => validate(t) == err('Unauthorized')",
        "check": {"kind": "property"},
    }
    content = {"domain": "g", "title": title, "invariants": [inv]}
    return {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": alias, "domain": "g", "title": title,
        "status": "VALIDATED", "version": 1,
        "content_hash": canonical_hash(content),
        "invariants": [inv], "external_links": [],
    }


def _seed_repo(tmp_path: Path, test_body: str | None = None) -> Path:
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    (spec / "gate-inv-01.json").write_text(
        json.dumps(_node("GATE-INV-01", "GATE-INV-01", EARS_STATEMENT)))
    (tmp_path / "impl.py").write_text("def expired(t):\n    return t > 100\n")
    (tmp_path / "oracle_GATE-INV-01.py").write_text("def expired(t):\n    return t > 100\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    body = test_body or (
        "from impl import expired\n\n\n"
        "def test_bound():\n    assert expired(150) is True\n"
    )
    (tests / "test_bound.py").write_text('# @trace("GATE-INV-01")\n' + body)
    return tmp_path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# @trace("DRIVER-GATE-GREEN")
def test_driver_gate_green_on_seeded_workspace(tmp_path):
    verdict = run_driver_gate(_seed_repo(tmp_path))
    assert verdict.ok, verdict.failures
    assert verdict.stages == {"ears": True, "l0": True, "l1": True, "l2_fast": True}
    assert verdict.l1 == {"executed": 1, "ok": True}
    doc = json.loads(verdict.payload)
    assert doc["ok"] is True and doc["ears_checked"] == 1
    assert doc["coverage"]["deterministic"] == "1/1"


def test_driver_gate_workspace_is_byte_identical(tmp_path):
    """READ-ONLY: green run leaves zero writes — no ledger, cache, bytecode,
    pytest cache, or hypothesis DB inside the governed folder."""
    root = _seed_repo(tmp_path, test_body=(
        "from hypothesis import given, strategies as st\n"
        "from impl import expired\n\n\n"
        "@given(st.integers(min_value=0, max_value=200))\n"
        "def test_bound(t):\n    assert expired(t) == (t > 100)\n"
    ))
    before = _snapshot(root)
    verdict = run_driver_gate(root)
    assert verdict.ok, verdict.failures
    assert _snapshot(root) == before, "the gate must not write into {folder}"
    after = _snapshot(root)
    for stateful in (".zft/runs", ".zft/cache", ".zft/sandbox",
                       ".hypothesis", ".pytest_cache", "__pycache__"):
        assert not any(name.startswith(stateful) for name in after), stateful


def test_driver_gate_non_ears_statement_is_typed_deny(tmp_path):
    root = _seed_repo(tmp_path)
    spec = root / ".zft" / "specs" / "g" / "gate-inv-01.json"
    spec.write_text(json.dumps(
        _node("GATE-INV-01", "GATE-INV-01", "The system should reject expired orders.")))
    verdict = run_driver_gate(root)
    assert verdict.ok is False
    assert verdict.stages["ears"] is False
    assert any("GATE-INV-01" in f and "not an EARS statement" in f
               for f in verdict.failures)


def test_driver_gate_unseeded_folder_fails_closed(tmp_path):
    verdict = run_driver_gate(tmp_path)
    assert verdict.ok is False
    # render_finding carries the message, not the rule code
    assert any("no clause store found" in f for f in verdict.failures)


def test_driver_gate_red_suite_names_clause_and_fits_budget(tmp_path):
    root = _seed_repo(tmp_path, test_body="def test_bound():\n    assert False\n")
    verdict = run_driver_gate(root)
    assert verdict.ok is False
    assert any("GATE-INV-01: bound suite failed" in f for f in verdict.failures)
    assert "GATE-INV-01" in verdict.payload
    assert len(verdict.payload) <= BUDGET_CHARS <= 2000, "driver sink is ~2000 chars"


def test_driver_gate_payload_fits_budget_under_many_failures(tmp_path):
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    for i in range(10):
        alias = f"GATE-INV-{i:02d}"
        (spec / f"{alias.lower()}.json").write_text(json.dumps(
            _node(alias, alias, EARS_STATEMENT, title=f"clause {i}")))
    verdict = run_driver_gate(tmp_path)  # property clauses, none bound
    assert verdict.ok is False
    assert len(verdict.failures) > 10
    assert len(verdict.payload) <= BUDGET_CHARS
    json.loads(verdict.payload)  # stays valid JSON after shrinking


def test_driver_gate_corrupt_store_degrades_to_typed_red(tmp_path):
    root = _seed_repo(tmp_path)
    (root / ".zft" / "specs" / "g" / "gate-inv-01.json").write_text("{broken")
    verdict = run_driver_gate(root)
    assert verdict.ok is False
    assert any("STORE_NODE_JSON" in f or "evidence collection failed" in f
               for f in verdict.failures)


def test_driver_gate_module_main_exit_codes(tmp_path, capsys):
    green = _seed_repo(tmp_path)
    assert main([str(green)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["stage"] == "DRIVER-GATE" and doc["ok"] is True

    (green / "tests" / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\ndef test_bound():\n    assert False\n')
    assert main([str(green)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


_DRIVER_IDENTITY_ENVS = ("ZFT_PRODUCER_MODEL", "ZFT_GATE_MODEL")


def test_driver_gate_identity_env_config_flows(tmp_path, monkeypatch):
    monkeypatch.setenv("ZFT_PRODUCER_MODEL", "env-prod")
    monkeypatch.setenv("ZFT_GATE_MODEL", "env-gate")
    verdict = run_driver_gate(_seed_repo(tmp_path))
    assert verdict.ok, verdict.failures
    assert verdict.models == {"producer": "env-prod", "gate": "env-gate",
                              "model_dependent": False}


def test_driver_gate_identity_unsupplied_is_null_not_dev_name(tmp_path, monkeypatch):
    for k in _DRIVER_IDENTITY_ENVS:
        monkeypatch.delenv(k, raising=False)
    verdict = run_driver_gate(_seed_repo(tmp_path))
    assert verdict.ok, verdict.failures
    assert verdict.models == {"producer": None, "gate": None,
                              "model_dependent": True}, (
        "fail-closed: no proven model difference -> the claim stays "
        "model-dependent, and no default name may stand in")
    assert "producer-dev" not in verdict.payload


def test_driver_gate_cli_identity_flag_beats_env(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ZFT_PRODUCER_MODEL", "env-prod")
    monkeypatch.setenv("ZFT_GATE_MODEL", "env-gate")
    from zft.cli.main import main as cli_main

    assert cli_main(["driver-gate", str(_seed_repo(tmp_path)),
                     "--producer-model", "flag-prod",
                     "--gate-model", "flag-gate"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["models"] == {"producer": "flag-prod", "gate": "flag-gate",
                             "model_dependent": False}


def test_l1_write_cache_false_leaves_no_trace(tmp_path):
    root = _seed_repo(tmp_path)
    assert run_l1(root, write_cache=False).ok is True
    for statedir in ("runs", "cache", "sandbox"):
        assert not (root / ".zft" / statedir).exists(), \
            "read-only runs never persist verdicts"
    assert run_l1(root, write_cache=False).executed == 1, "no cache write => no cache hit"
    assert run_l1(root).executed == 1, "default run executes (nothing was persisted)"
    assert run_l1(root).executed == 0, "default behavior still caches its own greens"


def _run_script(*args: str, folder: Path | str | None = None,
                env_extra: dict | None = None):
    env = os.environ | {"ZFT_PYTHON": sys.executable}
    if env_extra:
        env |= env_extra
    argv = ["bash", str(SCRIPT)]
    if folder is not None:
        argv.append(str(folder))
    return subprocess.run([*argv, *args], capture_output=True, text=True,
                          env=env, timeout=115)


@pytest.mark.skipif(not SCRIPT.exists() or sys.platform == "win32",
                    reason="driver-gate.sh is a bash artifact")
class TestDriverGateScript:
    def test_green_exits_zero_with_bounded_output(self, tmp_path):
        root = _seed_repo(tmp_path)
        before = _snapshot(root)
        r = _run_script(folder=root)
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.startswith('{"stage":"DRIVER-GATE"')
        assert '"ok":true' in r.stdout
        assert len(r.stdout) + len(r.stderr) <= 2000
        assert _snapshot(root) == before, "script must not write into {folder}"

    def test_red_exits_nonzero(self, tmp_path):
        root = _seed_repo(tmp_path, test_body="def test_bound():\n    assert False\n")
        r = _run_script(folder=root)
        assert r.returncode == 1
        assert "GATE-INV-01" in r.stdout

    def test_usage_and_missing_folder(self, tmp_path):
        assert _run_script().returncode == 2  # no folder argument
        assert _run_script(folder=tmp_path / "nope").returncode == 1

    def test_budget_overrun_rejects_instead_of_hanging(self, tmp_path):
        slow_body = "import time\n\n\ndef test_bound():\n    time.sleep(30)\n"
        slow = _seed_repo(tmp_path, test_body=slow_body)
        r = _run_script(folder=slow, env_extra={"DRIVER_GATE_BUDGET_S": "2"})
        assert r.returncode == 1
        assert "budget" in r.stdout


# ---------------------------------------------------------------------------
# Kill-shard pins, batch 1 (2026-09-18 sitting): the direct-call families.
# _render's shrink ladder, _ears_findings' shaping, and main()'s argv/exit
# contract are pinned by direct invocation with byte-exact expectations —
# the dsse lesson holds here too: every refusal/rendered string is asserted
# whole, never by substring.
# ---------------------------------------------------------------------------

def _j(d: dict) -> str:
    return json.dumps(d, separators=(",", ":"))


def test_render_shrink1_drops_warnings_at_exact_fit():
    doc = {"stage": "D", "warnings": ["w" * 40],
           "failures": [f"F{i}" for i in range(4)]}
    shrunk = _j({k: v for k, v in doc.items() if k != "warnings"})
    assert len(_j(doc)) > len(shrunk)
    # exact fit: the <= boundary at step 1 is load-bearing, and 4 failures
    # make step 2's [:3] a different string so a skipped step cannot pass
    assert _render(doc, len(shrunk)) == shrunk


def test_render_shrink2_truncates_failures_to_three():
    doc = {"stage": "D", "warnings": ["w" * 30],
           "failures": [f"F{i:02d}" + "x" * 20 for i in range(5)]}
    wless = {k: v for k, v in doc.items() if k != "warnings"}
    step2 = _j({**wless, "failures": doc["failures"][:3]})
    assert len(_j(doc)) > len(step2) and len(_j(wless)) > len(step2)
    assert _render(doc, len(step2)) == step2


def test_render_shrink3_keeps_single_failure():
    doc = {"stage": "D", "warnings": ["w" * 30],
           "failures": ["F" * 60 + str(i) for i in range(4)]}
    wless = {k: v for k, v in doc.items() if k != "warnings"}
    step3 = _j({**wless, "failures": doc["failures"][:1]})
    step2 = _j({**wless, "failures": doc["failures"][:3]})
    assert len(step2) > len(step3)
    assert _render(doc, len(step3)) == step3


def test_render_shrink4_drops_advisory_blocks():
    doc = {"stage": "D", "ok": True, "warnings": ["w" * 30],
           "failures": ["F" * 60],
           "coverage": {"deterministic": "c" * 60},
           "models": {"producer": "p" * 40, "gate": "g" * 40}}
    step4 = _j({k: v for k, v in doc.items()
                if k not in ("warnings", "coverage", "models")})
    assert _render(doc, len(step4)) == step4


def test_render_truncation_marker_is_exact():
    doc = {"stage": "D", "ok": True,
           "warnings": ["w" * 80, "v" * 80],
           "failures": ["F" * 150, "G" * 150],
           "coverage": {"deterministic": "c" * 100},
           "models": {"producer": "p" * 100, "gate": "g" * 100}}
    budget = 120  # every shrink step still exceeds it
    # the marker applies to the LAST attempted shrink (step 4), not the
    # untouched doc: by then warnings/coverage/models are already gone
    last = {k: v for k, v in doc.items()
            if k not in ("warnings", "coverage", "models")}
    expected = _j(last)[:budget - 15] + "...[truncated]"
    assert _render(doc, budget) == expected


def test_render_identity_step_honored_at_exact_fit():
    doc = {"stage": "D", "ok": True, "warnings": ["w"]}
    full = _j(doc)
    assert _render(doc, len(full)) == full


def test_render_separators_are_compact():
    assert _render({"a": 1, "b": [1, 2]}, 100) == '{"a":1,"b":[1,2]}'


def _ears_err(statement: str) -> str:
    """First line of the EARS diagnostic for an unparseable statement."""
    try:
        parse_statement(statement)
    except EarsError as e:
        return str(e).splitlines()[0]
    raise AssertionError("statement unexpectedly parsed")


def _ears_node(alias: str, invs: list[dict] | None) -> dict:
    # content_hash is computed over the content document; the node's own
    # invariants key is what _ears_findings reads and may legitimately be
    # absent (older nodes) — that shape is pinned by the no-key test below.
    content = {"domain": "g", "title": alias,
               "invariants": invs if invs is not None else []}
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": alias, "domain": "g", "title": alias,
        "status": "VALIDATED", "version": 1,
        "content_hash": canonical_hash(content), "external_links": [],
    }
    if invs is not None:
        node["invariants"] = invs
    return node


def _ears_root(tmp_path: Path,
               nodes: dict[str, tuple[str, list[dict] | None]]) -> Path:
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    for fname, (alias, invs) in nodes.items():
        (spec / fname).write_text(json.dumps(_ears_node(alias, invs)))
    return tmp_path


def test_ears_findings_sorted_by_alias_with_id_and_count(tmp_path):
    bad = "The system should reject expired orders."
    first_line = _ears_err(bad)
    root = _ears_root(tmp_path, {
        "b.json": ("B-ALIAS", [{"id": "I-2", "statement": bad}]),
        "a.json": ("A-ALIAS", [{"id": "I-1", "statement": bad}]),
    })
    failures, checked = _ears_findings(root)
    assert checked == 2
    assert failures == [
        ("A-ALIAS", f"A-ALIAS/I-1: {first_line}"),
        ("B-ALIAS", f"B-ALIAS/I-2: {first_line}"),
    ]


def test_ears_findings_missing_invariant_id_renders_question_mark(tmp_path):
    bad = "The system should reject expired orders."
    root = _ears_root(tmp_path, {
        "a.json": ("A-ALIAS", [{"statement": bad}]),
    })
    failures, checked = _ears_findings(root)
    assert checked == 1
    assert failures == [("A-ALIAS", f"A-ALIAS/?: {_ears_err(bad)}")]


def test_ears_findings_first_line_only_of_multiline_error(tmp_path):
    bad = "The system should reject expired orders."
    root = _ears_root(tmp_path, {
        "a.json": ("A-ALIAS", [{"id": "I-1", "statement": bad}]),
    })
    failures, _ = _ears_findings(root)
    # the diagnostic is multi-line; the finding carries the first line only
    assert "\n" not in failures[0][1]
    assert failures[0][1].endswith("is lowercase")


def test_ears_findings_node_without_invariants_key_is_silent(tmp_path):
    root = _ears_root(tmp_path, {"a.json": ("A-ALIAS", None)})
    spec = root / ".zft" / "specs" / "g" / "a.json"
    node = json.loads(spec.read_text())
    assert "invariants" not in node
    assert _ears_findings(root) == ([], 0)


def test_ears_findings_corrupt_store_returns_empty(tmp_path):
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    (spec / "a.json").write_text("{broken")
    assert _ears_findings(tmp_path) == ([], 0)


def test_main_no_args_prints_usage_byte_exact_and_returns_2(capsys):
    assert main([]) == 2
    assert capsys.readouterr().out == (
        "usage: python -m zft.gates.driver_gate <folder>\n")


def test_main_none_argv_gates_sysargv1_not_sysargv2(
        tmp_path, monkeypatch, capsys):
    green = _seed_repo(tmp_path)
    monkeypatch.setattr(sys, "argv",
                        ["driver_gate", str(green), str(tmp_path / "nope")])
    assert main(None) == 0  # argv[1] is green; argv[2] does not exist (red)
    assert json.loads(capsys.readouterr().out)["ok"] is True


# ---------------------------------------------------------------------------
# Kill-shard pins, batch 2 (2026-09-18 sitting): run_driver_gate via the
# run_l0/run_l2 seams. The fakes are verdict-shaped namespaces — the gate's
# own aggregation (stages, coverage shaping, doc construction, payload) is
# what's under pin, byte-exact; the l0/l2 engines have their own suites.
# ---------------------------------------------------------------------------

_UNSET = object()


class _FakeL1:
    def __init__(self, ok=True, executed=1):
        self.ok = ok
        self.executed = executed


class _FakeV2:
    def __init__(self, ok=True, failures=(), l1=_UNSET, rejection=None,
                 coverage=None):
        self.ok = ok
        self.failures = list(failures)
        self.l1 = _FakeL1() if l1 is _UNSET else l1
        self.rejection = rejection
        self.coverage = coverage if coverage is not None else {
            "coverage": "1/1", "judge_excluded": []}


def _stub_l2(captured=None, **v2_kwargs):
    def fake(root, **kwargs):
        if captured is not None:
            captured.update(kwargs)
        return _FakeV2(**v2_kwargs)
    return fake


def _clear_identity_envs(monkeypatch):
    for k in ("ZFT_PRODUCER_MODEL", "ZFT_GATE_MODEL"):
        monkeypatch.delenv(k, raising=False)


def test_run_gate_green_aggregates_stages_and_payload_byte_exact(
        tmp_path, monkeypatch):
    _clear_identity_envs(monkeypatch)
    captured = {}
    monkeypatch.setattr("zft.gates.driver_gate.run_l2",
                        _stub_l2(captured))
    root = _seed_repo(tmp_path)
    v = run_driver_gate(root, examples_timeout_s=33)
    # the l2 call shape is contract: fast tier, caller's budget, read-only
    assert captured == {"tier": "fast", "examples_timeout_s": 33,
                        "write_cache": False}
    # and the 60s default reaches run_l2 untouched when the caller omits it
    captured.clear()
    assert run_driver_gate(root).ok
    assert captured == {"tier": "fast", "examples_timeout_s": 60,
                        "write_cache": False}
    assert v.ok, v.failures
    assert v.stages == {"ears": True, "l0": True, "l1": True, "l2_fast": True}
    assert v.l1 == {"executed": 1, "ok": True}
    assert v.coverage == {"deterministic": "1/1", "judge_excluded": [],
                          "uncovered": []}
    assert v.warnings == []
    assert v.ears_checked == 1
    assert v.models == {"producer": None, "gate": None,
                        "model_dependent": True}
    assert json.loads(v.payload) == {
        "stage": "DRIVER-GATE", "ok": True, "folder": str(root),
        "stages": {"ears": True, "l0": True, "l1": True, "l2_fast": True},
        "ears_checked": 1,
        "coverage": {"deterministic": "1/1", "judge_excluded": [],
                     "uncovered": []},
        "l1": {"executed": 1, "ok": True},
        "models": {"producer": None, "gate": None, "model_dependent": True},
        "warnings": [], "failure_count": 0, "failures": [],
    }


def test_run_gate_l0_warning_codes_flow_capped_into_doc(
        tmp_path, monkeypatch):
    _clear_identity_envs(monkeypatch)
    codes = [f"W{i}" for i in range(10)]

    def fake_l0(root):
        return SimpleNamespace(ok=True, failures=[],
                               warnings=[{"code": c} for c in codes])

    monkeypatch.setattr("zft.gates.driver_gate.run_l0", fake_l0)
    monkeypatch.setattr("zft.gates.driver_gate.run_l2", _stub_l2())
    v = run_driver_gate(_seed_repo(tmp_path))
    assert v.ok, v.failures
    assert v.warnings == codes  # verdict carries every warning
    doc = json.loads(v.payload)
    assert doc["warnings"] == codes[:8]  # the doc is capped at MAX_WARNINGS


def test_run_gate_failures_capped_and_char_truncated_in_doc_only(
        tmp_path, monkeypatch):
    _clear_identity_envs(monkeypatch)
    msgs = [f"FAIL-{i:02d}:" + "x" * 250 for i in range(10)]

    def fake_l0(root):
        return SimpleNamespace(ok=False, failures=list(msgs), warnings=[])

    monkeypatch.setattr("zft.gates.driver_gate.run_l0", fake_l0)
    monkeypatch.setattr("zft.gates.driver_gate.run_l2", _stub_l2())
    v = run_driver_gate(_seed_repo(tmp_path))
    assert v.ok is False
    assert v.failures == msgs  # the verdict object is never truncated
    doc = json.loads(v.payload)
    assert doc["failure_count"] == 10
    assert doc["failures"] == [m[:200] for m in msgs[:6]]
    assert len(doc["failures"]) == 6


def test_run_gate_contract_fault_shapes_uncovered_and_caps(
        tmp_path, monkeypatch):
    _clear_identity_envs(monkeypatch)
    clause_ids = [f"C-{i}" for i in range(10)]
    judge = [f"AI-X{i}" for i in range(9)]
    monkeypatch.setattr(
        "zft.gates.driver_gate.run_l2",
        _stub_l2(ok=False,
                 failures=["clause C-0 uncovered"],
                 rejection={"fault": "contract", "clause_ids": clause_ids},
                 coverage={"coverage": "30/32", "judge_excluded": judge}))
    v = run_driver_gate(_seed_repo(tmp_path))
    assert v.ok is False
    assert v.coverage == {"deterministic": "30/32",
                          "judge_excluded": judge[:8],
                          "uncovered": clause_ids[:8]}
    doc = json.loads(v.payload)
    assert doc["failures"][0] == "clause C-0 uncovered"
    assert doc["coverage"]["uncovered"] == clause_ids[:8]


def test_run_gate_missing_coverage_key_falls_back_to_empty_string(
        tmp_path, monkeypatch):
    _clear_identity_envs(monkeypatch)
    monkeypatch.setattr(
        "zft.gates.driver_gate.run_l2",
        _stub_l2(l1=None, coverage={"judge_excluded": ["AI- subjective"]}))
    v = run_driver_gate(_seed_repo(tmp_path))
    assert v.stages == {"ears": True, "l0": True, "l1": False,
                        "l2_fast": True}
    assert v.l1 == {"executed": 0, "ok": False}
    assert v.coverage == {"deterministic": "",
                          "judge_excluded": ["AI- subjective"],
                          "uncovered": []}


def test_run_gate_l1_red_sets_stage_false_but_green_l2_stands(
        tmp_path, monkeypatch):
    _clear_identity_envs(monkeypatch)
    monkeypatch.setattr(
        "zft.gates.driver_gate.run_l2",
        _stub_l2(l1=_FakeL1(ok=False, executed=3)))
    v = run_driver_gate(_seed_repo(tmp_path))
    assert v.stages == {"ears": True, "l0": True, "l1": False,
                        "l2_fast": True}
    assert v.l1 == {"executed": 3, "ok": False}


def test_run_gate_crashed_stage_is_typed_red_and_doc_degrades(
        tmp_path, monkeypatch):
    _clear_identity_envs(monkeypatch)

    def boom(root):
        raise RuntimeError("l0 exploded")

    monkeypatch.setattr("zft.gates.driver_gate.run_l0", boom)
    monkeypatch.setattr("zft.gates.driver_gate.run_l2", _stub_l2())
    v = run_driver_gate(_seed_repo(tmp_path))
    assert v.ok is False
    # completed stages survive the crash; the crash itself is the stage red
    assert v.stages == {"ears": True, "driver_gate": False}
    assert v.failures == ["DRIVER_GATE_CRASHED: RuntimeError('l0 exploded')"]
    doc = json.loads(v.payload)
    assert doc["stages"] == {"ears": True, "driver_gate": False}
    # stages that never ran keep their initialized shapes in the doc
    assert doc["warnings"] == [] and doc["coverage"] == {}
    assert doc["l1"] == {} and doc["models"] == {}
