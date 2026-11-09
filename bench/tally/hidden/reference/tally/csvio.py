"""CSV (SPEC section 8)."""
from __future__ import annotations

import csv
import io

from .refs import index_to_col
from .values import display


def export_csv(wb, sheet: str) -> str:
    if not wb.has_sheet(sheet):
        raise ValueError(f"no sheet {sheet!r}")
    cells = wb._cells[sheet]
    if not cells:
        return ""
    max_col = max(c for c, _ in cells)
    max_row = max(r for _, r in cells)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    for r in range(max_row + 1):
        w.writerow([display(wb.cached(sheet, c, r)) for c in range(max_col + 1)])
    return out.getvalue()


def import_csv(wb, sheet: str, text: str) -> None:
    if not wb.has_sheet(sheet):
        raise ValueError(f"no sheet {sheet!r}")
    with wb.batch():
        for r, row in enumerate(csv.reader(io.StringIO(text))):
            for c, field in enumerate(row):
                if field != "":
                    wb.set(f"{sheet}!{index_to_col(c)}{r + 1}", field)
