"""python -m tally run SCRIPT (SPEC section 10)."""
from __future__ import annotations

import sys

from . import csvio, ops, store
from .fill import fill
from .render import render
from .workbook import Workbook


class _Usage(ValueError):
    pass


def _args(rest: str, n: int) -> list[str]:
    parts = rest.split()
    if len(parts) != n:
        raise _Usage(f"expected {n} argument(s)")
    return parts


def _count(text: str) -> int:
    if not text.isdigit():
        raise _Usage(f"not a count: {text!r}")
    return int(text)


def run_line(state: dict, line: str) -> None:
    wb = state["wb"]
    cmd, _, rest = line.partition(" ")
    if cmd == "set":
        address, sep, raw = rest.partition(" ")
        if not sep:
            raise _Usage("usage: set ADDRESS INPUT")
        wb.set(address, raw)
    elif cmd == "print":
        print(wb.display(_args(rest, 1)[0]))
    elif cmd == "raw":
        print(wb.raw(_args(rest, 1)[0]))
    elif cmd == "show":
        sys.stdout.write(render(wb, _args(rest, 1)[0]))
    elif cmd == "sheet":
        wb.add_sheet(_args(rest, 1)[0])
    elif cmd == "rename":
        wb.rename_sheet(*_args(rest, 2))
    elif cmd == "name":
        wb.define_name(*_args(rest, 2))
    elif cmd in ("insert-rows", "delete-rows"):
        sheet, at, n = _args(rest, 3)
        (ops.insert_rows if cmd == "insert-rows" else ops.delete_rows)(wb, sheet, _count(at), _count(n))
    elif cmd in ("insert-cols", "delete-cols"):
        sheet, at, n = _args(rest, 3)
        (ops.insert_cols if cmd == "insert-cols" else ops.delete_cols)(wb, sheet, at, _count(n))
    elif cmd == "fill":
        fill(wb, *_args(rest, 2))
    elif cmd == "recalc":
        _args(rest, 0)
        print(" ".join(["recalc:"] + wb.last_recalc()))
    elif cmd == "save":
        with open(_args(rest, 1)[0], "w", encoding="utf-8", newline="\n") as f:
            f.write(store.save(wb))
    elif cmd == "load":
        with open(_args(rest, 1)[0], encoding="utf-8") as f:
            state["wb"] = store.load(f.read())
    elif cmd == "export":
        sheet, path = _args(rest, 2)
        text = csvio.export_csv(wb, sheet)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    elif cmd == "import":
        sheet, path = _args(rest, 2)
        with open(path, encoding="utf-8", newline="") as f:
            csvio.import_csv(wb, sheet, f.read())
    else:
        raise _Usage(f"unknown command {cmd!r}")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "run":
        sys.stderr.write("usage: python -m tally run SCRIPT\n")
        return 2
    try:
        with open(argv[1], encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError as e:
        sys.stderr.write(f"cannot read {argv[1]}: {e}\n")
        return 2
    state, failed = {"wb": Workbook()}, False
    for n, line in enumerate(lines, 1):
        line = line.rstrip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        try:
            run_line(state, line)
        except (ValueError, OSError) as e:
            print(f"error line {n}: {e}")
            failed = True
    return 1 if failed else 0
