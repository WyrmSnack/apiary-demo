"""Test-first gates (Phase 10 gate f): tdd red and green, and the story ladder."""
import json
import os
import sys
from pathlib import Path

import pytest

from apiary.gates import stories, tdd

FAKE_GODOT = r'''import json, sys
# Plays apiary's GDScript runner: results come from results.json in the working directory.
args = sys.argv[1:]
only = []
if "--files" in args:
    only = args[args.index("--files") + 1].split(",")
results = json.load(open("results.json", encoding="utf-8"))
passed = failed = 0
for path, tests in results.items():
    if only and path not in only:
        continue
    if tests == "noload":
        print(f"FAIL {path}: does not load (parse error?)"); failed += 1; continue
    for name, ok in tests.items():
        print(f"{'PASS' if ok else 'FAIL'} {path}::{name}")
        passed += ok; failed += not ok
print(f"APIARY-TESTS: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 and passed > 0 else 1)
'''


@pytest.fixture
def colony(tmp_path, monkeypatch):
    root = tmp_path / "colony"
    (root / "game/tests/feature").mkdir(parents=True)
    (root / "game/tests/unit").mkdir(parents=True)
    (root / "game/project.godot").write_text("config_version=5\n", encoding="utf-8")
    script = tmp_path / "fake_godot.py"
    script.write_text(FAKE_GODOT, encoding="utf-8")
    if os.name == "nt":
        exe = tmp_path / "godot.bat"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="ascii")
    else:
        exe = tmp_path / "godot"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="ascii")
        exe.chmod(0o755)
    monkeypatch.chdir(root)
    root = Root(root)
    root.exe = str(exe)
    return root


class Root(type(Path())):
    """The colony folder, carrying the fake Godot's path."""


def results(root, **files):
    """files: res path -> {test: passed} or "noload"; also writes each test file so it can be hashed."""
    data = {}
    for key, tests in files.items():
        res = "res://tests/" + key.replace("__", "/") + ".gd"
        data[res] = tests
        p = root / "game/tests" / (key.replace("__", "/") + ".gd")
        if not p.exists():
            p.write_text(f"extends \"res://tests/case.gd\"\n# {key}\n", encoding="utf-8")
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


def red(root, *files, lock=True):
    return tdd.red("game", [f"game/tests/{f}.gd" for f in files], lock=lock, godot=root.exe)


def green(root, *files):
    return tdd.green("game", [f"game/tests/{f}.gd" for f in files], godot=root.exe)


# --- red ---------------------------------------------------------------------------

def test_red_passes_when_every_named_test_fails_and_locks_them(colony):
    results(colony, feature__test_zoning={"test_zone_a_lot": False, "test_demand": False})
    assert red(colony, "feature/test_zoning") == []
    locks = json.loads((colony / ".apiary/tdd/locks.json").read_text(encoding="utf-8"))
    assert list(locks) == ["game/tests/feature/test_zoning.gd"]
    assert locks["game/tests/feature/test_zoning.gd"]["green"] is None


@pytest.mark.parametrize("tests,why", [
    ({"test_a": False, "test_b": True}, "already passes"),
    ("noload", "does not load"),
    ({}, "no tests"),
])
def test_red_fails_unless_every_test_loads_and_fails(colony, tests, why):
    results(colony, feature__test_zoning=tests)
    problems = red(colony, "feature/test_zoning")
    assert problems and any(why in p for p in problems), problems
    assert not (colony / ".apiary/tdd/locks.json").exists()


def test_red_without_lock_checks_but_writes_nothing(colony):
    results(colony, unit__test_grid={"test_cell": False})
    assert red(colony, "unit/test_grid", lock=False) == []
    assert not (colony / ".apiary/tdd/locks.json").exists()


def test_red_ignores_other_files_failing_or_passing(colony):
    results(colony, unit__test_grid={"test_cell": False}, unit__test_other={"test_x": True})
    assert red(colony, "unit/test_grid") == []


def test_a_lock_is_never_replaced_with_different_tests(colony):
    results(colony, unit__test_grid={"test_cell": False})
    assert red(colony, "unit/test_grid") == []
    assert red(colony, "unit/test_grid") == []                  # same contents: fine, idempotent
    (colony / "game/tests/unit/test_grid.gd").write_text("extends RefCounted\n# weaker\n", encoding="utf-8")
    problems = red(colony, "unit/test_grid")
    assert problems and "locked" in problems[0] and "human" in problems[0], problems


def test_red_needs_a_named_file_that_exists_under_the_project(colony):
    results(colony)
    assert "does not exist" in red(colony, "unit/test_nothing")[0]


# --- green -------------------------------------------------------------------------

def test_green_passes_when_locked_tests_now_pass_and_records_it(colony):
    results(colony, unit__test_grid={"test_cell": False})
    assert red(colony, "unit/test_grid") == []
    results(colony, unit__test_grid={"test_cell": True})
    assert green(colony, "unit/test_grid") == []
    locks = json.loads((colony / ".apiary/tdd/locks.json").read_text(encoding="utf-8"))
    assert locks["game/tests/unit/test_grid.gd"]["green"]


def test_green_refuses_tests_never_seen_failing(colony):
    results(colony, unit__test_grid={"test_cell": True})
    problems = green(colony, "unit/test_grid")
    assert problems and "never seen failing" in problems[0], problems


def test_green_refuses_a_test_changed_since_red(colony):
    results(colony, unit__test_grid={"test_cell": False})
    red(colony, "unit/test_grid")
    (colony / "game/tests/unit/test_grid.gd").write_text("extends RefCounted\n# made easier\n", encoding="utf-8")
    results(colony, unit__test_grid={"test_cell": True})
    problems = green(colony, "unit/test_grid")
    assert problems and "changed since" in problems[0], problems


def test_green_ignores_line_endings_changed_by_git(colony):
    """Kevin's git has core.autocrlf: a checkout may turn a locked test's LF into CRLF without changing it."""
    p = colony / "game/tests/unit/test_grid.gd"
    p.write_bytes(b'extends "res://tests/case.gd"\nfunc test_a():\n\tcheck(false)\n')      # LF, as an agent writes it
    results(colony, unit__test_grid={"test_a": False})
    assert red(colony, "unit/test_grid") == []
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))                                  # git checkout: CRLF
    results(colony, unit__test_grid={"test_a": True})
    assert green(colony, "unit/test_grid") == []


def test_green_fails_while_a_named_test_still_fails(colony):
    results(colony, unit__test_grid={"test_a": False, "test_b": False})
    red(colony, "unit/test_grid")
    results(colony, unit__test_grid={"test_a": True, "test_b": False})
    problems = green(colony, "unit/test_grid")
    assert problems and "test_b" in problems[0], problems


def test_green_allows_other_locked_tests_still_waiting_for_their_code(colony):
    results(colony, unit__test_grid={"test_a": False}, feature__test_zoning={"test_f": False})
    red(colony, "unit/test_grid", "feature/test_zoning")
    results(colony, unit__test_grid={"test_a": True}, feature__test_zoning={"test_f": False})
    assert green(colony, "unit/test_grid") == []


def test_green_fails_on_a_regression_in_an_earlier_green_file(colony):
    results(colony, unit__test_grid={"test_a": False}, unit__test_power={"test_p": False})
    red(colony, "unit/test_grid", "unit/test_power")
    results(colony, unit__test_grid={"test_a": True}, unit__test_power={"test_p": False})
    assert green(colony, "unit/test_grid") == []
    results(colony, unit__test_grid={"test_a": False}, unit__test_power={"test_p": True})
    problems = green(colony, "unit/test_power")
    assert any("regression" in p and "test_grid" in p for p in problems), problems


def test_green_fails_on_an_unlocked_failing_test(colony):
    results(colony, unit__test_grid={"test_a": False}, unit__test_loose={"test_l": False})
    red(colony, "unit/test_grid")
    results(colony, unit__test_grid={"test_a": True}, unit__test_loose={"test_l": False})
    problems = green(colony, "unit/test_grid")
    assert any("test_loose" in p for p in problems), problems


def test_cli_exit_codes(colony, capsys):
    results(colony, unit__test_grid={"test_a": False})
    args = ["--project", "game", "--tests", "game/tests/unit/test_grid.gd", "--godot", colony.exe]
    assert tdd.main(["green", *args]) == 1
    assert tdd.main(["red", *args, "--lock"]) == 0
    assert "PASS" in capsys.readouterr().out


# --- stories ------------------------------------------------------------------------

MANUAL = """<html><body><h1>Beyond the Ice Wall</h1>
<h2>Building the city</h2><h3>Zones</h3><h3>Power</h3>
<h2>The continent</h2><h3>Terrain</h3><h3>Garrisons, bases and forts</h3></body></html>"""


def story(root, name, **fm):
    body = fm.pop("body", "As a mayor, I want to zone land, so that the city grows.\n\n## Acceptance criteria\n\n- a zone can be painted\n")
    lines = ["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["---", "", body]
    p = root / "docs/stories" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture
def ladder(colony):
    (colony / "docs/source").mkdir(parents=True)
    (colony / "docs/source/manual.html").write_text(MANUAL, encoding="utf-8")
    story(colony, "US-001.md", id="US-001", kind="user", title="Zone the city", slice="S1",
          source="Building the city; Zones; Power")
    story(colony, "US-002.md", id="US-002", kind="user", title="See the land", slice="S2",
          source="The continent; Terrain; Garrisons, bases and forts")
    story(colony, "FS-001.md", id="FS-001", kind="feature", parent="US-001", title="Paint zones",
          feature_tests="game/tests/feature/test_zoning.gd", unit_tests="game/tests/unit/test_grid.gd")
    results(colony, feature__test_zoning={"t": False}, unit__test_grid={"t": False})
    return colony


def check(stage, slice_="S1", manual="docs/source/manual.html"):
    return stories.check("docs/stories", stage=stage, manual=manual, slice_=slice_)


@pytest.mark.parametrize("stage", ["user", "feature", "tests", "units"])
def test_a_complete_ladder_passes_every_stage(ladder, stage):
    assert check(stage) == []


def test_every_manual_section_needs_a_user_story(ladder):
    story(ladder, "US-002.md", id="US-002", kind="user", title="See the land", slice="S2",
          source="The continent; Garrisons, bases and forts")
    problems = check("user")
    assert len(problems) == 1 and "Terrain" in problems[0], problems


def test_a_user_story_needs_the_story_form_and_criteria(ladder):
    story(ladder, "US-002.md", id="US-002", kind="user", title="x", slice="S2", source="The continent; Terrain",
          body="Make terrain.\n")
    problems = check("user")
    assert any("As a" in p for p in problems) and any("criteria" in p for p in problems), problems


def test_ids_are_unique_and_well_formed(ladder):
    story(ladder, "US-003.md", id="US-001", kind="user", title="dup", slice="S2", source="Terrain")
    story(ladder, "bad.md", id="story one", kind="epic", title="x")
    problems = check("user")
    assert any("US-001" in p and "twice" in p for p in problems), problems
    assert any("story one" in p for p in problems) and any("epic" in p for p in problems), problems


def test_feature_stage_needs_a_feature_story_per_user_story_in_the_slice(ladder):
    (ladder / "docs/stories/FS-001.md").unlink()
    problems = check("feature")
    assert len(problems) == 1 and "US-001" in problems[0], problems
    assert check("feature", slice_="S2") != []          # US-002 is in S2 and has none either


def test_feature_story_parent_must_exist(ladder):
    story(ladder, "FS-002.md", id="FS-002", kind="feature", parent="US-099", title="orphan",
          feature_tests="game/tests/feature/test_zoning.gd", unit_tests="game/tests/unit/test_grid.gd")
    assert any("US-099" in p for p in check("feature"))


@pytest.mark.parametrize("field,stage", [("feature_tests", "tests"), ("unit_tests", "units")])
def test_tests_and_units_stages_need_existing_test_files(ladder, field, stage):
    story(ladder, "FS-001.md", id="FS-001", kind="feature", parent="US-001", title="Paint zones",
          **{"feature_tests": "game/tests/feature/test_zoning.gd", "unit_tests": "game/tests/unit/test_grid.gd",
             field: "game/tests/x/test_missing.gd"})
    problems = check(stage)
    assert any("test_missing.gd" in p for p in problems), problems


def test_one_feature_story_can_be_checked_alone(ladder):
    story(ladder, "FS-002.md", id="FS-002", kind="feature", parent="US-001", title="Demand bars")
    assert any("FS-002" in p for p in check("units"))                  # the slice: FS-002 has no tests yet
    assert stories.check("docs/stories", stage="units", story="FS-001") == []
    assert any("FS-002" in p for p in stories.check("docs/stories", stage="units", story="FS-002"))
    assert "no story" in stories.check("docs/stories", stage="units", story="FS-404")[0]
    story(ladder, "FS-003.md", id="FS-003", kind="feature", parent="US-099", title="orphan")
    assert stories.check("docs/stories", stage="units", story="FS-001") == []     # another story's problem is not its


def test_tdd_red_can_check_the_story_rung_in_the_same_command(ladder, capsys):
    """A task has one acceptance command: the test task's gate checks its story names the tests, then RED."""
    args = ["red", "--project", "game", "--tests", "game/tests/feature/test_zoning.gd,game/tests/unit/test_grid.gd",
            "--godot", ladder.exe, "--story", "FS-001"]
    assert tdd.main(args) == 0
    story(ladder, "FS-001.md", id="FS-001", kind="feature", parent="US-001", title="Paint zones",
          feature_tests="game/tests/feature/test_zoning.gd")                     # unit tests no longer named
    assert tdd.main(args) == 1 and "unit tests" in capsys.readouterr().out


def test_stories_cli(ladder, capsys):
    assert stories.main(["docs/stories", "--stage", "units", "--slice", "S1",
                         "--manual", "docs/source/manual.html"]) == 0
    (ladder / "docs/stories/FS-001.md").unlink()
    assert stories.main(["docs/stories", "--stage", "feature", "--slice", "S1"]) == 1


# --- apiary init --tdd ----------------------------------------------------------------

def test_init_tdd_installs_the_ladder_skill_and_tells_the_queen(tmp_path):
    from apiary.cli import main
    root = tmp_path / "c"
    root.mkdir()
    assert main(["--root", str(root), "init", "--tdd"]) == 0
    skill = (root / ".claude/skills/colony-tdd/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: colony-tdd\ndescription: ")
    assert "apiary.gates.tdd red" in skill and "apiary.gates.tdd green" in skill and "apiary.gates.stories" in skill
    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
    assert "<!-- apiary:tdd -->" in claude and "@.claude/skills/colony-tdd/SKILL.md" in claude
    assert main(["--root", str(root), "init", "--tdd"]) == 0            # again: nothing doubled
    assert (root / "CLAUDE.md").read_text(encoding="utf-8").count("<!-- apiary:tdd -->") == 1


def test_plain_init_has_no_tdd_ladder(tmp_path):
    from apiary.cli import main
    root = tmp_path / "c"
    root.mkdir()
    main(["--root", str(root), "init"])
    assert not (root / ".claude/skills/colony-tdd").exists()
    assert "apiary:tdd" not in (root / "CLAUDE.md").read_text(encoding="utf-8")


def test_the_guard_protects_the_ladder_skill_and_the_locks(tmp_path):
    from apiary.cli import main
    from apiary.hook import decide
    root = tmp_path / "c"
    root.mkdir()
    main(["--root", str(root), "init", "--tdd"])
    for rel in (".claude/skills/colony-tdd/SKILL.md", ".apiary/tdd/locks.json"):
        ev = {"tool_name": "Write", "cwd": str(root), "tool_input": {"file_path": str(root / rel)}}
        assert not decide(ev, root)[0], rel
        ev = {"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": f"echo {{}} > {rel}"}}
        assert not decide(ev, root)[0], rel


def test_update_protocols_refreshes_the_ladder_only_in_a_tdd_colony(tmp_path):
    from apiary.cli import main
    from apiary.init import update_protocols
    plain, tdd_root = tmp_path / "p", tmp_path / "t"
    for r, extra in ((plain, []), (tdd_root, ["--tdd"])):
        r.mkdir()
        main(["--root", str(r), "init", *extra])
    skill = tdd_root / ".claude/skills/colony-tdd/SKILL.md"
    skill.write_text("stale\n", encoding="utf-8")
    update_protocols(tdd_root)
    update_protocols(plain)
    assert skill.read_text(encoding="utf-8").startswith("---\nname: colony-tdd")
    assert not (plain / ".claude/skills/colony-tdd").exists()


def test_every_gate_command_in_the_ladder_skill_is_valid():
    import re
    import shlex
    from apiary.init import TDD_SKILL
    found = 0
    for line in TDD_SKILL.splitlines():
        for mod, fn in (("tdd", tdd.main), ("stories", stories.main)):
            m = re.search(rf"python -m apiary\.gates\.{mod} ([^`\"]+)", line)
            if not m:
                continue
            found += 1
            argv = [a for a in shlex.split(m.group(1)) if a != "--lock"] + ["--help"]
            with pytest.raises(SystemExit) as e:
                fn(argv)                                   # --help exits 0 only if everything before it parses
            assert e.value.code == 0, line
    assert found >= 4
