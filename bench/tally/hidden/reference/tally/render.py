"""Text grid (SPEC section 9)."""
from __future__ import annotations

from .refs import bounds, index_to_col, parse_range
from .values import display, kind


def render(wb, range_text: str) -> str:
    rng = parse_range(range_text)
    sheet = rng.start.sheet or wb.sheet_names()[0]
    if not wb.has_sheet(sheet):
        raise ValueError(f"no sheet {sheet!r}")
    c0, r0, c1, r1 = bounds(rng)
    cols = list(range(c0, c1 + 1))
    rows = list(range(r0, r1 + 1))
    vals = {(c, r): wb.cached(sheet, c, r) for c in cols for r in rows}
    widths = [max([len(index_to_col(c))] + [len(display(vals[(c, r)])) for r in rows]) for c in cols]
    rw = max(len(str(r + 1)) for r in rows)
    lines = [" | ".join([" " * rw] + [index_to_col(c).ljust(w) for c, w in zip(cols, widths)]),
             "-+-".join(["-" * rw] + ["-" * w for w in widths])]
    for r in rows:
        parts = [str(r + 1).rjust(rw)]
        for c, w in zip(cols, widths):
            v = vals[(c, r)]
            t = display(v)
            parts.append(t.rjust(w) if kind(v) == "number" else t.ljust(w))
        lines.append(" | ".join(parts))
    return "".join(line.rstrip(" ") + "\n" for line in lines)
