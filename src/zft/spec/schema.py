"""§5.1 clause-node schema (with 2026-09-04 D1 amendment: check kinds extended)."""
from __future__ import annotations

import jsonschema

UUID7_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
ALIAS_RE = r"^[A-Z0-9]+-[A-Z0-9-]+$"
STATUSES = {"DRAFT", "PROPOSED", "VALIDATED", "IMPLEMENTED", "DEPRECATED"}
CHECK_KINDS = {"property", "type", "test", "judge", "process"}

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "ZFTClauseNode",
    "type": "object",
    "properties": {
        "node_id": {"type": "string", "pattern": UUID7_RE},
        "alias": {"type": "string", "pattern": ALIAS_RE},
        "domain": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "status": {"enum": sorted(STATUSES)},
        "version": {"type": "integer", "minimum": 1},
        "content_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "invariants": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "statement": {"type": "string", "minLength": 1},
                    "property": {"type": "string", "minLength": 1},
                    "check": {
                        "type": "object",
                        "properties": {
                            "kind": {"enum": sorted(CHECK_KINDS)},
                            "notes": {"type": "string"},
                        },
                        "required": ["kind"],
                    },
                },
                "required": ["id", "statement", "property", "check"],
            },
        },
        "external_links": {"type": "array"},
        "oracle_file": {"type": "string"},
        "oracle_sha256": {"type": "string"},
    },
    "required": ["node_id", "alias", "domain", "title", "status", "version",
                 "content_hash", "invariants"],
}


class SchemaError(ValueError):
    """Schema violation with schema-path detail (drives typed rejections)."""


def validate_node(node: dict) -> None:
    import re

    node_id = node.get("node_id", "")
    if not re.match(UUID7_RE, node_id):
        raise SchemaError(f"node_id: not a canonical UUIDv7 ({node_id!r})")
    validator = jsonschema.Draft202012Validator(SCHEMA)
    errors = sorted(validator.iter_errors(node), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "node"
        raise SchemaError(f"{path}: {first.message}")
