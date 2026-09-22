"""DSSE kill-shard pins (2026-09-15 cut — 82 suspects: 76 kills, 6 waivers).

attest/dsse.py is the attestation boundary: envelope parsing collects every
format problem before failing (parser-style error recovery), base64 fields
accept only the canonical RFC 4648 rendering (CANON-2/3/6: envelope equality
is byte equality), verification guards raise typed errors (never substrate
escapes), and subject digests are matched against the contract store with a
changed/missing/added detail render. Each pin states one contract fact; the
waiver sheet carries the five reviewed equivalents.

All pins exercise the module in-process (mutmut scores by parent-process
coverage — a subprocess pin would never be selected; see the lineage/matrix
shard). Error-message pins are byte-exact because the typed refusals are
contract surface: a caller keys automation on them.
"""

import base64
import hashlib
import json

import pytest
from securesystemslib.dsse import Envelope
from securesystemslib.signer import CryptoSigner, Key

from zft.attest import dsse
from zft.attest.dsse import (
    PAYLOAD_TYPE,
    _canonical_base64,
    _check_gate_manifest,
    _check_subjects,
    _deterministic_coverage,
    _statement_problems,
    decode_payload,
    parse_envelope,
    parse_payload,
    verify_attestation,
)


def _payload_b64(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


def _envelope(payload_obj, sig="QQ=="):
    """Shape-valid envelope (canonical base64 fields); content may be bogus."""
    return {
        "payload": _payload_b64(payload_obj),
        "payloadType": PAYLOAD_TYPE,
        "signatures": [{"sig": sig, "keyid": "test-key-id"}],
    }


def _signed_envelope(signer) -> dict:
    env = Envelope(payload=b'{"x": 1}', payload_type=PAYLOAD_TYPE, signatures={})
    env.sign(signer)
    return env.to_dict()


# ---------------------------------------------------------------------------
# _canonical_base64 — only the canonical RFC 4648 rendering is accepted, and
# the rejection names the field and the underlying decode error.
# ---------------------------------------------------------------------------

def test_non_alphabet_base64_rejects_with_decode_error_wording():
    """A non-alphabet character must surface the underlying b64 decode error
    ('…base64: Error: …'), not the round-trip wording — validate= is
    load-bearing: a falsy validate silently DISCARDS the '?' and re-raises as
    the '(non-zero pad bits…)' branch instead."""
    with pytest.raises(ValueError,
                       match=r"^probe is not canonical base64: "
                             r"Only base64 data is allowed$"):
        _canonical_base64("QQ?=", "probe")


# ---------------------------------------------------------------------------
# _check_gate_manifest — the gate's self-verification names the tampered file
# and the recorded hash, byte-exact.
# ---------------------------------------------------------------------------

def _manifest_payload(files: dict) -> dict:
    return {"predicate": {"gate_manifest": {"files": files}}}


def test_gate_manifest_missing_file_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(dsse, "_gate_source_root", lambda: tmp_path)
    with pytest.raises(dsse.AttestationError, match=
                       r"gate manifest file 'src/zft/gates/l1.py' "
                       r"missing or unreadable"):
        _check_gate_manifest(
            _manifest_payload({"src/zft/gates/l1.py": "0" * 64}))


def test_gate_manifest_hash_mismatch_names_recorded_hash(tmp_path, monkeypatch):
    gate = tmp_path / "src" / "zft" / "gates"
    gate.mkdir(parents=True)
    (gate / "l1.py").write_bytes(b"tampered")
    monkeypatch.setattr(dsse, "_gate_source_root", lambda: tmp_path)
    with pytest.raises(dsse.AttestationError, match=
                       r"hash mismatch: expected '0{12}\.\.\.|0{64}'"):
        _check_gate_manifest(
            _manifest_payload({"src/zft/gates/l1.py": "0" * 64}))


# ---------------------------------------------------------------------------
# _check_subjects — the mismatch detail is contract surface: changed entries
# render 12-hex-char digests per side, the three segments join with "; ", and
# empty segments vanish (no placeholder may leak).
# ---------------------------------------------------------------------------

def _subjects(got: dict) -> dict:
    return {"subject": [
        {"name": n, "digest": {"sha256": d}} for n, d in got.items()
    ]}


def _digest(tag: str) -> str:
    return hashlib.sha256(tag.encode()).hexdigest()


def test_subject_mismatch_two_changed_one_missing_full_render():
    got = {"a.json": _digest("A2"), "b.json": _digest("B2"),
           "d.json": _digest("D")}
    expected = {"a.json": _digest("A"), "b.json": _digest("B"),
                "c.json": _digest("C")}
    with pytest.raises(dsse.SubjectMismatchError) as excinfo:
        _check_subjects(_subjects(got), expected)
    msg = str(excinfo.value)
    assert msg.startswith("subject digests do not match the contract store: ")
    detail = msg.split(": ", 1)[1]
    assert detail == (
        f"changed: a.json (attested {_digest('A2')[:12]}…, "
        f"store {_digest('A')[:12]}…), b.json (attested {_digest('B2')[:12]}…, "
        f"store {_digest('B')[:12]}…)"
        f"; attested but not in store: d.json"
        f"; in store but not attested (subject-count mismatch): c.json"
    )


def test_subject_mismatch_attested_only_two_added():
    """Empty changed/missing segments must vanish entirely — no placeholder
    may leak into the detail."""
    got = {}
    expected = {"a.json": _digest("A"), "b.json": _digest("B")}
    with pytest.raises(dsse.SubjectMismatchError) as excinfo:
        _check_subjects(_subjects(got), expected)
    assert str(excinfo.value).endswith(
        "subject-count mismatch): a.json, b.json")
    assert "XXXX" not in str(excinfo.value)


def test_subject_mismatch_two_missing_full_join_render():
    got = {"d.json": _digest("D"), "e.json": _digest("E")}
    expected = {"a.json": _digest("A")}
    with pytest.raises(dsse.SubjectMismatchError) as excinfo:
        _check_subjects(_subjects(got), expected)
    assert str(excinfo.value).endswith(
        "attested but not in store: d.json, e.json"
        "; in store but not attested (subject-count mismatch): a.json")


def test_subject_mismatch_superset_store_attested_only_leaks_nothing():
    """got strictly contains expected: the added segment is empty and must
    vanish — no placeholder may leak in its place."""
    got = {"a.json": _digest("A"), "d.json": _digest("D")}
    expected = {"a.json": _digest("A")}
    with pytest.raises(dsse.SubjectMismatchError) as excinfo:
        _check_subjects(_subjects(got), expected)
    msg = str(excinfo.value)
    assert msg.endswith("attested but not in store: d.json")
    assert "XXXX" not in msg


def test_subject_not_a_list_names_the_type():
    with pytest.raises(dsse.EnvelopeFormatError,
                       match=r"payload 'subject' must be a list, got str"):
        _check_subjects({"subject": "nope"}, {"a.json": _digest("A")})


# ---------------------------------------------------------------------------
# _deterministic_coverage — covered/due is computed against the v0 milestone:
# an alias deferred to a later milestone drops out of `due`, and the count is
# bound aliases / due aliases.
# ---------------------------------------------------------------------------

class _FakeStore:
    def __init__(self, nodes):
        self.nodes = nodes


def _coverage_env(monkeypatch, nodes, contract):
    """Fake the store/binding/contract reads _deterministic_coverage composes
    (it imports them at call time from their source modules). *nodes* is the
    {alias: node} mapping the fake store carries; one binding per alias."""
    monkeypatch.setattr("zft.spec.store.Store",
                        type("S", (), {"load": staticmethod(
                            lambda root: _FakeStore(nodes))}))
    monkeypatch.setattr("zft.spec.store.load_contract",
                        lambda root: contract)
    monkeypatch.setattr("zft.lineage.extract.extract_bindings",
                        lambda root: [{"alias": a} for a in nodes])


def test_coverage_counts_deferred_alias_as_due(tmp_path, monkeypatch):
    """a2 is deferred to v0 = the milestone itself, so both aliases are due;
    both bound → 2/2. The milestone literal, the membership test, and the
    deferred-dict defaults are all load-bearing."""
    _coverage_env(monkeypatch, {"a1": None, "a2": None},
                  {"meta": {"target_milestone": {"a2": "v0"}}})
    assert _deterministic_coverage(tmp_path) == "2/2"


def test_coverage_contract_without_meta_or_target_defaults(tmp_path, monkeypatch):
    """A contract with no meta at all, and a contract whose meta carries no
    target_milestone, must both behave as 'nothing deferred' (empty dict) —
    a None default explodes on .get()/sorted()."""
    _coverage_env(monkeypatch, {"a1": None}, {})
    assert _deterministic_coverage(tmp_path) == "1/1"
    _coverage_env(monkeypatch, {"a1": None}, {"meta": {}})
    assert _deterministic_coverage(tmp_path) == "1/1"


# ---------------------------------------------------------------------------
# parse_envelope / _envelope_problems — every format problem is collected and
# reported at once, prefixed "malformed DSSE envelope: "; base64 field
# rejections name the field.
# ---------------------------------------------------------------------------

def test_non_object_envelope_names_the_type():
    with pytest.raises(dsse.EnvelopeFormatError,
                       match=r"malformed DSSE envelope: envelope must be a "
                             r"JSON object, got list"):
        parse_envelope([])


def test_non_string_payload_is_collected_not_smuggled():
    """A non-string truthy payload (123) must be a collected problem: the
    or-guard sends it to the typed rejection — an and-guard would let it
    escape as AttributeError from .encode deeper in."""
    with pytest.raises(dsse.EnvelopeFormatError,
                       match=r"^malformed DSSE envelope: 'payload' must be a "
                             r"non-empty base64 string, got 123$"):
        parse_envelope({"payload": 123, "payloadType": PAYLOAD_TYPE,
                        "signatures": [{"sig": "QQ=="}]})


def test_envelope_problems_join_two_findings():
    with pytest.raises(dsse.EnvelopeFormatError, match=
                       r"^malformed DSSE envelope: "
                       r"'payload' must be a non-empty base64 string, got ''"
                       r"; 'payloadType' must be a non-empty string, got None"
                       r"; 'signatures' must be a non-empty list, got \[\]$"):
        parse_envelope({"payload": "", "signatures": []})


def test_non_canonical_payload_rejection_names_the_field():
    with pytest.raises(dsse.EnvelopeFormatError,
                       match=r"^'payload' is not canonical base64: "):
        parse_envelope({"payload": "QQ?=", "payloadType": PAYLOAD_TYPE,
                        "signatures": [{"sig": "QQ=="}]})


def test_non_canonical_signature_rejection_names_the_field():
    with pytest.raises(dsse.EnvelopeFormatError,
                       match=r"^'signatures\[\]\.sig' is not canonical base64: "):
        parse_envelope(_envelope({"_type": "x"}, sig="QQ?="))


def test_non_string_sig_skips_the_canonical_guard_typed():
    """A dict entry whose 'sig' is not a str is a collected problem in
    _envelope_problems (typed), never a stray canonical-guard call."""
    with pytest.raises(dsse.EnvelopeFormatError, match=
                       r"'signatures\[0\]' must be an object with a string "
                       r"'sig'"):
        parse_envelope({"payload": _payload_b64({"_type": "x"}),
                        "payloadType": PAYLOAD_TYPE, "signatures": [{"sig": 123}]})


# ---------------------------------------------------------------------------
# decode_payload / _statement_problems / parse_payload — the statement
# rejection reports every problem with the offending value rendered.
# ---------------------------------------------------------------------------

def test_payload_non_object_json_names_the_type(tmp_path):
    env = {"payload": base64.b64encode(b"[]").decode(),
           "payloadType": PAYLOAD_TYPE,
           "signatures": [{"sig": "QQ==", "keyid": "test-key-id"}]}
    with pytest.raises(dsse.EnvelopeFormatError,
                       match=r"payload must be a JSON object, got list"):
        decode_payload(parse_envelope(env))


def test_statement_rejection_reports_type_and_predicate_problems():
    env = _envelope({"_type": "wrong", "subject": [{"name": "n"}],
                     "predicateType": "x", "predicate": []})
    with pytest.raises(dsse.EnvelopeFormatError, match=
                       r"^payload is not a valid in-toto statement: "
                       r"'_type' must be 'https://in-toto\.io/Statement/v1', "
                       r"got 'wrong'"
                       r"; 'predicate' must be an object, got \[\]$"):
        parse_payload(env)


def test_statement_problem_render_reads_the_real_key():
    """The 'got' render must read the real '_type' key: a mutant reading any
    other key renders None for a payload that HAS the key."""
    problems = _statement_problems({"_type": "wrong",
                                    "subject": [{"name": "n"}],
                                    "predicateType": "x",
                                    "predicate": {}})
    assert problems == ["'_type' must be 'https://in-toto.io/Statement/v1', "
                        "got 'wrong'"]


# ---------------------------------------------------------------------------
# attest_contract — the payload's predicate shape and the no-store refusal.
# ---------------------------------------------------------------------------

def _spec_root(tmp_path, names=("a.json", "b.json")):
    specs = tmp_path / ".zft" / "specs"
    specs.mkdir(parents=True)
    for n in names:
        (specs / n).write_text("{}", encoding="utf-8")
    return tmp_path


def test_attest_without_clauses_names_the_specs_dir(tmp_path):
    with pytest.raises(dsse.AttestationError, match=
                       r"no clause specs found under .*\.zft.specs — "
                       r"nothing to attest"):
        dsse.attest_contract(tmp_path)


def _attest_with_contract(tmp_path, monkeypatch, contract, signer,
                          coverage="1/1"):
    _spec_root(tmp_path)
    monkeypatch.setattr("zft.spec.store.load_contract",
                        lambda root: contract)
    monkeypatch.setattr(dsse, "_deterministic_coverage",
                        lambda root: coverage)
    return dsse.decode_payload(
        parse_envelope(dsse.attest_contract(tmp_path, signer=signer)))


def test_attest_payload_carries_deferred_and_judge_excluded(tmp_path, monkeypatch):
    """deferred is the sorted target_milestone key list; judge_excluded is an
    (empty) list — both are predicate keys the consumer reads by name."""
    signer = CryptoSigner.generate_ed25519()
    payload = _attest_with_contract(
        tmp_path, monkeypatch,
        {"meta": {"target_milestone": {"clause:a.json": "v1"}}}, signer)
    assert payload["predicate"]["deferred"] == ["clause:a.json"]
    assert payload["predicate"]["judge_excluded"] == []


def test_attest_contract_without_meta_defers_nothing(tmp_path, monkeypatch):
    signer = CryptoSigner.generate_ed25519()
    payload = _attest_with_contract(tmp_path, monkeypatch, {}, signer)
    assert payload["predicate"]["deferred"] == []


def test_attest_pending_coverage_fallback_string(tmp_path, monkeypatch):
    """An empty deterministic_coverage (falsy, caller-supplied) falls back to
    the exact 'pending-L2' marker in the signed payload."""
    signer = CryptoSigner.generate_ed25519()
    payload = _attest_with_contract(tmp_path, monkeypatch, {}, signer,
                                    coverage="")
    assert payload["predicate"]["coverage"]["clauses_covered"] == "pending-L2"


# ---------------------------------------------------------------------------
# verify_attestation — the guard ladders are typed, ordered, and byte-exact.
# ---------------------------------------------------------------------------

def test_verify_rejects_ambiguous_key_source():
    with pytest.raises(dsse.KeyValidationError, match=
                       r"^pass either public_key or key_document, not both — "
                       r"which key governs verification must be unambiguous$"):
        verify_attestation({}, public_key="x", key_document="y")


def test_verify_requires_a_key():
    with pytest.raises(dsse.KeyValidationError, match=
                       r"^verify_attestation requires public_key "
                       r"\(dev: signer\.public_key\)$"):
        verify_attestation(_envelope({"_type": "x"}))


def test_verify_rejects_non_key_type_by_name():
    with pytest.raises(dsse.KeyValidationError,
                       match=r"public_key must be a securesystemslib Key, "
                             r"got str$"):
        verify_attestation(_envelope({"_type": "x"}), public_key="junk")


class _KeyWithoutKeyid(Key):
    """A Key whose keyid attribute is ABSENT (property raises AttributeError):
    exercises getattr's default — the code's own "" default must route to the
    typed no-keyid rejection, not leak a truthy stand-in past the guard."""

    def __init__(self):
        # deliberately NOT calling Key.__init__ (it would assign self.keyid
        # straight through the property); the guard only needs isinstance
        self.keytype = "ed25519"
        self.scheme = "ed25519"
        self.keyval = {}

    def from_dict(self, d):  # pragma: no cover - never called
        raise NotImplementedError

    def to_dict(self):  # pragma: no cover - never called
        raise NotImplementedError

    def verify_signature(self, *a, **kw):  # pragma: no cover - never called
        raise NotImplementedError

    @property
    def keyid(self):
        raise AttributeError("keyid stripped for the pin")


def test_verify_rejects_key_without_keyid():
    with pytest.raises(dsse.KeyValidationError,
                       match=r"^public_key carries no keyid$"):
        verify_attestation(_envelope({"_type": "x"}),
                           public_key=_KeyWithoutKeyid())


def test_verify_wrong_key_is_a_typed_signature_failure():
    """A well-formed envelope signed by another key fails closed as
    SignatureVerificationError (the substrate raises VerificationError on the
    threshold check; the ValueError branch of the wrapper is unreachable with
    the hardcoded single-key threshold-1 call)."""
    signer = CryptoSigner.generate_ed25519()
    other = CryptoSigner.generate_ed25519()
    with pytest.raises(dsse.SignatureVerificationError, match=
                       r"^signature verification failed: "):
        verify_attestation(_signed_envelope(signer),
                           public_key=other.public_key)


def test_verify_substrate_escape_is_typed_with_the_real_cause(monkeypatch):
    class _Boom:
        @classmethod
        def from_dict(cls, d):
            return cls()

        def verify(self, *a, **kw):
            raise RuntimeError("boom")

    monkeypatch.setattr(dsse, "Envelope", _Boom)
    with pytest.raises(dsse.SignatureVerificationError, match=
                       r"^signature verification layer failed: "
                       r"RuntimeError: boom$"):
        verify_attestation(_envelope({"_type": "x"}),
                           public_key=CryptoSigner.generate_ed25519().public_key)
