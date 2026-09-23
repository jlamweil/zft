"""L1 batch-call construction pin — stub-level, early-sorting by design.

Hygiene sitting 2026-09-22 (l1 `_320`/`_326`): the regen's trials of the
confcutdir mutants recorded TIMEOUT although named runs kill them, because
the only confcutdir-sensitive pins live in test_oracle_batch.py — they run
the real inner pytest before asserting, so under a broken boundary the
trial pays the /tmp collection walk many times over (a named run measured
10m38s of vacuous green before the first failure) and crosses the trial
timeout under regen parallelism. This file sorts before every run_l1-
consuming module (test_cache_identity.py is the first), asserts the exact
run_pytest construction at stub level, and therefore fails in milliseconds
under the mutant — the `-x` trial kills without a single inner spawn.
"""
import json
from pathlib import Path

from zft.gates.l1 import run_l1
from zft.gates.runners.pytest_runner import RunnerResult


def _seed_repo(tmp_path):
    spec = tmp_path / ".zft" / "specs" / "g"
    spec.mkdir(parents=True)
    node = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": "GATE-INV-01", "domain": "g", "title": "expired -> err",
        "status": "VALIDATED", "version": 1, "content_hash": "0" * 64,
        "invariants": [{"id": "GATE-INV-01", "statement": "WHEN expired THE SYSTEM SHALL reject",
                        "property": "forall t: expired(t) => validate(t) == err('Unauthorized')",
                        "check": {"kind": "property"}}],
        "external_links": [],
    }
    (spec / "gate-inv-01.json").write_text(json.dumps(node))
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_bound.py").write_text(
        '# @trace("GATE-INV-01")\n'
        "def test_bound():\n    assert True\n"
    )
    (tmp_path / "oracle_GATE-INV-01.py").write_text(
        "def expired(t):\n    return t > 100\n"
    )
    return tmp_path


def test_l1_batch_call_carries_confcutdir_junit_and_budget(tmp_path, monkeypatch):
    root = _seed_repo(tmp_path)
    calls = []

    def stub_runner(sandbox, test_paths, **kwargs):
        calls.append((sandbox, list(test_paths), kwargs))
        return RunnerResult(ok=True, duration_ms=1)

    monkeypatch.setattr("zft.gates.l1.run_pytest", stub_runner)
    verdict = run_l1(root)
    assert verdict.ok is True, verdict.rejection
    assert len(calls) == 2, "one batch oracle run plus one bound suite"
    sandbox, batch_paths, kwargs = calls[0]
    assert sandbox == root
    driver = Path(batch_paths[0])
    assert driver.name == "tmp_oracle_batch.py"
    # The driver lives OUTSIDE the gated workspace (read-only gate contract).
    assert not driver.is_relative_to(root)
    # confcutdir is the driver's own dir: the collection boundary is the
    # batch dir — never None (_320) and never dropped to the runner default
    # (_326); the vacuity probe of 2026-09-15 is the behavioral backstop.
    conf = kwargs.get("confcutdir")
    assert conf is not None, "the batch run must carry confcutdir"
    assert Path(conf) == driver.parent
    assert Path(kwargs["junit_xml"]) == driver.parent / "tmp_oracle_batch.xml"
    assert kwargs["fail_fast"] is False
    assert kwargs["timeout_s"] == 300
