import sys

from .ai import take_turn
from .combat import attack
from .saveload import from_dict, from_json, to_dict
from .state import IllegalAction


def show(state):
    rows = [list(r) for r in state.grid.rows]
    for u in state.all_units():
        rows[u.y][u.x] = u.letter
    print("\n".join("".join(r) for r in rows))
    for u in state.all_units():
        print(f"{u.id} {u.faction} {u.kind} {u.x},{u.y} hp {u.hp}/{u.max_hp}")


def run(state, parts):
    """Apply one move or attack command and return its output lines. Raises IllegalAction or ValueError."""
    if parts[0] == "move" and len(parts) == 4:
        state.move(parts[1], (int(parts[2]), int(parts[3])))
        return [f"moved {parts[1]} {parts[2]} {parts[3]}"]
    if parts[0] == "attack" and len(parts) == 3:
        out = []
        for e in attack(state, parts[1], parts[2]):
            out.append(f"{e['attacker']} hits {e['defender']} for {e['damage']} (hp {e['defender_hp']})")
            if e["killed"]:
                out.append(f"{e['defender']} is defeated")
        return out
    raise IllegalAction(" ".join(parts))


def play(state, lines):
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        try:
            if parts == ["end"]:
                state.end_turn()
                print(f"turn {state.turn} {state.active}")
            elif parts == ["ai"]:
                actions = take_turn(from_dict(to_dict(state)))       # plan on a copy, then replay for the output
                for act in actions:
                    for out in run(state, act.split()):
                        print(out)
                    if state.winner():
                        break
                if not state.winner():
                    state.end_turn()
                    print(f"turn {state.turn} {state.active}")
            else:
                for out in run(state, parts):
                    print(out)
        except (IllegalAction, ValueError, KeyError):
            print(f"illegal: {raw.rstrip()}")
        if state.winner():
            break
    w = state.winner()
    print(f"winner {w}" if w else "no winner")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2 or argv[0] not in ("show", "play") or (argv[0] == "play" and len(argv) < 3):
        print("usage: python -m skirmish show SCENARIO.json | play SCENARIO.json SCRIPT.txt", file=sys.stderr)
        return 2
    try:
        with open(argv[1], encoding="utf-8") as f:
            state = from_json(f.read())
        script = []
        if argv[0] == "play":
            with open(argv[2], encoding="utf-8") as f:
                script = f.read().splitlines()
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    show(state) if argv[0] == "show" else play(state, script)
    return 0


if __name__ == "__main__":
    sys.exit(main())
