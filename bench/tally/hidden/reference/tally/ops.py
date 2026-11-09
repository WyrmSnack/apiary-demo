"""Inserting and deleting rows and columns (SPEC section 6)."""
from __future__ import annotations

from dataclasses import replace

from .parser import Err, Ref, Rng
from .refs import MAX_COL, MAX_ROW, col_to_index


def insert_rows(wb, sheet, at, count):
    _edit(wb, sheet, "row", _row(at), count, insert=True)


def delete_rows(wb, sheet, at, count):
    _edit(wb, sheet, "row", _row(at), count, insert=False)


def insert_cols(wb, sheet, at, count):
    _edit(wb, sheet, "col", _col(at), count, insert=True)


def delete_cols(wb, sheet, at, count):
    _edit(wb, sheet, "col", _col(at), count, insert=False)


def _row(at) -> int:
    if not isinstance(at, int) or isinstance(at, bool) or not 1 <= at <= MAX_ROW + 1:
        raise ValueError(f"not a row number: {at!r}")
    return at - 1


def _col(at) -> int:
    if not isinstance(at, str):
        raise ValueError(f"not a column: {at!r}")
    return col_to_index(at.upper())


def _edit(wb, sheet, axis, a, n, insert):
    if not wb.has_sheet(sheet):
        raise ValueError(f"no sheet {sheet!r}")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError(f"count must be at least 1: {n!r}")
    limit = MAX_ROW if axis == "row" else MAX_COL

    def point(c):
        """New coordinate, or None if the cell is deleted or pushed off the grid."""
        if insert:
            if c >= a:
                c += n
            return None if c > limit else c
        if a <= c < a + n:
            return None
        return c - n if c >= a + n else c

    def fix_ref(ref):
        c = point(getattr(ref, axis))
        return None if c is None else replace(ref, **{axis: c})

    def fix(formula_sheet, node):
        if isinstance(node, Ref):
            if (node.ref.sheet or formula_sheet) != sheet:
                return node
            r = fix_ref(node.ref)
            return Err("#REF!") if r is None else Ref(r)
        rng = node.rng
        if (rng.start.sheet or formula_sheet) != sheet:
            return node
        s, e = getattr(rng.start, axis), getattr(rng.end, axis)
        lo, hi = min(s, e), max(s, e)
        if insert:
            ns, ne = point(s), point(e)
            if ns is None or ne is None:
                return Err("#REF!")
        else:
            if a <= lo and hi < a + n:
                return Err("#REF!")
            nlo = lo if lo < a else (lo - n if lo >= a + n else a)
            nhi = hi if hi < a else (hi - n if hi >= a + n else a - 1)
            ns, ne = (nlo, nhi) if s <= e else (nhi, nlo)
        return Rng(replace(rng, start=replace(rng.start, **{axis: ns}), end=replace(rng.end, **{axis: ne})))

    wb.transform(fix, names=True)
    cells = wb._cells[sheet]
    moved = {}
    for (col, row), entry in cells.items():
        pos = {"col": col, "row": row}
        c = point(pos[axis])
        if c is None:
            continue
        pos[axis] = c
        moved[(pos["col"], pos["row"])] = entry
    wb._cells[sheet] = moved
    wb._recompute(all_formulas=True)
