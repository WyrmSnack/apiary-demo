"""Integration tests: the command line, which needs every module working together. A build that passes the unit
tests but fails these has an integration defect (textbook Ch 3.5: parts that pass alone and fail together)."""
import json


def scenario(rows, units, **extra):
    return json.dumps({"version": 1, "map": rows, "units": units, **extra})


def u(id, faction, kind, x, y, **kw):
    return {"id": id, "faction": faction, "kind": kind, "x": x, "y": y, **kw}


def test_show_draws_units_and_lists_them(cli):
    code, out, _ = cli("show", "s.json", files={"s.json": scenario(
        ["...", ".F.", "..."], [u("r1", "red", "archer", 2, 2, hp=5), u("b1", "blue", "soldier", 0, 0)])})
    assert code == 0
    assert out == "S..\n.F.\n..a\nb1 blue soldier 0,0 hp 10/10\nr1 red archer 2,2 hp 5/7"


def test_play_moves_attacks_and_reports_illegal_lines(cli):
    code, out, _ = cli("play", "s.json", "moves.txt", files={
        "s.json": scenario(["....."], [u("b1", "blue", "soldier", 0, 0), u("r1", "red", "soldier", 3, 0)]),
        "moves.txt": "# opening\nmove b1 2 0\n\nattack b1 r1\nmove b1 1 0\njump b1\nend\n"})
    assert code == 0
    assert out.split("\n") == ["moved b1 2 0", "b1 hits r1 for 2 (hp 8)", "r1 hits b1 for 2 (hp 8)",
                               "illegal: move b1 1 0", "illegal: jump b1", "turn 1 red", "no winner"]


def test_ai_command_plays_and_ends_the_turn(cli):
    code, out, _ = cli("play", "s.json", "moves.txt", files={
        "s.json": scenario(["....."], [u("b1", "blue", "soldier", 2, 0), u("r1", "red", "soldier", 3, 0)]),
        "moves.txt": "end\nai\n"})
    assert out.split("\n") == ["turn 1 red", "r1 hits b1 for 2 (hp 8)", "b1 hits r1 for 2 (hp 8)", "turn 2 blue",
                               "no winner"]


def test_ai_moves_then_attacks_from_the_command_line(cli):
    code, out, _ = cli("play", "s.json", "moves.txt", files={
        "s.json": scenario(["....."], [u("b1", "blue", "soldier", 3, 0), u("r1", "red", "soldier", 0, 0)],
                           active="red"),
        "moves.txt": "ai\n"})
    assert out.split("\n") == ["moved r1 2 0", "r1 hits b1 for 2 (hp 8)", "b1 hits r1 for 2 (hp 8)", "turn 2 blue",
                               "no winner"]


def test_a_winner_stops_the_script(cli):
    code, out, _ = cli("play", "s.json", "moves.txt", files={
        "s.json": scenario(["..."], [u("b1", "blue", "knight", 0, 0), u("r1", "red", "archer", 1, 0, hp=4)]),
        "moves.txt": "attack b1 r1\nend\nend\n"})
    assert code == 0 and out.split("\n") == ["b1 hits r1 for 4 (hp 0)", "r1 is defeated", "winner blue"]


def test_ai_that_wins_does_not_end_the_turn(cli):
    code, out, _ = cli("play", "s.json", "moves.txt", files={
        "s.json": scenario(["..."], [u("b1", "blue", "archer", 0, 0, hp=1), u("r1", "red", "soldier", 1, 0)],
                           active="red"),
        "moves.txt": "ai\nend\n"})
    assert out.split("\n") == ["r1 hits b1 for 3 (hp -2)", "b1 is defeated", "winner red"]


def test_saved_state_resumes_where_it_left_off(cli):
    code, out, _ = cli("play", "s.json", "moves.txt", files={
        "s.json": scenario(["....."], [u("b1", "blue", "soldier", 0, 0), u("r1", "red", "soldier", 4, 0)],
                           turn=3, active="red", moved=["r1"]),
        "moves.txt": "move r1 3 0\nend\n"})
    assert out.split("\n") == ["illegal: move r1 3 0", "turn 4 blue", "no winner"]


def test_missing_files_exit_2(cli):
    code, out, err = cli("show", "nope.json")
    assert code == 2 and err.strip()
