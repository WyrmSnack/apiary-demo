"""Formula evaluation (SPEC section 4.1, 4.2)."""
from __future__ import annotations

from .parser import Bin, Bool, Call, Err, Name, Num, Pct, Ref, Rng, Str, Unary
from .refs import RangeRef, bounds, range_cells
from .values import (BLANK, DIV0, NAME, NUM, REF, VALUE, CellError, kind, num, to_bool, to_number,
                     to_text)

REFERENCE_NODES = (Ref, Rng, Name)


class Evaluator:
    """Evaluates one formula on `sheet`. `book` gives cell values, sheets and names."""

    def __init__(self, book, sheet: str):
        self.book, self.sheet = book, sheet

    # --- references ------------------------------------------------------------
    def _cell(self, sheet, col, row):
        if not self.book.has_sheet(sheet):
            return REF
        return self.book.cached(sheet, col, row)

    def target(self, node):
        """A reference node as ('cell', sheet, col, row) or ('range', sheet, RangeRef), or an error."""
        if isinstance(node, Name):
            t = self.book.name_target(node.name)
            if t is None:
                return NAME
            if isinstance(t, CellError):
                return t
            return self.target(t)
        if isinstance(node, Ref):
            r = node.ref
            sheet = r.sheet or self.sheet
            if not self.book.has_sheet(sheet):
                return REF
            return ("cell", sheet, r.col, r.row)
        if isinstance(node, Rng):
            sheet = node.rng.start.sheet or self.sheet
            if not self.book.has_sheet(sheet):
                return REF
            return ("range", sheet, node.rng)
        raise TypeError(node)

    def cells(self, node):
        """Values of a reference argument, row by row, or an error."""
        t = self.target(node)
        if isinstance(t, CellError):
            return t
        if t[0] == "cell":
            return [self._cell(t[1], t[2], t[3])]
        return [self._cell(t[1], c, r) for c, r in range_cells(t[2])]

    def grid(self, node):
        """A reference argument as rows of values, or an error."""
        t = self.target(node)
        if isinstance(t, CellError):
            return t
        if t[0] == "cell":
            return [[self._cell(t[1], t[2], t[3])]]
        c0, r0, c1, r1 = bounds(t[2])
        return [[self._cell(t[1], c, r) for c in range(c0, c1 + 1)] for r in range(r0, r1 + 1)]

    # --- values ----------------------------------------------------------------
    def value(self, node):
        if isinstance(node, Num):
            return node.value
        if isinstance(node, Str):
            return node.value
        if isinstance(node, Bool):
            return node.value
        if isinstance(node, Err):
            return CellError(node.code)
        if isinstance(node, REFERENCE_NODES):
            t = self.target(node)
            if isinstance(t, CellError):
                return t
            if t[0] == "range":
                return VALUE
            return self._cell(t[1], t[2], t[3])
        if isinstance(node, Unary):
            x = to_number(self.value(node.operand))
            if isinstance(x, CellError):
                return x
            return -x if node.op == "-" else x
        if isinstance(node, Pct):
            x = to_number(self.value(node.operand))
            return x if isinstance(x, CellError) else x / 100
        if isinstance(node, Bin):
            return self.binary(node)
        if isinstance(node, Call):
            from .functions import call
            return call(self, node)
        raise TypeError(node)

    def binary(self, node):
        a = self.value(node.left)
        b = self.value(node.right)
        op = node.op
        if op == "&":
            a, b = to_text(a), to_text(b)
            for x in (a, b):
                if isinstance(x, CellError):
                    return x
            return a + b
        if op in ("=", "<>", "<", ">", "<=", ">="):
            for x in (a, b):
                if isinstance(x, CellError):
                    return x
            c = compare(a, b)
            return {"=": c == 0, "<>": c != 0, "<": c < 0, ">": c > 0, "<=": c <= 0, ">=": c >= 0}[op]
        a, b = to_number(a), to_number(b)
        for x in (a, b):
            if isinstance(x, CellError):
                return x
        try:
            if op == "+":
                return num(a + b)
            if op == "-":
                return num(a - b)
            if op == "*":
                return num(a * b)
            if op == "/":
                return DIV0 if b == 0 else num(a / b)
            if op == "^":
                return power(a, b)
        except OverflowError:
            return NUM
        raise ValueError(op)


def power(a: float, b: float):
    if a == 0 and b < 0:
        return DIV0
    try:
        r = a ** b
    except OverflowError:
        return NUM
    except ZeroDivisionError:
        return DIV0
    return num(r)


_ORDER = {"number": 0, "text": 1, "bool": 2}
_ZERO = {"number": 0.0, "text": "", "bool": False}


def compare(a, b) -> int:
    ka, kb = kind(a), kind(b)
    if ka == "blank" and kb == "blank":
        return 0
    if ka == "blank":
        a, ka = _ZERO[kb], kb
    if kb == "blank":
        b, kb = _ZERO[ka], ka
    if ka != kb:
        return -1 if _ORDER[ka] < _ORDER[kb] else 1
    if ka == "text":
        a, b = a.casefold(), b.casefold()
    return (a > b) - (a < b)


def result(v):
    """A formula's final value: blank becomes 0."""
    return 0.0 if v is BLANK else v
