"""DSL v1 predicate grammar (VERIFIED-DESIGNS D-DSL) — lab-promoted.

Grammar forms (each pinned by a golden test):
  quantifiers    forall x: / forall a, b: / forall exports e: / forall pairs (a, b): /
                 forall clauses c in g:   (recursive — nested exists/forall allowed)
                 exists x: compiles faithfully as not(forall x: not P)
  implication    A => B   ->  (not (A)) or (B)
  membership     x in S   ->  member_of(x, S)
  prime          v'       ->  next_v
  set-builder    {c | P(c)}  ->  { c for c in CLAUSES if P(c) }
  set literal    {A, B, C}
  arithmetic     conventional precedence, left-assoc: * / bind tighter than + -;
                 comparisons bind looser than both (pinned byte-exact)
Reserved-word collisions are corpus-level rewrites (patch P1): in( -> member_of(.
DSL_VERSION = "v1".

Edge cases fail gracefully: tokens carry their source offset, and every
lexing, parsing, or codegen failure raises ParseError with the position, a
caret-marked excerpt, and the expected shape — never a bare token dump, and
never a silent None.
"""
from __future__ import annotations

import re
from typing import NamedTuple

DSL_VERSION = "v1"

TOKEN_RE = re.compile(r"""
    \s*(?:
      (?P<quant>forall|exists) |
      (?P<num>\d+) |
      (?P<prime>[A-Za-z_][A-Za-z0-9_]*)(?=') |
      (?P<in>\bin\b) |
      (?P<name>[A-Za-z_]\w*) |
      (?P<geq>=>) |
      (?P<op>[!=<>]=|[<>+\-*/]) |
      (?P<dot>\.) |
      (?P<setbld>\{[A-Za-z_][\w ]*\|) |
      (?P<lp>\() | (?P<rp>\)) | (?P<lb>\{) | (?P<rb>\}) |
      (?P<colon>:) | (?P<pipe>\|) | (?P<comma>,)
    )""", re.X)

_KIND_DISPLAY = {
    "name": "identifier",
    "colon": "':'",
    "rp": "')'",
    "rb": "'}'",
    "lp": "'('",
    "lb": "'{'",
    "setbld": "set-builder '{x |'",
    "quant": "'forall'/'exists'",
    "in": "'in'",
}


class Tok(NamedTuple):
    kind: str
    value: str
    pos: int  # offset of the token in the source


class ParseError(ValueError):
    """Predicate is not parseable DSL v1."""


def _point(src: str, pos: int) -> str:
    """Caret-marked excerpt around pos: '…context…' plus a ^ line."""
    lo, hi = max(0, pos - 20), min(len(src), pos + 20)
    body = src[lo:hi].replace("\n", "\\n")
    return f"{body!r}\n    {' ' * (pos - lo)}^"


def _display(tok: Tok) -> str:
    if tok.kind == "end":
        return "end of input"
    return f"{tok.value!r} ({tok.kind})"


def tokenize(src: str) -> tuple[list[Tok], None] | tuple[None, str]:
    toks, pos = [], 0
    while pos < len(src):
        if src[pos] == "'" or src[pos].isspace():  # primes are consumed by the lexer
            pos += 1
            continue
        m = TOKEN_RE.match(src, pos)
        if not m:
            return None, (
                f"unlexable input at position {pos}: {src[pos]!r}\n"
                f"  at: {_point(src, pos)}"
            )
        if m.lastgroup:
            toks.append(Tok(m.lastgroup, m.group(m.lastgroup), m.start(m.lastgroup)))
        pos = m.end()
    toks.append(Tok("end", "", len(src)))
    return toks, None


class P:
    def __init__(self, toks: list[Tok], src: str):
        self.toks, self.i, self.src = toks, 0, src

    def peek(self) -> Tok:
        return self.toks[self.i]

    def take(self, kind: str | None = None) -> Tok:
        t = self.toks[self.i]
        if kind and t.kind != kind:
            expected = _KIND_DISPLAY.get(kind, kind)
            found = "end of input" if t.kind == "end" else _display(t)
            raise ParseError(
                f"expected {expected} but found {found} at position {t.pos}\n"
                f"  at: {_point(self.src, t.pos)}"
            )
        self.i += 1
        return t

    def parse(self) -> str:
        e = self.quant()
        t = self.peek()
        if t.kind != "end":
            raise ParseError(
                f"unexpected trailing input after the expression: {_display(t)} "
                f"at position {t.pos}\n  at: {_point(self.src, t.pos)}"
            )
        return e

    def quant(self) -> str:
        if self.peek().kind == "quant":
            q = self.take()
            groups = [self.binder_group()]
            while self.peek().kind == "comma":
                self.take()
                groups.append(self.binder_group())
            self.take("colon")
            body = self.quant()
            bound = [v for g in groups for v in g]
            # exists x: P  ≡  not (forall x: not P) — the negation rides inside
            # the lambda so the emitted runtime contract stays `all_`-only.
            # Compiling exists as a bare forall silently inverted the meaning
            # of every accepted existential clause.
            if q.value == "exists":
                body = f"(not ({body}))"
                return f"(not (all_({bound!r}, lambda {', '.join(bound)}: {body})))"
            return f"(all_({bound!r}, lambda {', '.join(bound)}: {body}))"
        return self.implies()

    def binder_group(self) -> list[str]:
        # forms:  var | domain var | pairs (a, b) | var in domain
        names = [self.take("name").value]
        while self.peek().kind == "name" and self.toks[self.i + 1].kind in ("comma", "colon", "lp", "in", "name"):  # noqa: E501
            names.append(self.take("name").value)
        if self.peek().kind == "lp":                   # tuple group: pairs (a, b)
            self.take()
            inner = [self.take("name").value]
            while self.peek().kind == "comma":
                self.take()
                inner.append(self.take("name").value)
            self.take("rp")
            return inner
        if self.peek().kind == "in":                   # membership binder: var in domain
            self.take()
            self.take("name")
        return [names[-1]]                             # last name is the variable

    def implies(self) -> str:
        a = self.or_()
        if self.peek().kind == "geq":
            self.take()
            return f"(not ({a})) or ({self.implies()})"
        return a

    def or_(self) -> str:
        a = self.and_()
        while self.peek().kind == "name" and self.peek().value == "or":
            self.take()
            a = f"({a}) or ({self.and_()})"
        return a

    def and_(self) -> str:
        a = self.cmp()
        while self.peek().kind == "name" and self.peek().value == "and":
            self.take()
            a = f"({a}) and ({self.cmp()})"
        return a

    def cmp(self) -> str:
        a = self.sum()
        while self.peek().kind in ("op", "in"):
            op = self.take()
            if op.kind == "in":
                a = f"member_of({a}, {self.sum()})"
            else:
                a = f"({a} {op.value} {self.sum()})"
        return a

    def sum(self) -> str:
        a = self.mul()
        while self.peek().kind == "op" and self.peek().value in ("+", "-"):
            op = self.take().value
            a = f"({a} {op} {self.mul()})"
        return a

    def mul(self) -> str:
        a = self.atom()
        while self.peek().kind == "op" and self.peek().value in ("*", "/"):
            op = self.take().value
            a = f"({a} {op} {self.atom()})"
        return a

    def atom(self) -> str:
        t = self.peek()
        if t.kind == "prime":
            self.take()
            return f"next_{self.suffix_name(t.value)}"
        if t.kind == "lp":
            self.take()
            e = self.quant()
            self.take("rp")
            return f"({e})"
        if t.kind == "setbld":
            inner = self.take("setbld").value
            var = inner[1:inner.index("|")].strip()
            body = self.quant()
            self.take("rb")
            return f"{{ {var} for {var} in CLAUSES if {body} }}"
        if t.kind == "lb":                             # set literal: {A, B, C}
            self.take()
            if self.peek().kind == "rb":
                raise ParseError(
                    "empty set literal '{}' is not valid DSL — use a "
                    f"set-builder '{{x | P(x)}}' instead at position {t.pos}\n"
                    f"  at: {_point(self.src, t.pos)}"
                )
            items = [self.sum()]
            while self.peek().kind == "comma":
                self.take()
                items.append(self.sum())
            self.take("rb")
            return f"{{{', '.join(items)}}}"
        if t.kind == "quant":
            return self.quant()
        if t.kind == "num":
            return self.take().value
        if t.kind == "name":
            if t.value == "not":
                self.take()
                return f"(not ({self.quant()}))"
            return self.call_chain(self.take().value)
        if t.kind == "end":
            raise ParseError(
                f"expression is empty or incomplete (reached end of input at "
                f"position {t.pos})\n  at: {_point(self.src, t.pos)}"
            )
        raise ParseError(
            f"unexpected {_display(t)} at position {t.pos}\n"
            f"  at: {_point(self.src, t.pos)}"
        )

    def suffix_name(self, base: str) -> str:
        # prime target: v' -> next_v; call args render v'(a, b) -> next_v(a, b)
        out = base
        while self.peek().kind == "lp":
            self.take()
            args = [self.quant()]
            while self.peek().kind == "comma":
                self.take()
                args.append(self.quant())
            self.take("rp")
            out = f"{out}({', '.join(args)})"
        return out

    def call_chain(self, first: str) -> str:
        out = first
        while True:
            t = self.peek()
            if t.kind == "lp":
                self.take()
                args = [self.quant()]
                while self.peek().kind == "comma":
                    self.take()
                    args.append(self.quant())
                self.take("rp")
                out = f"{out}({', '.join(args)})"
            elif t.kind == "dot":
                self.take()
                out = f"{out}.{self.take('name').value}"
            else:
                return out


def compile_predicate(prop: str) -> str:
    """Compile a DSL predicate to a Python boolean expression.

    Raises ParseError on any failure — lexing, parsing, or compilation of the
    generated code — with the position, a caret-marked excerpt, and for
    codegen failures the offending generated Python.
    """
    if not isinstance(prop, str):
        raise TypeError(f"predicate must be str, got {type(prop).__name__}: {prop!r}")
    toks, err = tokenize(prop)
    if err:
        raise ParseError(err)
    try:
        py = P(toks, prop).parse()
    except RecursionError as e:
        raise ParseError(
            f"expression nests too deeply to parse (recursion limit: {e})"
        ) from e
    try:
        compile(py, "<dsl>", "eval")
    except SyntaxError as e:
        raise ParseError(
            f"compiled DSL generated invalid Python: {e.msg}\n"
            f"  generated: {py}"
        ) from e
    return py
