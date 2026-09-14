"""Fuzzed canonicalization / malleability / statelessness properties.

Companion to ATTACK_MATRIX.md (FUZZ rows): the malformed-envelope table pins
hand-picked cuts and flips; these properties assert the same defenses hold
for *arbitrary* inputs — every acceptance is a round-trip proof, every
rejection leaves the original envelope verifiable (no oracle bleed).
Row ids are stable and mirrored in ATTACK_MATRIX.md.
"""

import base64
import json

from hypothesis import given, settings
from hypothesis import strategies as st
from securesystemslib.dsse import Envelope
from securesystemslib.signer import CryptoSigner

from traceagent.attest.dsse import (
    AttestationError,
    EnvelopeFormatError,
    _canonical_base64,
    verify_attestation,
)
from traceagent.attest.jcs import canonicalize

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
PAYLOAD_TYPE = "application/vnd.in-toto+json"

# strict-JSON values a signer could legally commit to (RFC 8785 subset: no
# NaN/Infinity, integers within the exact double range, string keys). Integral
# floats ≥ 2**53 are excluded: their canonical text re-parses as an int outside
# the documented jcs.py bound (L-4 carve-out — pinned in test_jcs.py).
_json_scalars = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53) + 1, max_value=2**53 - 1)
    | st.floats(allow_nan=False, allow_infinity=False).filter(
        lambda v: not (v.is_integer() and abs(v) > 2**53 - 1))
    | st.text(max_size=32)
)
_json_values = st.recursive(
    _json_scalars,
    lambda children: st.lists(children, max_size=4)
    | st.dictionaries(st.text(max_size=16), children, max_size=4),
    max_leaves=8,
)


@settings(max_examples=50, deadline=None)
@given(st.binary(min_size=1, max_size=200))
def test_fuzz_canonical_base64_accepts_exactly_the_canonical_form(data):
    """FUZZ-1: standard base64 of arbitrary bytes always passes the canonical
    gate (no false rejections), and ANY single-character mutation either
    fails the gate or decodes to different bytes — the pad-bit/alphabet
    malleability is closed at every length, not just the table's examples."""
    text = base64.b64encode(data).decode()
    _canonical_base64(text, "'payload'")  # must not raise
    for i in range(len(text)):
        for ch in ("A", "Z", "+", "/", "Q"):
            mutated = text[:i] + ch + text[i + 1:]
            if mutated == text:
                continue
            try:
                _canonical_base64(mutated, "'payload'")
            except EnvelopeFormatError:
                continue
            assert base64.b64decode(mutated) != data


@settings(max_examples=50, deadline=None)
@given(_json_values)
def test_fuzz_jcs_is_an_idempotent_information_preserving_fixpoint(value):
    """FUZZ-2: canonicalization is a fixed point (canonicalize∘parse∘canonicalize
    is identity on bytes) and information-preserving (parse inverts it) —
    G6's determinism claim holds for arbitrary payloads, not just fixtures."""
    once = canonicalize(value)
    assert canonicalize(json.loads(once)) == once
    assert json.loads(once) == value


def _signed_envelope() -> tuple[dict, CryptoSigner]:
    signer = CryptoSigner.generate_ed25519()
    statement = canonicalize(
        {
            "_type": "https://in-toto.io/Statement/v1",
            "predicateType": "https://example.com/pred/v1",
            "subject": [{"name": "clause:x.json", "digest": {"sha256": "d" * 64}}],
            "predicate": {},
        }
    )
    envelope = Envelope(payload=statement, payload_type=PAYLOAD_TYPE, signatures={})
    envelope.sign(signer)
    return envelope.to_dict(), signer


def _mutation(text: str, kind: str, where: int, ch: str) -> str:
    if kind == "flip":
        i = where % len(text)
        return text[:i] + ch + text[i + 1:]
    if kind == "truncate":
        return text[:-1 - where % max(len(text) - 1, 1)]
    return text + ch  # append — usually breaks the padding-length invariant


_pick = st.tuples(
    st.sampled_from(["flip", "truncate", "append"]),
    st.sampled_from(["payload", "sig"]),
    st.integers(min_value=0, max_value=2**32),
    st.sampled_from(list(_ALPHABET)),
)


@settings(max_examples=40, deadline=None)
@given(_pick)
def test_fuzz_mutated_envelope_rejected_typed_original_unharmed(pick):
    """FUZZ-3: arbitrary single mutations of the payload or signature base64
    are rejected TYPED (never a bare substrate exception) and the untouched
    envelope still verifies to the same payload afterwards — verifier
    statelessness under arbitrary attacks, not just the matrix rows."""
    att, signer = _signed_envelope()
    kind, field, where, ch = pick
    if field == "payload":
        broken = {**att, "payload": _mutation(att["payload"], kind, where, ch)}
    else:
        entry = att["signatures"][0]
        broken = {**att,
                  "signatures": [{**entry, "sig": _mutation(entry["sig"], kind, where, ch)}]}
    try:
        verify_attestation(broken, public_key=signer.public_key)
    except AttestationError:
        pass
    else:
        # acceptance is only legal if the mutation was the identity
        assert broken == att
    payload = verify_attestation(json.loads(json.dumps(att)), public_key=signer.public_key)
    assert json.loads(base64.b64decode(att["payload"])) == payload
