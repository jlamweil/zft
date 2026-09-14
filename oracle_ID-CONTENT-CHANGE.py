def check():
    """Oracle for ID-CONTENT-CHANGE property clause.

    Verifies that the canonical content hash changes when meaningful fields
    (title, domain) change, and stays unchanged for irrelevant metadata.
    """
    import copy
    from traceagent.spec.canon import canonical_hash

    # Base clause (mirrors the one used in test_canon.py)
    base = {
        "node_id": "018f3a2b-9e41-7100-8000-000000000001",
        "alias": "TR-FORWARD-COVERAGE",
        "domain": "Traceability",
        "title": "  Forward coverage: every clause mapped ",
        "status": "PROPOSED",
        "version": 3,
        "content_hash": "x",
        "invariants": [
            {
                "id": "TR-INV-01",
                "statement": "every clause mapped",
                "property": "forall c: covered(c)",
                "check": {"kind": "test"},
            }
        ],
        "external_links": [{"system": "JIRA", "external_id": "X-1"}],
    }

    # Original hash
    h0 = canonical_hash(base)

    # Meaningful change: title
    mutated_title = copy.deepcopy(base)
    mutated_title["title"] = "other title"
    h_title = canonical_hash(mutated_title)
    assert h0 != h_title, "changing title must affect hash"

    # Meaningful change: domain
    mutated_domain = copy.deepcopy(base)
    mutated_domain["domain"] = "auth"
    h_domain = canonical_hash(mutated_domain)
    assert h0 != h_domain, "changing domain must affect hash"

    # Irrelevant change: alias (should not affect hash)
    mutated_alias = copy.deepcopy(base)
    mutated_alias["alias"] = "SOME-OTHER"
    h_alias = canonical_hash(mutated_alias)
    assert h0 == h_alias, "changing alias must NOT affect hash"
