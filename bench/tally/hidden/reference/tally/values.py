"""Cell values and conversions (SPEC section 1)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

ERROR_CODES = ("#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#N/A", "#CYCLE!", "#NUM!")


class _Blank:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "BLANK"


BLANK = _Blank()


@dataclass(frozen=True)
class CellError:
    code: str


DIV0, VALUE, REF, NAME, NA, CYCLE, NUM = (CellError(c) for c in ERROR_CODES)

_NUMBER = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def kind(v) -> str:
    if isinstance(v, CellError):
        return "error"
    if v is BLANK:
        return "blank"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "text"
    raise TypeError(f"not a cell value: {v!r}")


def num(x: float):
    """A number result: infinite or NaN becomes #NUM!."""
    if isinstance(x, complex) or math.isinf(x) or math.isnan(x):
        return NUM
    return float(x)


def format_number(x: float) -> str:
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return format(x, ".10g")


def parse_number(text: str):
    t = text.strip(" ")
    if not _NUMBER.fullmatch(t):
        return None
    x = float(t)
    if math.isinf(x) or math.isnan(x):
        return None
    return x


def to_number(v):
    k = kind(v)
    if k == "number":
        return v
    if k == "bool":
        return 1.0 if v else 0.0
    if k == "blank":
        return 0.0
    if k == "text":
        n = parse_number(v)
        return VALUE if n is None else n
    return v


def to_text(v):
    k = kind(v)
    if k == "text":
        return v
    if k == "number":
        return format_number(v)
    if k == "bool":
        return "TRUE" if v else "FALSE"
    if k == "blank":
        return ""
    return v


def to_bool(v):
    k = kind(v)
    if k == "bool":
        return v
    if k == "number":
        return v != 0
    if k == "blank":
        return False
    if k == "text":
        u = v.upper()
        if u == "TRUE":
            return True
        if u == "FALSE":
            return False
        return VALUE
    return v


def display(v) -> str:
    k = kind(v)
    if k == "error":
        return v.code
    return to_text(v)
