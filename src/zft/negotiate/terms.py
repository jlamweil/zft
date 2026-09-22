"""Counter-terms documents: the bargain input that arrives from outside.

`zft negotiate --counter-terms <file|->` takes the counter-party's
term sheet as JSON — the `counter` transition carries the sheet's terms and
the sheet's decision decides the terminal state (CON-COUNTER-RECORDED: the
counter-proposal and the accept/reject decision are both recorded). This
module parses and validates that document; it does no IO and owns no policy.

Schema (strict — unknown keys are defects, not extensions):

  {"terms": <any JSON value>,        // the counter-proposal itself
   "decision": "accept" | "refuse",  // the counter-party's decision on it
   "reason": <string>}               // required with refuse, banned otherwise
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from zft.spec.canon import canonical_json

_DECISIONS = ("accept", "refuse")


@dataclass(frozen=True)
class CounterTerms:
    terms: Any
    decision: str
    reason: str | None


class CounterTermsError(ValueError):
    """The counter-terms document is not a bargain we can record."""


def parse_counter_terms(raw: str | bytes) -> CounterTerms:
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CounterTermsError(f"malformed JSON: {e}") from e
    if not isinstance(doc, dict):
        raise CounterTermsError(
            f"counter-terms document must be a JSON object, got {type(doc).__name__}")
    unknown = sorted(set(doc) - {"terms", "decision", "reason"})
    if unknown:
        raise CounterTermsError(f"unknown key(s) {unknown} — allowed: "
                                f"['decision', 'reason', 'terms']")
    if "terms" not in doc:
        raise CounterTermsError("missing 'terms' — a bargain must state its terms")
    decision = doc.get("decision")
    if decision not in _DECISIONS:
        raise CounterTermsError(
            f"'decision' must be one of {list(_DECISIONS)}, got {decision!r}")
    reason = doc.get("reason")
    if decision == "refuse":
        if not isinstance(reason, str) or not reason:
            raise CounterTermsError("'refuse' requires a non-empty 'reason' string")
    elif reason is not None:
        raise CounterTermsError("'reason' is only allowed with 'decision': 'refuse'")
    return CounterTerms(terms=doc["terms"], decision=decision,
                        reason=reason if decision == "refuse" else None)


def terms_digest(terms: Any) -> str:
    """Bind the recorded outcome to the exact terms bargained over."""
    return hashlib.sha256(canonical_json(terms).encode()).hexdigest()


def terms_string(terms: Any) -> str:
    """The ledger form of a term sheet: strings verbatim, anything else canonical."""
    return terms if isinstance(terms, str) else canonical_json(terms)


def terms_from_recorded(recorded: str) -> Any:
    """The terms value behind a recorded counter string — the inverse of
    `terms_string` wherever the two forms are distinguishable: structured
    terms round-trip exactly through their canonical JSON, plain strings
    verbatim. A string that itself parses as JSON is indistinguishable in
    the ledger from that JSON value; the JSON-value reading wins (the
    recorded bytes bind either way). Non-string values (legacy ledger
    lines that recorded raw JSON terms) pass through as themselves."""
    if not isinstance(recorded, str):
        return recorded
    try:
        return json.loads(recorded)
    except json.JSONDecodeError:
        return recorded


def digest_from_recorded(recorded: str) -> str:
    """Bind a validated outcome to the counter-proposal the ledger records —
    computable from history alone (resumed runs, wire turns), and equal to
    `terms_digest` of the document the counter originally carried."""
    return terms_digest(terms_from_recorded(recorded))
