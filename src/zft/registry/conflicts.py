"""Concurrent-minting conflict detection (V9): same identity, divergent content."""
from __future__ import annotations

from zft.spec.canon import canonical_hash


def detect_conflicts(nodes: list[dict]) -> list[dict]:
    """Detect nodes sharing node_id whose content diverges."""
    by_id: dict[str, list[dict]] = {}
    for n in nodes:
        by_id.setdefault(n["node_id"], []).append(n)
    conflicts = []
    for node_id, group in by_id.items():
        hashes = {canonical_hash(n) for n in group}
        if len(hashes) > 1:
            conflicts.append({
                "node_id": node_id,
                "reason": "same version, divergent content",
                "versions": [n["version"] for n in group],
            })
    return conflicts
