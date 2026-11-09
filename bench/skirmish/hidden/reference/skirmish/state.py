class IllegalAction(Exception):
    pass


class GameState:
    def __init__(self, grid, units, turn=1, active="blue"):
        self.grid = grid
        self._units = {u.id: u for u in units}
        self.turn = turn
        self.active = active
        self.moved = set()
        self.acted = set()

    def unit(self, id):
        return self._units[id]

    def unit_at(self, x, y):
        return next((u for u in self._units.values() if u.pos == (x, y)), None)

    def units_of(self, faction):
        return sorted((u for u in self._units.values() if u.faction == faction), key=lambda u: u.id)

    def all_units(self):
        return sorted(self._units.values(), key=lambda u: u.id)

    def remove(self, id):
        self._units.pop(id, None)

    def move(self, unit_id, dest):
        from .movement import reachable
        try:
            u = self.unit(unit_id)
        except KeyError:
            raise IllegalAction(f"no unit {unit_id}") from None
        if u.faction != self.active or unit_id in self.moved or unit_id in self.acted:
            raise IllegalAction(f"{unit_id} cannot move now")
        dest = tuple(dest)
        if dest not in reachable(self, u):
            raise IllegalAction(f"{unit_id} cannot reach {dest}")
        u.x, u.y = dest
        self.moved.add(unit_id)

    def end_turn(self):
        if self.active == "red":
            self.turn += 1
        self.active = "red" if self.active == "blue" else "blue"
        self.moved.clear()
        self.acted.clear()

    def winner(self):
        if not self.units_of("red"):
            return "blue"
        if not self.units_of("blue"):
            return "red"
        return None
