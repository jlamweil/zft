"""C-05: clause schema validation (§5.1 incl. amended check kinds) + UUIDv7 identity."""
import pytest

from traceagent.spec.identity import new_uuid7
from traceagent.spec.schema import SchemaError, validate_node

VALID = {
    "node_id": new_uuid7(),
    "alias": "TR-FORWARD-COVERAGE",
    "domain": "traceability",
    "title": "Forward coverage",
    "status": "PROPOSED",
    "version": 1,
    "content_hash": "0" * 64,
    "invariants": [
        {"id": "TR-INV-01", "statement": "WHEN x THE SYSTEM SHALL y",
         "property": "forall x: ok(x)", "check": {"kind": "test"}}
    ],
    "external_links": [],
}


def test_valid_node_passes():
    validate_node(VALID)  # no exception


def test_uuidv7_shape_enforced():
    bad = dict(VALID, node_id="00000000-0000-0000-0000-000000000000")
    with pytest.raises(SchemaError, match="UUIDv7"):
        validate_node(bad)


# @trace("ID-UUIDV7-ALIAS")
def test_new_uuid7_is_v7_canonical():
    n = new_uuid7()
    assert len(n) == 36 and n[14] == "7" and n[19] in "89ab"


def test_new_uuid7_timestamp_binds_to_wall_clock():
    """RFC 9562 §4.2: the first 48 bits are unix time in milliseconds."""
    import time

    before = int(time.time() * 1000) - 5
    ms = int(new_uuid7().replace("-", "")[:12], 16)
    after = int(time.time() * 1000) + 5
    assert before <= ms <= after


def test_new_uuid7_exact_vector_from_mocked_clock_and_rng(monkeypatch):
    """Deterministic field-layout pin: clock and CSPRNG mocked, the full
    UUID string is a hand-derived constant (018bcfe5-687b-7fff-bfff-
    ffffffffffff). The random-draw pin above kills field-shift mutants only
    with probability ~1/4 per draw — not evidence; this vector kills every
    field-shift and mask-tightening mutant deterministically, including the
    1-in-16 rand_a bit-12 case (0xffff draws rand_a = 0xfff, bit 12 set).
    Proof-run residue (2026-09-13): the survivors are exactly the waived
    equivalents — identity masks (& -1), Python >= 3.11 implicit byteorder,
    unreachable mask bits, slice clamp."""
    monkeypatch.setattr("traceagent.spec.identity.time.time",
                        lambda: 1_700_000_000.123)
    calls = []

    def fake_urandom(n):
        calls.append(n)
        return b"\xff" * n

    monkeypatch.setattr("traceagent.spec.identity.os.urandom", fake_urandom)
    assert new_uuid7() == "018bcfe5-687b-7fff-bfff-ffffffffffff"
    assert calls == [2, 8]  # 12 rand_a bits + 62 rand_b bits, in that order


def test_alias_pattern_enforced():
    with pytest.raises(SchemaError, match="alias"):
        validate_node(dict(VALID, alias="not-a-alias"))


def test_status_enum_enforced():
    with pytest.raises(SchemaError, match="status"):
        validate_node(dict(VALID, status="SHIPPED"))


def test_check_kind_enum_includes_amended_kinds():
    for kind in ("property", "type", "test", "judge", "process"):
        n = dict(VALID, invariants=[dict(VALID["invariants"][0], check={"kind": kind})])
        validate_node(n)
    with pytest.raises(SchemaError, match=r"check.kind.*vibes|vibes.*check"):
        validate_node(dict(VALID, invariants=[
            dict(VALID["invariants"][0], check={"kind": "vibes"})]))


def test_missing_required_field():
    bad = {k: v for k, v in VALID.items() if k != "title"}
    with pytest.raises(SchemaError, match="title"):
        validate_node(bad)


def test_missing_node_id_pins_the_empty_default():
    # GATE-MUTATION-KILL: a node without node_id reports the '' default in the
    # typed message (a None default would TypeError, "XXXX" would print wrong)
    with pytest.raises(SchemaError, match=r"node_id: not a canonical UUIDv7 \(''\)"):
        validate_node({})


def test_validation_reports_lowest_path_first():
    # GATE-MUTATION-KILL: errors sort by JSON path — the required-field error
    # (path []) outranks a property-type error (path ["version"]) even though
    # jsonschema iterates properties before required
    bad = {k: v for k, v in VALID.items() if k != "alias"}
    bad["version"] = "x"
    with pytest.raises(SchemaError, match=r"'alias' is a required property"):
        validate_node(bad)
