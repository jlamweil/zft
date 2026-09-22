"""Typed attestation errors, shared by dsse.py (crypto + envelope) and
keys.py (key documents + policy). Lives in its own module so the two can
import the taxonomy without a cycle; dsse re-exports everything, so
``from zft.attest.dsse import …`` keeps working.
"""
from __future__ import annotations


class AttestationError(ValueError):
    """Base class: malformed attestations, bad keys, failed verification."""


class EnvelopeFormatError(AttestationError):
    """DSSE envelope is structurally malformed (fields, base64, JSON payload)."""


class KeyValidationError(AttestationError):
    """Verification key is missing, unusable, or fails key policy
    (revoked, outside its validity window, keyid pin mismatch)."""


class SignatureVerificationError(AttestationError):
    """Envelope signature did not verify against the provided key."""


class SubjectMismatchError(AttestationError):
    """Verified payload's subject digests differ from the expected set."""
