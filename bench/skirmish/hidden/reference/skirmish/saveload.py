import json

from .grid import Grid
from .state import GameState
from .units import Unit, make_unit


def to_dict(state):
    return {"version": 1, "turn": state.turn, "active": state.active, "map": list(state.grid.rows),
            "units": [{"id": u.id, "faction": u.faction, "kind": u.kind, "x": u.x, "y": u.y, "hp": u.hp}
                      for u in state.all_units()],
            "moved": sorted(state.moved), "acted": sorted(state.acted)}


def from_dict(d):
    if d.get("version") != 1:
        raise ValueError("unsupported version")
    units = []
    for u in d["units"]:
        made = make_unit(u["id"], u["faction"], u["kind"], u["x"], u["y"])
        units.append(Unit(made.id, made.faction, made.kind, made.x, made.y, u.get("hp", made.max_hp)))
    s = GameState(Grid.from_text("\n".join(d["map"])), units, d.get("turn", 1), d.get("active", "blue"))
    s.moved = set(d.get("moved", []))
    s.acted = set(d.get("acted", []))
    return s


def to_json(state):
    return json.dumps(to_dict(state), sort_keys=True)


def from_json(text):
    return from_dict(json.loads(text))
