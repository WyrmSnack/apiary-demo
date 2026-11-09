"""The functions (SPEC section 4.3, 4.4)."""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal, localcontext

from .evaluator import REFERENCE_NODES, power
from .values import (BLANK, DIV0, NA, NAME, NUM, REF, VALUE, CellError, kind, num, parse_number,
                     to_bool, to_number, to_text)


def _is_ref(node) -> bool:
    return isinstance(node, REFERENCE_NODES)


def _numbers(ev, args):
    out = []
    for a in args:
        if _is_ref(a):
            cells = ev.cells(a)
            if isinstance(cells, CellError):
                return cells
            for v in cells:
                if isinstance(v, CellError):
                    return v
                if kind(v) == "number":
                    out.append(v)
        else:
            n = to_number(ev.value(a))
            if isinstance(n, CellError):
                return n
            out.append(n)
    return out


def _scalar_number(ev, node):
    return to_number(ev.value(node))


def _scalar_text(ev, node):
    return to_text(ev.value(node))


def _count(ev, node):
    """A count or position argument: to_number truncated toward zero."""
    n = to_number(ev.value(node))
    return n if isinstance(n, CellError) else int(n)


def _first_error(*xs):
    for x in xs:
        if isinstance(x, CellError):
            return x
    return None


# --- math ---------------------------------------------------------------------------

def f_sum(ev, args):
    ns = _numbers(ev, args)
    return ns if isinstance(ns, CellError) else num(sum(ns))


def f_product(ev, args):
    ns = _numbers(ev, args)
    if isinstance(ns, CellError):
        return ns
    if not ns:
        return 0.0
    p = 1.0
    for n in ns:
        p *= n
    return num(p)


def f_min(ev, args):
    ns = _numbers(ev, args)
    return ns if isinstance(ns, CellError) else (min(ns) if ns else 0.0)


def f_max(ev, args):
    ns = _numbers(ev, args)
    return ns if isinstance(ns, CellError) else (max(ns) if ns else 0.0)


def f_average(ev, args):
    ns = _numbers(ev, args)
    if isinstance(ns, CellError):
        return ns
    return DIV0 if not ns else num(sum(ns) / len(ns))


def f_median(ev, args):
    ns = _numbers(ev, args)
    if isinstance(ns, CellError):
        return ns
    if not ns:
        return NUM
    s = sorted(ns)
    m = len(s) // 2
    return s[m] if len(s) % 2 else num((s[m - 1] + s[m]) / 2)


def _unary_math(fn):
    def f(ev, args):
        x = _scalar_number(ev, args[0])
        return x if isinstance(x, CellError) else fn(x)
    return f


def _sqrt(x):
    return NUM if x < 0 else num(math.sqrt(x))


def f_round(ev, args):
    x = _scalar_number(ev, args[0])
    d = _count(ev, args[1]) if len(args) > 1 else 0
    e = _first_error(x, d)
    if e:
        return e
    d = max(-400, min(400, d))
    with localcontext() as ctx:
        ctx.prec = 400
        q = Decimal(repr(x)).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    return num(float(q))


def f_mod(ev, args):
    a, b = _scalar_number(ev, args[0]), _scalar_number(ev, args[1])
    e = _first_error(a, b)
    if e:
        return e
    if b == 0:
        return DIV0
    return num(a - b * math.floor(a / b))


def f_power(ev, args):
    a, b = _scalar_number(ev, args[0]), _scalar_number(ev, args[1])
    e = _first_error(a, b)
    return e if e else power(a, b)


# --- counting -----------------------------------------------------------------------

def f_count(ev, args):
    n = 0
    for a in args:
        if _is_ref(a):
            cells = ev.cells(a)
            if isinstance(cells, CellError):
                continue
            n += sum(1 for v in cells if kind(v) == "number")
        else:
            v = ev.value(a)
            k = kind(v)
            if k in ("number", "bool") or (k == "text" and parse_number(v) is not None):
                n += 1
    return float(n)


def f_counta(ev, args):
    n = 0
    for a in args:
        if _is_ref(a):
            cells = ev.cells(a)
            if isinstance(cells, CellError):
                n += 1
                continue
            n += sum(1 for v in cells if v is not BLANK)
        else:
            n += 1
    return float(n)


def f_countblank(ev, args):
    if not _is_ref(args[0]):
        return VALUE
    cells = ev.cells(args[0])
    if isinstance(cells, CellError):
        return cells
    for v in cells:                       # 4.1: errors inside a range propagate
        if isinstance(v, CellError):
            return v
    return float(sum(1 for v in cells if v is BLANK or v == ""))


def matcher(c):
    """A function cell -> bool for criterion c (4.4), or an error."""
    k = kind(c)
    if k == "error":
        return c
    if k == "number":
        return lambda v: kind(v) == "number" and v == c
    if k == "bool":
        return lambda v: kind(v) == "bool" and v == c
    text = "" if k == "blank" else c
    op = ""
    for o in (">=", "<=", "<>", ">", "<", "="):
        if text.startswith(o):
            op = o
            break
    r = text[len(op):]
    n = parse_number(r)
    cmp = {">": lambda a, b: a > b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
    if n is not None:
        if op in ("", "="):
            return lambda v: kind(v) == "number" and v == n
        if op == "<>":
            return lambda v: not (kind(v) == "number" and v == n)
        return lambda v: kind(v) == "number" and cmp[op](v, n)
    rf = r.casefold()
    if op in ("", "="):
        return lambda v: (kind(v) == "text" and v.casefold() == rf) or (r == "" and v is BLANK)
    if op == "<>":
        return lambda v: not (kind(v) == "text" and v.casefold() == rf)
    return lambda v: kind(v) == "text" and cmp[op](v.casefold(), rf)


def f_countif(ev, args):
    if not _is_ref(args[0]):
        return VALUE
    cells = ev.cells(args[0])
    if isinstance(cells, CellError):
        return cells
    m = matcher(ev.value(args[1]))
    if isinstance(m, CellError):
        return m
    return float(sum(1 for v in cells if m(v)))


def f_sumif(ev, args):
    if not _is_ref(args[0]) or (len(args) > 2 and not _is_ref(args[2])):
        return VALUE
    g = ev.grid(args[0])
    if isinstance(g, CellError):
        return g
    s = ev.grid(args[2]) if len(args) > 2 else g
    if isinstance(s, CellError):
        return s
    if len(g) != len(s) or len(g[0]) != len(s[0]):
        return VALUE
    m = matcher(ev.value(args[1]))
    if isinstance(m, CellError):
        return m
    total = [s[i][j] for i in range(len(g)) for j in range(len(g[0]))
             if m(g[i][j]) and kind(s[i][j]) == "number"]
    return num(sum(total))


# --- logic --------------------------------------------------------------------------

def f_if(ev, args):
    c = to_bool(ev.value(args[0]))
    if isinstance(c, CellError):
        return c
    if c:
        return ev.value(args[1])
    return ev.value(args[2]) if len(args) > 2 else False


def _bools(ev, args):
    out = []
    for a in args:
        if _is_ref(a):
            cells = ev.cells(a)
            if isinstance(cells, CellError):
                return cells
            for v in cells:
                k = kind(v)
                if k == "error":
                    return v
                if k == "bool":
                    out.append(v)
                elif k == "number":
                    out.append(v != 0)
        else:
            b = to_bool(ev.value(a))
            if isinstance(b, CellError):
                return b
            out.append(b)
    return out


def f_and(ev, args):
    bs = _bools(ev, args)
    return bs if isinstance(bs, CellError) else (VALUE if not bs else all(bs))


def f_or(ev, args):
    bs = _bools(ev, args)
    return bs if isinstance(bs, CellError) else (VALUE if not bs else any(bs))


def f_not(ev, args):
    b = to_bool(ev.value(args[0]))
    return b if isinstance(b, CellError) else (not b)


def f_iferror(ev, args):
    v = ev.value(args[0])
    return ev.value(args[1]) if isinstance(v, CellError) else v


# --- text ---------------------------------------------------------------------------

def _text_fn(fn):
    def f(ev, args):
        t = _scalar_text(ev, args[0])
        return t if isinstance(t, CellError) else fn(t)
    return f


def _trim(t: str) -> str:
    out = t.strip(" ")
    while "  " in out:
        out = out.replace("  ", " ")
    return out


def f_left(ev, args):
    t = _scalar_text(ev, args[0])
    n = _count(ev, args[1]) if len(args) > 1 else 1
    e = _first_error(t, n)
    if e:
        return e
    return VALUE if n < 0 else t[:n]


def f_right(ev, args):
    t = _scalar_text(ev, args[0])
    n = _count(ev, args[1]) if len(args) > 1 else 1
    e = _first_error(t, n)
    if e:
        return e
    if n < 0:
        return VALUE
    return t[len(t) - n:] if n < len(t) else t


def f_mid(ev, args):
    t, s, n = _scalar_text(ev, args[0]), _count(ev, args[1]), _count(ev, args[2])
    e = _first_error(t, s, n)
    if e:
        return e
    if s < 1 or n < 0:
        return VALUE
    return t[s - 1:s - 1 + n]


def f_concat(ev, args):
    parts = []
    for a in args:
        vals = ev.cells(a) if _is_ref(a) else [ev.value(a)]
        if isinstance(vals, CellError):
            return vals
        for v in vals:
            t = to_text(v)
            if isinstance(t, CellError):
                return t
            parts.append(t)
    return "".join(parts)


def f_find(ev, args):
    needle, hay = _scalar_text(ev, args[0]), _scalar_text(ev, args[1])
    start = _count(ev, args[2]) if len(args) > 2 else 1
    e = _first_error(needle, hay, start)
    if e:
        return e
    if start < 1 or start > len(hay) + 1:
        return VALUE
    i = hay.find(needle, start - 1)
    return VALUE if i < 0 else float(i + 1)


def f_substitute(ev, args):
    t, old, new = (_scalar_text(ev, a) for a in args)
    e = _first_error(t, old, new)
    if e:
        return e
    return t if old == "" else t.replace(old, new)


# --- lookup -------------------------------------------------------------------------

def equal(a, b) -> bool:
    ka, kb = kind(a), kind(b)
    if ka != kb or ka in ("blank", "error"):
        return False
    if ka == "text":
        return a.casefold() == b.casefold()
    return a == b


def _blank0(v):
    return 0.0 if v is BLANK else v


def f_vlookup(ev, args):
    key = ev.value(args[0])
    if isinstance(key, CellError):
        return key
    if not _is_ref(args[1]):
        return VALUE
    g = ev.grid(args[1])
    if isinstance(g, CellError):
        return g
    col = _count(ev, args[2])
    if isinstance(col, CellError):
        return col
    if col < 1:
        return VALUE
    if col > len(g[0]):
        return REF
    if key is BLANK:
        return NA
    for row in g:
        if equal(row[0], key):
            return _blank0(row[col - 1])
    return NA


def f_index(ev, args):
    if not _is_ref(args[0]):
        return VALUE
    g = ev.grid(args[0])
    if isinstance(g, CellError):
        return g
    i = _count(ev, args[1])
    j = _count(ev, args[2]) if len(args) > 2 else None
    e = _first_error(i, j)
    if e:
        return e
    if j is None:
        if len(g) == 1 and len(g[0]) > 1:
            i, j = 1, i
        else:
            j = 1
    if i < 1 or j < 1 or i > len(g) or j > len(g[0]):
        return REF
    return _blank0(g[i - 1][j - 1])


def f_match(ev, args):
    key = ev.value(args[0])
    if isinstance(key, CellError):
        return key
    if not _is_ref(args[1]):
        return VALUE
    g = ev.grid(args[1])
    if isinstance(g, CellError):
        return g
    if len(g) > 1 and len(g[0]) > 1:
        return NA
    if key is BLANK:
        return NA
    flat = [v for row in g for v in row]
    for i, v in enumerate(flat):
        if equal(v, key):
            return float(i + 1)
    return NA


INF = None
FUNCTIONS = {
    "SUM": (1, INF, f_sum), "PRODUCT": (1, INF, f_product), "MIN": (1, INF, f_min), "MAX": (1, INF, f_max),
    "AVERAGE": (1, INF, f_average), "MEDIAN": (1, INF, f_median),
    "ABS": (1, 1, _unary_math(lambda x: abs(x))), "INT": (1, 1, _unary_math(lambda x: float(math.floor(x)))),
    "SQRT": (1, 1, _unary_math(_sqrt)), "ROUND": (1, 2, f_round), "MOD": (2, 2, f_mod), "POWER": (2, 2, f_power),
    "COUNT": (1, INF, f_count), "COUNTA": (1, INF, f_counta), "COUNTBLANK": (1, 1, f_countblank),
    "COUNTIF": (2, 2, f_countif), "SUMIF": (2, 3, f_sumif),
    "IF": (2, 3, f_if), "AND": (1, INF, f_and), "OR": (1, INF, f_or), "NOT": (1, 1, f_not),
    "IFERROR": (2, 2, f_iferror),
    "LEN": (1, 1, _text_fn(lambda t: float(len(t)))), "UPPER": (1, 1, _text_fn(str.upper)),
    "LOWER": (1, 1, _text_fn(str.lower)), "TRIM": (1, 1, _text_fn(_trim)),
    "LEFT": (1, 2, f_left), "RIGHT": (1, 2, f_right), "MID": (3, 3, f_mid), "CONCAT": (1, INF, f_concat),
    "FIND": (2, 3, f_find), "SUBSTITUTE": (3, 3, f_substitute),
    "VLOOKUP": (3, 3, f_vlookup), "INDEX": (2, 3, f_index), "MATCH": (2, 2, f_match),
}


def call(ev, node):
    spec = FUNCTIONS.get(node.name)
    if spec is None:
        return NAME
    lo, hi, fn = spec
    if len(node.args) < lo or (hi is not None and len(node.args) > hi):
        return VALUE
    return fn(ev, node.args)
