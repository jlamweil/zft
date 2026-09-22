"""EARS statement parser — surface syntax of contract clauses.

Grammar (per Mavin 2009, plan D-DSL):
    [<Trigger> ,] THE SYSTEM <modal> <response> .
with Trigger forms WHEN / IF / WHILE / WHERE; modal SHALL|MUST.

Edge cases fail gracefully: every rejection raises EarsError with a layered
diagnostic — the specific problem, the offending excerpt, the expected shape,
and a fix hint — instead of a bare "not parseable".
"""
from __future__ import annotations

import re

TRIGGER_RE = re.compile(
    r"^\s*(?:(?P<trigger>WHEN|IF|WHILE|WHERE)\s+(?P<trigger_text>.+?),\s+)?"
    r"THE SYSTEM\s+(?P<modal>SHALL|MUST)\s+(?P<response>.+?)\s*\.?\s*$",
    re.S,
)

_TRIGGER_WORDS = ("WHEN", "IF", "WHILE", "WHERE")
_MODAL_WORDS = ("SHALL", "MUST")
_GRAMMAR = "[<WHEN|IF|WHILE|WHERE> <trigger>,] THE SYSTEM <SHALL|MUST> <response> [.]"


class EarsError(ValueError):
    """Statement is not parseable as EARS."""


def _problem(stmt: str, problem: str, hint: str) -> str:
    excerpt = stmt if len(stmt) <= 80 else stmt[:77] + "..."
    return (
        f"not an EARS statement: {problem}\n"
        f"  statement: {excerpt!r}\n"
        f"  expected: {_GRAMMAR}\n"
        f"  hint: {hint}"
    )


def _diagnose(stmt: str) -> str:
    """Explain WHY the statement did not match the EARS grammar."""
    s = stmt.strip()
    if not s:
        return _problem(stmt, "statement is empty",
                        "write a response, e.g. THE SYSTEM SHALL refuse unvalidated contracts")
    if "the system" in s.lower() and "THE SYSTEM" not in s:
        return _problem(stmt, "keyword 'THE SYSTEM' is lowercase",
                        "EARS keywords are uppercase: THE SYSTEM SHALL ...")
    if "THE SYSTEM" not in s:
        return _problem(stmt, "missing 'THE SYSTEM' clause",
                        "every EARS statement names the system: THE SYSTEM SHALL ...")
    after = re.search(r"THE SYSTEM\s+(\w+)", s)
    if not after:
        return _problem(stmt, "statement ends at 'THE SYSTEM'",
                        "add a modal (SHALL or MUST) and a response")
    if after.group(1) not in _MODAL_WORDS:
        return _problem(stmt, f"modal after 'THE SYSTEM' is {after.group(1)!r}, "
                              f"expected {' or '.join(_MODAL_WORDS)}",
                        "the only valid modals are SHALL and MUST (uppercase)")
    if re.search(r"THE SYSTEM\s+(?:SHALL|MUST)\s*\.?\s*$", s):
        return _problem(stmt, f"response is missing after {after.group(1)}",
                        "state what THE SYSTEM SHALL do, e.g. SHALL refuse "
                        "unvalidated contracts")
    first = re.match(r"([A-Za-z]+)", s)
    word = first.group(1) if first else ""
    if word.upper() in _TRIGGER_WORDS:
        if word not in _TRIGGER_WORDS:
            return _problem(stmt, f"trigger keyword is lowercase ({word!r})",
                            "EARS keywords are uppercase: "
                            f"{'/'.join(_TRIGGER_WORDS)}")
        between = s[len(word):s.index("THE SYSTEM")]
        if "," not in between:
            return _problem(stmt, "trigger is not followed by a comma before 'THE SYSTEM'",
                            "separate trigger and response with a comma: "
                            "WHEN <trigger>, THE SYSTEM SHALL ...")
        if not any(ch.isalnum() for ch in between.split(",")[0]):
            return _problem(stmt, f"trigger after {word} is empty or punctuation-only",
                            "state a concrete condition, e.g. WHEN a work order "
                            "is assigned,")
    elif word != "THE":
        return _problem(stmt, f"statement starts with {word!r}, not a trigger keyword",
                        f"start with {'/'.join(_TRIGGER_WORDS)} for conditional "
                        "statements, or go straight to 'THE SYSTEM' for a "
                        "ubiquitous statement")
    return _problem(stmt, "syntax does not match the EARS grammar",
                    f"shape: {_GRAMMAR}")


def parse_statement(stmt: str) -> dict[str, str | None]:
    """Parse one EARS statement; raises EarsError with a fix hint on failure."""
    if not isinstance(stmt, str):
        raise TypeError(f"statement must be str, got {type(stmt).__name__}: {stmt!r}")
    m = TRIGGER_RE.match(stmt.strip())
    if not m:
        raise EarsError(_diagnose(stmt))
    trigger = m.group("trigger_text")
    response = m.group("response").strip().rstrip(".")
    if trigger is not None and not any(ch.isalnum() for ch in trigger):
        raise EarsError(_problem(
            stmt,
            f"trigger after {m.group('trigger')} is empty or punctuation-only",
            "state a concrete condition, e.g. WHEN a work order is assigned,"))
    if not response:
        raise EarsError(_problem(
            stmt, "response is empty",
            "state what THE SYSTEM SHALL do before the closing period"))
    return {
        "type": m.group("trigger") or "UBIQUITOUS",
        "trigger": trigger,
        "modal": m.group("modal"),
        "response": response,
    }
