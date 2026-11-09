from .grid import line_of_sight
from .state import IllegalAction


def distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def can_attack(state, attacker, defender, from_pos=None):
    if attacker.faction == defender.faction:
        return False
    src = tuple(from_pos) if from_pos is not None else attacker.pos
    d = distance(src, defender.pos)
    if not attacker.range_min <= d <= attacker.range_max:
        return False
    return attacker.range_max <= 1 or line_of_sight(state.grid, src, defender.pos)


def damage(state, attacker, defender):
    return max(1, attacker.attack - defender.defense - state.grid.defense(*defender.pos))


def _hit(state, a, d):
    n = damage(state, a, d)
    d.hp -= n
    killed = d.hp <= 0
    if killed:
        state.remove(d.id)
    return {"attacker": a.id, "defender": d.id, "damage": n, "defender_hp": d.hp, "killed": killed}


def attack(state, attacker_id, defender_id):
    try:
        a, d = state.unit(attacker_id), state.unit(defender_id)
    except KeyError:
        raise IllegalAction("no such unit") from None
    if a.faction != state.active or attacker_id in state.acted or not can_attack(state, a, d):
        raise IllegalAction(f"{attacker_id} cannot attack {defender_id}")
    events = [_hit(state, a, d)]
    if not events[0]["killed"] and can_attack(state, d, a):
        events.append(_hit(state, d, a))
    state.acted.add(attacker_id)
    state.moved.add(attacker_id)
    return events
