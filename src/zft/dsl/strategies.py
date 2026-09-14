"""Binder -> Hypothesis strategy mapping (plan C-11).

Conventions cover the common corpus binders, ordered specific -> general:
corpus-pinned collections first, then structural/nested shapes (compound
plural optionals, tensors, matrices, edge/adjacency graphs, point lists,
interval lists, mappings, sets, optionals, pairs, recursive JSON-like
payloads, heterogeneous scalar maps), then the broad scalar patterns, then a
guarded plural-collection fallback. Explicit `check.generator` always wins;
anything else is StrategyError — which routes the clause to judge.

Ordering is load-bearing: corpus pins win by design, compound plurals must
precede their singular bands (e.g. `coords` before `coord`), plural
collections must precede the guarded plural fallback, everything structural
must precede the broad scalars, and the integer band is whole-name anchored
(`^t$|^x$`) so t-final text names are not captured by the end-of-string word
boundary. Existing mappings are pinned by tests/unit/test_strategies_oracle.py
and the golden codegen fixtures — reordering is a breaking change.

New collection strategies are size-bounded (max_size caps) so generated
property tests stay inside Hypothesis health-check budgets; the pinned
pre-existing shapes are left unbounded for golden stability.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

# Arbitrarily nested JSON-like payloads (lists/dicts of lists/dicts of
# scalars), rendered verbatim into generated property tests.
_RECURSIVE_JSON = (
    "st.recursive("
    "st.none() | st.booleans() | st.integers() | st.text(),"
    " lambda kids: st.lists(kids, max_size=8)"
    " | st.dictionaries(st.text(), kids, max_size=8),"
    " max_leaves=25)"
)

# Bounded structural shapes (size caps keep L1 property runs cheap).
_TENSOR = "st.lists(st.lists(st.lists(st.integers(), max_size=4), max_size=4), max_size=8)"  # noqa: E501
_EDGE_LIST = "st.lists(st.tuples(st.integers(), st.integers()), max_size=32)"
_POINT_LIST = "st.lists(st.tuples(st.integers(), st.integers()), max_size=16)"
_ADJACENCY = "st.dictionaries(st.integers(), st.lists(st.integers(), max_size=8), max_size=16)"  # noqa: E501
_OPT_LIST = "st.lists(st.none() | st.integers(), max_size=16)"
_SCALAR_MAP = (
    "st.dictionaries(st.text(), st.integers() | st.text() | st.booleans(), max_size=8)"
)

CONVENTIONS: list[tuple[str, str]] = [
    # corpus-pinned collections (exact vocabulary, checked first)
    (r"rows$", "st.lists(st.integers())"),
    (r"names$", "st.lists(st.text())"),
    (r"^rows", "st.lists(st.integers())"),
    # structural / nested shapes — must precede the broad scalar patterns
    (r"(opt|maybe|nullable)[a-z_]*s$", _OPT_LIST),
    (r"tensor|cube", _TENSOR),
    (r"matrix|grid", "st.lists(st.lists(st.integers()))"),
    (r"edges?[_s]|arcs?[_s]|links", _EDGE_LIST),
    (r"graph|adjacency", _ADJACENCY),
    (r"points$|vectors$|coords$", _POINT_LIST),
    (r"records|entries", "st.lists(st.dictionaries(st.text(), st.integers()))"),
    (r"map|mapping|dict|table", "st.dictionaries(st.text(), st.integers())"),
    (r"grouped|by_", "st.dictionaries(st.text(), st.lists(st.integers()))"),
    (r"intervals|ranges|windows|spans", _EDGE_LIST),
    (r"tags|sets$|_set$", "st.sets(st.text())"),
    (r"opt|maybe|nullable", "st.one_of(st.none(), st.integers())"),
    (r"pair|tuple|coord", "st.tuples(st.integers(), st.integers())"),
    (r"tree|nested|payload|json|doc\b|obj\b", _RECURSIVE_JSON),
    # heterogeneous scalar maps — after the recursive band so payload-ish
    # names keep their structural reading (e.g. 'payload_fields')
    (r"config|attrs|props|fields", _SCALAR_MAP),
    # guarded plural fallback: orders/gates/nodes/... -> lists of names
    (r"^[a-z_]{4,}s$", "st.lists(st.text())"),
    # broad scalar conventions (booleans first: is_/has_/..._flag names would
    # otherwise fall through to the integer band). The integer band is
    # whole-name anchored: bare `t\b`/`x\b` also matched any t-final name
    # (end-of-string is a word boundary), so 'text', 'stmt', 'result',
    # 'output' silently drew integers — text binders must reach the text band.
    (r"^is_|^has_|flag$|enabled", "st.booleans()"),
    (r"num|count|ver|^t$|^x$", "st.integers()"),
    (r"name|title|text|stmt", "st.text()"),
]


class StrategyError(ValueError):
    """No strategy convention for a binder — clause routes to judge."""


def strategy_for(binder: str, check: Mapping) -> str:
    """Map a binder name to a Hypothesis strategy expression (source string).

    Raises TypeError on type violations (caller bugs) and StrategyError on
    value violations (unknown binder, malformed explicit generator).
    """
    if not isinstance(binder, str):
        raise TypeError(f"binder must be str, got {type(binder).__name__}: {binder!r}")
    if not isinstance(check, Mapping):
        raise TypeError(f"check must be a Mapping, got {type(check).__name__}: {check!r}")
    explicit = check.get("generator")
    if explicit is not None:
        if not isinstance(explicit, str) or not explicit.strip():
            raise StrategyError(
                f"invalid check.generator for binder '{binder}': {explicit!r} "
                "(expected a Hypothesis strategy expression, e.g. 'st.integers()')"
            )
        return explicit
    for pattern, strategy in CONVENTIONS:
        if re.search(pattern, binder):
            return strategy
    raise StrategyError(
        f"no strategy convention for binder '{binder}' — route to judge "
        "(or set check.generator explicitly)"
    )
