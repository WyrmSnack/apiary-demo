"""The workbook (SPEC section 5)."""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import replace

from . import graph
from .evaluator import Evaluator, result
from .parser import Bin, Call, Err, FormulaError, Name, Pct, Ref, Rng, Unary, parse, to_formula
from .refs import SHEET_NAME, index_to_col, parse_address, range_cells
from .values import BLANK, CYCLE, REF, CellError, display, parse_number

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_REF_LIKE = re.compile(r"[A-Za-z]{1,2}\d+")


def map_refs(node, fn):
    """Rebuild a tree, replacing every Ref and Rng node with fn(node)."""
    if isinstance(node, (Ref, Rng)):
        return fn(node)
    if isinstance(node, Unary):
        return Unary(node.op, map_refs(node.operand, fn))
    if isinstance(node, Pct):
        return Pct(map_refs(node.operand, fn))
    if isinstance(node, Bin):
        return Bin(node.op, map_refs(node.left, fn), map_refs(node.right, fn))
    if isinstance(node, Call):
        return Call(node.name, tuple(map_refs(a, fn) for a in node.args))
    return node


def walk(node):
    yield node
    for child in (getattr(node, "operand", None), getattr(node, "left", None), getattr(node, "right", None)):
        if child is not None:
            yield from walk(child)
    for a in getattr(node, "args", ()):
        yield from walk(a)


class Workbook:
    def __init__(self):
        self._sheets: list[str] = ["Sheet1"]
        self._cells: dict[str, dict] = {"Sheet1": {}}      # sheet -> (col, row) -> (raw, kind, payload)
        self._values: dict = {}                            # (sheet, col, row) -> value, formula cells
        self._names: dict[str, tuple[str, object]] = {}    # NAME -> (name as given, Ref/Rng/Err node)
        self._last: list[str] = []
        self._batching = False

    # --- sheets ---------------------------------------------------------------
    def sheet_names(self) -> list[str]:
        return list(self._sheets)

    def has_sheet(self, name) -> bool:
        return name in self._cells

    def add_sheet(self, name: str) -> None:
        if not isinstance(name, str) or not SHEET_NAME.fullmatch(name):
            raise ValueError(f"not a sheet name: {name!r}")
        if name in self._cells:
            raise ValueError(f"sheet {name!r} exists")
        self._sheets.append(name)
        self._cells[name] = {}
        self._recompute()

    def rename_sheet(self, old: str, new: str) -> None:
        if old not in self._cells:
            raise ValueError(f"no sheet {old!r}")
        if not isinstance(new, str) or not SHEET_NAME.fullmatch(new):
            raise ValueError(f"not a sheet name: {new!r}")
        if new in self._cells:
            raise ValueError(f"sheet {new!r} exists")
        self._sheets[self._sheets.index(old)] = new
        self._cells[new] = self._cells.pop(old)

        def fix(node):
            if isinstance(node, Ref) and node.ref.sheet == old:
                return Ref(replace(node.ref, sheet=new))
            if isinstance(node, Rng) and node.rng.start.sheet == old:
                r = node.rng
                return Rng(replace(r, start=replace(r.start, sheet=new), end=replace(r.end, sheet=new)))
            return node
        self.transform(lambda sheet, node: fix(node), names=True)
        self._recompute(all_formulas=True)

    # --- cells ----------------------------------------------------------------
    def _locate(self, address: str):
        ref = parse_address(address)
        sheet = ref.sheet or self._sheets[0]
        if sheet not in self._cells:
            raise ValueError(f"no sheet {sheet!r}")
        return sheet, ref.col, ref.row

    def addr(self, key) -> str:
        sheet, col, row = key
        return f"{sheet}!{index_to_col(col)}{row + 1}"

    def key(self, k):
        sheet, col, row = k
        return (self._sheets.index(sheet), row, col)

    def set(self, address: str, raw: str) -> None:
        sheet, col, row = self._locate(address)
        if not isinstance(raw, str):
            raise ValueError("input is text")
        entry = self.parse_input(raw)
        self._store(sheet, col, row, entry)
        self._recompute(changed={(sheet, col, row)})

    @staticmethod
    def parse_input(raw: str):
        if raw == "":
            return None
        if raw.startswith("="):
            tree = parse(raw[1:])
            return ("=" + to_formula(tree), "formula", tree)
        n = parse_number(raw)
        if n is not None:
            return (raw, "const", n)
        if raw.upper() in ("TRUE", "FALSE"):
            return (raw, "const", raw.upper() == "TRUE")
        if raw.startswith("'"):
            return (raw, "const", raw[1:])
        return (raw, "const", raw)

    def _store(self, sheet, col, row, entry):
        cells = self._cells[sheet]
        if entry is None:
            cells.pop((col, row), None)
        else:
            cells[(col, row)] = entry
        self._values.pop((sheet, col, row), None)

    def value(self, address: str):
        return self.cached(*self._locate(address), final=True)

    def cached(self, sheet, col, row, final=False):
        e = self._cells.get(sheet, {}).get((col, row))
        if e is None:
            return BLANK
        if e[1] == "const":
            return e[2]
        return self._values.get((sheet, col, row), BLANK)

    def raw(self, address: str) -> str:
        sheet, col, row = self._locate(address)
        e = self._cells[sheet].get((col, row))
        return "" if e is None else e[0]

    def display(self, address: str) -> str:
        return display(self.value(address))

    def last_recalc(self) -> list[str]:
        return list(self._last)

    # --- names ----------------------------------------------------------------
    def define_name(self, name: str, target: str) -> None:
        if (not isinstance(name, str) or not _NAME.fullmatch(name) or _REF_LIKE.fullmatch(name)
                or name.upper() in ("TRUE", "FALSE")):
            raise ValueError(f"not a name: {name!r}")
        try:
            node = parse(target)
        except FormulaError as e:
            raise ValueError(f"not a reference or range: {target!r}") from e
        sheet = node.ref.sheet if isinstance(node, Ref) else node.rng.start.sheet if isinstance(node, Rng) else None
        if sheet is None:
            raise ValueError(f"a name's target is a reference or range with a sheet prefix: {target!r}")
        self._names[name.upper()] = (name, node)
        up = name.upper()
        users = {k for k in self._formulas() if any(isinstance(n, Name) and n.name.upper() == up
                                                     for n in walk(self._tree(k)))}
        self._recompute(seeds=users)

    def name_target(self, name: str):
        got = self._names.get(name.upper())
        if got is None:
            return None
        node = got[1]
        return REF if isinstance(node, Err) else node

    def names(self) -> dict[str, str]:
        return {n: to_formula(node) for n, node in self._names.values()}

    # --- formulas, dependencies, recalculation -------------------------------
    def _formulas(self):
        return [(s, c, r) for s in self._sheets for (c, r), e in self._cells[s].items() if e[1] == "formula"]

    def _tree(self, k):
        return self._cells[k[0]][(k[1], k[2])][2]

    def _deps(self, sheet, tree, seen_names=None) -> set:
        out = set()
        for n in walk(tree):
            if isinstance(n, Ref):
                s = n.ref.sheet or sheet
                if s in self._cells:
                    out.add((s, n.ref.col, n.ref.row))
            elif isinstance(n, Rng):
                s = n.rng.start.sheet or sheet
                if s in self._cells:
                    out.update((s, c, r) for c, r in range_cells(n.rng))
            elif isinstance(n, Name):
                t = self.name_target(n.name)
                if t is not None and not isinstance(t, CellError):
                    out |= self._deps(sheet, t)
        return out

    def transform(self, fn, names=False):
        """Rewrite every formula: fn(formula's sheet, Ref or Rng node) -> node. Optionally name targets too."""
        for s in self._sheets:
            for pos, (raw, kind, payload) in list(self._cells[s].items()):
                if kind == "formula":
                    tree = map_refs(payload, lambda node, s=s: fn(s, node))
                    self._cells[s][pos] = ("=" + to_formula(tree), "formula", tree)
        if names:
            for up, (name, node) in list(self._names.items()):
                if isinstance(node, (Ref, Rng)):
                    sheet = node.ref.sheet if isinstance(node, Ref) else node.rng.start.sheet
                    self._names[up] = (name, fn(sheet, node))

    @contextmanager
    def batch(self):
        """Many changes, one recalculation at the end."""
        self._batching, pending = True, set()
        self._pending = pending
        try:
            yield
        finally:
            self._batching = False
            self._recompute(changed=pending)

    def _recompute(self, changed=None, seeds=None, all_formulas=False):
        if self._batching:
            self._pending |= changed or set()
            return
        formulas = self._formulas()
        fset = set(formulas)
        deps = {k: self._deps(k[0], self._tree(k)) for k in formulas}
        preds = {k: {d for d in v if d in fset} for k, v in deps.items()}
        users: dict = {}
        for k, v in deps.items():
            for d in v:
                users.setdefault(d, set()).add(k)
        self._values = {}
        for members, cyclic in graph.order(formulas, preds, self.key):
            for k in members:
                if cyclic:
                    self._values[k] = CYCLE
                else:
                    ev = Evaluator(self, k[0])
                    self._values[k] = result(ev.value(self._tree(k)))
        if all_formulas:
            affected = fset
        else:
            start = set(seeds or ())
            start |= {c for c in (changed or ()) if c in fset}
            affected, todo = set(start), list(start) + [c for c in (changed or ())]
            while todo:
                for u in users.get(todo.pop(), ()):
                    if u not in affected:
                        affected.add(u)
                        todo.append(u)
        self._last = [self.addr(k) for members, _ in graph.order(affected, preds, self.key) for k in members]
