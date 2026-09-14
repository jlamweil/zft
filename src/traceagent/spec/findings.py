"""Structured gate findings (C-41, roadmap R-01): OPA-style deny/warn tiers.

Every integrity rule emits a Finding — a fixed six-key record
{alias, code, file, hint, msg, severity} — and evaluation ACCUMULATES
findings instead of stopping at the first. `deny` blocks the gate (L0 red);
`warn` publishes an advisory (ledger event, gate log, check summary) without
blocking. The shape is pinned by tests/golden/findings.json: adding or
re-tiering a rule is a golden change, not a silent one.
"""
from __future__ import annotations

from dataclasses import dataclass

DENY = "deny"
WARN = "warn"
SEVERITIES = (DENY, WARN)


@dataclass(frozen=True)
class Finding:
    """One integrity finding. Fixed shape; nulls explicit, never missing keys."""

    code: str
    severity: str
    msg: str
    hint: str = ""
    alias: str | None = None
    file: str | None = None

    def __post_init__(self):
        for name in ("code", "severity", "msg", "hint"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(
                    f"finding {name} must be str, got {type(value).__name__}: {value!r}")
        for name in ("alias", "file"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(
                    f"finding {name} must be str or None, got {type(value).__name__}: {value!r}")
        if not self.code.strip():
            raise ValueError("finding code must be a non-empty rule id")
        if not self.msg.strip():
            raise ValueError(f"finding {self.code} carries no message")
        if self.severity not in SEVERITIES:
            raise ValueError(
                f"finding severity must be one of {SEVERITIES}, got {self.severity!r}")

    def to_dict(self) -> dict:
        return {
            "alias": self.alias,
            "code": self.code,
            "file": self.file,
            "hint": self.hint,
            "msg": self.msg,
            "severity": self.severity,
        }


def render_finding(f: Finding) -> str:
    """Legacy-compatible single finding: '[file: ]msg' plus a hint line, if any."""
    out = f"{f.file}: {f.msg}" if f.file else f.msg
    if f.hint:
        out += f"\n  hint: {f.hint}"
    return out


def partition(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """(denies, warns): the gate decision and the advisory publication."""
    return ([f for f in findings if f.severity == DENY],
            [f for f in findings if f.severity == WARN])
