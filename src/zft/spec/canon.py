"""§5.2 canonical content hash — hash covers meaning, not revision state.

Canonical payload: {domain, title, invariants} — names lowercased/stripped,
invariants sorted by id, JSON with sorted keys and no whitespace.
Excluded deliberately: version, status, external_links, node_id, alias.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

_EXCLUDED = ("version", "status", "external_links", "node_id", "alias", "content_hash")


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def canonical_payload(node: dict) -> dict:
    return {
        "domain": node.get("domain", "").strip().lower(),
        "title": node.get("title", "").strip().lower(),
        "invariants": sorted(
            (
                {
                    "id": inv.get("id", "").strip(),
                    "statement": inv.get("statement", "").strip(),
                    "property": inv.get("property", "").strip(),
                    "check": inv.get("check", {}),
                }
                for inv in node.get("invariants", [])
            ),
            key=lambda i: i["id"],
        ),
    }


def canonical_hash(node: dict) -> str:
    return hashlib.sha256(canonical_json(canonical_payload(node)).encode()).hexdigest()
