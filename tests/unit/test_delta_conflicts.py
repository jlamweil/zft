"""C-07: delta replay (ADDED/MODIFIED/REMOVED) + concurrent-edit conflicts (V9)."""
import pytest

from traceagent.registry.conflicts import detect_conflicts
from traceagent.spec.canon import canonical_hash
from traceagent.spec.delta import DeltaError, apply_delta


def _node(alias, title="t", version=1):
    import uuid

    n = {"node_id": uuid.uuid5(uuid.NAMESPACE_OID, alias).hex.replace("-", ""),
         "alias": alias, "domain": "x", "title": title,
         "status": "PROPOSED", "version": version,
         "invariants": [{"id": alias + "-INV-01", "statement": "s", "property": "p",
                         "check": {"kind": "test"}}],
         "external_links": []}
    return n


def test_added_applies():
    store = {}
    n = _node("X-ONE")
    apply_delta(store, {"op": "ADDED", "clause": n})
    assert "X-ONE" in store


def test_added_rejects_existing_alias():
    store = {"X-ONE": _node("X-ONE")}
    with pytest.raises(DeltaError, match="alias exists"):
        apply_delta(store, {"op": "ADDED", "clause": _node("X-ONE")})


# @trace("CON-AMEND-VIA-DELTAS")
def test_modified_requires_matching_old_hash():
    n = _node("X-ONE")
    store = {"X-ONE": n}
    good = dict(n, title="amended")
    apply_delta(store, {"op": "MODIFIED", "alias": "X-ONE",
                        "old_hash": canonical_hash(n), "clause": good})
    assert store["X-ONE"]["title"] == "amended"
    assert store["X-ONE"]["version"] == 2
    with pytest.raises(DeltaError, match="stale base"):
        apply_delta(store, {"op": "MODIFIED", "alias": "X-ONE",
                            "old_hash": "0" * 64,
                            "clause": dict(good, title="stale edit")})


def test_removed_applies():
    store = {"X-ONE": _node("X-ONE")}
    apply_delta(store, {"op": "REMOVED", "alias": "X-ONE"})
    assert "X-ONE" not in store


# @trace("ID-CONFLICT-HALT")
def test_concurrent_edit_conflict_detected():
    """Same node_id, both bumped to v2, divergent content -> conflict (V9-C)."""
    base = _node("X-ONE")
    a = dict(base, version=2, title="from agent A")
    b = dict(base, version=2, title="from agent B")
    conflicts = detect_conflicts([a, b])
    assert conflicts == [{"node_id": base["node_id"],
                          "reason": "same version, divergent content",
                          "versions": [2, 2]}]


def test_added_stores_the_clause_itself():
    # GATE-MUTATION-KILL: ADD storing None (mutation_bar survivor class logic)
    store = {}
    n = _node("X-ONE")
    apply_delta(store, {"op": "ADDED", "clause": n})
    assert store["X-ONE"] == n


def test_modified_missing_alias_is_typed():
    # GATE-MUTATION-KILL: the no-such-clause reason text is contractual
    with pytest.raises(DeltaError, match=r"MODIFIED X-GONE: no such clause"):
        apply_delta({}, {"op": "MODIFIED", "alias": "X-GONE",
                         "old_hash": "0" * 64, "clause": _node("X-GONE")})


def test_modified_reseals_content_hash():
    # GATE-MUTATION-KILL: the applied clause carries the canonical hash of
    # itself under the content_hash key (canonical_hash excludes that key)
    n = _node("X-ONE")
    store = {"X-ONE": n}
    apply_delta(store, {"op": "MODIFIED", "alias": "X-ONE",
                        "old_hash": canonical_hash(n),
                        "clause": dict(n, title="amended")})
    applied = store["X-ONE"]
    assert applied["content_hash"] == canonical_hash(applied)


def test_removed_absent_alias_is_a_noop():
    # GATE-MUTATION-KILL: REMOVE tolerates a missing alias (pop default), no raise
    store = {}
    apply_delta(store, {"op": "REMOVED", "alias": "X-GONE"})
    assert store == {}


def test_unknown_op_is_typed():
    # GATE-MUTATION-KILL: the unknown-op reason text is contractual
    with pytest.raises(DeltaError, match=r"unknown op 'ARCHIVED'"):
        apply_delta({}, {"op": "ARCHIVED", "alias": "X-ONE"})


def test_conflicts_require_divergent_content():
    # GATE-MUTATION-KILL: a single-node group (or identical-content group)
    # has one hash — not a conflict; only divergence flags
    n = _node("X-ONE")
    assert detect_conflicts([n]) == []
    assert detect_conflicts([dict(n, version=2), dict(n, version=2)]) == []
