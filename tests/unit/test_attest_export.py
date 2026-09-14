"""C-30 export formats: raw DSSE envelope, trace matrix, human-readable summary.

Envelopes are signed over the real REPO store, then placed in a tmp root so
exports only depend on .traceagent/attest.json.
"""
import base64
import json
from pathlib import Path

import pytest
from securesystemslib.signer import CryptoSigner

from traceagent.attest.dsse import EnvelopeFormatError, attest_contract
from traceagent.attest.export import (
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
    (tmp_path / ".traceagent").mkdir()
    (tmp_path / ".traceagent" / "attest.json").write_text(json.dumps(envelope))
    return tmp_path, envelope


def test_export_envelope_is_raw_and_validated(attested_root):
    root, envelope = attested_root
    assert export_envelope(root) == envelope


def test_export_matrix_matches_attested_payload(attested_root):
    root, _envelope = attested_root
    matrix = export_matrix(root)
    assert matrix["predicateType"] == "https://traceagent.dev/attestations/TraceManifest/v1"
    assert matrix["clauses"] and all(c.startswith("clause:") for c in matrix["clauses"])
    covered, due = matrix["coverage"]["clauses_covered"].split("/")
    assert int(covered) <= int(due)
    assert matrix["model_dependent"] is False  # producer-dev != gate-dev


def test_export_summary_is_human_readable(attested_root):
    root, envelope = attested_root
    summary = export_summary(root)
    assert "TraceAgent attestation summary" in summary
    assert "predicate type: https://traceagent.dev/attestations/TraceManifest/v1" in summary
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
    (tmp_path / ".traceagent").mkdir()
    good_signer = CryptoSigner.generate_ed25519()
    envelope = attest_contract(REPO, signer=good_signer)

    broken_json = tmp_path / ".traceagent" / "attest.json"
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
    (root / ".traceagent" / "attest.json").write_text(json.dumps(broken))
    with pytest.raises(EnvelopeFormatError, match="incomplete"):
        export_matrix(root)
