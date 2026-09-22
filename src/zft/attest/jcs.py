"""RFC 8785 JSON Canonicalization Scheme (JCS) — the serialization we sign over.

securesystemslib's ``encode_canonical`` implements the older OLPC "Canonical
JSON" draft, which diverges from RFC 8785: it cannot serialize floats at all,
and orders object keys by Unicode code point instead of UTF-16 code units.
DSSE payloads here are canonicalized with this module instead, so any
independent JCS implementation re-derives byte-identical bytes for a signature.

Implements RFC 8785 §3.2: ECMAScript ``JSON.stringify`` string escaping and
``Number::toString`` number serialization, object keys sorted by UTF-16 code
units, output encoded as UTF-8.
"""
from __future__ import annotations

import json
import math
from typing import Any

# Largest integer exactly representable as an IEEE 754 double (RFC 8785 §3.1:
# values outside double precision are not interoperable JCS input).
_MAX_SAFE_INTEGER = (1 << 53) - 1


def canonical_text(value: Any) -> str:
    """Serialize ``value`` to canonical JSON text per RFC 8785."""
    fragments: list[str] = []
    _emit(value, fragments)
    return "".join(fragments)


def canonicalize(value: Any) -> bytes:
    """Serialize ``value`` to canonical JSON bytes per RFC 8785 (UTF-8)."""
    return canonical_text(value).encode("utf-8")


def _emit(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        # bools were handled above; Python ints are unbounded but JCS input
        # must stay within IEEE 754 double precision.
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ValueError(
                f"JCS: integer {value} exceeds the IEEE 754 double-safe range")
        out.append(str(value))
    elif isinstance(value, float):
        out.append(_number_token(value))
    elif isinstance(value, str):
        out.append(_string_token(value))
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _emit(item, out)
        out.append("]")
    elif isinstance(value, dict):
        out.append("{")
        for i, key in enumerate(_sorted_keys(value)):
            if i:
                out.append(",")
            out.append(_string_token(key))
            out.append(":")
            _emit(value[key], out)
        out.append("}")
    else:
        raise ValueError(
            f"JCS: cannot canonicalize {type(value).__name__} value: {value!r}")


def _sorted_keys(obj: dict) -> list[str]:
    keys = list(obj)
    for key in keys:
        if not isinstance(key, str):
            raise ValueError(
                f"JCS: object keys must be strings, got {type(key).__name__}")
    # UTF-16 code-unit order (RFC 8785 §3.2.3): big-endian UTF-16 bytes compare
    # exactly like the uint16 sequences the spec sorts by.  This differs from
    # code-point order whenever non-BMP characters meet U+E000..U+FFFF.
    try:
        keys.sort(key=lambda k: k.encode("utf-16-be"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"JCS: invalid object key: {exc}") from exc
    return keys


def _string_token(text: str) -> str:
    # RFC 8785 input is parsed JSON; unpaired surrogates cannot round-trip
    # through UTF-8 and would silently corrupt signatures.
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"JCS: string is not valid Unicode: {exc}") from exc
    # json.dumps(ensure_ascii=False) escapes exactly like JSON.stringify:
    # \b \t \n \f \r, \" and \\, other C0 controls as lowercase \u00xx,
    # everything non-ASCII literal.
    return json.dumps(text, ensure_ascii=False)


def _number_token(value: float) -> str:
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"JCS: cannot canonicalize non-JSON number {value!r}")
    if value == 0:  # 0.0 and -0.0 both serialize as "0" (RFC 8785 §3.1.1)
        return "0"
    sign = "-" if value < 0 else ""
    # repr() yields the same shortest round-trip digits as ECMAScript's
    # Number::toString; re-render those digits in ECMA notation, which
    # switches to exponent form only outside 1e-6 .. 1e21.
    mantissa, _, exp_text = repr(abs(value)).partition("e")
    exponent = int(exp_text) if exp_text else 0
    int_part, _, frac_part = mantissa.partition(".")
    digits = int_part + frac_part
    point = len(int_part) + exponent  # digits before the decimal point
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    s = stripped.rstrip("0") or "0"
    k, n = len(s), point
    if k <= n <= 21:
        return sign + s + "0" * (n - k)
    if 0 < n <= 21:
        return sign + s[:n] + "." + s[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * -n + s
    e = n - 1
    return (sign + s[:1] + ("." + s[1:] if k > 1 else "")
            + "e" + ("+" if e >= 0 else "-") + str(abs(e)))
