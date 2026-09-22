"""C-30 export formats: raw DSSE envelope, trace matrix, human-readable summary.

Envelopes are signed over the real REPO store, then placed in a tmp root so
exports only depend on .zft/attest.json.
"""
import base64
import json
from pathlib import Path

import pytest
from securesystemslib.signer import CryptoSigner

from zft.attest.dsse import EnvelopeFormatError, attest_contract
from zft.attest.export import (
    _predicate_problems,
    _signature_keyids,
    export_attestation,
    export_envelope,
    export_matrix,
    export_summary,
)

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def attested_root(tmp_path):
    signer = CryptoSigner.generate_ed25519()
    envelope = attest_contract(REPO, producer_model="producer-dev",
                               gate_model="gate-dev", signer=signer)
    (tmp_path / ".zft").mkdir()
    (tmp_path / ".zft" / "attest.json").write_text(json.dumps(envelope))
    return tmp_path, envelope


def test_export_envelope_is_raw_and_validated(attested_root):
    root, envelope = attested_root
    assert export_envelope(root) == envelope


def test_export_matrix_matches_attested_payload(attested_root):
    root, _envelope = attested_root
    matrix = export_matrix(root)
    assert matrix["predicateType"] == "https://zft.dev/attestations/TraceManifest/v1"
    assert matrix["clauses"] and all(c.startswith("clause:") for c in matrix["clauses"])
    covered, due = matrix["coverage"]["clauses_covered"].split("/")
    assert int(covered) <= int(due)
    assert matrix["model_dependent"] is False  # producer-dev != gate-dev


def test_export_summary_is_human_readable(attested_root):
    root, envelope = attested_root
    summary = export_summary(root)
    assert "ZFT attestation summary" in summary
    assert "predicate type: https://zft.dev/attestations/TraceManifest/v1" in summary
    assert "clauses covered" in summary
    assert "model_dependent: False" in summary
    assert "clause:" in summary
    keyid = next(iter(envelope["signatures"]))["keyid"]
    assert keyid[:16] in summary


def test_export_refuses_without_attestation(tmp_path):
    with pytest.raises(FileNotFoundError, match="ATT-EXPORTS-FROM-ATTESTATIONS"):
        export_matrix(tmp_path)
    with pytest.raises(FileNotFoundError):
        export_envelope(tmp_path)
    with pytest.raises(FileNotFoundError):
        export_summary(tmp_path)


def test_export_refuses_malformed_attestation(tmp_path):
    (tmp_path / ".zft").mkdir()
    good_signer = CryptoSigner.generate_ed25519()
    envelope = attest_contract(REPO, signer=good_signer)

    broken_json = tmp_path / ".zft" / "attest.json"
    broken_json.write_text("{not json")
    with pytest.raises(EnvelopeFormatError, match="not valid JSON"):
        export_matrix(tmp_path)

    broken_json.write_text(json.dumps([envelope]))  # envelope must be an object
    with pytest.raises(EnvelopeFormatError, match="JSON object"):
        export_matrix(tmp_path)

    broken_json.write_text(json.dumps({**envelope, "signatures": {}}))
    with pytest.raises(EnvelopeFormatError, match="signatures"):
        export_summary(tmp_path)


def test_export_attestation_dispatches_formats(attested_root):
    root, envelope = attested_root
    assert export_attestation(root, "dsse") == envelope
    assert export_attestation(root, "matrix") == export_matrix(root)
    assert export_attestation(root, "summary") == export_summary(root)
    with pytest.raises(ValueError, match="unknown export format"):
        export_attestation(root, "pdf")


def test_export_matrix_rejects_incomplete_predicate_typed(attested_root):
    root, envelope = attested_root
    raw = json.loads(base64.b64decode(envelope["payload"]))
    del raw["predicate"]["coverage"]
    broken = dict(envelope, payload=base64.b64encode(
        json.dumps(raw).encode()).decode())
    (root / ".zft" / "attest.json").write_text(json.dumps(broken))
    with pytest.raises(EnvelopeFormatError, match="incomplete"):
        export_matrix(root)


STATEMENT = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://zft.dev/attestations/TraceManifest/v1"
def _synthetic_envelope(predicate=None, subject=None, signatures=None):
    """Shape-valid envelope over a synthetic statement; content fully chosen."""
    payload = {
        "_type": STATEMENT,
        "subject": subject if subject is not None else [
            {"name": "clause:demo", "digest": {"sha256": "ab" * 32}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": predicate if predicate is not None else {
            "coverage": {"clauses_covered": "32/32"},
            "model_dependent": True,
            "models": {"producer": "producer-x", "gate": "gate-y"},
            "deferred": ["m1", "m2"],
        },
    }
    return {
        "payload": base64.b64encode(json.dumps(payload).encode()).decode(),
        "payloadType": "application/vnd.in-toto+json",
        "signatures": signatures if signatures is not None else [
            {"sig": "QQ==", "keyid": "0123456789abcdefXYZ"}],
    }
def _write_synthetic(root, envelope):
    (root / ".zft").mkdir(parents=True, exist_ok=True)
    (root / ".zft" / "attest.json").write_text(json.dumps(envelope))
def test_dispatch_default_is_matrix_and_unknown_message_byte_exact(tmp_path):
    _write_synthetic(tmp_path, _synthetic_envelope())
    assert export_attestation(tmp_path) == export_matrix(tmp_path)  # default fmt
    with pytest.raises(ValueError, match=(
            r"^unknown export format 'pdf' — "
            r"expected one of: dsse, matrix, summary$")):
        export_attestation(tmp_path, "pdf")
def test_load_envelope_missing_file_message_byte_exact(tmp_path):
    with pytest.raises(FileNotFoundError, match=(
            r"^no attestation found — export refused "
            r"\(ATT-EXPORTS-FROM-ATTESTATIONS\)$")):
        export_summary(tmp_path)
def test_load_envelope_non_object_names_the_type(tmp_path):
    _write_synthetic(tmp_path, [1, 2])
    with pytest.raises(EnvelopeFormatError,
                       match=r"^attestation file .* must contain a JSON "
                             r"object, got list$"):
        export_matrix(tmp_path)
def test_predicate_problems_missing_keys_collected_in_order():
    assert _predicate_problems({}) == [
        "'predicate.coverage' missing",
        "'predicate.model_dependent' missing",
    ]
def test_predicate_problems_type_messages_byte_exact():
    assert _predicate_problems({"coverage": 5, "model_dependent": "yes"}) == [
        "'predicate.coverage' must be an object, got int",
        "'predicate.model_dependent' must be a bool, got str",
    ]
def test_export_matrix_incomplete_message_two_problems_byte_exact(tmp_path):
    _write_synthetic(tmp_path, _synthetic_envelope(predicate={"coverage": 5}))
    with pytest.raises(EnvelopeFormatError, match=(
            r"^attested predicate is incomplete: "
            r"'predicate\.model_dependent' missing; "
            r"'predicate\.coverage' must be an object, got int$")):
        export_matrix(tmp_path)
def test_export_matrix_malformed_subject_entry_byte_exact(tmp_path):
    _write_synthetic(tmp_path, _synthetic_envelope(subject=[None]))
    with pytest.raises(EnvelopeFormatError, match=(
            r"^malformed subject entry None: "
            r"'NoneType' object is not subscriptable$")):
        export_matrix(tmp_path)
def test_export_summary_full_render_byte_exact(tmp_path):
    _write_synthetic(tmp_path, _synthetic_envelope())
    assert export_summary(tmp_path) == "\n".join([
        "ZFT attestation summary",
        "==============================",
        f"statement type: {STATEMENT}",
        f"predicate type: {PREDICATE_TYPE}",
        "payload type:   application/vnd.in-toto+json",
        "signatures:     1 (keyid 0123456789abcdef…)",  # 16-char prefix + ellipsis
        "coverage:       clauses covered 32/32",
        "models:         producer=producer-x gate=gate-y (model_dependent: True)",
        "deferred:       2 milestone target(s)",
        "subjects:       1 clause digest(s)",
        "  - clause:demo",
        "      sha256:" + "ab" * 32,
    ])
def test_export_summary_fallbacks_byte_exact(tmp_path):
    _write_synthetic(tmp_path, _synthetic_envelope(predicate={
        "coverage": {"clauses_covered": None},  # present but unknown count
        "model_dependent": False,
        # no models, no deferred
    }))
    text = export_summary(tmp_path)
    assert "coverage:       clauses covered unknown" in text
    assert "models:         producer=unspecified gate=unspecified " \
           "(model_dependent: False)" in text
    assert "deferred:       0 milestone target(s)" in text
def test_export_summary_incomplete_predicate_message_byte_exact(tmp_path):
    _write_synthetic(tmp_path, _synthetic_envelope(predicate={"coverage": 5}))
    with pytest.raises(EnvelopeFormatError, match=(
            r"^attested predicate is incomplete: "
            r"'predicate\.model_dependent' missing; "
            r"'predicate\.coverage' must be an object, got int$")):
        export_summary(tmp_path)
def test_export_summary_keyidless_signature_renders_placeholder(tmp_path):
    # A keyid-less signature entry cannot reach the summary render — the
    # substrate's Envelope.from_dict refuses it — but _signature_keyids'
    # own contract for one is the '?' placeholder, pinned directly.
    assert _signature_keyids({"signatures": [{"sig": "QQ=="}]}) == ["?"]
def test_signature_keyids_shapes_absent_legacy_and_plain(tmp_path):
    assert _signature_keyids({}) == []  # absent key → empty, never a crash
    assert _signature_keyids({"signatures": {"legacy-kid": "sig"}}) == ["legacy-kid"]
    assert _signature_keyids({"signatures": [
        {"sig": "QQ==", "keyid": "kid"}]}) == ["kid"]
def test_export_summary_malformed_subject_entry_renders_placeholder(tmp_path):
    _write_synthetic(tmp_path, _synthetic_envelope(
        subject=[{"name": "clause:ok", "digest": {"sha256": "cd" * 32}}, None]))
    text = export_summary(tmp_path)
    assert "  - clause:ok" in text
    assert "  - (malformed subject entry: None)" in text
