"""Key-document timestamps: RFC 3339 parsing and UTC coercion (keys.py).

The policy half of the key format fails closed on ambiguity: a validity
window without a timezone is rejected, everything admitted is normalized to
UTC. The pins here hold that surface where mutants drifted it: the typed
non-string rejection, the Z/z suffix handling, and _as_utc's branch table.
"""
from datetime import datetime, timedelta, timezone

import pytest

from zft.attest import keys as keys_mod
from zft.attest.errors import KeyValidationError
from zft.attest.keys import _as_utc, parse_timestamp

UTC = timezone.utc


def test_parse_timestamp_normalizes_offsets_and_suffixes_to_utc():
    # +02:00 converts (12:00+02:00 is 10:00Z), not merely re-labeled
    got = parse_timestamp("2026-09-06T12:00:00+02:00", "t")
    assert got == datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC)
    assert got.tzinfo is UTC
    assert parse_timestamp("2026-09-06T00:00:00Z", "t") == \
        datetime(2026, 9, 6, 0, 0, 0, tzinfo=UTC)
    # lowercase 'z' is not accepted by fromisoformat (verified on 3.13); the
    # Z/z suffix replacement is what admits it — a key file carrying one must
    # still verify
    assert parse_timestamp("2026-09-06T00:00:00z", "t") == \
        datetime(2026, 9, 6, 0, 0, 0, tzinfo=UTC)


def test_parse_timestamp_rejects_trailing_garbage_rather_than_absorbing_it():
    # 'X' ends no valid RFC 3339 timestamp and must not ride the Z/z suffix
    # branch: with the suffix set widened ('Zz' -> 'XXZzXX') the X is stripped
    # and '+00:00' appended, silently admitting the garbage as a UTC moment
    with pytest.raises(
        KeyValidationError,
        match=r"^t is not a valid RFC 3339 timestamp '2026-09-06T00:00:00X':",
    ):
        parse_timestamp("2026-09-06T00:00:00X", "t")


@pytest.mark.parametrize("bad,reprd", [(42, "42"), (None, "None"), ([], "[]")])
def test_parse_timestamp_nonstring_rejection_is_typed_and_exact(bad, reprd):
    with pytest.raises(
        KeyValidationError,
        match=r"^t must be an RFC 3339 timestamp string, got " + reprd.replace("[", r"\[") + r"$",
    ):
        parse_timestamp(bad, "t")


def test_as_utc_coerces_naive_to_utc_and_converts_offsets():
    # naive is interpreted as UTC (replace, not local-shift: on a CEST box the
    # local-shift mutant renders 11:00Z here — the value pin sees it; on a UTC
    # host that particular mutant is equivalent by environment)
    assert _as_utc(datetime(2026, 1, 1, 12, 0, 0)) == \
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert _as_utc(datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)).tzinfo is UTC
    # aware offsets convert, they do not re-label: astimezone(None) would
    # return the wall clock in local tz (verified 12:00 CEST != 10:00Z)
    got = _as_utc(datetime(2026, 9, 6, 12, 0, 0,
                           tzinfo=timezone(timedelta(hours=2))))
    assert got == datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC)
    assert got.tzinfo is UTC


def test_as_utc_now_is_requested_in_utc(monkeypatch):
    calls = {}
    real_datetime = datetime

    class _FakeDT:
        @staticmethod
        def now(tz=None):
            calls["tz"] = tz
            if tz is None:
                return real_datetime(2026, 9, 14, 12, 0, 0)
            return real_datetime(2026, 9, 14, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(keys_mod, "datetime", _FakeDT)
    moment = keys_mod._as_utc(None)
    assert calls["tz"] is UTC, "the expiry clock must be asked for UTC"
    assert moment.tzinfo is not None, "a naive now() would break window math"
