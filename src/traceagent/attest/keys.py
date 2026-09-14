"""Verification-key documents: the file format ``attest --key-out`` writes,
``verify --key-in`` reads, and the key-policy gates evaluated before any
cryptographic work (ATTACK_MATRIX G7; closes the revocation/expiry/pinning
half of SECURITY_REVIEW H-1 and the keyid-loading half of L-5).

File format (superset of the pre-policy format; unknown fields are rejected
so a typo like ``"expire"`` can never silently disable an expiry):

    {"keytype": "ed25519", "scheme": "ed25519",
     "keyval": {"public": "<hex>"}, "keyid": "<hex64>",
     "revoked": false,                       # optional, operator-set
     "not_before": "2026-09-06T00:00:00Z",   # optional, inclusive
     "expires": "2026-12-31T00:00:00Z"}      # optional, exclusive

The crypto half is a stock securesystemslib Key. The policy fields are
custody metadata maintained where the key is published; they are enforced
by :meth:`KeyDocument.check` (directly or through
``verify_attestation(key_document=…)``). Absent metadata means "no claim" —
with no policy fields the trust model is exactly the pre-policy one (R1/R2).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from securesystemslib.exceptions import FormatError
from securesystemslib.signer import Key

from traceagent.attest.errors import KeyValidationError

_FIELDS = {"keytype", "scheme", "keyval", "keyid", "revoked", "not_before", "expires"}


def parse_timestamp(text: object, what: str) -> datetime:
    """Parse an RFC 3339 timestamp; naive (offset-less) values are rejected —
    a validity window without a timezone is ambiguous and fail-closed."""
    if not isinstance(text, str) or not text:
        raise KeyValidationError(
            f"{what} must be an RFC 3339 timestamp string, got {text!r}")
    raw = text[:-1] + "+00:00" if text[-1] in "Zz" else text
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise KeyValidationError(
            f"{what} is not a valid RFC 3339 timestamp {text!r}: {exc}") from exc
    if moment.tzinfo is None:
        raise KeyValidationError(
            f"{what} must carry a UTC offset ('Z' or '+00:00'), got {text!r}")
    return moment.astimezone(timezone.utc)


def _as_utc(moment: datetime | None) -> datetime:
    if moment is None:
        return datetime.now(timezone.utc)
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None \
        else moment.astimezone(timezone.utc)


@dataclass(frozen=True)
class KeyDocument:
    """A public key plus its operator-maintained policy metadata."""

    key: Key
    keyid: str
    revoked: bool = False
    not_before: datetime | None = None  # inclusive
    expires: datetime | None = None     # exclusive

    @classmethod
    def from_dict(cls, data: object) -> "KeyDocument":
        if not isinstance(data, dict):
            raise KeyValidationError(
                f"key document must be a JSON object, got {type(data).__name__}")
        unknown = set(data) - _FIELDS
        if unknown:
            raise KeyValidationError(
                f"unknown key file field(s) {sorted(unknown)} — "
                "policy fields are enforced, typos must not be ignored")
        keyid = data.get("keyid")
        if not isinstance(keyid, str) or not keyid:
            raise KeyValidationError(
                f"key file carries no usable 'keyid' (got {keyid!r}) — "
                "DSSE verification matches signatures by keyid")
        try:
            key = Key.from_dict(
                keyid=keyid,
                key_dict={f: data[f] for f in ("keytype", "scheme", "keyval")
                          if f in data})
        except (KeyError, TypeError, ValueError, FormatError) as exc:
            raise KeyValidationError(f"unusable verification key: {exc}") from exc
        revoked = data.get("revoked", False)
        if not isinstance(revoked, bool):
            raise KeyValidationError(f"'revoked' must be a bool, got {revoked!r}")
        return cls(
            key=key,
            keyid=keyid,
            revoked=revoked,
            not_before=parse_timestamp(data["not_before"], "'not_before'")
            if "not_before" in data else None,
            expires=parse_timestamp(data["expires"], "'expires'")
            if "expires" in data else None,
        )

    @classmethod
    def load(cls, path: Path | str) -> "KeyDocument":
        text = Path(path).read_text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise KeyValidationError(
                f"key file {path} is not valid JSON: {exc}") from exc
        return cls.from_dict(data)

    def to_dict(self) -> dict:
        data = {**self.key.to_dict(), "keyid": self.keyid}
        if self.revoked:
            data["revoked"] = True
        if self.not_before is not None:
            data["not_before"] = self.not_before.isoformat()
        if self.expires is not None:
            data["expires"] = self.expires.isoformat()
        return data

    def check(self, *, now: datetime | None = None,
              expect_keyid: str | None = None) -> Key:
        """Enforce the policy gates and return the key on success.

        Order is most-diagnostic-first: a pin mismatch means the verifier is
        not even holding the key it meant to hold; revocation is an explicit
        operator decision; then the validity window. All gates are cheap and
        run before any cryptographic work (matrix KEY-9..13).
        """
        moment = _as_utc(now)
        if expect_keyid is not None and expect_keyid != self.keyid:
            raise KeyValidationError(
                f"keyid pin mismatch: expected {expect_keyid!r}, "
                f"key file carries {self.keyid!r}")
        if self.revoked:
            raise KeyValidationError(
                f"verification key {self.keyid!r} is revoked")
        if self.not_before is not None and moment < self.not_before:
            raise KeyValidationError(
                f"key {self.keyid!r} is not valid before "
                f"{self.not_before.isoformat()} (now {moment.isoformat()})")
        if self.expires is not None and moment >= self.expires:
            raise KeyValidationError(
                f"key {self.keyid!r} expired at {self.expires.isoformat()} "
                f"(now {moment.isoformat()})")
        return self.key
