"""Clause-node store: discovery, load, index (alias / content hash / node_id)."""
from __future__ import annotations

import json
from pathlib import Path

from traceagent.spec.canon import canonical_hash


class Store:
    """Read-side view over .zft/specs/**/*.json."""

    def __init__(self, root: Path, nodes: dict[str, dict]):
        self.root = root
        self.nodes = nodes  # alias -> node

    @classmethod
    def load(cls, root: Path | str) -> "Store":
        root = Path(root)
        nodes: dict[str, dict] = {}
        for path in sorted(root.rglob("*.json")):
            rel = path.relative_to(root)
            parts = rel.parts
            if len(parts) < 2 or parts[0] != ".zft" or parts[1] != "specs":
                continue
            node = json.loads(path.read_text())
            node["_file"] = str(rel)
            nodes[node.get("alias", rel.stem)] = node
        return cls(root, nodes)

    def aliases(self) -> list[str]:
        return sorted(self.nodes)

    def canonical_hash_of(self, alias: str) -> str:
        return canonical_hash(self.nodes[alias])


def load_contract(root: Path | str) -> dict:
    """Load .zft/contracts/<name>.json — the versioned clause-set container."""
    root = Path(root)
    contracts = sorted((root / ".zft" / "contracts").glob("*.json"))
    if not contracts:
        raise FileNotFoundError("no contract manifest under .zft/contracts")
    return json.loads(contracts[-1].read_text())
