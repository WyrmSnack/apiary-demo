"""Cell references and ranges (SPEC section 2)."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

MAX_COL = 701          # ZZ
MAX_ROW = 9998         # row 9999, 0-based
SHEET_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_REF = re.compile(r"(?:([A-Za-z][A-Za-z0-9_]*)!)?(\$?)([A-Za-z]{1,2})(\$?)(\d+)")


def col_to_index(letters: str) -> int:
    if not isinstance(letters, str) or not re.fullmatch(r"[A-Z]{1,2}", letters):
        raise ValueError(f"not a column: {letters!r}")
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def index_to_col(index: int) -> str:
    if not isinstance(index, int) or not 0 <= index <= MAX_COL:
        raise ValueError(f"column index out of range: {index!r}")
    out = ""
    n = index + 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


@dataclass(frozen=True)
class CellRef:
    sheet: str | None
    col: int
    row: int
    col_abs: bool
    row_abs: bool


@dataclass(frozen=True)
class RangeRef:
    start: CellRef
    end: CellRef


def parse_ref(text: str) -> CellRef:
    m = _REF.fullmatch(text) if isinstance(text, str) else None
    if not m:
        raise ValueError(f"not a cell reference: {text!r}")
    sheet, cabs, letters, rabs, digits = m.groups()
    row = int(digits)
    if not 1 <= row <= MAX_ROW + 1:
        raise ValueError(f"row out of range: {text!r}")
    return CellRef(sheet, col_to_index(letters.upper()), row - 1, cabs == "$", rabs == "$")


def format_ref(ref: CellRef) -> str:
    prefix = f"{ref.sheet}!" if ref.sheet else ""
    return (f"{prefix}{'$' if ref.col_abs else ''}{index_to_col(ref.col)}"
            f"{'$' if ref.row_abs else ''}{ref.row + 1}")


def parse_range(text: str) -> RangeRef:
    if not isinstance(text, str) or text.count(":") != 1:
        raise ValueError(f"not a range: {text!r}")
    a, b = text.split(":")
    start, end = parse_ref(a), parse_ref(b)
    if end.sheet is not None:
        raise ValueError(f"only the first corner of a range may name a sheet: {text!r}")
    return RangeRef(start, replace(end, sheet=start.sheet))


def format_range(r: RangeRef) -> str:
    return f"{format_ref(r.start)}:{format_ref(replace(r.end, sheet=None))}"


def bounds(r: RangeRef) -> tuple[int, int, int, int]:
    """(col_lo, row_lo, col_hi, row_hi)"""
    return (min(r.start.col, r.end.col), min(r.start.row, r.end.row),
            max(r.start.col, r.end.col), max(r.start.row, r.end.row))


def range_cells(r: RangeRef) -> list[tuple[int, int]]:
    c0, r0, c1, r1 = bounds(r)
    return [(c, row) for row in range(r0, r1 + 1) for c in range(c0, c1 + 1)]


def parse_address(text: str) -> CellRef:
    """An address: a reference without $."""
    if not isinstance(text, str) or "$" in text:
        raise ValueError(f"not an address: {text!r}")
    return parse_ref(text)
