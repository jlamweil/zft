"""Compliance export (plan C-30): derive formats from attested manifests ONLY.

Structured views over the attested envelope in ``.traceagent/attest.json``:
``export_envelope`` (raw DSSE envelope, validated), ``export_matrix`` (trace
matrix dict), and ``export_summary`` (human-readable attestation summary).
Envelopes are structure-validated with the dsse guards; export is refused
without an attestation file (ATT-EXPORTS-FROM-ATTESTATIONS).
"""
from __future__ import annotations

import json
from pathlib import Path

from traceagent.attest.dsse import EnvelopeFormatError, parse_envelope, parse_payload

FORMATS = ("dsse", "matrix", "summary")


def export_attestation(root: Path | str, fmt: str = "matrix") -> dict | str:
    """Dispatch an export by format: 'dsse' (raw envelope), 'matrix', 'summary'."""
    if fmt not in FORMATS:
        raise ValueError(
            f"unknown export format {fmt!r} — expected one of: {', '.join(FORMATS)}")
    if fmt == "dsse":
        return export_envelope(root)
    if fmt == "summary":
        return export_summary(root)
    return export_matrix(root)


def load_envelope(root: Path | str) -> dict:
    """Load the attested envelope; refuse without one (ATT-EXPORTS-FROM-ATTESTATIONS)."""
    att_path = Path(root) / ".traceagent" / "attest.json"
    if not att_path.exists():
        raise FileNotFoundError(
            "no attestation found — export refused (ATT-EXPORTS-FROM-ATTESTATIONS)")  # noqa: E501
    try:
        envelope = json.loads(att_path.read_text())
    except json.JSONDecodeError as exc:
        raise EnvelopeFormatError(
            f"attestation file {att_path} is not valid JSON: {exc}") from exc
    if not isinstance(envelope, dict):
        raise EnvelopeFormatError(
            f"attestation file {att_path} must contain a JSON object, "
            f"got {type(envelope).__name__}")
    return envelope


def export_envelope(root: Path | str) -> dict:
    """Raw DSSE envelope export: the attested envelope exactly as stored, validated."""
    envelope = load_envelope(root)
    parse_envelope(envelope)  # refuse to hand on a structurally malformed envelope
    return envelope


def _predicate_problems(predicate: dict) -> list[str]:
    """Every way ``predicate`` violates the TraceManifest shape, at once."""
    problems = [f"'predicate.{key}' missing" for key in ("coverage", "model_dependent")
                if key not in predicate]
    if "coverage" in predicate and not isinstance(predicate["coverage"], dict):
        problems.append("'predicate.coverage' must be an object, got "
                        f"{type(predicate['coverage']).__name__}")
    if ("model_dependent" in predicate
            and not isinstance(predicate["model_dependent"], bool)):
        problems.append("'predicate.model_dependent' must be a bool, got "
                        f"{type(predicate['model_dependent']).__name__}")
    return problems


def export_matrix(root: Path | str) -> dict:
    """Build a trace matrix from the attested envelope; refuse without one."""
    payload = parse_payload(load_envelope(root))
    predicate = payload["predicate"]
    problems = _predicate_problems(predicate)
    if problems:
        raise EnvelopeFormatError("attested predicate is incomplete: " + "; ".join(problems))
    clauses = []
    for entry in payload["subject"]:
        try:
            clauses.append(entry["name"])
        except (TypeError, KeyError) as exc:
            raise EnvelopeFormatError(f"malformed subject entry {entry!r}: {exc}") from exc
    return {
        "predicateType": payload["predicateType"],
        "clauses": clauses,
        "coverage": predicate["coverage"],
        "model_dependent": predicate["model_dependent"],
    }


def export_summary(root: Path | str) -> str:
    """Human-readable attestation summary derived from the attested envelope."""
    envelope = load_envelope(root)
    payload = parse_payload(envelope)
    predicate = payload["predicate"]
    problems = _predicate_problems(predicate)
    if problems:
        raise EnvelopeFormatError("attested predicate is incomplete: " + "; ".join(problems))
    coverage = predicate["coverage"]
    covered = (str(coverage["clauses_covered"])
               if coverage.get("clauses_covered") is not None
               else "unknown")
    models = predicate.get("models") or {}
    deferred = predicate.get("deferred") or []
    keyids = _signature_keyids(envelope)
    lines = [
        "TraceAgent attestation summary",
        "==============================",
        f"statement type: {payload['_type']}",
        f"predicate type: {payload['predicateType']}",
        f"payload type:   {envelope.get('payloadType', '?')}",
        f"signatures:     {len(keyids)}"
        + (f" (keyid {keyids[0][:16]}…)" if keyids else ""),
        f"coverage:       clauses covered {covered}",
        f"models:         producer={models.get('producer') or 'unspecified'} "
        f"gate={models.get('gate') or 'unspecified'} "
        f"(model_dependent: {predicate.get('model_dependent', False)})",
        f"deferred:       {len(deferred)} milestone target(s)",
        f"subjects:       {len(payload['subject'])} clause digest(s)",
    ]
    for entry in payload["subject"]:
        try:
            lines.append(f"  - {entry['name']}")
            lines.append(f"      sha256:{entry['digest']['sha256']}")
        except (TypeError, KeyError):
            lines.append(f"  - (malformed subject entry: {entry!r})")
    return "\n".join(lines)


def _signature_keyids(envelope: dict) -> list[str]:
    signatures = envelope.get("signatures", [])
    if isinstance(signatures, dict):  # legacy {keyid: sig} form
        return [str(keyid) for keyid in signatures]
    return [str(sig.get("keyid", "?")) for sig in signatures if isinstance(sig, dict)]

