"""Save files (SPEC section 8)."""
from __future__ import annotations

import json

from .refs import index_to_col
from .workbook import Workbook


def save(wb) -> str:
    sheets = []
    for s in wb.sheet_names():
        cells = wb._cells[s]
        sheets.append({"name": s, "cells": {f"{index_to_col(c)}{r + 1}": cells[(c, r)][0]
                                            for c, r in sorted(cells, key=lambda p: (p[1], p[0]))}})
    return json.dumps({"format": "tally", "version": 1, "sheets": sheets, "names": wb.names()}, indent=2) + "\n"


def load(text: str) -> Workbook:
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("format") != "tally" or data.get("version") != 1:
            raise ValueError("not a tally version 1 file")
        sheets = data["sheets"]
        if not isinstance(sheets, list) or not sheets:
            raise ValueError("a file needs at least one sheet")
        wb = Workbook()
        with wb.batch():
            for i, sheet in enumerate(sheets):
                name = sheet["name"]
                if i == 0:
                    if name != "Sheet1":
                        wb.rename_sheet("Sheet1", name)
                else:
                    wb.add_sheet(name)
            for sheet in sheets:
                cells = sheet["cells"]
                if not isinstance(cells, dict):
                    raise ValueError("cells must be an object")
                for address, raw in cells.items():
                    if "!" in address:
                        raise ValueError(f"cell addresses in a file have no sheet: {address!r}")
                    wb.set(f"{sheet['name']}!{address}", raw)
            for name, target in (data.get("names") or {}).items():
                wb.define_name(name, target)
        return wb
    except (KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"not a tally file: {e}") from None
