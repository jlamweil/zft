"""Delta replay (OpenSpec-style) over the clause store: ADDED/MODIFIED/REMOVED."""
from __future__ import annotations

from traceagent.spec.canon import canonical_hash


class DeltaError(ValueError):
    """Delta application failure with typed reason."""


def apply_delta(store: dict, delta: dict) -> None:
    """Apply one delta in place; raise DeltaError on alias/stale-base failures."""
    op = delta["op"]
    if op == "ADDED":
        alias = delta["clause"]["alias"]
        if alias in store:
            raise DeltaError(f"ADDED {alias}: alias exists")
        store[alias] = delta["clause"]
    elif op == "MODIFIED":
        alias = delta["alias"]
        cur = store.get(alias)
        if cur is None:
            raise DeltaError(f"MODIFIED {alias}: no such clause")
        if canonical_hash(cur) != delta["old_hash"]:
            raise DeltaError(f"MODIFIED {alias}: stale base (concurrent change)")
        new = delta["clause"]
        new["version"] = cur["version"] + 1
        new["content_hash"] = canonical_hash(new)
        store[alias] = new
    elif op == "REMOVED":
        store.pop(delta["alias"], None)
    else:
        raise DeltaError(f"unknown op {op!r}")
