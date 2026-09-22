"""Signing-key / malformed-envelope attack matrix (companion to ATTACK_MATRIX.md).

Attack classes against attest.dsse, attest.keys and attest.export: KEY
(rotated and foreign keys, keyid splicing, plus the policy half — validity
windows, revocation, keyid pinning via attest.keys.KeyDocument), TRUNC
(truncated payloads, signatures, files), CANON (wrong canonicalization:
non-canonical JSON, non-canonical and urlsafe-alphabet base64), REPLAY
(grafted signatures, cross-envelope swaps, replay against a changed store),
EXPORT (the export surface over .zft/attest.json). Row ids are stable
and mirrored in ATTACK_MATRIX.md. Fuzzed canonicalization properties live in
test_attest_fuzz.py (FUZZ rows).

Every rejection row also proves verifier statelessness: the untampered
envelope still verifies after the attack attempt (no oracle bleed). Every
acceptance row is a round-trip proof: envelope -> JSON on disk -> reload ->
verify -> same payload.
"""

import base64
import binascii
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from securesystemslib.dsse import Envelope
from securesystemslib.signer import CryptoSigner, Key

from zft.attest.dsse import (
    EnvelopeFormatError,
    KeyValidationError,
    SignatureVerificationError,
    SubjectMismatchError,
    attest_contract,
    clause_subjects,
    verify_attestation,
)
from zft.attest.export import (
    export_envelope,
    export_matrix,
    export_summary,
    load_envelope,
)
from zft.attest.jcs import canonicalize
from zft.attest.keys import KeyDocument

REPO = Path(__file__).resolve().parents[2]
PAYLOAD_TYPE = "application/vnd.in-toto+json"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

_FROZEN = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


def _doc(signer, **meta) -> KeyDocument:
    """A key document exactly as `attest --key-out` (+ operator fields) writes it."""
    pub = signer.public_key
    return KeyDocument.from_dict({**pub.to_dict(), "keyid": pub.keyid, **meta})

# --------------------------------------------------------------------------
# helpers


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _signed_envelope(payload: bytes, signer, payload_type: str = PAYLOAD_TYPE) -> dict:
    envelope = Envelope(payload=payload, payload_type=payload_type, signatures={})
    envelope.sign(signer)
    return envelope.to_dict()


def _statement_bytes() -> bytes:
    return canonicalize(
        {
            "_type": STATEMENT_TYPE,
            "predicateType": "https://example.com/pred/v1",
            "subject": [{"name": "clause:x.json", "digest": {"sha256": "d" * 64}}],
            "predicate": {},
        }
    )


def _statement_bytes_with_pad_bits() -> bytes:
    """A payload whose base64 has non-zero ignored pad bits (len % 3 != 0) —
    only those lengths admit the CANON-2 pad-bit-flip malleability."""
    statement = {
        "_type": STATEMENT_TYPE,
        "predicateType": "https://example.com/pred/v1",
        "subject": [{"name": "clause:x.json", "digest": {"sha256": "d" * 64}}],
        "predicate": {},
    }
    raw = canonicalize(statement)
    while len(raw) % 3 == 0:
        statement["subject"][0]["name"] += "x"
        raw = canonicalize(statement)
    return raw


def _repo_attestation(signer):
    return attest_contract(
        REPO, producer_model="p", gate_model="g", signer=signer, deterministic_coverage="1/1"
    )


def _pad_bit_flip(b64_text: str) -> str:
    """Return a DIFFERENT base64 text decoding to the SAME bytes (ignored
    pad bits), or raise if the text is already canonical."""
    data = base64.b64decode(b64_text)
    head = b64_text.rstrip("=")
    pad = b64_text[len(head) :]
    for ch in _ALPHABET:
        candidate = head[:-1] + ch + pad
        if candidate == b64_text:
            continue
        try:
            if base64.b64decode(candidate, validate=True) == data:
                return candidate
        except binascii.Error:
            continue
    raise AssertionError(f"no pad-bit flip exists for {b64_text!r}")


def _roundtrip_verifies(envelope: dict, key: Key) -> dict:
    """Round-trip proof: dict -> JSON text -> dict -> verify -> same payload.

    Also proves the verifier never mutates its input: the reloaded dict must
    compare equal to the envelope we started from.
    """
    reloaded = json.loads(json.dumps(envelope))
    payload = verify_attestation(reloaded, public_key=key)
    assert reloaded == envelope
    return payload


def _root_with_spec(tmp_path) -> Path:
    (tmp_path / ".zft" / "specs").mkdir(parents=True)
    (tmp_path / ".zft" / "specs" / "a.json").write_text('{"clause": "a"}')
    return tmp_path


# --------------------------------------------------------------------------
# KEY class: rotated / foreign keys, keyid splicing


def test_key_rotated_key_rejects_old_envelope():
    """KEY-1: envelope signed by retired key v1, verifier holds rotated-in v2."""
    v1, v2 = CryptoSigner.generate_ed25519(), CryptoSigner.generate_ed25519()
    att = _repo_attestation(v1)
    with pytest.raises(SignatureVerificationError):
        verify_attestation(att, public_key=v2.public_key)
    _roundtrip_verifies(att, v1.public_key)  # stateless: v1 still verifies


def test_key_rotated_key_rejects_new_envelope_with_old_key():
    """KEY-2: after rotation the new envelope must fail under the retired key."""
    v1, v2 = CryptoSigner.generate_ed25519(), CryptoSigner.generate_ed25519()
    att = _repo_attestation(v2)
    with pytest.raises(SignatureVerificationError):
        verify_attestation(att, public_key=v1.public_key)
    _roundtrip_verifies(att, v2.public_key)


def test_key_forged_keyid_splice():
    """KEY-3: attacker signature bytes carrying the VERIFIER's keyid."""
    victim, attacker = (CryptoSigner.generate_ed25519(), CryptoSigner.generate_ed25519())
    forged = _signed_envelope(b'{"evil": true}', attacker)
    forged["signatures"][0]["keyid"] = victim.public_key.keyid
    with pytest.raises(SignatureVerificationError):
        verify_attestation(forged, public_key=victim.public_key)


def test_key_foreign_envelope_unknown_keyid():
    """KEY-4: envelope signed by an attacker key, verified against our key."""
    ours, attacker = (CryptoSigner.generate_ed25519(), CryptoSigner.generate_ed25519())
    foreign = _signed_envelope(_statement_bytes(), attacker)
    with pytest.raises(SignatureVerificationError):
        verify_attestation(foreign, public_key=ours.public_key)


def test_key_duplicate_keyid_entries_rejected():
    """KEY-5: two signature entries with one keyid — DSSE requires uniqueness."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    entry = att["signatures"][0]
    # distinct dicts: from_dict consumes entries in place, so sharing one
    # object would die on a missing 'sig' key before the duplicate check
    att["signatures"] = [dict(entry), dict(entry)]
    with pytest.raises(EnvelopeFormatError, match="[Mm]ultiple signatures"):
        verify_attestation(att, public_key=signer.public_key)


def test_key_bogus_key_objects_rejected():
    """KEY-6: non-Key and keyid-less keys never reach the crypto layer."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    with pytest.raises(KeyValidationError):
        verify_attestation(att, public_key="not-a-key")
    with pytest.raises(KeyValidationError, match="no keyid"):
        verify_attestation(att, public_key=_KeyidLessKey(signer.public_key))


class _KeyidLessKey(Key):
    """A real securesystemslib Key whose keyid was lost in storage."""

    def __init__(self, inner: Key):
        super().__init__(keyid="", keytype=inner.keytype, scheme=inner.scheme, keyval=inner.keyval)

    @classmethod
    def from_dict(cls, keyid: str, key_dict: dict) -> "_KeyidLessKey":
        raise NotImplementedError

    def to_dict(self) -> dict:
        return {"keytype": self.keytype, "scheme": self.scheme, "keyval": self.keyval}

    def verify_signature(self, signature, data) -> None:
        raise NotImplementedError


def test_key_pubkey_file_roundtrip():
    """KEY-7 (round trip): CLI --key-in flow — pub key dict + keyid on disk,
    Key.from_dict, verify. The exact serialization the attest CLI writes."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    pub = signer.public_key
    key_file = json.dumps({**pub.to_dict(), "keyid": pub.keyid})
    # exactly the CLI --key-in flow: pop the stored keyid, pass it separately
    key_data = json.loads(key_file)
    keyid = key_data.pop("keyid")
    restored = Key.from_dict(keyid=keyid, key_dict=key_data)
    assert restored.keyid == pub.keyid
    payload = verify_attestation(json.loads(json.dumps(att)), public_key=restored)
    assert payload["predicateType"].endswith("TraceManifest/v1")


# --------------------------------------------------------------------------
# KEY class (policy): rotation chains, validity windows, revocation, pinning
# (attest.keys — the revocation/expiry/pinning half of review H-1, L-5)


def test_key_rotation_chain_cross_pairs():
    """KEY-8: three-generation rotation — every envelope verifies only under
    its own generation's key; the newest key is not a master key, and no
    generation needs knowledge of any other (stateless, history-free)."""
    v1, v2, v3 = (CryptoSigner.generate_ed25519() for _ in range(3))
    envs = [_repo_attestation(s) for s in (v1, v2, v3)]
    for signer, env in zip((v1, v2, v3), envs):
        _roundtrip_verifies(env, signer.public_key)
    for i, env in enumerate(envs):
        for j, other in enumerate((v1, v2, v3)):
            if i == j:
                continue
            with pytest.raises(SignatureVerificationError):
                verify_attestation(env, public_key=other.public_key)


def test_key_expired_key_refused_before_crypto():
    """KEY-9: an expired key is refused even though the signature is genuinely
    valid — policy gates fire before the crypto layer (frozen `now`)."""
    signer = CryptoSigner.generate_ed25519()
    doc = _doc(signer, expires="2026-09-01T00:00:00Z")
    att = _repo_attestation(signer)
    with pytest.raises(KeyValidationError, match="expired at"):
        verify_attestation(att, key_document=doc,
                           now=_FROZEN + timedelta(days=1))
    _roundtrip_verifies(att, signer.public_key)  # bare crypto path unaffected


def test_key_not_yet_valid_key_refused():
    """KEY-10: a key published ahead of its validity window is refused."""
    signer = CryptoSigner.generate_ed25519()
    doc = _doc(signer, not_before="2026-09-07T00:00:00Z")
    att = _repo_attestation(signer)
    with pytest.raises(KeyValidationError, match="not valid before"):
        verify_attestation(att, key_document=doc, now=_FROZEN)


def test_key_revoked_key_refused_despite_valid_signature():
    """KEY-11: revocation is an explicit operator decision and outranks a
    perfectly good signature — the whole point of revoking after a leak."""
    signer = CryptoSigner.generate_ed25519()
    doc = _doc(signer, revoked=True)
    att = _repo_attestation(signer)
    with pytest.raises(KeyValidationError, match="revoked"):
        verify_attestation(att, key_document=doc, now=_FROZEN)
    _roundtrip_verifies(att, signer.public_key)


def test_key_validity_window_is_half_open():
    """KEY-12: window edges — not_before inclusive, expires exclusive."""
    signer = CryptoSigner.generate_ed25519()
    doc = _doc(signer, not_before="2026-09-06T00:00:00Z",
               expires="2026-09-06T12:00:00Z")
    att = _repo_attestation(signer)
    verify_attestation(att, key_document=doc,
                       now=datetime(2026, 9, 6, 0, 0, tzinfo=timezone.utc))  # == not_before
    verify_attestation(att, key_document=doc,
                       now=_FROZEN - timedelta(microseconds=1))  # just inside
    with pytest.raises(KeyValidationError, match="not valid before"):
        verify_attestation(att, key_document=doc,
                           now=_FROZEN - timedelta(days=1))  # before the window
    with pytest.raises(KeyValidationError, match="expired at"):
        verify_attestation(att, key_document=doc, now=_FROZEN)  # == expires: closed


def test_key_pin_detects_substituted_key_file():
    """KEY-13: --expect-keyid pinning — a wholesale-substituted (otherwise
    perfectly valid) key file becomes a typed failure before any crypto.
    Un-pinned substitution remains undetectable by design (risk R2)."""
    honest, attacker = (CryptoSigner.generate_ed25519(), CryptoSigner.generate_ed25519())
    doc = _doc(attacker)  # attacker swapped the published key file wholesale
    att = _repo_attestation(attacker)  # signature matches the attacker's key
    with pytest.raises(KeyValidationError, match="keyid pin mismatch"):
        verify_attestation(att, key_document=doc,
                           expect_keyid=honest.public_key.keyid)
    verify_attestation(att, key_document=doc,
                       expect_keyid=attacker.public_key.keyid)  # honest pin passes


def test_key_document_and_public_key_are_exclusive():
    """KEY-14: key_document and public_key are mutually exclusive — ambiguity
    about which key (and whose policy) governs is a typed error."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    with pytest.raises(KeyValidationError, match="not both"):
        verify_attestation(att, public_key=signer.public_key,
                           key_document=_doc(signer))


@pytest.mark.parametrize("mutate,match", [
    (lambda b: {**b, "expire": "2026-01-01T00:00:00Z"}, "unknown key file field"),
    (lambda b: {**b, "revoked": "yes"}, "'revoked' must be a bool"),
    (lambda b: {**b, "expires": "2026-01-01 00:00:00"}, "UTC offset"),
    (lambda b: {**b, "expires": "not-a-timestamp"}, "RFC 3339"),
    (lambda b: {k: v for k, v in b.items() if k != "keyid"}, "usable 'keyid'"),
    (lambda b: {**b, "keytype": "rusty"}, "unusable verification key"),
    (lambda b: [b], "JSON object"),
])
def test_key_malformed_documents_rejected_at_load(mutate, match):
    """KEY-15: malformed key documents fail at load, typed — including the
    typo'd 'expire' field (a policy typo must never silently disable policy)
    and offset-less timestamps (an ambiguous window fails closed)."""
    signer = CryptoSigner.generate_ed25519()
    pub = signer.public_key
    base = {**pub.to_dict(), "keyid": pub.keyid}
    with pytest.raises(KeyValidationError, match=match):
        KeyDocument.from_dict(mutate(base))


def test_key_substrate_escape_mapped_typed(monkeypatch):
    """KEY-16 (review L-3): a substrate failure outside the mapped exception
    set still leaves the verify boundary typed — never a bare Exception."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)

    def boom(self, keys, threshold):
        raise RuntimeError("crypto backend detonated")

    monkeypatch.setattr(Envelope, "verify", boom)
    with pytest.raises(SignatureVerificationError, match="verification layer failed"):
        verify_attestation(att, public_key=signer.public_key)


# --------------------------------------------------------------------------
# TRUNC class: truncated payloads, signatures, files


def _truncated_rejection(signer, mutate, exc, match):
    att = _repo_attestation(signer)
    broken = mutate(json.loads(json.dumps(att)))
    with pytest.raises(exc, match=match):
        verify_attestation(broken, public_key=signer.public_key)
    _roundtrip_verifies(att, signer.public_key)  # stateless verifier


def test_trunc_payload_cut_mid_alphabet():
    """TRUNC-1: payload cut mid-alphabet breaks base64 padding."""
    signer = CryptoSigner.generate_ed25519()
    _truncated_rejection(
        signer, lambda a: {**a, "payload": a["payload"][:-5]}, EnvelopeFormatError, "base64"
    )


def test_trunc_payload_cut_aligned():
    """TRUNC-2: an aligned cut keeps base64 valid — the truncated payload is
    then caught by the PAE-bound signature gate (verify runs before any JSON
    decoding), not by the payload decoder."""
    signer = CryptoSigner.generate_ed25519()
    _truncated_rejection(
        signer,
        lambda a: {**a, "payload": a["payload"][:-4]},
        SignatureVerificationError,
        "verification failed",
    )


def test_trunc_signature_cut():
    """TRUNC-3: truncated signature bytes."""
    signer = CryptoSigner.generate_ed25519()
    _truncated_rejection(
        signer,
        lambda a: {
            **a,
            "signatures": [{**a["signatures"][0], "sig": a["signatures"][0]["sig"][:-2]}],
        },
        EnvelopeFormatError,
        "base64",
    )


def test_trunc_attest_file_truncated_on_disk(tmp_path):
    """TRUNC-4: truncated attest.json is refused by the export path."""
    signer = CryptoSigner.generate_ed25519()
    root = _attested_root(tmp_path, signer, envelope=_repo_attestation(signer))
    (root / ".zft" / "attest.json").write_text(
        (root / ".zft" / "attest.json").read_text()[:-20]
    )
    with pytest.raises(EnvelopeFormatError, match="not valid JSON"):
        export_matrix(root)


def test_trunc_non_dict_signature_entry():
    """TRUNC-5: a string where a signature object belongs."""
    signer = CryptoSigner.generate_ed25519()
    _truncated_rejection(
        signer,
        lambda a: {**a, "signatures": ["nope"]},
        EnvelopeFormatError,
        "malformed DSSE envelope",
    )


# --------------------------------------------------------------------------
# CANON class: wrong canonicalization


def test_canon_reserialized_payload_breaks_signature():
    """CANON-1: payload re-serialized with non-canonical JSON is new bytes —
    the stale signature must fail (typed, not a bare Exception)."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    raw = base64.b64decode(att["payload"])
    data = json.loads(raw)
    reserialized = json.dumps(data).encode()  # not RFC 8785: spaces, key order
    assert reserialized != raw
    att["payload"] = _b64(reserialized)
    with pytest.raises(SignatureVerificationError):
        verify_attestation(att, public_key=signer.public_key)


def test_canon_payload_base64_pad_bits_rejected():
    """CANON-2: payload b64 with non-zero ignored pad bits decodes to the
    SAME bytes — a byte-different envelope that used to verify. Canonical
    base64 enforcement must reject it at parse time."""
    signer = CryptoSigner.generate_ed25519()
    original = _signed_envelope(_statement_bytes_with_pad_bits(), signer)
    att = {**original, "payload": _pad_bit_flip(original["payload"])}
    with pytest.raises(EnvelopeFormatError, match="canonical base64"):
        verify_attestation(att, public_key=signer.public_key)
    _roundtrip_verifies(original, signer.public_key)  # original untouched


def test_canon_signature_base64_pad_bits_rejected():
    """CANON-3: same malleability on signatures[].sig — envelope bytes change
    while the signature stays the same; replay bookkeeping by envelope
    identity requires this to be rejected, not silently accepted."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    entry = att["signatures"][0]
    att["signatures"] = [{**entry, "sig": _pad_bit_flip(entry["sig"])}]
    with pytest.raises(EnvelopeFormatError, match="canonical base64"):
        verify_attestation(att, public_key=signer.public_key)


def test_canon_foreign_noncanonical_payload_still_verifies():
    """CANON-4 (accepted): a foreign envelope whose payload is valid JSON but
    NOT RFC 8785 canonical verifies byte-faithfully — DSSE signatures cover
    the actual payload bytes, and we never re-canonicalize on verify."""
    signer = CryptoSigner.generate_ed25519()
    raw = (
        b'{\n  "_type": "https://in-toto.io/Statement/v1",\n'
        b'  "subject": [{"digest": {"sha256": "' + b"d" * 64 + b'"}'
        b', "name": "clause:x.json"}],\n'
        b'  "predicateType": "https://example.com/pred/v1",\n'
        b'  "predicate": {"z": 1, "a": 2}\n}'
    )
    assert canonicalize(json.loads(raw)) != raw
    att = _signed_envelope(raw, signer)
    payload = _roundtrip_verifies(att, signer.public_key)
    assert payload["predicate"] == {"z": 1, "a": 2}


def test_canon_signing_path_is_jcs_fixed_point():
    """CANON-5: our own signing always emits RFC 8785 bytes (never OLPC
    canonical JSON — which orders by code point, not UTF-16 units)."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    raw = base64.b64decode(att["payload"])
    assert canonicalize(json.loads(raw)) == raw


_URLSAFE = str.maketrans("+/", "-_")


def test_canon_urlsafe_alphabet_rejected():
    """CANON-6: urlsafe re-render of payload or signature — same signed
    content, textually different envelope bytes (review M-4: G5's byte
    equality requires the standard alphabet only). The gate fires at parse
    time, before any crypto, so the fake short signature below is fine."""
    signer = CryptoSigner.generate_ed25519()
    # statement payload whose canonical base64 contains both '+' and '/'
    payload = canonicalize(
        {
            "_type": STATEMENT_TYPE,
            "predicateType": "https://example.com/pred/v1",
            "subject": [{"name": "clause:" + "Ϗ" * 8, "digest": {"sha256": "d" * 64}}],
            "predicate": {},
        }
    )
    att = _signed_envelope(payload, signer)
    assert "+" in att["payload"] and "/" in att["payload"]

    payload_urlsafe = {**att, "payload": att["payload"].translate(_URLSAFE)}
    with pytest.raises(EnvelopeFormatError, match="canonical base64"):
        verify_attestation(payload_urlsafe, public_key=signer.public_key)

    sig_urlsafe = {**att, "signatures": [{"keyid": att["signatures"][0]["keyid"],
                                          "sig": "+///".translate(_URLSAFE)}]}
    with pytest.raises(EnvelopeFormatError, match="canonical base64"):
        verify_attestation(sig_urlsafe, public_key=signer.public_key)

    _roundtrip_verifies(att, signer.public_key)  # untouched original verifies


# --------------------------------------------------------------------------
# REPLAY class: grafted signatures, swaps, store-drift replay


def test_replay_exact_envelope_verifies_twice():
    """REPLAY-1 (accepted): replaying the identical envelope against the
    unchanged store verifies — signatures carry no expiry; drift is caught
    via expected_subjects (REPLAY-2), not freshness."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    _roundtrip_verifies(att, signer.public_key)
    _roundtrip_verifies(att, signer.public_key)


def test_replay_against_changed_store():
    """REPLAY-2: an old envelope replayed after the store changed is caught
    by the subject-digest gate, not the signature gate."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    with pytest.raises(SubjectMismatchError):
        verify_attestation(att, expected_subjects={}, public_key=signer.public_key)


def test_replay_mismatch_names_drifted_clause(tmp_path):
    """REPLAY-2 diagnostic: the rejection is clause-IDed — it names the
    drifted clause and shows attested vs store digest prefixes, so a red
    CI log says WHICH clause was tampered, not merely that something was."""
    root = _root_with_spec(tmp_path)
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(root, producer_model="p", gate_model="g", signer=signer)
    (root / ".zft" / "specs" / "a.json").write_text('{"clause": "a drifted"}')
    with pytest.raises(SubjectMismatchError) as excinfo:
        verify_attestation(
            att,
            expected_subjects={s["name"]: s["digest"]["sha256"]
                               for s in clause_subjects(root)},
            public_key=signer.public_key)
    msg = str(excinfo.value)
    assert "clause:a.json (attested " in msg, msg
    assert ", store " in msg, msg
    _roundtrip_verifies(att, signer.public_key)


def test_replay_store_gained_clause_names_it(tmp_path):
    """Subject-count mismatch, store side: a clause added after signing is
    named by the rejection — dict inequality alone never said which side
    grew, so the count-mismatch case was indistinguishable from drift."""
    root = _root_with_spec(tmp_path)
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(root, producer_model="p", gate_model="g", signer=signer)
    (root / ".zft" / "specs" / "b.json").write_text('{"clause": "b"}')
    with pytest.raises(SubjectMismatchError) as excinfo:
        verify_attestation(
            att,
            expected_subjects={s["name"]: s["digest"]["sha256"]
                               for s in clause_subjects(root)},
            public_key=signer.public_key)
    msg = str(excinfo.value)
    assert "clause:b.json" in msg, msg
    assert "subject-count mismatch" in msg and "not attested" in msg, msg
    _roundtrip_verifies(att, signer.public_key)


def test_replay_store_lost_clause_names_it(tmp_path):
    """Subject-count mismatch, envelope side: a clause deleted from the
    store after signing is named as attested-but-gone."""
    root = _root_with_spec(tmp_path)
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(root, producer_model="p", gate_model="g", signer=signer)
    (root / ".zft" / "specs" / "a.json").unlink()
    with pytest.raises(SubjectMismatchError) as excinfo:
        verify_attestation(
            att,
            expected_subjects={s["name"]: s["digest"]["sha256"]
                               for s in clause_subjects(root)},
            public_key=signer.public_key)
    msg = str(excinfo.value)
    assert "clause:a.json" in msg, msg
    assert "attested but not in store" in msg, msg
    _roundtrip_verifies(att, signer.public_key)


def test_replay_signature_graft_across_envelopes():
    """REPLAY-3: a valid (keyid, sig) pair grafted from envelope A onto
    envelope B fails — PAE binds each signature to A's exact bytes."""
    signer = CryptoSigner.generate_ed25519()
    env_a = _signed_envelope(_statement_bytes(), signer)
    payload_b = canonicalize(
        {
            "_type": STATEMENT_TYPE,
            "predicateType": "https://example.com/pred/v1",
            "subject": [{"name": "clause:OTHER.json", "digest": {"sha256": "e" * 64}}],
            "predicate": {},
        }
    )
    env_b = _signed_envelope(payload_b, signer)
    grafted = {**env_b, "signatures": env_a["signatures"]}
    with pytest.raises(SignatureVerificationError):
        verify_attestation(grafted, public_key=signer.public_key)
    _roundtrip_verifies(env_b, signer.public_key)  # B unharmed


def test_replay_payload_swap_between_envelopes():
    """REPLAY-4: envelope B's wrapper around envelope A's payload."""
    signer = CryptoSigner.generate_ed25519()
    env_a = _signed_envelope(_statement_bytes(), signer)
    env_b = _signed_envelope(canonicalize({"other": True}), signer)
    swapped = {**env_b, "payload": env_a["payload"]}
    with pytest.raises(SignatureVerificationError):
        verify_attestation(swapped, public_key=signer.public_key)


def test_replay_payload_type_swap_rejected_before_crypto():
    """REPLAY-5: payloadType is PAE-bound; the typed gate fires before any
    signature work."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    with pytest.raises(EnvelopeFormatError, match="unsupported payloadType"):
        verify_attestation({**att, "payloadType": "application/json"}, public_key=signer.public_key)


def test_replay_cross_root_replay_via_export_flow(tmp_path):
    """REPLAY-6: the REPO envelope copied into another root fails that root's
    verify (the CLI `verify` flow: expected_subjects from the local store)."""
    signer = CryptoSigner.generate_ed25519()
    att = _repo_attestation(signer)
    expected = {
        s["name"]: s["digest"]["sha256"] for s in clause_subjects(_root_with_spec(tmp_path))
    }
    with pytest.raises(SubjectMismatchError):
        verify_attestation(att, expected_subjects=expected, public_key=signer.public_key)


def test_replay_rotation_roundtrip():
    """REPLAY-7 (round trip): key rotation end to end — the old envelope
    stays verifiable under the old key, the new under the new, and every
    cross pair fails."""
    v1, v2 = CryptoSigner.generate_ed25519(), CryptoSigner.generate_ed25519()
    old_env, new_env = _repo_attestation(v1), _repo_attestation(v2)
    assert _roundtrip_verifies(old_env, v1.public_key) is not None
    assert _roundtrip_verifies(new_env, v2.public_key) is not None
    with pytest.raises(SignatureVerificationError):
        verify_attestation(old_env, public_key=v2.public_key)
    with pytest.raises(SignatureVerificationError):
        verify_attestation(new_env, public_key=v1.public_key)


# --------------------------------------------------------------------------
# EXPORT class: the export surface over .zft/attest.json


def _attested_root(tmp_path, signer, envelope=None):
    (tmp_path / ".zft").mkdir()
    (tmp_path / ".zft" / "attest.json").write_text(
        json.dumps(envelope if envelope is not None else _repo_attestation(signer))
    )
    return tmp_path


def test_export_dsse_roundtrip_matches_envelope(tmp_path):
    """EXPORT-1 (round trip): attest -> file -> export dsse -> the same
    envelope, and it still verifies with the signing key."""
    signer = CryptoSigner.generate_ed25519()
    envelope = _repo_attestation(signer)
    root = _attested_root(tmp_path, signer, envelope)
    exported = export_envelope(root)
    assert exported == envelope == load_envelope(root)
    payload = verify_attestation(exported, public_key=signer.public_key)
    assert payload["_type"] == STATEMENT_TYPE


def test_export_matrix_refuses_wrong_payload_type(tmp_path):
    """EXPORT-2: matrix/summary derive from TraceManifest attestations only —
    a structurally valid envelope with a foreign payloadType is refused."""
    signer = CryptoSigner.generate_ed25519()
    envelope = _signed_envelope(_statement_bytes(), signer, payload_type="application/json")
    root = _attested_root(tmp_path, signer, envelope)
    with pytest.raises(EnvelopeFormatError, match="unsupported payloadType"):
        export_matrix(root)
    with pytest.raises(EnvelopeFormatError, match="unsupported payloadType"):
        export_summary(root)


def test_export_matrix_refuses_scalar_coverage(tmp_path):
    """EXPORT-3: predicate.coverage must be an object."""
    signer = CryptoSigner.generate_ed25519()
    payload = json.loads(base64.b64decode(_repo_attestation(signer)["payload"]))
    payload["predicate"]["coverage"] = "24/24"  # scalar, not an object
    envelope = _signed_envelope(canonicalize(payload), signer)
    root = _attested_root(tmp_path, signer, envelope)
    with pytest.raises(EnvelopeFormatError, match="'predicate.coverage' must be an object"):
        export_matrix(root)


def test_export_summary_refuses_non_bool_model_dependent(tmp_path):
    """EXPORT-4: predicate.model_dependent must be a bool."""
    signer = CryptoSigner.generate_ed25519()
    payload = json.loads(base64.b64decode(_repo_attestation(signer)["payload"]))
    payload["predicate"]["model_dependent"] = "no"
    envelope = _signed_envelope(canonicalize(payload), signer)
    root = _attested_root(tmp_path, signer, envelope)
    with pytest.raises(EnvelopeFormatError, match="'predicate.model_dependent' must be a bool"):
        export_summary(root)


def test_export_dsse_is_structural_only(tmp_path):
    """EXPORT-5 (accepted, documented): export dsse validates STRUCTURE only —
    no key exists at export time; signature checking is the explicit
    `zft verify` step. A well-formed envelope with an invalid
    signature still exports."""
    signer, other = (CryptoSigner.generate_ed25519(), CryptoSigner.generate_ed25519())
    envelope = _repo_attestation(signer)
    root = _attested_root(tmp_path, signer, envelope)
    assert export_envelope(root) == envelope  # structure fine, export fine
    with pytest.raises(SignatureVerificationError):
        verify_attestation(export_envelope(root), public_key=other.public_key)


def test_export_refuses_truncated_payload_file(tmp_path):
    """EXPORT-6: export never hands on a structurally broken envelope."""
    signer = CryptoSigner.generate_ed25519()
    envelope = _repo_attestation(signer)
    envelope["payload"] = envelope["payload"][:-7]
    root = _attested_root(tmp_path, signer, envelope)
    with pytest.raises(EnvelopeFormatError, match="base64"):
        export_envelope(root)
    with pytest.raises(EnvelopeFormatError):
        export_matrix(root)
    with pytest.raises(EnvelopeFormatError):
        export_summary(root)
