from dataclasses import dataclass

KINDS = {  # letter, max_hp, attack, defense, move, range_min, range_max
    "soldier": ("S", 10, 4, 2, 4, 1, 1),
    "archer": ("A", 7, 4, 1, 3, 2, 3),
    "knight": ("K", 14, 5, 3, 5, 1, 1),
}
FACTIONS = ("blue", "red")


@dataclass
class Unit:
    id: str
    faction: str
    kind: str
    x: int
    y: int
    hp: int

    def _stat(self, i):
        return KINDS[self.kind][i]

    max_hp = property(lambda self: self._stat(1))
    attack = property(lambda self: self._stat(2))
    defense = property(lambda self: self._stat(3))
    move = property(lambda self: self._stat(4))
    range_min = property(lambda self: self._stat(5))
    range_max = property(lambda self: self._stat(6))
    pos = property(lambda self: (self.x, self.y))

    @property
    def letter(self):
        return self._stat(0) if self.faction == "blue" else self._stat(0).lower()


def make_unit(id, faction, kind, x, y):
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if faction not in FACTIONS:
        raise ValueError(f"unknown faction {faction!r}")
    return Unit(id, faction, kind, x, y, KINDS[kind][1])
