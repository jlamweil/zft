"""C-14: Gherkin fallback — every clause minimally compiles to a runnable scenario.

The V3 guarantee: no clause is ever un-checkable, only un-checked-yet.
"""

import re
from types import SimpleNamespace

from zft.codegen.gherkin_gen import (
    gherkin_fallback_green,
    render_feature,
    render_steps,
)
from zft.gates.runners.pytest_runner import run_pytest

CLAUSES = [
    {"alias": "CON-A", "title": "No implementation without contract",
     "statement": "WHEN a work order is assigned, THE SYSTEM SHALL refuse implementation start"},
    {"alias": "TR-B", "title": "Deterministic extraction",
     "statement": "WHERE the store is unchanged, THE SYSTEM SHALL produce identical manifests"},
]


def test_feature_renders_valid_gherkin_shape():
    out = render_feature(CLAUSES[0])
    assert out.startswith("Feature: CON-A")
    assert "  Scenario:" in out
    assert out.count("Scenario:") == 1
    for line in out.splitlines():
        assert "Given" not in line or line.strip().startswith("Given")


def test_steps_render_binds_every_scenario(tmp_path):
    steps_py = render_steps(CLAUSES)
    assert "scenarios('.')" in steps_py
    assert "@given" in steps_py and "@when" in steps_py and "@then" in steps_py


# @trace("TR-FORWARD-COVERAGE")
def test_all_clauses_collect_and_pass(tmp_path):
    """Integration: N clauses -> N passing scenarios (V3: 26/26 in 0.26s)."""
    for clause in CLAUSES:
        (tmp_path / f"{clause['alias'].lower()}.feature").write_text(render_feature(clause))
    (tmp_path / "test_generated.py").write_text(render_steps(CLAUSES))
    result = run_pytest(tmp_path)
    assert result.ok, result.tail
    assert f"{len(CLAUSES)} passed" in result.tail


# --- GATE-MUTATION-KILL (mut-dsl-codegen campaign 2026-09-06) ----------------
# gherkin_fallback_green previously had zero coverage: all 12 of its mutants
# reported "no tests".

# GATE-MUTATION-KILL: fallback writes one lowercased .feature per clause plus
# test_generated.py into the sandbox, passes the sandbox to run_pytest, and
# returns run_pytest(...).ok faithfully in both directions
def test_fallback_green_writes_artifacts_and_returns_ok(tmp_path):
    seen = []

    def fake_run(sandbox):
        seen.append(sandbox)
        return SimpleNamespace(ok=True)

    assert gherkin_fallback_green(CLAUSES, tmp_path, fake_run) is True
    assert seen == [tmp_path]
    assert (tmp_path / "con-a.feature").read_text() == render_feature(CLAUSES[0])
    assert (tmp_path / "tr-b.feature").read_text() == render_feature(CLAUSES[1])
    assert (tmp_path / "test_generated.py").read_text() == render_steps(CLAUSES)


def test_fallback_green_reflects_failing_pytest(tmp_path):
    assert gherkin_fallback_green(
        CLAUSES, tmp_path, lambda sb: SimpleNamespace(ok=False)
    ) is False


# GATE-MUTATION-KILL: feature title falls back to the alias only when 'title'
# is absent; the blank separator lines are part of the artifact contract
# (render_feature 4/5/6/7/8/9/10/12)
def test_feature_title_falls_back_to_alias_and_layout_byte_exact():
    body = (
        "Feature: A-1\n"
        "\n"
        "  Scenario: {title}\n"
        "    Given the contract clause A-1 is validated\n"
        "    When the trigger condition of A-1 holds\n"
        "    Then the system satisfies the clause response\n"
    )
    assert render_feature({"alias": "A-1", "title": "T"}) == body.format(title="T")
    assert render_feature({"alias": "A-1"}) == body.format(title="A-1")


# GATE-MUTATION-KILL: step fn names hash (kind, text) into an 8-hex-digit
# namespace — a collision or wrong namespace silently shadows a step
# (render_steps 16/26/27/28/31/32/33/34)
def test_step_function_names_are_unique_eight_digit_namespaces():
    out = render_steps(CLAUSES)
    names = re.findall(r"def (step_[0-9a-f]{8})\(", out)
    assert len(names) == 5  # 2 given + 2 when + 1 then
    assert len(set(names)) == 5
    # namespace is sha256("kind\0text")[:8] — stable across processes, so a
    # regen must be byte-identical (builtin hash() is per-process salted and
    # churned the tracked file on every `check .` run)
    again = render_steps(CLAUSES)
    assert again == out
    assert re.findall(r"def (step_[0-9a-f]{8})\(", again) == names
    assert 'parsers.parse("the system satisfies the clause response")' in out
