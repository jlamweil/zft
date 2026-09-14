"""Oracle-artifact generation (D-CG, plan C-12): predicate terms bind to the
contract-side oracle, never to the producer module (the V2 self-reference lesson).

Deterministic by construction: inputs are validated up front (TypeError for
type violations, OracleError for value violations), rendering iterates in
sorted order, and the finished module is compile-checked before it is
returned — so identical inputs always yield an identical, importable source.
"""
from __future__ import annotations

import keyword
import re
from collections.abc import Mapping

_STDLIKE = {"forall", "exists", "in", "not", "and", "or", "member_of", "all_", "set", "if"}

_SYMBOL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# prime desugaring: v' compiles to next_v, so the oracle needs next_v even
# though the surface symbol is v (campaign F1, 2026-09-07)
_PRIME_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*'")


class OracleError(ValueError):
    """Predicate references a symbol with no oracle implementation."""


def _require_str(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{what} must be str, got {type(value).__name__}: {value!r}")
    return value


def _require_identifier(value: str, what: str) -> str:
    if not value.isidentifier() or keyword.iskeyword(value):
        raise OracleError(f"{what} must be a non-keyword identifier, got {value!r}")
    return value


def _require_name_bag(value: object, what: str) -> list[str]:
    if isinstance(value, str) or not isinstance(value, (list, tuple, set, frozenset)):
        raise TypeError(
            f"{what} must be a list of symbol names, got "
            f"{type(value).__name__}: {value!r}"
        )
    return [_require_identifier(_require_str(name, f"{what} entry"), f"{what} entry")
            for name in value]


def predicate_symbols(prop: str) -> set[str]:
    """Names referenced by the predicate (callable + identifier leaves).

    Primed names count under their desugared form: `v'` emits `next_v`, so a
    prime here demands a `next_v` oracle implementation, not a `v` one.
    """
    _require_str(prop, "predicate")
    toks = set(_SYMBOL_RE.findall(prop))
    toks |= {f"next_{name}" for name in _PRIME_RE.findall(prop)}
    return toks - _STDLIKE - {"CLAUSES"}


def _check_impl_compiles(name: str, impl: str) -> None:
    try:
        compile(impl, f"<oracle-term:{name}>", "exec")
    except SyntaxError as e:
        detail = f"{e.msg} (line {e.lineno})"
        raise OracleError(f"oracle term {name!r} does not compile: {detail} in {impl!r}") from e


def generate_oracle(
    alias: str,
    oracle_terms: Mapping[str, str],
    producer_terms: list[str],
    symbols: set[str] | None = None,
) -> str:
    """Render an oracle module source for a clause; raises on invalid input.

    Every predicate symbol that is neither a producer term nor DSL built-in must
    have an oracle implementation. Validation contract:
      - alias: non-empty str (TypeError if not str, OracleError if blank)
      - oracle_terms: Mapping of identifier -> compilable Python source
      - producer_terms: list of identifiers (a bare string is a caller bug)
      - symbols: optional set of identifiers
    """
    _require_str(alias, "alias")
    if not alias.strip():
        raise OracleError("alias must be a non-empty clause identifier, got ''")
    if isinstance(oracle_terms, str) or not isinstance(oracle_terms, Mapping):
        raise TypeError(
            f"oracle_terms must be a Mapping of name -> source, got "
            f"{type(oracle_terms).__name__}: {oracle_terms!r}"
        )
    for name, impl in oracle_terms.items():
        _require_identifier(_require_str(name, "oracle term name"), "oracle term name")
        _check_impl_compiles(name, _require_str(impl, f"oracle term {name!r} source"))
    _require_name_bag(producer_terms, "producer_terms")
    if symbols is not None:
        _require_name_bag(symbols, "symbols")

    refs = (symbols or set()) - set(producer_terms)
    missing = sorted(refs - set(oracle_terms))
    if missing:
        raise OracleError(f"oracle missing implementations for symbols: {missing}")
    parts = [
        f'"""Oracle for clause {alias} — contract-side reference (authored with the contract)."""',
        "",
    ]
    for name in sorted(oracle_terms):
        impl = oracle_terms[name]
        parts.append(impl.rstrip())
        parts.append("")
    if producer_terms:
        parts.append("# PRODUCER-side symbols (resolved at gate time, never imported here):")
        for name in sorted(producer_terms):
            parts.append(f"#   {name}")
        parts.append("")
    src = "\n".join(parts)
    try:
        compile(src, f"<oracle:{alias}>", "exec")
    except SyntaxError as e:  # defensive: sorted, validated parts should never trip this
        raise OracleError(f"rendered oracle for {alias!r} does not compile: {e.msg}") from e
    return src
