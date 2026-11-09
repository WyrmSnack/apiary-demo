"""Fill (SPEC section 7)."""
from __future__ import annotations

from dataclasses import replace

from .parser import Err, Ref, Rng, to_formula
from .refs import MAX_COL, MAX_ROW, parse_address, parse_range, range_cells
from .workbook import map_refs


def _shift(ref, dc, dr):
    col = ref.col if ref.col_abs else ref.col + dc
    row = ref.row if ref.row_abs else ref.row + dr
    if not (0 <= col <= MAX_COL and 0 <= row <= MAX_ROW):
        return None
    return replace(ref, col=col, row=row)


def shifted(tree, dc, dr):
    def fix(node):
        if isinstance(node, Ref):
            r = _shift(node.ref, dc, dr)
            return Err("#REF!") if r is None else Ref(r)
        s, e = _shift(node.rng.start, dc, dr), _shift(node.rng.end, dc, dr)
        if s is None or e is None:
            return Err("#REF!")
        return Rng(replace(node.rng, start=s, end=e))
    return map_refs(tree, fix)


def fill(wb, source: str, target: str) -> None:
    sheet, col, row = wb._locate(source)
    rng = parse_range(target)
    tsheet = rng.start.sheet or sheet
    if not wb.has_sheet(tsheet):
        raise ValueError(f"no sheet {tsheet!r}")
    entry = wb._cells[sheet].get((col, row))
    with wb.batch():
        for c, r in range_cells(rng):
            if entry is None:
                raw = ""
            elif entry[1] == "formula":
                raw = "=" + to_formula(shifted(entry[2], c - col, r - row))
            else:
                raw = entry[0]
            wb.set(f"{tsheet}!{_addr(c, r)}", raw)


def _addr(c, r):
    from .refs import index_to_col
    return f"{index_to_col(c)}{r + 1}"
