"""WP-E2 — gate manifest in the attestation (tool confidence)."""

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest
from securesystemslib.dsse import Envelope
from securesystemslib.signer import CryptoSigner

from zft.attest.dsse import (
    AttestationError,
    attest_contract,
    verify_attestation,
)

REPO = Path(__file__).resolve().parents[2]


def _payload(att: dict) -> dict:
    raw = base64.urlsafe_b64decode(att["payload"] + "=" * (-len(att["payload"]) % 4))
    return json.loads(raw)


def test_gate_manifest_hashes_and_versions():
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(REPO, signer=signer)
    payload = verify_attestation(att, public_key=signer.public_key)
    manifest = payload["predicate"]["gate_manifest"]
    files = manifest["files"]
    expected = [
        "src/zft/gates/l1.py",
        "src/zft/gates/l2.py",
        "src/zft/codegen/property_gen.py",
    ]
    for rel in expected:
        full = REPO / rel
        expected_hash = hashlib.sha256(full.read_bytes()).hexdigest()
        assert files[rel] == expected_hash, f"hash mismatch for {rel}"
    assert manifest["python"] == sys.version.split()[0]
    assert manifest["pytest"] == pytest.__version__


def test_tampered_manifest_file_hash_rejected():
    signer = CryptoSigner.generate_ed25519()
    att = attest_contract(REPO, signer=signer)

    # Tamper the manifest hash for l1.py, re-sign so the signature is valid.
    tampered = _payload(att)
    tampered["predicate"]["gate_manifest"]["files"][
        "src/zft/gates/l1.py"
    ] = "0" * 64
    att["payload"] = base64.urlsafe_b64encode(
        json.dumps(tampered).encode()
    ).decode()
    env = Envelope.from_dict(att)
    env.sign(signer)
    att = env.to_dict()

    with pytest.raises(AttestationError):
        verify_attestation(att, public_key=signer.public_key)
