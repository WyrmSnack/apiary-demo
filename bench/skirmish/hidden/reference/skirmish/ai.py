from .combat import attack, can_attack, distance
from .movement import reachable


def _target(state, unit, from_pos=None):
    enemies = [e for e in state.all_units() if can_attack(state, unit, e, from_pos)]
    return min(enemies, key=lambda e: (e.hp, e.id)) if enemies else None


def take_turn(state):
    actions = []
    for uid in [u.id for u in state.units_of(state.active)]:
        try:
            unit = state.unit(uid)
        except KeyError:
            continue
        target = _target(state, unit)
        if target is None:
            cells = reachable(state, unit)
            attack_cells = [c for c in cells if _target(state, unit, c) is not None]
            if attack_cells:
                dest = min(attack_cells, key=lambda c: (cells[c], c[1], c[0]))
            else:
                enemies = [u for u in state.all_units() if u.faction != unit.faction]
                if not enemies:
                    break
                dest = min(cells, key=lambda c: (min(distance(c, e.pos) for e in enemies), cells[c], c[1], c[0]))
            if dest != unit.pos:
                state.move(uid, dest)
                actions.append(f"move {uid} {dest[0]} {dest[1]}")
            target = _target(state, unit)
        if target is not None:
            attack(state, uid, target.id)
            actions.append(f"attack {uid} {target.id}")
    return actions
