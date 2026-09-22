"""Batch oracle verification tests for L1.

Ensures that all oracles are executed in a single pytest invocation, and that per‑clause
verdicts are preserved.
"""
import json
import time
from pathlib import Path

from zft.gates.l1 import run_l1

ALIAS_COUNT = 5
ALIASES = [f"BATCH-ORACLE-{i}" for i in range(ALIAS_COUNT)]


def _node(alias: str) -> dict:
    return {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": alias,
        "domain": "g",
        "title": f"batch oracle {alias}",
        "status": "VALIDATED",
        "version": 1,
        "content_hash": "0" * 64,
        "invariants": [
            {
                "id": alias,
                "statement": "when value() then ok",
                "property": "value() == 42",
                "check": {"kind": "property"},
            }
        ],
        "external_links": [],
    }


def _seed_repo(tmp_path: Path, *, mutate_alias: str | None = None) -> Path:
    # spec nodes
    spec_dir = tmp_path / ".zft" / "specs" / "g"
    spec_dir.mkdir(parents=True)
    for alias in ALIASES:
        (spec_dir / f"{alias}.json").write_text(json.dumps(_node(alias)))

    # contract (optional, not required for this test but ensure presence)
    contracts_dir = tmp_path / ".zft" / "contracts"
    contracts_dir.mkdir(parents=True)
    (contracts_dir / "batch-v0.json").write_text(
        json.dumps({"name": "batch-v0", "clause_ids": ALIASES})
    )

    # target module
    (tmp_path / "target.py").write_text(
        "def value():\n    return 42\n"
    )

    # bound tests for each clause
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    for alias in ALIASES:
        (tests_dir / f"test_{alias}.py").write_text(
            f"# @trace(\"{alias}\")\n"
            "def test_dummy():\n    assert True\n"
        )

    # oracle files
    for alias in ALIASES:
        oracle_path = tmp_path / f"oracle_{alias}.py"
        # Determine the expected value for the assertion
        expected_val = 41 if mutate_alias == alias else 42
        # Oracle writes a sentinel file before performing the check
        content = (
            "def check():\n"
            "    from pathlib import Path\n"
            f"    Path('sentinel_{alias}').write_text('')\n"
            "    import target\n"
            f"    assert target.value() == {expected_val}\n"
        )
        oracle_path.write_text(content)
    return tmp_path


def test_all_oracles_pass(tmp_path):
    root = _seed_repo(tmp_path)
    verdict = run_l1(root)
    assert verdict.ok, verdict.rejection


def test_one_oracle_fails(tmp_path):
    bad = ALIASES[2]
    root = _seed_repo(tmp_path, mutate_alias=bad)
    verdict = run_l1(root)
    assert not verdict.ok
    # Failure should be exactly the bad alias
    assert verdict.rejection is not None
    assert verdict.rejection["code"] == "L1_ORACLE_FAIL"
    assert verdict.rejection["clause_ids"] == [bad]
    # Other clauses should not be in failures
    for alias in ALIASES:
        if alias != bad:
            assert not any(alias in f for f in verdict.failures)

def test_batch_oracle_one_pytest_call(monkeypatch, tmp_path):
    root = _seed_repo(tmp_path)
    calls = []
    from zft.gates.runners.pytest_runner import run_pytest as real_run
    durations = []
    def spy(sandbox, test_paths=None, timeout_s=300, fail_fast=True, env=None,
            junit_xml=None, confcutdir=None):
        t0 = time.time()
        result = real_run(
            sandbox, test_paths, timeout_s,
            fail_fast=fail_fast, env=env, junit_xml=junit_xml, confcutdir=confcutdir,
        )
        calls.append((test_paths, junit_xml, fail_fast, confcutdir))
        if junit_xml is not None:
            durations.append(time.time() - t0)
        return result
    monkeypatch.setattr('zft.gates.l1.run_pytest', spy)
    _ = run_l1(root)
    # One call with junit_xml set (oracle batch) and multiple calls for test suites (no junit_xml)
    junit_calls = [c for c in calls if c[1] is not None]
    assert len(junit_calls) == 1
    # Verify that the batch call disabled fail-fast
    assert junit_calls[0][2] is False
    # The batch call pins the collection boundary to the batch dir (vacuity
    # probe, 2026-09-15): without it pytest walks the common ancestor of the
    # workspace and the driver, and the driver may go uncollected.
    assert junit_calls[0][3] is not None
    # The single oracle batch must complete quickly (five trivial oracle checks)
    assert len(durations) == 1
    assert durations[0] < 5.0


def test_failing_oracle_executes_and_fails_batch(tmp_path):
    """Regression (vacuity probe, 2026-09-15).

    Geometry: the gated workspace sits under /tmp (pytest tmp_path) while the
    batch driver is materialized in a separate mkdtemp dir. Without the
    confcutdir pin, pytest resolved rootdir to the common ancestor /tmp and
    the collection walk died before the driver was collected — zero oracle
    tests ran and the gate reported ok (vacuous pass). The batch call now
    pins --confcutdir to the batch dir, so the driver must be collected and
    executed: the CWD-independent marker proves the oracle body ran, and the
    failing oracle must turn the run red.
    """
    alias = "BATCH-VACUITY-REGRESS"
    spec_dir = tmp_path / ".zft" / "specs" / "g"
    spec_dir.mkdir(parents=True)
    (spec_dir / f"{alias}.json").write_text(json.dumps(_node(alias)))

    (tmp_path / "target.py").write_text("def value():\n    return 42\n")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / f"test_{alias}.py").write_text(
        f'# @trace("{alias}")\n'
        "def test_dummy():\n    assert True\n"
    )

    marker = tmp_path / f"marker_{alias}"
    (tmp_path / f"oracle_{alias}.py").write_text(
        "def check():\n"
        "    from pathlib import Path\n"
        f"    Path({str(marker)!r}).write_text('executed')\n"
        "    import target\n"
        "    assert target.value() == 41  # deliberately wrong expectation\n"
    )

    verdict = run_l1(tmp_path)
    assert marker.is_file(), "oracle body never executed — vacuous batch run"
    assert not verdict.ok
    assert verdict.rejection is not None
    assert verdict.rejection["code"] == "L1_ORACLE_FAIL"
    assert verdict.rejection["clause_ids"] == [alias]


def test_batch_runs_all_oracles_even_when_first_fails(tmp_path):
    # Use the first alias as the failing oracle
    bad = ALIASES[0]
    root = _seed_repo(tmp_path, mutate_alias=bad)
    verdict = run_l1(root)
    assert not verdict.ok
    assert verdict.rejection is not None
    assert verdict.rejection["code"] == "L1_ORACLE_FAIL"
    assert verdict.rejection["clause_ids"] == [bad]
    # Ensure that each oracle wrote its sentinel file, indicating execution
    for alias in ALIASES:
        sentinel = root / f"sentinel_{alias}"
        assert sentinel.is_file(), f"Sentinel for {alias} missing"
