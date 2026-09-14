"""RFC 8785 (JCS) conformance: vectors from the RFC + Python-specific edges."""
import json

import pytest

from traceagent.attest.jcs import canonical_text, canonicalize


def test_rfc8785_section_3_2_2_number_and_string_vector():
    # RFC 8785 §3.2.2 example (keys re-sorted per §3.2.3): ECMAScript number
    # rendering — 1E30 → "1e+30", 4.50 → "4.5", 2e-3 → "0.002", 1e-27 stays
    # exponential — and JSON.stringify string escaping (raw €, lowercase
    # \u000f, short \n, \" for quotes, unescaped slashes).
    value = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3,
                    0.000000000000000000000000001],
        "string": "€$\u000f\nA'B\"\\\\\"/",
        "literals": [None, True, False],
    }
    expected = (
        r"""{"literals":[null,true,false],"numbers":[333333333.3333333,"""
        r"""1e+30,4.5,0.002,1e-27],"string":"€$\u000f\nA'B\"\\\\\"/"}"""
    )
    assert canonical_text(value) == expected


def test_rfc8785_section_3_2_3_key_order_vector():
    # RFC 8785 §3.2.3: keys sort by UTF-16 code units — the emoji (surrogate
    # pair D83D DE00) sorts BEFORE U+FB33, but AFTER U+20AC.  A plain
    # code-point sort would put the emoji last; U+0080 stays literal.
    value = {
        "\u20ac": "Euro Sign",
        "\r": "Carriage Return",
        "\ufb33": "Hebrew Letter Dalet With Dagesh",
        "1": "One",
        "\U0001f600": "Emoji: Grinning Face",
        "\u0080": "Control",
        "\u00f6": "Latin Small Letter O With Diaeresis",
    }
    expected = (
        '{"\\r":"Carriage Return","1":"One","\u0080":"Control",'
        '"\u00f6":"Latin Small Letter O With Diaeresis",'
        '"\u20ac":"Euro Sign","\U0001f600":"Emoji: Grinning Face",'
        '"\ufb33":"Hebrew Letter Dalet With Dagesh"}'
    )
    assert canonical_text(value) == expected


def test_number_serialization_ecmascript_notation():
    assert canonical_text(1.0) == "1"
    assert canonical_text(15.0) == "15"
    assert canonical_text(-1.5) == "-1.5"
    assert canonical_text(-0.0) == "0"
    assert canonical_text(0.1) == "0.1"
    assert canonical_text(1e20) == "100000000000000000000"  # fixed below 1e21
    assert canonical_text(1e21) == "1e+21"  # ECMA switches at 1e21, repr at 1e16
    assert canonical_text(1e-6) == "0.000001"  # fixed at 1e-6
    assert canonical_text(1e-7) == "1e-7"  # exponent form, unpadded exponent


def test_literal_and_container_serialization():
    assert canonical_text(None) == "null"
    assert canonical_text(True) == "true"
    assert canonical_text(False) == "false"
    assert canonical_text([1, [2, {"b": {}, "a": {}}]]) == '[1,[2,{"a":{},"b":{}}]]'
    assert canonicalize({"é": "ü"}) == '{"é":"ü"}'.encode("utf-8")
    assert canonicalize({}) == b"{}"


def test_rejects_non_jcs_input():
    # every rejection pins its typed message: a bare ValueError would pass a
    # mutant that raises ValueError(None) (mut-dsl shard 2026-09-07 survivors
    # _emit_17/_emit_51/_number_token_4/_string_token_4/_sorted_keys_4/11)
    with pytest.raises(ValueError, match="non-JSON number nan"):  # beyond JSON numbers
        canonical_text(float("nan"))
    with pytest.raises(ValueError, match="non-JSON number inf"):
        canonical_text(float("inf"))
    with pytest.raises(ValueError, match="exceeds the IEEE 754 double-safe range"):
        canonical_text(2 ** 53)
    with pytest.raises(ValueError, match="string is not valid Unicode"):
        canonical_text("\ud800")  # unpaired surrogate cannot round-trip UTF-8
    with pytest.raises(ValueError, match="object keys must be strings, got int"):
        canonical_text({1: "x"})  # JSON object keys must be strings
    with pytest.raises(ValueError, match="invalid object key"):
        canonical_text({"\ud800": 1})  # surrogate key breaks the UTF-16 sort
    with pytest.raises(ValueError, match="cannot canonicalize set value"):
        canonical_text({"a": {object()}})  # no Python-only types
    with pytest.raises(ValueError, match="cannot canonicalize object value"):
        canonical_text(object())


def test_canonicalization_is_idempotent_through_parse():
    for value in (
        {"numbers": [333333333.33333329, 1e30, 2e-3], "s": "€\n\\"},
        {"\U0001f600": 1, "\ufb33": 2},
    ):
        once = canonical_text(value)
        assert canonical_text(json.loads(once)) == once


def test_integral_float_at_double_boundary_renders_but_reparse_is_rejected():
    """The FUZZ-2 boundary (L-4 carve-out, made explicit): an integral float
    ≥ 2**53 renders RFC-exactly (ES6 number formatting emits no '.0'), but
    that canonical text re-parses as an INT outside the deliberate
    double-safe bound — so parse∘canonicalize is not the identity there and
    canonicalize refuses it. Fail-closed, never silently switching number
    semantics; the fuzz property scopes itself to the documented domain."""
    once = canonical_text(9007199254740992.0)
    assert once == "9007199254740992"
    assert json.loads(once) == 2**53  # legal render, but now an int...
    with pytest.raises(ValueError):  # ...outside the documented int bound
        canonicalize(json.loads(once))


# --- GATE-MUTATION-KILL (mut-attest-negotiate shard 2026-09-07) --------------

# GATE-MUTATION-KILL: the int-range boundary is INCLUSIVE — 2**53-1 must
# render (kills `abs(value) > _MAX_SAFE_INTEGER` -> `>=`, _emit_16)
def test_max_safe_integer_boundary_is_inclusive():
    assert canonical_text(9007199254740991) == "9007199254740991"
    assert canonical_text(-9007199254740991) == "-9007199254740991"


# GATE-MUTATION-KILL: exponent-form edge vectors — fractional mantissa keeps
# its dot and full digits (kills _number_token_81..86, the k==1 dot-drop and
# exponent-sign mutants), subnormal/normal extremes pin the e-notation window
def test_number_vectors_pin_exponent_form_edges():
    assert canonical_text(1.5e-8) == "1.5e-8"  # k>1 mantissa, negative exponent
    assert canonical_text(-1.5e-8) == "-1.5e-8"
    assert canonical_text(5e-324) == "5e-324"  # min subnormal
    assert canonical_text(1.7976931348623157e308) == "1.7976931348623157e+308"
    assert canonical_text(0.30000000000000004) == "0.30000000000000004"
    assert canonical_text(1234567890.123) == "1234567890.123"


def test_exponent_form_keeps_the_decimal_point():
    # >=2 significant digits in exponent form: ECMAScript prints 1.5e21 as
    # "1.5e+21", never "15e+21" — the dot is decided by the k > 1 branch
    assert canonical_text(1.5e21) == "1.5e+21"
    assert canonical_text(1.25e-7) == "1.25e-7"
