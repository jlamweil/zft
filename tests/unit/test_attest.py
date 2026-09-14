"""C-28: DSSE attestation binding REAL clause hashes (securesystemslib substrate).

V8 fixtures: sign → verify untampered → tampered clause digest detected.
Plus malformed-envelope guards: typed errors, all format problems reported.
Mock cryptographic signers (deterministic keyed-digest Signer/Key subclasses)
prove the attestation seam is crypto-implementation-agnostic, and signed
invalid payloads pin the decode/validate error paths end to end.
"""
import base64
import hashlib
import json
from pathlib import Path

import pytest
from securesystemslib.dsse import Envelope
from securesystemslib.exceptions import UnverifiedSignatureError
from securesystemslib.signer import CryptoSigner, Key, Signature, Signer

from traceagent.attest.dsse import (
    AttestationError,
    EnvelopeFormatError,
    KeyValidationError,
    SignatureVerificationError,
    SubjectMismatchError,
    attest_contract,
    parse_payload,
    verify_attestation,
)
from traceagent.attest.jcs import canonicalize

REPO = Path(__file__).resolve().parents[2]


def _live_due(root: Path) -> int:
    """Milestone-scoped due clause count, mirroring gates.l2 logic."""
    from traceagent.gates.l2 import _current_milestone
    from traceagent.spec.store import Store, load_contract

    nodes = Store.load(root).nodes
    deferred = load_contract(root).get("meta", {}).get("target_milestone", {})
    milestone = _current_milestone(root)
    return len({a for a in nodes if deferred.get(a, milestone) <= milestone})


# @trace("ATT-SIGNED-ACCEPTANCE")
def test_sign_and_verify_real_contract():
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(REPO, producer_model="m", gate_model="g", signer=signer)
    payload = verify_attestation(att, public_key=signer.public_key)
    assert payload["predicateType"] == "https://traceagent.dev/attestations/TraceManifest/v1"
    # bindings grow as we bind more tests; assert format + due bounds, not a fixed count
    covered, due = payload["predicate"]["coverage"]["clauses_covered"].split("/")
    live_due = _live_due(REPO)
    assert int(covered) <= int(due) == live_due


def test_payload_is_rfc8785_canonical():
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(REPO, producer_model="m", gate_model="g", signer=signer)
    raw = base64.urlsafe_b64decode(att["payload"] + "=" * (-len(att["payload"]) % 4))
    assert canonicalize(json.loads(raw)) == raw


def test_uncanonicalizable_payload_rejected_typed_and_unsigned():
    # Lone surrogates arrive via surrogateescaped argv or escaped \ud800 in
    # contract JSON and cannot round-trip UTF-8; JCS must reject them before
    # signing, as AttestationError (not the bare ValueError from jcs).
    with pytest.raises(AttestationError, match="RFC 8785"):
        attest_contract(REPO, producer_model="p\ud800", gate_model="g")


def test_tampered_clause_detected():
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(REPO, producer_model="m", gate_model="g", signer=signer)
    att["payload"] = _tamper(att["payload"])
    with pytest.raises(Exception):
        verify_attestation(att, public_key=signer.public_key)


def _tamper(b64_payload: str) -> str:
    import base64

    raw = base64.urlsafe_b64decode(b64_payload + "==")
    data = json.loads(raw)
    subj = data["subject"][0]
    subj["digest"]["sha256"] = hashlib.sha256(b"tampered").hexdigest()
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def test_wrong_key_fails_verification():
    signer = CryptoSigner.generate_ed25519()
    other = CryptoSigner.generate_ed25519()
    att = attest_contract(REPO, producer_model="m", gate_model="g", signer=signer)
    with pytest.raises(SignatureVerificationError):
        verify_attestation(att, public_key=other.public_key)


def test_subject_mismatch_detected_after_verify():
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(REPO, producer_model="m", gate_model="g", signer=signer)
    with pytest.raises(SubjectMismatchError):
        verify_attestation(att, expected_subjects={}, public_key=signer.public_key)


def test_missing_or_bogus_key_rejected():
    att = attest_contract(REPO, producer_model="m", gate_model="g")
    with pytest.raises(KeyValidationError):
        verify_attestation(att, public_key=None)
    with pytest.raises(KeyValidationError):
        verify_attestation(att, public_key="not-a-key")


def test_malformed_envelopes_raise_typed_format_errors():
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(REPO, producer_model="m", gate_model="g", signer=signer)
    broken_envelopes = [
        {},
        {**att, "payload": None},
        {**att, "payloadType": ""},
        {**att, "signatures": {}},
        {**att, "payload": "!!!not-base64!!!"},
        [att],
    ]
    for broken in broken_envelopes:
        with pytest.raises(EnvelopeFormatError):
            verify_attestation(broken, public_key=signer.public_key)


def test_all_format_problems_reported_at_once():
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(REPO, producer_model="m", gate_model="g", signer=signer)
    broken = {**att, "payloadType": "", "signatures": []}
    with pytest.raises(EnvelopeFormatError) as excinfo:
        verify_attestation(broken, public_key=signer.public_key)
    assert "payloadType" in str(excinfo.value)
    assert "signatures" in str(excinfo.value)


def test_signed_but_unparseable_payload_detected():
    signer = CryptoSigner.generate_ed25519()
    envelope = Envelope(payload=b"not-json{", payload_type="application/vnd.in-toto+json",
                        signatures={})
    envelope.sign(signer)
    with pytest.raises(EnvelopeFormatError, match="not valid JSON"):
        verify_attestation(envelope.to_dict(), public_key=signer.public_key)


# --- mock cryptographic signing keys ----------------------------------------
# A deterministic Signer/Key pair: the "signature" is a keyed SHA-256 digest.
# No asymmetric crypto involved — proves attest_contract/verify_attestation
# depend only on the securesystemslib Signer/Key seam, never on ed25519.

class MockKey(Key):
    """Verification half: accepts only digests sealed with our secret."""

    def __init__(self, keyid: str, secret: str):
        self._keyid, self._secret = keyid, secret

    @property
    def keyid(self) -> str:
        return self._keyid

    def to_dict(self) -> dict:
        return {"keyid": self._keyid, "keytype": "mock", "scheme": "mock",
                "public_key_material": self._secret}

    @classmethod
    def from_dict(cls, keyid: str, key_dict: dict) -> "MockKey":
        return cls(keyid, key_dict["public_key_material"])

    def _seal(self, data: bytes) -> str:
        return hashlib.sha256(self._secret.encode() + data).hexdigest()

    def verify_signature(self, signature: Signature, data: bytes) -> None:
        if signature.signature != self._seal(data):
            raise UnverifiedSignatureError(f"mock key {self._keyid} mismatch")


class MockSigner(Signer):
    """Signing half of the mock key pair."""

    def __init__(self, keyid: str, secret: str):
        self._key = MockKey(keyid, secret)

    def sign(self, payload: bytes) -> Signature:
        return Signature(self._key.keyid, self._key._seal(payload))

    @property
    def public_key(self) -> MockKey:
        return self._key

    @classmethod
    def from_priv_key_uri(cls, priv_key_uri, public_key, secrets_handler=None):
        raise NotImplementedError("mock signer supports no key URIs")


KID_A = "a" * 64  # securesystemslib keyids are sha256 hex strings
KID_B = "b" * 64


def _mock_signer_a() -> MockSigner:
    return MockSigner(KID_A, "secret-A")


def _signed_envelope(payload_bytes: bytes, signer: Signer,
                     payload_type: str = "application/vnd.in-toto+json") -> dict:
    envelope = Envelope(payload=payload_bytes, payload_type=payload_type,
                        signatures={})
    envelope.sign(signer)
    return envelope.to_dict()


# @trace("ATT-SIGNED-ACCEPTANCE")
def test_mock_signer_roundtrip_through_attest_contract():
    signer = _mock_signer_a()
    att = attest_contract(REPO, producer_model="p", gate_model="g", signer=signer,
                          deterministic_coverage="3/5")
    assert [s["keyid"] for s in att["signatures"]] == [KID_A]
    payload = verify_attestation(att, public_key=signer.public_key)
    assert payload["predicate"]["models"] == {"producer": "p", "gate": "g"}
    assert payload["predicate"]["coverage"]["clauses_covered"] == "3/5"


def test_mock_signer_with_wrong_secret_fails_verification():
    att = attest_contract(REPO, signer=_mock_signer_a(), deterministic_coverage="1/1")
    impostor = MockSigner(KID_B, "secret-B")
    with pytest.raises(SignatureVerificationError):
        verify_attestation(att, public_key=impostor.public_key)


def test_mock_and_real_signatures_coexist_threshold_one():
    signer = _mock_signer_a()
    att = attest_contract(REPO, signer=signer, deterministic_coverage="1/1")
    envelope = Envelope.from_dict(att)
    real = CryptoSigner.generate_ed25519()
    envelope.sign(real)
    co_signed = envelope.to_dict()
    assert len(co_signed["signatures"]) == 2
    # threshold 1: either key alone verifies the co-signed envelope
    assert verify_attestation(co_signed, public_key=signer.public_key)
    assert verify_attestation(co_signed, public_key=real.public_key)


def test_mock_key_without_keyid_rejected_before_verification():
    signer = _mock_signer_a()
    att = attest_contract(REPO, signer=signer, deterministic_coverage="1/1")
    with pytest.raises(KeyValidationError, match="no keyid"):
        verify_attestation(att, public_key=MockKey("", "secret-A"))


def test_mock_key_roundtrip_via_dict():
    restored = MockKey.from_dict(KID_A, MockKey(KID_A, "secret-A").to_dict())
    assert restored.keyid == KID_A
    att = attest_contract(REPO, signer=_mock_signer_a(), deterministic_coverage="1/1")
    payload = verify_attestation(att, public_key=restored)
    assert payload["predicateType"].endswith("TraceManifest/v1")


# --- signed-but-invalid payloads ---------------------------------------------

def test_signature_value_tampering_detected():
    signer = _mock_signer_a()
    att = attest_contract(REPO, signer=signer, deterministic_coverage="1/1")
    att["signatures"] = [{"keyid": KID_A, "sig": "AAAA"}]
    with pytest.raises(SignatureVerificationError):
        verify_attestation(att, public_key=signer.public_key)


def test_signed_non_object_payload_rejected():
    signer = _mock_signer_a()
    att = _signed_envelope(b"[1, 2]", signer)
    with pytest.raises(EnvelopeFormatError, match="payload must be a JSON object"):
        verify_attestation(att, public_key=signer.public_key)


def test_signed_non_utf8_payload_rejected():
    signer = _mock_signer_a()
    att = _signed_envelope(b"\xff\xfe\x00bad", signer)
    with pytest.raises(EnvelopeFormatError, match="not valid UTF-8"):
        verify_attestation(att, public_key=signer.public_key)


def test_signed_unsupported_payload_type_rejected():
    signer = _mock_signer_a()
    att = _signed_envelope(b"{}", signer, payload_type="application/json")
    with pytest.raises(EnvelopeFormatError, match="unsupported payloadType"):
        verify_attestation(att, public_key=signer.public_key)


def test_malformed_subject_entry_detected_after_verify():
    signer = _mock_signer_a()
    statement = {"_type": "https://in-toto.io/Statement/v1", "predicateType": "x",
                 "subject": [{"oops": 1}], "predicate": {}}
    att = _signed_envelope(canonicalize(statement), signer)
    with pytest.raises(EnvelopeFormatError, match="malformed subject entry"):
        verify_attestation(att, expected_subjects={}, public_key=signer.public_key)


def test_parse_payload_reports_every_statement_problem():
    signer = _mock_signer_a()
    statement = {"_type": "wrong", "subject": [], "predicateType": "", "predicate": "nope"}
    att = _signed_envelope(canonicalize(statement), signer)
    with pytest.raises(EnvelopeFormatError) as excinfo:
        parse_payload(att)
    message = str(excinfo.value)
    for fragment in ("'_type' must be", "'subject' must be a non-empty list",
                     "'predicateType' must be", "'predicate' must be an object"):
        assert fragment in message, fragment


def test_attest_contract_refuses_empty_store(tmp_path):
    with pytest.raises(AttestationError, match="nothing to attest"):
        attest_contract(tmp_path, signer=_mock_signer_a())


def test_predicate_records_model_dependence_honestly():
    # the attested predicate's model_dependent flag is derived from the two
    # identities — a producer != gate pair must never be marked dependent
    signer = CryptoSigner.generate_ed25519()
    distinct = verify_attestation(
        attest_contract(REPO, producer_model="m", gate_model="g", signer=signer),
        public_key=signer.public_key)
    same = verify_attestation(
        attest_contract(REPO, producer_model="m", gate_model="m", signer=signer),
        public_key=signer.public_key)
    assert distinct["predicate"]["model_dependent"] is False
    assert same["predicate"]["model_dependent"] is True
