"""DSSE attestation (plan C-28): TraceManifest predicate binding clause hashes.

Substrate: securesystemslib (in-toto 3.x's underlying DSSE library; in-toto 3.1
removed its legacy models API). Predicate URI versioned: .../TraceManifest/v1.

Payloads are canonicalized per RFC 8785 (JCS, see attest.jcs) before signing —
securesystemslib's encode_canonical is the older OLPC Canonical-JSON draft
(no float support, code-point key ordering), not JCS, so we do not sign over it.

Malformed envelopes raise the typed errors below instead of leaking
securesystemslib/binascii internals; parse_envelope collects every format
problem it finds before failing (parser-style error recovery).
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from securesystemslib.dsse import Envelope
from securesystemslib.exceptions import FormatError, VerificationError
from securesystemslib.signer import CryptoSigner, Key, Signer

from zft.attest.errors import (
    AttestationError,
    EnvelopeFormatError,
    KeyValidationError,
    SignatureVerificationError,
    SubjectMismatchError,
)
from zft.attest.jcs import canonicalize

if TYPE_CHECKING:
    from zft.attest.keys import KeyDocument

PREDICATE_TYPE = "https://zft.dev/attestations/TraceManifest/v1"
PAYLOAD_TYPE = "application/vnd.in-toto+json"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"

__all__ = [
    "AttestationError", "EnvelopeFormatError", "KeyValidationError",
    "SignatureVerificationError", "SubjectMismatchError",
    "attest_contract", "clause_subjects", "decode_payload", "parse_envelope",
    "parse_payload", "verify_attestation",
]


def _gate_source_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _gate_source_files() -> dict[str, str]:
    """Relative-path -> sha256 hex for the gate source files embedded in the manifest."""
    source_root = _gate_source_root()
    gate_files = [
        source_root / "src" / "zft" / "gates" / "l1.py",
        source_root / "src" / "zft" / "gates" / "l2.py",
        source_root / "src" / "zft" / "codegen" / "property_gen.py",
    ]
    gate_hashes: dict[str, str] = {}
    for f in gate_files:
        rel = f.relative_to(source_root)
        gate_hashes[str(rel)] = hashlib.sha256(f.read_bytes()).hexdigest()
    return gate_hashes


def _check_gate_manifest(payload: dict) -> None:
    """Fail if the gate manifest's own file hashes are tampered (zft lineage:
    gate self-verification, unioned 2026-09-12)."""
    predicate = payload.get("predicate")
    if not isinstance(predicate, dict):
        return
    manifest = predicate.get("gate_manifest")
    if not isinstance(manifest, dict):
        return
    files = manifest.get("files")
    if not isinstance(files, dict):
        return
    for rel, recorded in files.items():
        actual_path = _gate_source_root() / rel
        try:
            actual = hashlib.sha256(actual_path.read_bytes()).hexdigest()
        except OSError:
            raise AttestationError(
                f"gate manifest file {rel!r} missing or unreadable"
            ) from None
        if actual != recorded:
            raise AttestationError(
                f"gate manifest file {rel!r} hash mismatch: expected {recorded!r}, "
                f"found {actual!r}")


def clause_subjects(root: Path) -> list[dict]:
    subjects = []
    for path in sorted((root / ".zft" / "specs").rglob("*.json")):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        subjects.append({"name": f"clause:{path.name}", "digest": {"sha256": digest}})
    return subjects


def _deterministic_coverage(root: Path) -> str:
    """covered/due clause count for milestone v0 (bindings vs deferred targets)."""
    from zft.lineage.extract import extract_bindings
    from zft.spec.store import Store, load_contract

    store = Store.load(root)
    milestone = "v0"
    try:
        deferred = load_contract(root).get("meta", {}).get("target_milestone", {})
    except (FileNotFoundError, json.JSONDecodeError):
        deferred = {}
    due = {a for a, _n in store.nodes.items() if deferred.get(a, milestone) <= milestone}
    bindings = extract_bindings(root)
    bound = sorted({b["alias"] for b in bindings if b["alias"] in due})
    return f"{len(bound)}/{len(due)}"


def attest_contract(root: Path | str, producer_model: str | None = None,
                    gate_model: str | None = None, signer: Signer | None = None,
                    deterministic_coverage: str | None = None) -> dict:
    """Sign a TraceManifest statement over the current store; returns DSSE envelope dict.

    Payload is RFC 8785-canonicalized before signing. Sign with the passed
    signer; the caller MUST keep it for verification. deterministic_coverage:
    if None, computed from bindings vs due clauses.
    """
    root = Path(root)
    signer = signer or CryptoSigner.generate_ed25519()
    subjects = clause_subjects(root)
    if not subjects:
        raise AttestationError(
            f"no clause specs found under {root / '.zft' / 'specs'} — nothing to attest")

    from zft.spec.store import load_contract

    try:
        contract = load_contract(root)
        deferred = contract.get("meta", {}).get("target_milestone", {})
    except (FileNotFoundError, json.JSONDecodeError):
        deferred = {}
    if deterministic_coverage is None:
        deterministic_coverage = _deterministic_coverage(root)


    payload = {
        "_type": STATEMENT_TYPE,
        "subject": subjects,
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "coverage": {"clauses_covered": deterministic_coverage or "pending-L2"},
            "judge_excluded": [],
            "deferred": sorted(deferred),
            "models": {"producer": producer_model, "gate": gate_model},
            "model_dependent": producer_model == gate_model,
            "gate_manifest": {
                "files": _gate_source_files(),
                "python": sys.version.split()[0],
                "pytest": pytest.__version__,
            },
        },
    }
    # JCS is the last gate before signing: a payload we cannot canonicalize
    # (lone surrogate from surrogateescaped argv or escaped contract JSON,
    # an out-of-double-range integer, ...) must be rejected typed and unsigned.
    try:
        payload_bytes = canonicalize(payload)
    except ValueError as exc:
        raise AttestationError(
            f"payload is not RFC 8785 canonicalizable: {exc}") from exc
    envelope = Envelope(
        payload=payload_bytes,
        payload_type=PAYLOAD_TYPE,
        signatures={},
    )
    envelope.sign(signer)
    return envelope.to_dict()


def _envelope_problems(envelope_dict: object) -> list[str]:
    """Collect ALL structural problems in a would-be DSSE envelope (error recovery)."""
    if not isinstance(envelope_dict, dict):
        return [f"envelope must be a JSON object, got {type(envelope_dict).__name__}"]
    problems: list[str] = []
    payload = envelope_dict.get("payload")
    if not isinstance(payload, str) or not payload:
        problems.append(f"'payload' must be a non-empty base64 string, got {payload!r}")
    payload_type = envelope_dict.get("payloadType")
    if not isinstance(payload_type, str) or not payload_type:
        problems.append(f"'payloadType' must be a non-empty string, got {payload_type!r}")
    signatures = envelope_dict.get("signatures")
    # DSSE envelopes carry signatures as an array; securesystemslib's
    # from_dict iterates it, so the legacy {keyid: sig} mapping shape is
    # rejected here rather than by a stray TypeError deeper in.
    if not isinstance(signatures, list) or not signatures:
        problems.append(f"'signatures' must be a non-empty list, got {signatures!r}")
        return problems
    # each entry must at least be shaped for from_dict (a bare null/str/int
    # entry used to escape as AttributeError from the substrate)
    for i, entry in enumerate(signatures):
        if not isinstance(entry, dict) or not isinstance(entry.get("sig"), str):
            problems.append(
                f"'signatures[{i}]' must be an object with a string 'sig', got {entry!r}")
    return problems


def _canonical_base64(text: str, what: str) -> None:
    """Accept only canonical RFC 4648 standard-alphabet base64 (zero pad bits).

    Two malleabilities are closed here: Python's b64decode ignores non-zero
    pad bits, so 'QR==' decodes like 'QQ==' — a flipped last character yields
    a byte-different envelope that still verifies; and securesystemslib also
    decodes the urlsafe alphabet, so re-rendering a field urlsafe would give
    the same signed content a textually different envelope (G5: envelope
    equality must be byte equality — matrix CANON-2/3/6).
    """
    try:
        data = base64.b64decode(text.encode("utf-8"), validate=True)
    except (binascii.Error, ValueError) as exc:  # binascii.Error ⊂ ValueError
        raise EnvelopeFormatError(
            f"{what} is not canonical base64: {exc}") from exc
    if base64.b64encode(data).decode("ascii") != text:
        raise EnvelopeFormatError(
            f"{what} is not canonical base64 "
            f"(non-zero pad bits or altered padding): got {text!r}")


def parse_envelope(envelope_dict: dict) -> Envelope:
    """Validate + parse an envelope dict, reporting every format problem at once."""
    problems = _envelope_problems(envelope_dict)
    if problems:
        raise EnvelopeFormatError("malformed DSSE envelope: " + "; ".join(problems))
    _canonical_base64(envelope_dict["payload"], "'payload'")
    for entry in envelope_dict["signatures"]:
        if isinstance(entry, dict) and isinstance(entry.get("sig"), str):
            _canonical_base64(entry["sig"], "'signatures[].sig'")
    try:
        # from_dict consumes signature entries in place — parse a copy so the
        # caller's dict (and raw-envelope exports) stay pristine.
        return Envelope.from_dict(copy.deepcopy(envelope_dict))
    except (KeyError, TypeError, ValueError, FormatError) as exc:
        # bad base64 (binascii.Error ⊂ ValueError), missing fields, bad shapes
        raise EnvelopeFormatError(f"malformed DSSE envelope: {exc}") from exc


def decode_payload(envelope: Envelope) -> dict:
    """UTF-8 + JSON decode a parsed envelope's payload into a dict."""
    try:
        text = envelope.payload.decode("utf-8")
    except (UnicodeDecodeError, AttributeError) as exc:
        raise EnvelopeFormatError(f"payload is not valid UTF-8: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EnvelopeFormatError(f"payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EnvelopeFormatError(
            f"payload must be a JSON object, got {type(payload).__name__}")
    return payload


def _statement_problems(payload: dict) -> list[str]:
    problems = []
    if payload.get("_type") != STATEMENT_TYPE:
        problems.append(f"'_type' must be {STATEMENT_TYPE!r}, got {payload.get('_type')!r}")
    subject = payload.get("subject")
    if not isinstance(subject, list) or not subject:
        problems.append(f"'subject' must be a non-empty list, got {subject!r}")
    predicate_type = payload.get("predicateType")
    if not isinstance(predicate_type, str) or not predicate_type:
        problems.append(f"'predicateType' must be a non-empty string, got {predicate_type!r}")
    if not isinstance(payload.get("predicate"), dict):
        problems.append(f"'predicate' must be an object, got {payload.get('predicate')!r}")
    return problems


def parse_payload(envelope_dict: dict) -> dict:
    """Parse an envelope dict all the way to a validated in-toto Statement dict."""
    payload = decode_payload(parse_envelope(envelope_dict))
    if envelope_dict["payloadType"] != PAYLOAD_TYPE:
        raise EnvelopeFormatError(
            f"unsupported payloadType {envelope_dict['payloadType']!r} "
            f"(expected {PAYLOAD_TYPE!r})")
    problems = _statement_problems(payload)
    if problems:
        raise EnvelopeFormatError(
            "payload is not a valid in-toto statement: " + "; ".join(problems))
    return payload


def _check_subjects(payload: dict, expected_subjects: dict[str, str]) -> None:
    subjects = payload.get("subject")
    if not isinstance(subjects, list):
        raise EnvelopeFormatError(
            f"payload 'subject' must be a list, got {type(subjects).__name__}")
    got: dict[str, str] = {}
    for entry in subjects:
        try:
            got[entry["name"]] = entry["digest"]["sha256"]
        except (TypeError, KeyError, IndexError) as exc:
            raise EnvelopeFormatError(f"malformed subject entry {entry!r}: {exc}") from exc
    if got != expected_subjects:
        changed = sorted(
            f"{n} (attested {got[n][:12]}…, store {expected_subjects[n][:12]}…)"
            for n in got.keys() & expected_subjects.keys()
            if got[n] != expected_subjects[n])
        missing = sorted(got.keys() - expected_subjects.keys())
        added = sorted(expected_subjects.keys() - got.keys())
        detail = "; ".join(
            part for part in (
                f"changed: {', '.join(changed)}" if changed else "",
                f"attested but not in store: {', '.join(missing)}" if missing else "",
                f"in store but not attested (subject-count mismatch): "
                f"{', '.join(added)}" if added else "",
            ) if part)
        raise SubjectMismatchError(
            f"subject digests do not match the contract store: {detail}")


def verify_attestation(envelope_dict: dict, expected_subjects: dict[str, str] | None = None,
                       public_key: Key | None = None, *,
                       key_document: "KeyDocument | None" = None,
                       now=None, expect_keyid: str | None = None) -> dict:
    """Verify signature + subject digests; returns the payload dict on success.

    Guards raise EnvelopeFormatError for malformed envelopes (all format
    problems reported at once), KeyValidationError for missing/unusable keys
    and key-policy failures, SignatureVerificationError when the signature
    check fails, and SubjectMismatchError when verified digests differ from
    expected_subjects.

    Key policy (ATTACK_MATRIX G7): pass key_document (attest.keys.KeyDocument,
    parsed from the published key file) instead of a bare public_key to have
    revocation, the validity window, and an optional expect_keyid pin enforced
    BEFORE any cryptographic work. now overrides the clock for the window
    check (deterministic tests); naive datetimes are taken as UTC.
    """
    if key_document is not None and public_key is not None:
        raise KeyValidationError(
            "pass either public_key or key_document, not both — "
            "which key governs verification must be unambiguous")
    if key_document is not None:
        public_key = key_document.check(now=now, expect_keyid=expect_keyid)
    if public_key is None:
        raise KeyValidationError(
            "verify_attestation requires public_key (dev: signer.public_key)")
    if not isinstance(public_key, Key):
        raise KeyValidationError(
            f"public_key must be a securesystemslib Key, got {type(public_key).__name__}")
    if not getattr(public_key, "keyid", ""):
        raise KeyValidationError("public_key carries no keyid")
    envelope = parse_envelope(envelope_dict)
    if envelope_dict["payloadType"] != PAYLOAD_TYPE:
        raise EnvelopeFormatError(
            f"unsupported payloadType {envelope_dict['payloadType']!r} "
            f"(expected {PAYLOAD_TYPE!r})")
    try:
        envelope.verify([public_key], 1)
    except VerificationError as exc:
        raise SignatureVerificationError(f"signature verification failed: {exc}") from exc
    except ValueError as exc:  # threshold / keyid-matching rejections
        raise KeyValidationError(f"key rejected by DSSE verifier: {exc}") from exc
    except Exception as exc:  # substrate escapes (review L-3): typed, never raw
        if isinstance(exc, AttestationError):
            raise
        raise SignatureVerificationError(
            f"signature verification layer failed: "
            f"{type(exc).__name__}: {exc}") from exc
    payload = decode_payload(envelope)
    if expected_subjects is not None:
        _check_subjects(payload, expected_subjects)
    _check_gate_manifest(payload)
    return payload
