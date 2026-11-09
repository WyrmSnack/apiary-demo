"""Formula tokens, grammar and canonical form (SPEC section 3)."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .refs import CellRef, RangeRef, format_range, format_ref, parse_ref
from .values import ERROR_CODES, format_number


class FormulaError(ValueError):
    pass


# --- tree ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Num:
    value: float


@dataclass(frozen=True)
class Str:
    value: str


@dataclass(frozen=True)
class Bool:
    value: bool


@dataclass(frozen=True)
class Err:
    code: str


@dataclass(frozen=True)
class Ref:
    ref: CellRef


@dataclass(frozen=True)
class Rng:
    rng: RangeRef


@dataclass(frozen=True)
class Name:
    name: str


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object


@dataclass(frozen=True)
class Pct:
    operand: object


@dataclass(frozen=True)
class Bin:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple


# --- tokens ---------------------------------------------------------------------------

_NUMBER = re.compile(r"(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BARE_REF = re.compile(r"\$?[A-Za-z]{1,2}\$?\d+")
_REF_WORD = re.compile(r"[A-Za-z]{1,2}\d+")
_TWO = ("<>", "<=", ">=")
_ONE = "+-*/^&=<>%(),:"
_ERRORS = sorted(ERROR_CODES, key=len, reverse=True)


@dataclass
class Tok:
    kind: str     # num str bool err ref func name op end
    value: object


def _word_char(text: str, i: int) -> bool:
    return i < len(text) and (text[i].isalnum() or text[i] == "_")


def _ref_at(text: str, i: int, sheet):
    """A reference starting at i (after any sheet prefix), or None."""
    m = _BARE_REF.match(text, i)
    if not m or _word_char(text, m.end()) or (m.end() < len(text) and text[m.end()] in "(!$"):
        return None
    try:
        ref = parse_ref(m.group(0))
    except ValueError:
        raise FormulaError(f"reference out of range: {m.group(0)}") from None
    return replace(ref, sheet=sheet), m.end()


def tokenize(text: str) -> list[Tok]:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch == " ":
            i += 1
            continue
        if ch == '"':
            j, buf = i + 1, []
            while True:
                if j >= len(text):
                    raise FormulaError("unterminated text")
                if text[j] == '"':
                    if j + 1 < len(text) and text[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(text[j])
                j += 1
            out.append(Tok("str", "".join(buf)))
            i = j + 1
            continue
        if ch.isdigit() or (ch == "." and i + 1 < len(text) and text[i + 1].isdigit()):
            m = _NUMBER.match(text, i)
            out.append(Tok("num", float(m.group(0))))
            i = m.end()
            continue
        if ch == "#":
            for code in _ERRORS:
                if text.startswith(code, i):
                    out.append(Tok("err", code))
                    i += len(code)
                    break
            else:
                raise FormulaError(f"unknown error code at {i + 1}")
            continue
        if ch == "$":
            got = _ref_at(text, i, None)
            if not got:
                raise FormulaError(f"bad reference at {i + 1}")
            out.append(Tok("ref", got[0]))
            i = got[1]
            continue
        if ch.isalpha() or ch == "_":
            got = _ref_at(text, i, None) if ch.isalpha() else None
            if got:
                out.append(Tok("ref", got[0]))
                i = got[1]
                continue
            m = _WORD.match(text, i)
            word, j = m.group(0), m.end()
            if j < len(text) and text[j] == "(":
                out.append(Tok("func", word.upper()))
                i = j
                continue
            if j < len(text) and text[j] == "!":
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", word):
                    raise FormulaError(f"bad sheet name {word!r}")
                got = _ref_at(text, j + 1, word)
                if not got:
                    raise FormulaError(f"a sheet prefix must be followed by a reference: {word}!")
                out.append(Tok("ref", got[0]))
                i = got[1]
                continue
            if _REF_WORD.fullmatch(word):
                raise FormulaError(f"bad reference {word!r}")
            if word.upper() in ("TRUE", "FALSE"):
                out.append(Tok("bool", word.upper() == "TRUE"))
            else:
                out.append(Tok("name", word))
            i = j
            continue
        if text.startswith(_TWO, i):
            out.append(Tok("op", text[i:i + 2]))
            i += 2
            continue
        if ch in _ONE:
            out.append(Tok("op", ch))
            i += 1
            continue
        raise FormulaError(f"unexpected character {ch!r} at {i + 1}")
    out.append(Tok("end", None))
    return out


# --- grammar --------------------------------------------------------------------------

_COMPARE = ("=", "<>", "<", ">", "<=", ">=")


class _Parser:
    def __init__(self, toks):
        self.toks, self.i = toks, 0

    def peek(self):
        return self.toks[self.i]

    def is_op(self, *ops):
        t = self.peek()
        return t.kind == "op" and t.value in ops

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, op):
        if not self.is_op(op):
            raise FormulaError(f"expected {op!r}")
        self.take()

    def expr(self):
        left = self.concat()
        while self.is_op(*_COMPARE):
            op = self.take().value
            left = Bin(op, left, self.concat())
        return left

    def concat(self):
        left = self.additive()
        while self.is_op("&"):
            self.take()
            left = Bin("&", left, self.additive())
        return left

    def additive(self):
        left = self.mult()
        while self.is_op("+", "-"):
            op = self.take().value
            left = Bin(op, left, self.mult())
        return left

    def mult(self):
        left = self.power()
        while self.is_op("*", "/"):
            op = self.take().value
            left = Bin(op, left, self.power())
        return left

    def power(self):
        left = self.unary()
        while self.is_op("^"):
            self.take()
            left = Bin("^", left, self.unary())
        return left

    def unary(self):
        if self.is_op("-", "+"):
            op = self.take().value
            return Unary(op, self.unary())
        return self.postfix()

    def postfix(self):
        x = self.primary()
        while self.is_op("%"):
            self.take()
            x = Pct(x)
        return x

    def primary(self):
        t = self.take()
        if t.kind == "num":
            return Num(t.value)
        if t.kind == "str":
            return Str(t.value)
        if t.kind == "bool":
            return Bool(t.value)
        if t.kind == "err":
            return Err(t.value)
        if t.kind == "name":
            return Name(t.value)
        if t.kind == "ref":
            if self.is_op(":"):
                self.take()
                end = self.take()
                if end.kind != "ref":
                    raise FormulaError("a range needs a reference after ':'")
                if end.value.sheet is not None:
                    raise FormulaError("only the first corner of a range may name a sheet")
                return Rng(RangeRef(t.value, replace(end.value, sheet=t.value.sheet)))
            return Ref(t.value)
        if t.kind == "func":
            self.expect("(")
            args = []
            if not self.is_op(")"):
                args.append(self.expr())
                while self.is_op(","):
                    self.take()
                    args.append(self.expr())
            self.expect(")")
            return Call(t.value, tuple(args))
        if t.kind == "op" and t.value == "(":
            x = self.expr()
            self.expect(")")
            return x
        raise FormulaError("expected a value" if t.kind == "end" else f"unexpected {t.value!r}")


def parse(text: str):
    if not isinstance(text, str):
        raise FormulaError("a formula is text")
    p = _Parser(tokenize(text))
    tree = p.expr()
    if p.peek().kind != "end":
        raise FormulaError(f"unexpected {p.peek().value!r}")
    return tree


# --- canonical form -------------------------------------------------------------------

_PREC = {**{op: 1 for op in _COMPARE}, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4, "^": 5}


def _prec(node) -> int:
    if isinstance(node, Bin):
        return _PREC[node.op]
    if isinstance(node, Unary):
        return 6
    if isinstance(node, Pct):
        return 7
    return 8


def to_formula(node) -> str:
    if isinstance(node, Num):
        return format_number(node.value)
    if isinstance(node, Str):
        return '"' + node.value.replace('"', '""') + '"'
    if isinstance(node, Bool):
        return "TRUE" if node.value else "FALSE"
    if isinstance(node, Err):
        return node.code
    if isinstance(node, Ref):
        return format_ref(node.ref)
    if isinstance(node, Rng):
        return format_range(node.rng)
    if isinstance(node, Name):
        return node.name
    if isinstance(node, Call):
        return f"{node.name}({','.join(to_formula(a) for a in node.args)})"
    if isinstance(node, Unary):
        inner = to_formula(node.operand)
        return node.op + (f"({inner})" if _prec(node.operand) < 6 else inner)
    if isinstance(node, Pct):
        inner = to_formula(node.operand)
        return (f"({inner})" if _prec(node.operand) < 7 else inner) + "%"
    if isinstance(node, Bin):
        p = _PREC[node.op]
        left, right = to_formula(node.left), to_formula(node.right)
        if _prec(node.left) < p:
            left = f"({left})"
        if _prec(node.right) <= p:
            right = f"({right})"
        return f"{left}{node.op}{right}"
    raise TypeError(f"not a formula tree: {node!r}")
