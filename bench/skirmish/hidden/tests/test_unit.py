"""Component tests: each checks one module against SPEC.md. Expected values are worked out by hand from the spec."""
import json

import pytest

from skirmish.grid import Grid, line_of_sight
from skirmish.units import make_unit
from skirmish.state import GameState, IllegalAction
from skirmish.movement import reachable
from skirmish.combat import attack, can_attack, damage, distance
from skirmish.ai import take_turn
from skirmish.saveload import from_dict, from_json, to_dict, to_json


def game(rows, *units, active="blue"):
    return GameState(Grid.from_text("\n".join(rows)), [make_unit(*u) for u in units], active=active)


# --- grid --------------------------------------------------------------------

def test_grid_terrain_table():
    g = Grid.from_text("...\n.F^\n~#.")
    assert (g.width, g.height, g.char(1, 1)) == (3, 3, "F")
    assert [g.move_cost(*c) for c in ((0, 0), (1, 1), (2, 1), (0, 2), (1, 2))] == [1, 2, 3, None, None]
    assert [g.defense(*c) for c in ((0, 0), (1, 1), (2, 1))] == [0, 1, 2]
    assert g.blocks_sight(1, 2) and not g.blocks_sight(0, 2)


def test_grid_ignores_trailing_whitespace_and_blank_edges():
    g = Grid.from_text("\n...  \n...\n\n")
    assert (g.width, g.height, g.to_text()) == (3, 2, "...\n...")


@pytest.mark.parametrize("text", ["..\n...", "..X", "", "\n\n"])
def test_grid_rejects_bad_maps(text):
    with pytest.raises(ValueError):
        Grid.from_text(text)


def test_grid_neighbors_order_and_bounds():
    g = Grid.from_text("...\n...\n...")
    assert g.neighbors(0, 0) == [(1, 0), (0, 1)]
    assert g.neighbors(1, 1) == [(1, 0), (2, 1), (1, 2), (0, 1)]
    assert g.in_bounds(2, 2) and not g.in_bounds(3, 0) and not g.in_bounds(0, -1)


def test_line_of_sight():
    g = Grid.from_text(".....\n..#..\n.....")
    assert not line_of_sight(g, (0, 1), (4, 1))
    assert line_of_sight(g, (0, 0), (4, 0))
    assert line_of_sight(g, (1, 1), (2, 1))          # the wall is an endpoint, not between
    assert not line_of_sight(g, (1, 0), (3, 2))      # the diagonal passes through (2, 1)


# --- units -------------------------------------------------------------------

def test_unit_stats():
    a = make_unit("b1", "blue", "archer", 2, 3)
    assert (a.hp, a.max_hp, a.attack, a.defense, a.move, a.range_min, a.range_max) == (7, 7, 4, 1, 3, 2, 3)
    assert (a.pos, a.letter) == ((2, 3), "A")
    assert make_unit("r1", "red", "knight", 0, 0).letter == "k"
    k = make_unit("x", "red", "knight", 0, 0)
    assert (k.max_hp, k.attack, k.defense, k.move) == (14, 5, 3, 5)


@pytest.mark.parametrize("faction,kind", [("green", "soldier"), ("blue", "dragon")])
def test_unit_rejects_unknown_values(faction, kind):
    with pytest.raises(ValueError):
        make_unit("x", faction, kind, 0, 0)


# --- movement ----------------------------------------------------------------

def test_reachable_costs():
    s = game([".....", ".F...", "....."], ("b1", "blue", "soldier", 0, 0))
    r = reachable(s, s.unit("b1"))
    assert r[(0, 0)] == 0 and r[(4, 0)] == 4 and r[(1, 1)] == 3 and r[(2, 1)] == 3 and r[(2, 2)] == 4
    assert (4, 1) not in r


def test_enemies_block_and_allies_do_not():
    s = game([".....", ".F...", "....."], ("b1", "blue", "soldier", 0, 0), ("r1", "red", "soldier", 1, 0))
    r = reachable(s, s.unit("b1"))
    assert (1, 0) not in r and (2, 0) not in r
    s = game([".....", ".F...", "....."], ("b1", "blue", "soldier", 0, 0), ("b2", "blue", "soldier", 1, 0))
    r = reachable(s, s.unit("b1"))
    assert (1, 0) not in r and r[(2, 0)] == 2


def test_impassable_terrain():
    s = game(["..~.."], ("b1", "blue", "soldier", 0, 0))
    assert set(reachable(s, s.unit("b1"))) == {(0, 0), (1, 0)}


# --- state -------------------------------------------------------------------

def test_move_rules():
    s = game([".....", "....."], ("b1", "blue", "soldier", 0, 0), ("r1", "red", "soldier", 4, 1))
    s.move("b1", (2, 0))
    assert s.unit("b1").pos == (2, 0) and "b1" in s.moved and s.unit_at(2, 0).id == "b1"
    with pytest.raises(IllegalAction):
        s.move("b1", (3, 0))                       # already moved
    with pytest.raises(IllegalAction):
        s.move("r1", (3, 1))                       # not red's turn
    t = game([".....", "....."], ("b1", "blue", "soldier", 0, 0))
    with pytest.raises(IllegalAction):
        t.move("b1", (4, 1))                       # cost 5, move 4
    t.move("b1", (0, 0))                           # staying put counts as the move
    assert "b1" in t.moved


def test_turns_and_winner():
    s = game(["...."], ("b1", "blue", "soldier", 0, 0), ("r1", "red", "soldier", 3, 0))
    s.move("b1", (1, 0))
    s.end_turn()
    assert (s.turn, s.active, s.moved) == (1, "red", set())
    s.end_turn()
    assert (s.turn, s.active) == (2, "blue")
    assert s.winner() is None
    assert [u.id for u in s.units_of("blue")] == ["b1"] and [u.id for u in s.all_units()] == ["b1", "r1"]
    with pytest.raises(KeyError):
        s.unit("zz")
    assert s.unit_at(2, 0) is None


# --- combat ------------------------------------------------------------------

def test_melee_with_counterattack():
    s = game([".....", ".....", "....."], ("b1", "blue", "soldier", 1, 1), ("r1", "red", "soldier", 2, 1))
    events = attack(s, "b1", "r1")
    assert events == [{"attacker": "b1", "defender": "r1", "damage": 2, "defender_hp": 8, "killed": False},
                      {"attacker": "r1", "defender": "b1", "damage": 2, "defender_hp": 8, "killed": False}]
    assert "b1" in s.acted and "b1" in s.moved
    with pytest.raises(IllegalAction):
        attack(s, "b1", "r1")                      # once per turn
    with pytest.raises(IllegalAction):
        s.move("b1", (1, 0))                       # no move after attacking


def test_terrain_defense_and_minimum_damage():
    s = game([".F^"], ("b1", "blue", "soldier", 0, 0), ("r1", "red", "soldier", 1, 0), ("r2", "red", "knight", 2, 0))
    assert damage(s, s.unit("b1"), s.unit("r1")) == 1           # 4 - 2 - 1
    assert damage(s, s.unit("b1"), s.unit("r2")) == 1           # 4 - 3 - 2 is below 1


def test_archer_range_and_no_counter_from_melee():
    s = game(["....."], ("b2", "blue", "archer", 0, 0), ("r1", "red", "soldier", 2, 0))
    events = attack(s, "b2", "r1")
    assert len(events) == 1 and events[0]["damage"] == 2 and s.unit("r1").hp == 8
    t = game(["....."], ("b2", "blue", "archer", 0, 0), ("r1", "red", "soldier", 1, 0))
    assert not can_attack(t, t.unit("b2"), t.unit("r1"))       # too close
    with pytest.raises(IllegalAction):
        attack(t, "b2", "r1")


def test_walls_block_archers_but_not_melee_range_checks():
    s = game([".#."], ("b2", "blue", "archer", 0, 0), ("r1", "red", "soldier", 2, 0))
    assert not can_attack(s, s.unit("b2"), s.unit("r1"))
    t = game(["...", "...", "..."], ("b2", "blue", "archer", 0, 0), ("r1", "red", "soldier", 2, 0))
    assert can_attack(t, t.unit("b2"), t.unit("r1")) and distance((0, 0), (2, 1)) == 3


def test_kills_remove_units_and_skip_the_counter():
    s = game(["..."], ("b1", "blue", "knight", 0, 0), ("r1", "red", "archer", 1, 0))
    s.unit("r1").hp = 3
    events = attack(s, "b1", "r1")
    assert events == [{"attacker": "b1", "defender": "r1", "damage": 4, "defender_hp": -1, "killed": True}]
    assert s.unit_at(1, 0) is None and s.winner() == "blue"


def test_a_counterattack_can_kill_the_attacker():
    s = game(["..."], ("b1", "blue", "soldier", 0, 0), ("r1", "red", "soldier", 1, 0))
    s.unit("b1").hp = 2
    events = attack(s, "b1", "r1")
    assert events[1]["killed"] is True and s.winner() == "red"


def test_only_the_active_faction_attacks():
    s = game(["..."], ("b1", "blue", "soldier", 0, 0), ("r1", "red", "soldier", 1, 0))
    with pytest.raises(IllegalAction):
        attack(s, "r1", "b1")


# --- ai ----------------------------------------------------------------------

def test_ai_attacks_without_moving_when_it_can():
    s = game(["....."], ("b1", "blue", "soldier", 3, 0), ("r1", "red", "soldier", 2, 0), active="red")
    assert take_turn(s) == ["attack r1 b1"] and s.unit("b1").hp == 8 and s.active == "red"


def test_ai_moves_to_the_cheapest_attack_cell():
    s = game(["....."], ("b1", "blue", "soldier", 3, 0), ("r1", "red", "soldier", 0, 0), active="red")
    assert take_turn(s) == ["move r1 2 0", "attack r1 b1"]


def test_ai_breaks_cost_ties_by_y_then_x():
    s = game([".....", "..~..", "....."], ("b1", "blue", "soldier", 2, 0), ("r1", "red", "soldier", 2, 2),
             active="red")
    assert take_turn(s) == ["move r1 1 0", "attack r1 b1"]


def test_ai_targets_the_weakest_then_lowest_id():
    s = game(["...", "...", "..."], ("b1", "blue", "soldier", 1, 0), ("b2", "blue", "soldier", 2, 1),
             ("r1", "red", "soldier", 1, 1), active="red")
    s.unit("b2").hp = 5
    assert take_turn(s) == ["attack r1 b2"]
    t = game(["...", "...", "..."], ("b2", "blue", "soldier", 1, 0), ("b1", "blue", "soldier", 2, 1),
             ("r1", "red", "soldier", 1, 1), active="red")
    assert take_turn(t) == ["attack r1 b1"]


def test_ai_approaches_when_nothing_is_in_reach():
    s = game([".........."], ("b1", "blue", "soldier", 9, 0), ("r1", "red", "soldier", 0, 0), active="red")
    assert take_turn(s) == ["move r1 4 0"] and s.unit("r1").pos == (4, 0)


# --- saveload ----------------------------------------------------------------

def test_save_round_trip_and_format():
    s = game(["..F", "^.."], ("r1", "red", "archer", 2, 1), ("b1", "blue", "soldier", 0, 0))
    s.move("b1", (1, 0))
    d = json.loads(to_json(s))
    assert d == {"version": 1, "turn": 1, "active": "blue", "map": ["..F", "^.."],
                 "units": [{"id": "b1", "faction": "blue", "kind": "soldier", "x": 1, "y": 0, "hp": 10},
                           {"id": "r1", "faction": "red", "kind": "archer", "x": 2, "y": 1, "hp": 7}],
                 "moved": ["b1"], "acted": []}
    assert to_dict(from_json(to_json(s))) == to_dict(s)
    assert list(json.loads(to_json(s))) == sorted(json.loads(to_json(s)))


def test_load_defaults_and_version():
    s = from_dict({"version": 1, "map": ["..."], "units": [{"id": "b1", "faction": "blue", "kind": "knight",
                                                            "x": 0, "y": 0}]})
    assert (s.turn, s.active, s.moved, s.acted, s.unit("b1").hp) == (1, "blue", set(), set(), 14)
    with pytest.raises(ValueError):
        from_dict({"version": 2, "map": ["..."], "units": []})
