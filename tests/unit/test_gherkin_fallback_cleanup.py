"""Gherkin fallback stage: orphan .feature cleanup.

An orphan feature (a clause removed from the store leaves its .feature behind)
breaks every later `check .`: pytest_bdd auto-collects the stale scenario,
whose step definitions no longer exist in the freshly rendered test file, and
the stage fails with StepDefinitionNotFoundError. The fallback stage must
rebuild the feature set from the current store only.
"""
from types import SimpleNamespace

from zft.codegen.gherkin_gen import gherkin_fallback_green


def test_gherkin_fallback_removes_orphan_features(tmp_path):
    (tmp_path / "zz-drift-probe.feature").write_text(
        "Feature: ZZ-DRIFT-PROBE\n\n  Scenario: ZZ-DRIFT-PROBE\n"
        "    Given the contract clause ZZ-DRIFT-PROBE is validated\n")
    clauses = [{"alias": "A-CLAUSE", "title": "A Clause"}]
    assert gherkin_fallback_green(clauses, tmp_path,
                                  lambda d: SimpleNamespace(ok=True))
    assert sorted(p.name for p in tmp_path.glob("*.feature")) == ["a-clause.feature"]
