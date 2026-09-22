"""Unit pins for the dsse seam families (kill shard, 2026-09-16 morning).

Scope: ALL suspect families of the attest-negotiate bar's dsse.py cut —
canonical base64 malleability, envelope/payload type renderings,
statement-problem message joins, gate-manifest self-check, contract
refusal/deferral/predicate shape, key-policy guard wordings, subject-
mismatch detail, and the deterministic-coverage milestone compare.
The typed-error messages are contract surface, so the anchors are
byte-exact (re.escape'd or full-equality on captured excinfo — a plain
substring match cannot kill XX-wrapped or end-appended message mutants)
where the wording is stable, and empirically probed (Python 3.12 floor)
where it comes from the stdlib.

Landed per family largest-first (killproof-dsse A/B per batch):
attest_contract -> verify_attestation -> _check_subjects ->
parse_envelope -> _deterministic_coverage -> _statement_problems ->
tail families (_canonical_base64, parse_payload, _check_gate_manifest,
_envelope_problems, decode_payload).
"""
import base64
import hashlib
import json
import re
from pathlib import Path

import pytest
from securesystemslib.dsse import Envelope
from securesystemslib.exceptions import UnverifiedSignatureError
from securesystemslib.signer import CryptoSigner, Key, Signature, Signer

from zft.attest.dsse import (
    PAYLOAD_TYPE,
    STATEMENT_TYPE,
    AttestationError,
    EnvelopeFormatError,
    KeyValidationError,
    SignatureVerificationError,
    SubjectMismatchError,
    _canonical_base64,
    _check_gate_manifest,
    _deterministic_coverage,
    _envelope_problems,
    _statement_problems,
    attest_contract,
    decode_payload,
    parse_envelope,
    parse_payload,
    verify_attestation,
)

# --- attest_contract: refusal path, contract-meta deferral, predicate shape ----

def _specs_root(tmp_path, contract=None, alias="ALIAS-B"):
    """Minimal attestable root: one clause spec, optionally a contract manifest."""
    specs = tmp_path / ".zft" / "specs"
    specs.mkdir(parents=True)
    (specs / "a.json").write_text(json.dumps({"alias": alias}))
    if contract is not None:
        contracts = tmp_path / ".zft" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "c.json").write_text(json.dumps(contract))
    return tmp_path


def _payload_of(att):
    return json.loads(base64.b64decode(att["payload"]))


def test_attest_contract_empty_root_refusal_names_the_specs_path(tmp_path):
    # the "nothing to attest" refusal renders the exact specs path it searched
    root = Path(tmp_path)
    with pytest.raises(AttestationError, match=re.escape(
            f"no clause specs found under {root / '.zft' / 'specs'} — nothing to attest")):
        attest_contract(root)


def test_attest_contract_deferred_reads_the_contract_meta(tmp_path):
    root = _specs_root(
        tmp_path, contract={"meta": {"target_milestone": {"ALIAS-B": "v1"}}})
    att = attest_contract(root, deterministic_coverage="0/1")
    assert _payload_of(att)["predicate"]["deferred"] == ["ALIAS-B"]


def test_attest_contract_deferred_defaults_to_empty_without_contract_meta(tmp_path):
    # load_contract succeeds but meta is absent: the get-chain defaults are
    # load-bearing (a None default crashes .get on None / sorted(None))
    root = _specs_root(tmp_path, contract={"other": 1})
    att = attest_contract(root, deterministic_coverage="0/1")
    assert _payload_of(att)["predicate"]["deferred"] == []


def test_attest_contract_predicate_shape_is_byte_stable(tmp_path):
    # empty deterministic_coverage must land on the "pending-L2" sentinel
    # (case-exact), and the predicate keys are contract surface
    root = _specs_root(tmp_path, contract={"meta": {}})
    att = attest_contract(root, deterministic_coverage="",
                          producer_model="m", gate_model="g")
    predicate = _payload_of(att)["predicate"]
    predicate.pop("gate_manifest")  # environment hashes, pinned elsewhere
    assert predicate == {
        "coverage": {"clauses_covered": "pending-L2"},
        "judge_excluded": [],
        "deferred": [],
        "models": {"producer": "m", "gate": "g"},
        "model_dependent": False,
    }


# --- verify_attestation: key-policy guards are byte-loud, in order -------------

class _MockKey(Key):
    """Mock verification key (test_attest.MockKey idiom; attribute keyid)."""

    def __init__(self, keyid: str, secret: str):
        self._secret = secret
        self._keyid = keyid
        self.keyid = keyid

    def to_dict(self) -> dict:
        return {"keyid": self._keyid, "keytype": "mock", "scheme": "mock",
                "public_key_material": self._secret}

    @classmethod
    def from_dict(cls, keyid: str, key_dict: dict) -> "_MockKey":
        return cls(keyid, key_dict["public_key_material"])

    def _seal(self, data: bytes) -> str:
        return hashlib.sha256(self._secret.encode() + data).hexdigest()

    def verify_signature(self, signature, data) -> None:
        if signature.signature != self._seal(data):
            raise UnverifiedSignatureError("mock key mismatch")


class _MockSigner(Signer):
    def __init__(self, keyid: str, secret: str):
        self._key = _MockKey(keyid, secret)

    def sign(self, payload: bytes) -> Signature:
        return Signature(self._key.keyid, self._key._seal(payload))

    @property
    def public_key(self) -> _MockKey:
        return self._key

    @classmethod
    def from_priv_key_uri(cls, priv_key_uri, public_key, secrets_handler=None):
        raise NotImplementedError("mock signer supports no key URIs")


_PIN_KID = "a" * 64


def _signed_envelope_dict(payload_bytes: bytes) -> dict:
    envelope = Envelope(payload=payload_bytes, payload_type=PAYLOAD_TYPE,
                        signatures={})
    envelope.sign(_MockSigner(_PIN_KID, "secret-A"))
    return envelope.to_dict()


def test_verify_rejects_key_document_and_public_key_together():
    # both key sources at once: the refusal names the unambiguity policy in
    # full — both of its lines are contract surface
    with pytest.raises(KeyValidationError, match=re.escape(
            "pass either public_key or key_document, not both — "
            "which key governs verification must be unambiguous")):
        verify_attestation({}, public_key=_MockKey(_PIN_KID, "secret-A"),
                           key_document=object())


def test_verify_requires_a_public_key():
    # full-equality assert: a XX-wrapped or re-cased refusal must fail the pin
    with pytest.raises(KeyValidationError) as excinfo:
        verify_attestation({})
    assert str(excinfo.value) == \
        "verify_attestation requires public_key (dev: signer.public_key)"


def test_verify_rejects_non_key_public_key_by_type_name():
    with pytest.raises(KeyValidationError, match=re.escape(
            "public_key must be a securesystemslib Key, got str")):
        verify_attestation({}, public_key="not-a-key")


def test_verify_rejects_key_with_empty_keyid():
    with pytest.raises(KeyValidationError) as excinfo:
        verify_attestation({}, public_key=_MockKey("", "secret-A"))
    assert str(excinfo.value) == "public_key carries no keyid"


def test_verify_rejects_key_without_keyid_attribute():
    # a Key instance that never set the keyid attribute: only the falsy
    # getattr default reaches the guard — a dropped default (two-arg getattr)
    # would AttributeError here, a truthy default would let the key slip
    # through to the substrate
    class _KeyWithoutKeyid(_MockKey):
        def __init__(self, keyid, secret):
            self._secret = secret
            self._keyid = keyid  # deliberately no self.keyid

    with pytest.raises(KeyValidationError, match=re.escape(
            "public_key carries no keyid")):
        verify_attestation({}, public_key=_KeyWithoutKeyid("k", "secret-A"))


def test_verify_wraps_substrate_escapes_with_the_type_name():
    # a verify_signature blowup that is not UnverifiedSignatureError must be
    # wrapped typed, naming the raising exception's type
    class _BlowupKey(_MockKey):
        def verify_signature(self, signature, data):
            raise RuntimeError("mock substrate blowup")

    att = _signed_envelope_dict(b"{}")
    with pytest.raises(SignatureVerificationError, match=re.escape(
            "signature verification layer failed: "
            "RuntimeError: mock substrate blowup")):
        verify_attestation(att, public_key=_BlowupKey(_PIN_KID, "secret-A"))


# --- _check_subjects: the mismatch detail is the contract ----------------------

_D1, _D2, _D3 = "1" * 64, "2" * 64, "3" * 64
_MISMATCH_PREFIX = "subject digests do not match the contract store: "


def _signed_subjects(subject) -> dict:
    return _signed_envelope_dict(json.dumps({"subject": subject}).encode())


def _verify_with(subject, expected):
    return verify_attestation(_signed_subjects(subject),
                              expected_subjects=expected,
                              public_key=_MockKey(_PIN_KID, "secret-A"))


def test_subject_mismatch_names_both_digest_prefixes_for_two_changed():
    # the 12-char digest prefixes are contract surface: a widened slice
    # renders a different 13th character; two changed entries also pin the
    # ", " joiner inside the changed part
    with pytest.raises(SubjectMismatchError, match=re.escape(
            _MISMATCH_PREFIX + "changed: n1 (attested "
            f"{_D2[:12]}…, store {_D1[:12]}…), n2 (attested "
            f"{_D3[:12]}…, store {_D2[:12]}…)")):
        _verify_with([{"name": "n1", "digest": {"sha256": _D2}},
                      {"name": "n2", "digest": {"sha256": _D3}}],
                     {"n1": _D1, "n2": _D2})


def test_subject_mismatch_with_only_missing_and_added_parts():
    # changed is empty here: the empty-part filters are load-bearing — a
    # truthy else-branch or an always-true condition would leak a "changed: "
    # (or "XXXX") part into the message
    with pytest.raises(SubjectMismatchError, match=re.escape(
            _MISMATCH_PREFIX + "attested but not in store: gone; "
            "in store but not attested (subject-count mismatch): added")):
        _verify_with([{"name": "gone", "digest": {"sha256": _D1}}],
                     {"added": _D1})


def test_subject_mismatch_with_changed_and_added_parts():
    # missing is empty here: its else-branch must stay silent, and the two
    # rendered parts pin the "; " joiner between parts
    with pytest.raises(SubjectMismatchError, match=re.escape(
            _MISMATCH_PREFIX + f"changed: n1 (attested {_D2[:12]}…, "
            f"store {_D1[:12]}…); in store but not attested "
            "(subject-count mismatch): added")):
        _verify_with([{"name": "n1", "digest": {"sha256": _D2}}],
                     {"n1": _D1, "added": _D1})


def test_subject_mismatch_with_changed_and_missing_parts():
    # added is empty here: its else-branch must stay silent — full-equality
    # assert, because an end-appended else-branch would survive a prefix match
    with pytest.raises(SubjectMismatchError) as excinfo:
        _verify_with([{"name": "n1", "digest": {"sha256": _D2}},
                      {"name": "gone", "digest": {"sha256": _D1}}],
                     {"n1": _D1})
    assert str(excinfo.value) == (
        _MISMATCH_PREFIX + f"changed: n1 (attested {_D2[:12]}…, "
        f"store {_D1[:12]}…); attested but not in store: gone")


def test_subject_mismatch_joins_two_missing_names_with_commas():
    with pytest.raises(SubjectMismatchError, match=re.escape(
            _MISMATCH_PREFIX + "attested but not in store: g1, g2; "
            "in store but not attested (subject-count mismatch): added")):
        _verify_with([{"name": "g1", "digest": {"sha256": _D1}},
                      {"name": "g2", "digest": {"sha256": _D2}}],
                     {"added": _D1})


def test_subject_mismatch_for_unattested_store_names_only():
    with pytest.raises(SubjectMismatchError, match=re.escape(
            _MISMATCH_PREFIX +
            "in store but not attested (subject-count mismatch): a1, a2")):
        _verify_with([], {"a1": _D1, "a2": _D2})


def test_subject_refusal_names_the_actual_subject_type():
    # both arrivals pin the type rendering: None renders "NoneType", and a
    # non-None non-list renders its own type — a hardcoded type(None) name
    # only diverges on the second
    with pytest.raises(EnvelopeFormatError) as excinfo:
        _verify_with(None, {"n1": _D1})
    assert str(excinfo.value) == "payload 'subject' must be a list, got NoneType"
    with pytest.raises(EnvelopeFormatError) as excinfo:
        _verify_with("not-a-list", {"n1": _D1})
    assert str(excinfo.value) == "payload 'subject' must be a list, got str"


# --- parse_envelope: every format problem is collected and named ----------------

def test_parse_envelope_reports_all_structural_problems_joined():
    with pytest.raises(EnvelopeFormatError, match=re.escape(
            "malformed DSSE envelope: "
            "'payload' must be a non-empty base64 string, got None; "
            "'payloadType' must be a non-empty string, got None; "
            "'signatures' must be a non-empty list, got None")):
        parse_envelope({})


def test_parse_envelope_names_payload_in_the_base64_refusal():
    bad = {"payload": "a*GVsbG8h", "payloadType": PAYLOAD_TYPE,
           "signatures": [{"keyid": "k", "sig": "AAAA"}]}
    with pytest.raises(EnvelopeFormatError, match=re.escape(
            "'payload' is not canonical base64: "
            "Only base64 data is allowed")):
        parse_envelope(bad)


def test_parse_envelope_names_the_signature_entry_in_its_refusal():
    env = {"payload": base64.b64encode(b"{}").decode(),
           "payloadType": PAYLOAD_TYPE,
           "signatures": [{"keyid": "k", "sig": "QR=="}]}
    with pytest.raises(EnvelopeFormatError, match=re.escape(
            "'signatures[].sig' is not canonical base64 "
            "(non-zero pad bits or altered padding): got 'QR=='")):
        parse_envelope(env)


# --- _deterministic_coverage: milestone compare + contract get-chain ------------

def _coverage_root(tmp_path, contract):
    root = _specs_root(tmp_path, contract=contract)
    (root / "mod.py").write_text('# @trace("ALIAS-B")\nx = 1\n')
    return root


def test_deterministic_coverage_counts_bound_clause_for_milestone_v0(tmp_path):
    # ALIAS-B is deferred to v0 == the seam's milestone, so it is due and
    # bound: 1/1 — a case-mangled or padded milestone string drops it, and
    # an inverted membership test unbinds it
    root = _coverage_root(tmp_path,
                          contract={"meta": {"target_milestone":
                                             {"ALIAS-B": "v0"}}})
    assert _deterministic_coverage(root) == "1/1"


def test_deterministic_coverage_defaults_when_contract_has_no_meta(tmp_path):
    # the contract get-chain defaults are load-bearing: a dropped or None
    # default crashes .get on None downstream
    root = _coverage_root(tmp_path, contract={"other": 1})
    assert _deterministic_coverage(root) == "1/1"


# --- tail families: canonical base64, payload/gate-manifest/envelope wording ----

def test_canonical_base64_rejects_invalid_characters():
    # validate=True path: the stdlib rejects non-alphabet characters outright.
    # A validate-less decode would SKIP them and land on the pad-bits wording
    # instead — the two failure paths are distinguishable by message.
    with pytest.raises(EnvelopeFormatError, match=re.escape(
            "payload is not canonical base64: Only base64 data is allowed")):
        _canonical_base64("a*GVsbG8h", "payload")


def test_canonical_base64_rejects_non_zero_pad_bits():
    # the re-encode path: 'QR==' decodes like 'QQ==' (flipped pad bits) —
    # envelope equality is byte equality (matrix CANON-2/3/6)
    with pytest.raises(EnvelopeFormatError, match=re.escape(
            "payload is not canonical base64 "
            "(non-zero pad bits or altered padding): got 'QR=='")):
        _canonical_base64("QR==", "payload")


def test_decode_payload_names_the_actual_payload_type():
    envelope = Envelope(payload=b"[1, 2]", payload_type=PAYLOAD_TYPE,
                        signatures={})
    with pytest.raises(EnvelopeFormatError, match=re.escape(
            "payload must be a JSON object, got list")):
        decode_payload(envelope)


def test_parse_payload_joins_all_statement_problems_in_one_message():
    signer = CryptoSigner.generate_ed25519()
    envelope = Envelope(payload=b"{}", payload_type=PAYLOAD_TYPE,
                        signatures={})
    envelope.sign(signer)
    expected = ("payload is not a valid in-toto statement: "
                f"'_type' must be {STATEMENT_TYPE!r}, got None; "
                "'subject' must be a non-empty list, got None; "
                "'predicateType' must be a non-empty string, got None; "
                "'predicate' must be an object, got None")
    assert _statement_problems({}) == [
        f"'_type' must be {STATEMENT_TYPE!r}, got None",
        "'subject' must be a non-empty list, got None",
        "'predicateType' must be a non-empty string, got None",
        "'predicate' must be an object, got None",
    ]
    with pytest.raises(EnvelopeFormatError, match=re.escape(expected)):
        parse_payload(envelope.to_dict())


def test_envelope_problems_names_the_actual_container_type():
    assert _envelope_problems([]) == [
        "envelope must be a JSON object, got list"]


def test_envelope_problems_flags_a_non_string_payload():
    # a non-empty non-string payload must be reported: `not isinstance or
    # not payload` — the or-polarity is load-bearing (123 is not a str, and
    # it is truthy; only the isinstance half may save it)
    problems = _envelope_problems({
        "payload": 123,
        "payloadType": PAYLOAD_TYPE,
        "signatures": [{"sig": "x"}],
    })
    assert problems == [
        "'payload' must be a non-empty base64 string, got 123"]


def test_check_gate_manifest_missing_file_message(tmp_path, monkeypatch):
    monkeypatch.setattr("zft.attest.dsse._gate_source_root",
                        lambda: tmp_path)
    payload = {"predicate": {"gate_manifest": {"files": {
        "gone/branch.json": "0" * 64}}}}
    with pytest.raises(AttestationError, match=re.escape(
            "gate manifest file 'gone/branch.json' missing or unreadable")):
        _check_gate_manifest(payload)


def test_check_gate_manifest_hash_mismatch_message(tmp_path, monkeypatch):
    monkeypatch.setattr("zft.attest.dsse._gate_source_root",
                        lambda: tmp_path)
    (tmp_path / "f.txt").write_bytes(b"content")
    actual = hashlib.sha256(b"content").hexdigest()
    payload = {"predicate": {"gate_manifest": {"files": {
        "f.txt": "0" * 64}}}}
    with pytest.raises(AttestationError, match=re.escape(
            f"gate manifest file 'f.txt' hash mismatch: "
            f"expected {'0' * 64!r}, found {actual!r}")):
        _check_gate_manifest(payload)


# --- _statement_problems: the arriving value is rendered, not dropped -----------

def test_statement_problems_render_the_arriving_type_value():
    # a wrong _type is echoed with its own repr — a key-swap mutant renders
    # "got None" here and dies
    assert _statement_problems({"_type": "wrong"}) == [
        f"'_type' must be {STATEMENT_TYPE!r}, got 'wrong'",
        "'subject' must be a non-empty list, got None",
        "'predicateType' must be a non-empty string, got None",
        "'predicate' must be an object, got None",
    ]


def test_statement_problems_render_the_arriving_predicate_value():
    assert _statement_problems({"_type": STATEMENT_TYPE,
                                "predicate": "nope"}) == [
        "'subject' must be a non-empty list, got None",
        "'predicateType' must be a non-empty string, got None",
        "'predicate' must be an object, got 'nope'",
    ]
