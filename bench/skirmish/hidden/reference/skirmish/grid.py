TERRAIN = {".": (1, 0, False), "F": (2, 1, False), "^": (3, 2, False), "~": (None, 0, False), "#": (None, 0, True)}


class Grid:
    def __init__(self, rows):
        self.rows = rows
        self.height = len(rows)
        self.width = len(rows[0])

    @classmethod
    def from_text(cls, text):
        rows = [line.rstrip() for line in text.split("\n")]
        while rows and not rows[0]:
            rows.pop(0)
        while rows and not rows[-1]:
            rows.pop()
        if not rows:
            raise ValueError("no rows")
        if len({len(r) for r in rows}) != 1:
            raise ValueError("rows differ in length")
        for r in rows:
            for c in r:
                if c not in TERRAIN:
                    raise ValueError(f"unknown terrain {c!r}")
        return cls(rows)

    def char(self, x, y):
        return self.rows[y][x]

    def in_bounds(self, x, y):
        return 0 <= x < self.width and 0 <= y < self.height

    def move_cost(self, x, y):
        return TERRAIN[self.char(x, y)][0]

    def defense(self, x, y):
        return TERRAIN[self.char(x, y)][1]

    def blocks_sight(self, x, y):
        return TERRAIN[self.char(x, y)][2]

    def neighbors(self, x, y):
        return [(nx, ny) for nx, ny in ((x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)) if self.in_bounds(nx, ny)]

    def to_text(self):
        return "\n".join(self.rows)


def _line(a, b):
    x, y = a
    x1, y1 = b
    dx, dy = abs(x1 - x), -abs(y1 - y)
    sx, sy = (1 if x < x1 else -1), (1 if y < y1 else -1)
    err = dx + dy
    while True:
        yield (x, y)
        if (x, y) == (x1, y1):
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def line_of_sight(grid, a, b):
    return not any(grid.blocks_sight(*c) for c in _line(a, b) if c not in (tuple(a), tuple(b)))
