# Skirmish: a turn-based tactics game core

Build a Python package named `skirmish` in the root of this repository (`skirmish/__init__.py` and the modules
below). Python 3.11 or later, **standard library only**. A hidden test suite will import the modules and run the
command-line interface, so module names, function names, signatures, exceptions and output text must match this
specification exactly. Write your own tests as well.

Coordinates are `(x, y)` tuples: `x` is the column, counted from 0 at the left; `y` is the row, counted from 0 at the top.

## 1. `skirmish.grid`

| Char | Terrain | Move cost | Defense bonus | Blocks sight |
|---|---|---|---|---|
| `.` | plain | 1 | 0 | no |
| `F` | forest | 2 | 1 | no |
| `^` | hill | 3 | 2 | no |
| `~` | water | impassable | 0 | no |
| `#` | wall | impassable | 0 | yes |

`class Grid`:
- `Grid.from_text(text: str) -> Grid`. Each line is a row. Trailing whitespace on a line is ignored, and blank lines
  at the start and end are ignored. Raises `ValueError` if rows differ in length, if there are no rows, or if a
  character is not in the table.
- Attributes `width` and `height`.
- `char(x, y) -> str`, `in_bounds(x, y) -> bool`, `move_cost(x, y) -> int | None` (`None` when impassable),
  `defense(x, y) -> int`, `blocks_sight(x, y) -> bool`.
- `neighbors(x, y) -> list[tuple[int, int]]`: the in-bounds orthogonal neighbours, in the order north `(x, y-1)`,
  east `(x+1, y)`, south `(x, y+1)`, west `(x-1, y)`.
- `to_text() -> str`: the rows joined by `"\n"`, with no trailing newline.

`line_of_sight(grid, a, b) -> bool`, for cells `a` and `b`: true when no cell strictly between them blocks sight.
The cells between them are those this algorithm visits, excluding `a` and `b`:

```
x, y = a; x1, y1 = b
dx = abs(x1 - x); dy = -abs(y1 - y)
sx = 1 if x < x1 else -1; sy = 1 if y < y1 else -1
err = dx + dy
loop:
    visit (x, y)
    if (x, y) == (x1, y1): stop
    e2 = 2 * err
    if e2 >= dy: err += dy; x += sx
    if e2 <= dx: err += dx; y += sy
```

## 2. `skirmish.units`

| Kind | Letter | max_hp | attack | defense | move | range_min | range_max |
|---|---|---|---|---|---|---|---|
| soldier | S | 10 | 4 | 2 | 4 | 1 | 1 |
| archer | A | 7 | 4 | 1 | 3 | 2 | 3 |
| knight | K | 14 | 5 | 3 | 5 | 1 | 1 |

- `@dataclass class Unit` with fields `id: str`, `faction: str` (`"blue"` or `"red"`), `kind: str`, `x: int`,
  `y: int`, `hp: int`, and read-only properties `max_hp`, `attack`, `defense`, `move`, `range_min`, `range_max`,
  `pos` (the tuple `(x, y)`) and `letter` (the table's letter, upper case for blue, lower case for red).
- `make_unit(id, faction, kind, x, y) -> Unit` with `hp` set to `max_hp`. Raises `ValueError` for an unknown kind or
  faction.

## 3. `skirmish.state`

- `class IllegalAction(Exception)`.
- `class GameState(grid, units, turn=1, active="blue")`, where `units` is a list of `Unit`. Attributes `grid`,
  `turn`, `active`, `moved` and `acted` (sets of unit ids).
- `unit(id) -> Unit` (raises `KeyError` if absent), `unit_at(x, y) -> Unit | None`,
  `units_of(faction) -> list[Unit]` sorted by id, `all_units() -> list[Unit]` sorted by id.
- Each turn, each unit of the active faction may **move once, then attack once**. It cannot move after attacking.
- `move(unit_id, dest)`: raises `IllegalAction` if the unit does not belong to the active faction, has already moved
  or attacked this turn, or `dest` is not in `reachable(state, unit)`. Otherwise it moves the unit and adds its id to
  `moved`. Moving to the unit's own cell is allowed and counts as its move.
- `end_turn()`: the active faction switches from blue to red or from red to blue. When red's turn ends, `turn` goes
  up by 1. `moved` and `acted` are cleared.
- `winner() -> str | None`: `"blue"` if red has no units left, `"red"` if blue has none, otherwise `None`.

## 4. `skirmish.movement`

`reachable(state, unit) -> dict[tuple[int, int], int]`: every cell the unit may end its move on, mapped to the
lowest total cost of getting there. The cost of a route is the sum of the move costs of the cells it enters (not the
start cell). A route may not enter an impassable cell or a cell holding an enemy unit. It may pass through cells
holding units of its own faction, but may not end on any cell holding another unit. The total cost must be at most
`unit.move`. The start cell is included, with cost 0.

## 5. `skirmish.combat`

- `distance(a, b) -> int`: Manhattan distance between two cells.
- `can_attack(state, attacker, defender, from_pos=None) -> bool`: true when the two units belong to different
  factions, `range_min <= distance <= range_max` (from the attacker's position, or from `from_pos` if given), and,
  when the attacker's `range_max` is greater than 1, there is line of sight between those cells.
- `damage(state, attacker, defender) -> int`:
  `max(1, attacker.attack - defender.defense - grid.defense(defender's cell))`.
- `attack(state, attacker_id, defender_id) -> list[dict]`: raises `IllegalAction` if the attacker does not belong to
  the active faction, has already attacked this turn, or `can_attack` is false. Otherwise the defender loses
  `damage(...)` hp and an event `{"attacker": ..., "defender": ..., "damage": ..., "defender_hp": ..., "killed": ...}`
  is recorded. A unit at 0 hp or below is removed from the game. If the defender survives and can attack the attacker
  back (by `can_attack`, from where they stand), it counterattacks once, recorded as a second event in the same form
  with the roles swapped. The attacker's id is added to both `acted` and `moved`. Returns the events in order.

## 6. `skirmish.ai`

`take_turn(state) -> list[str]` plays every unit of the active faction, in id order, skipping units that have died.
It does **not** end the turn. For each unit:

1. If it can attack an enemy from where it stands, it attacks. Target: the enemy with the lowest hp; ties go to the
   lowest id.
2. Otherwise, among the cells in `reachable(state, unit)`, take those from which it could attack some enemy
   (`can_attack` with `from_pos`). If there are any, move to the one with the lowest cost (ties: lowest `y`, then
   lowest `x`), then attack, choosing the target as in rule 1.
3. Otherwise, move to the reachable cell with the smallest Manhattan distance to its nearest enemy (ties: lowest
   cost, then lowest `y`, then lowest `x`). If that cell is the one it stands on, it does not move.

It returns the actions it took, as the same command strings the CLI accepts: `"move <id> <x> <y>"` and
`"attack <id> <target>"`.

## 7. `skirmish.saveload`

`to_dict(state) -> dict`, `from_dict(d) -> GameState`, `to_json(state) -> str` (`json.dumps` of `to_dict` with
`sort_keys=True`), `from_json(text) -> GameState`. The format:

```json
{"version": 1, "turn": 1, "active": "blue",
 "map": ["....", ".F^.", "..#~"],
 "units": [{"id": "b1", "faction": "blue", "kind": "soldier", "x": 0, "y": 0, "hp": 10}],
 "moved": [], "acted": []}
```

`units`, `moved` and `acted` are sorted by id. `from_dict` raises `ValueError` if `version` is not 1, and accepts
files that leave out `turn` (default 1), `active` (default `"blue"`), `moved` and `acted` (default empty), and a
unit's `hp` (default its `max_hp`). A round trip `to_dict(from_json(to_json(state)))` equals `to_dict(state)`.
Scenario files for the CLI use this format.

## 8. Command line: `python -m skirmish`

`python -m skirmish show SCENARIO.json` prints the map, one row per line, with each unit's letter drawn over its cell,
then one line per unit, sorted by id: `<id> <faction> <kind> <x>,<y> hp <hp>/<max_hp>`.

`python -m skirmish play SCENARIO.json SCRIPT.txt` runs the commands in the script, one per line. Blank lines and lines
starting with `#` are ignored. Output, one line each:

| Command | Prints |
|---|---|
| `move <id> <x> <y>` | `moved <id> <x> <y>` |
| `attack <id> <target>` | for each event, `<attacker> hits <defender> for <damage> (hp <defender_hp>)`, followed by `<defender> is defeated` if it was killed |
| `end` | ends the turn, then `turn <turn> <active>` |
| `ai` | the AI plays the active faction, printing the lines its moves and attacks would print as commands, then ends the turn and prints `turn <turn> <active>`. If a winner appears during the AI's turn, the AI stops and the turn does not end |

A command that is illegal or malformed prints `illegal: <the line as written>` and the script continues. As soon as
there is a winner, the script stops. At the end the program prints `winner <faction>`, or `no winner`, and exits 0. If
a file cannot be read, it prints an error to stderr and exits 2.
