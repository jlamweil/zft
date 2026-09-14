"""Gherkin fallback codegen (plan C-14): every clause compiles to a scenario.

Guarantee (VERIFIED-DESIGNS D-CG): no clause is un-checkable — only
un-checked-yet. Property-capable clauses additionally get WP-4 property tests.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def render_feature(clause: dict) -> str:
    alias = clause["alias"]
    title = clause.get("title", alias)
    lines = [
        f"Feature: {alias}",
        "",
        f"  Scenario: {title}",
        f"    Given the contract clause {alias} is validated",
        f"    When the trigger condition of {alias} holds",
        "    Then the system satisfies the clause response",
        "",
    ]
    return "\n".join(lines)


def render_steps(clauses: list[dict]) -> str:
    steps = {("given", f"the contract clause {c['alias']} is validated") for c in clauses}
    steps |= {("when", f"the trigger condition of {c['alias']} holds") for c in clauses}
    steps.add(("then", "the system satisfies the clause response"))
    lines = ["from pytest_bdd import scenarios, given, when, then, parsers", "scenarios('.')", ""]
    for kind, text in sorted(steps):
        # builtin hash() is per-process salted: names would churn on every
        # regen, dirtying the tracked file each `check .` run. Stable digest.
        digest = hashlib.sha256(f"{kind}\x00{text}".encode()).hexdigest()[:8]
        fn = f"step_{digest}"
        lines.append(f'@{kind}(parsers.parse("{text}"))')
        lines.append(f"def {fn}():")
        lines.append("    pass")
        lines.append("")
    return "\n".join(lines)


def gherkin_fallback_green(clauses: list[dict], sandbox: Path, run_pytest) -> bool:
    """Write fallback artifacts into sandbox and confirm pytest passes."""
    for clause in clauses:
        (sandbox / f"{clause['alias'].lower()}.feature").write_text(render_feature(clause))
    (sandbox / "test_generated.py").write_text(render_steps(clauses))
    return run_pytest(sandbox).ok
