"""C-04: §5.2 canonical content hash — meaning-bearing content only.

Golden vectors from the verification lab (V9 fixtures). Independent source of
truth: ARCHITECTURE.md §5.2 normalization rules, hand-computed expected value.
"""
import json

from traceagent.spec.canon import canonical_hash, canonical_json, canonical_payload

CLAUSE = {
    "node_id": "018f3a2b-9e41-7100-8000-000000000001",
    "alias": "TR-FORWARD-COVERAGE",
    "domain": "Traceability",
    "title": "  Forward coverage: every clause mapped ",
    "status": "PROPOSED",
    "version": 3,
    "content_hash": "x",
    "invariants": [
        {"id": "TR-INV-01", "statement": "every clause mapped", "property": "forall c: covered(c)",
         "check": {"kind": "test"}},
    ],
    "external_links": [{"system": "JIRA", "external_id": "X-1"}],
}


def test_golden_hash():
    """Hand-derived: SHA256 of canonical json {domain,title,invariants sorted}."""
    expected_payload = {
        "domain": "traceability",
        "title": "forward coverage: every clause mapped",
        "invariants": [
            {"id": "TR-INV-01", "statement": "every clause mapped",
             "property": "forall c: covered(c)", "check": {"kind": "test"}},
        ],
    }
    import hashlib

    expected = hashlib.sha256(
        json.dumps(expected_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert canonical_hash(CLAUSE) == expected


def test_alias_status_version_excluded():
    """Identity/revision/metadata changes must NOT move the content hash (D2)."""
    mutated = dict(CLAUSE, alias="TR-REBORN", status="VALIDATED", version=99,
                   content_hash="different", node_id="ffffffff-ffff-7fff-8fff-ffffffffffff")
    assert canonical_hash(mutated) == canonical_hash(CLAUSE)


# @trace("ID-CONTENT-CHANGE")
def test_meaning_changes_move_hash():
    for field, value in [("title", "other title"), ("domain", "auth")]:
        mutated = dict(CLAUSE, **{field: value})
        assert canonical_hash(mutated) != canonical_hash(CLAUSE), field


def test_invariant_order_is_canonical():
    reordered = dict(CLAUSE, invariants=list(reversed(CLAUSE["invariants"])))
    reordered["invariants"].append(
        {"id": "TR-INV-00", "statement": "s", "property": "p", "check": {"kind": "judge"}}
    )
    # order of invariants in the file must not change the hash
    assert canonical_hash(reordered) == canonical_hash(reordered)


def test_canonical_json_is_compact_and_sorted():
    out = canonical_json({"b": 1, "a": 2})
    assert out == '{"a":2,"b":1}'  # sorted keys, no whitespace (§5.2)
    assert " " not in out


# §5.2 defaults are part of the contract: a sparse node must canonicalize to
# exactly the explicit-empty form — no key may fall back to a sentinel or a
# crash, or two spellings of the same clause would hash differently.
def test_missing_node_keys_canonicalize_to_explicit_empty():
    payload = canonical_payload({})
    assert payload == {"domain": "", "title": "", "invariants": []}
    explicit = {"domain": "", "title": "", "invariants": []}
    assert canonical_hash({}) == canonical_hash(explicit)


def test_missing_invariant_fields_canonicalize_to_explicit_empty():
    sparse = {"invariants": [{}]}
    payload = canonical_payload(sparse)
    assert payload["invariants"] == [
        {"id": "", "statement": "", "property": "", "check": {}}
    ]
    explicit = {"invariants": [{"id": "", "statement": "", "property": "",
                                "check": {}}]}
    assert canonical_hash(sparse) == canonical_hash(explicit)


def test_missing_domain_and_title_independently():
    assert canonical_payload({"title": "t"})["domain"] == ""
    assert canonical_payload({"domain": "d"})["title"] == ""
    assert canonical_hash({"domain": "d"}) == canonical_hash(
        {"domain": "d", "title": "", "invariants": []}
    )
