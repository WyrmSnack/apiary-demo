"""Game-development connectors and skills (Phase 10 gate b), and the GDScript test runner (gate c)."""
import os
import re
import shlex
import sys
from pathlib import Path

import pytest

from apiary import connect, connectors
from apiary.cli import main
from apiary.colony import Colony
from apiary.gates import assets
from apiary.hook import decide
from apiary.init import update_protocols

GAME = ["godot", "aseprite", "blender", "ffmpeg", "sox", "tiled", "inkscape"]
# What each program prints for its version (Measured on Kevin's machine, 2026-10-17); Tiled prints nothing on Windows.
SAYS = {"godot": "4.7.2.stable.steam.ed1daf0bf", "aseprite": "Aseprite 1.3.18.3-x64", "blender": "Blender 4.4.3",
        "ffmpeg": "ffmpeg version 9.0.2-full_build-www.gyan.dev Copyright (c) 2000-2026",
        "sox": "sox:      SoX v14.4.2", "tiled": "", "inkscape": "Inkscape 1.4.4 (dcaf3e7, 2026-05-05)"}
VERSION = {"godot": "4.7.2", "aseprite": "1.3.18.3", "blender": "4.4.3", "ffmpeg": "9.0.2", "sox": "14.4.2",
           "tiled": "1.12.2", "inkscape": "1.4.4"}
SKILLS = {"godot": ["godot-project", "godot-gdscript-tests"], "aseprite": ["sprite-pipeline"],
          "blender": ["blender-asset-pipeline"], "ffmpeg": ["game-audio"], "sox": ["game-audio"],
          "tiled": ["tilemaps"], "inkscape": ["vector-art"]}
ALL_SKILLS = sorted({s for v in SKILLS.values() for s in v})
DATA = Path(__file__).parent / "data"


def fake_program(tmp_path, monkeypatch, name: str) -> Path:
    """A program called `name` on PATH that prints what the real one prints for its version."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    script = bindir / f"fake_{name}.py"
    script.write_text(f"print({SAYS[name]!r})\n" if SAYS[name] else "pass\n", encoding="utf-8")
    cmd = connectors.CATALOG[name].commands[0]
    if os.name == "nt":
        launcher = bindir / f"{cmd}.bat"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="ascii")
    else:
        launcher = bindir / cmd
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="ascii")
        launcher.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setitem(connectors.CATALOG[name].__dict__, "places", [])
    if name == "tiled":
        monkeypatch.setattr(connectors, "file_version", lambda exe: "1.12.2.0")
    return launcher


@pytest.fixture
def colony(tmp_path):
    root = tmp_path / "colony"
    root.mkdir()
    main(["--root", str(root), "init"])
    return root


@pytest.mark.parametrize("name", GAME)
def test_connect_add_knows_each_game_program_and_writes_its_traps(colony, tmp_path, monkeypatch, capsys, name):
    fake_program(tmp_path, monkeypatch, name)
    capsys.readouterr()
    assert main(["--root", str(colony), "connect", "add", name]) == 0, capsys.readouterr().out
    c = connectors.load(colony, name)
    known = connectors.CATALOG[name]
    assert c.version == VERSION[name]
    assert c.timeout_s == known.timeout_s and 1 <= c.timeout_s <= connectors.MAX_TIMEOUT_S
    assert c.error_patterns == known.error_patterns
    for skill in SKILLS[name]:
        text = (colony / f".claude/skills/{skill}/SKILL.md").read_text(encoding="utf-8")
        assert text.startswith(f"---\nname: {skill}\ndescription: "), skill
        assert "run_connector" in text and "python -m apiary.gates.assets" in text, skill
    others = set(ALL_SKILLS) - set(SKILLS[name])
    assert not any((colony / f".claude/skills/{s}").exists() for s in others)
    assert f"## `{name}`" in (colony / connect.SKILL_PATH).read_text(encoding="utf-8")


def test_a_program_that_prints_no_version_is_read_from_its_file(tmp_path, monkeypatch):
    """Measured: Tiled 1.12.2 on Windows prints nothing for --version; its program file says 1.12.2.0."""
    exe = fake_program(tmp_path, monkeypatch, "tiled")
    c = connectors.Connector("tiled", str(exe), ["--version"], r"(\d+\.\d+(?:\.\d+)?)")
    assert c.probe() == "1.12.2"
    monkeypatch.setattr(connectors, "file_version", lambda exe: "")
    assert c.probe() == "unknown"


@pytest.mark.parametrize("name,line,bad", [
    ("godot", "SCRIPT ERROR: Invalid call. Nonexistent function 'foo' in base 'Nil'.", True),
    ("godot", "ERROR: Failed to load script \"res://bad.gd\" with error \"Parse error\".", True),
    ("godot", "Godot Engine v4.7.2.stable.steam.ed1daf0bf - https://godotengine.org", False),
    ("godot", "APIARY-TESTS: 3 passed, 0 failed", False),
    ("aseprite", "No documents to export", True),
    ("aseprite", "C:\\x\\make.lua:1: boom", True),
    ("aseprite", "frames=3", False),
    ("inkscape", "** (org.inkscape.Inkscape:13548): WARNING **: 20:04:05.721: Can't open file: C:\\x\\missing.svg", True),
    ("inkscape", "C:\\x\\broken.svg:2: parser error : Couldn't find end of Start Tag svg line 1", True),
    ("inkscape", "** (org.inkscape.Inkscape:4456): WARNING **: 20:03:57.314: Units file  is missing", False),
    ("sox", "sox.exe FAIL formats: can't open input file `missing.wav': No such file or directory", True),
    ("sox", "sox.exe WARN rate: rate clipped 3 samples", False),
    ("blender", "Traceback (most recent call last):", True),
    ("blender", "Blender quit", False),
])
def test_catalog_error_patterns_match_the_measured_failures_and_not_ordinary_output(name, line, bad):
    c = connectors.Connector(name, "x", [], "", error_patterns=connectors.CATALOG[name].error_patterns)
    assert bool(c.errors(line)) is bad, (name, line)


def test_init_without_connectors_writes_what_070_wrote(colony):
    """Phase 9's runs must not be disturbed: no new files, and the one file Phase 10 touches is unchanged."""
    import hashlib
    expected = (DATA / "init-0.7.0-files.txt").read_text(encoding="utf-8").splitlines()
    expected.append(".claude/skills/colony-board/SKILL.md")      # Phase 13 (Forge decree 003): the board skill
    made = sorted(p.relative_to(colony).as_posix() for p in colony.rglob("*") if p.is_file()
                  and p.name not in (".mcp.json", "settings.json") and ".git" not in p.relative_to(colony).parts)
    assert made == sorted(expected)
    skill = (colony / connect.SKILL_PATH).read_bytes()
    assert hashlib.sha256(skill).hexdigest() == "db93832f2310e5c15d3fa799990a0a11c3947aeb4609799622bfee3845d9db3b"


@pytest.mark.parametrize("skill", ALL_SKILLS)
def test_the_guard_protects_the_game_skills(colony, skill):
    rel = f".claude/skills/{skill}/SKILL.md"
    ev = {"tool_name": "Write", "cwd": str(colony), "tool_input": {"file_path": str(colony / rel)}}
    assert not decide(ev, colony)[0], rel
    ev = {"tool_name": "Bash", "cwd": str(colony), "tool_input": {"command": f"echo x >> {rel}"}}
    assert not decide(ev, colony)[0], rel


def test_a_persons_own_skill_stays_editable(colony):
    ev = {"tool_name": "Write", "cwd": str(colony),
          "tool_input": {"file_path": str(colony / ".claude/skills/my-godot-notes/SKILL.md")}}
    assert decide(ev, colony)[0]


def test_update_protocols_refreshes_game_skills_only_for_connected_programs(colony, tmp_path, monkeypatch):
    fake_program(tmp_path, monkeypatch, "aseprite")
    main(["--root", str(colony), "connect", "add", "aseprite"])
    path = colony / ".claude/skills/sprite-pipeline/SKILL.md"
    path.write_text("stale\n", encoding="utf-8")
    code, report = update_protocols(colony)
    assert code == 0 and any("sprite-pipeline" in r for r in report), report
    assert path.read_text(encoding="utf-8").startswith("---\nname: sprite-pipeline\n")
    assert not (colony / ".claude/skills/godot-project").exists()


def test_every_gate_command_in_the_skills_is_valid(tmp_path):
    """The skills teach agents gate commands; each must parse (exit 2 would mean the skill is wrong)."""
    found = 0
    for md in (Path(connect.SKILL_TEMPLATES)).glob("*.md"):
        for line in md.read_text(encoding="utf-8").splitlines():
            m = re.search(r"python -m apiary\.gates\.assets ([^`]+)", line)
            if not m:
                continue
            found += 1
            argv = shlex.split(m.group(1))
            try:
                assets.main(argv)
            except SystemExit as e:
                pytest.fail(f"{md.name}: `{line.strip()}` is not a valid gate command (exit {e.code})")
    assert found >= 8


def test_the_skill_templates_ship_in_the_package():
    import tomllib
    data = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    globs = data["tool"]["setuptools"]["package-data"]["apiary"]
    assert "templates/skills/*.md" in globs and "templates/godot/*.gd" in globs


# --- the GDScript test runner (gate c) ---------------------------------------------

def test_godot_tests_writes_the_runner_into_a_project(tmp_path, capsys):
    game = tmp_path / "game"
    game.mkdir()
    (game / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    assert main(["gamedev", "godot-tests", str(game)]) == 0, capsys.readouterr().out
    runner = (game / "tests/run_tests.gd").read_text(encoding="utf-8")
    case = (game / "tests/case.gd").read_text(encoding="utf-8")
    assert runner.startswith("#") and "extends SceneTree" in runner and "quit(" in runner and "Logger" in runner
    assert "func check_eq(" in case and "func check_loads(" in case


def test_godot_tests_never_overwrites_a_changed_runner(tmp_path, capsys):
    game = tmp_path / "game"
    (game / "tests").mkdir(parents=True)
    (game / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    (game / "tests/run_tests.gd").write_text("extends SceneTree\n# mine\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["gamedev", "godot-tests", str(game)]) == 1
    assert "run_tests.gd" in capsys.readouterr().out
    assert (game / "tests/run_tests.gd").read_text(encoding="utf-8").endswith("# mine\n")
    assert main(["gamedev", "godot-tests", str(game)]) == 1      # still refuses; never half-written
    assert main(["gamedev", "godot-tests", str(game)]) == 1


def test_godot_tests_is_idempotent_and_refuses_a_non_project(tmp_path, capsys):
    game = tmp_path / "game"
    game.mkdir()
    (game / "project.godot").write_text("config_version=5\n", encoding="utf-8")
    assert main(["gamedev", "godot-tests", str(game)]) == 0
    assert main(["gamedev", "godot-tests", str(game)]) == 0
    capsys.readouterr()
    assert main(["gamedev", "godot-tests", str(tmp_path / "nothing")]) == 1
    assert "project.godot" in capsys.readouterr().out


def test_a_godot_test_gate_fails_on_script_error_through_the_connector(colony, tmp_path, monkeypatch):
    """Spec C-2 and C-6 together: the acceptance line names the godot connector, so its error patterns apply."""
    bindir = tmp_path / "bin2"
    bindir.mkdir()
    script = bindir / "godot_says.py"
    script.write_text("import sys\nprint('4.7.2.stable' if '--version' in sys.argv else "
                      "'SCRIPT ERROR: Invalid call.\\nAPIARY-TESTS: 1 passed, 0 failed')\n", encoding="utf-8")
    (colony / "connectors").mkdir(exist_ok=True)
    c = connectors.Connector("godot", Path(sys.executable).as_posix(), [str(script), "--version"], r"(\d+\.\d+\.\d+)",
                             timeout_s=60, error_patterns=connectors.CATALOG["godot"].error_patterns)
    (colony / "connectors/godot.toml").write_text(connectors.to_toml(c), encoding="utf-8")
    col = Colony(colony)
    created = col.create_task("Queen", "game-tests", "Run the game's tests",
                              f'godot "{Path(script).as_posix()}" --headless', "game/**")
    task = re.search(r"\d{3}-game-tests\.task", created).group(0)
    tok = re.search(r"token=([0-9a-f]{16})", col.claim(task)).group(1)
    r = col.close(task, tok)
    assert r.startswith("REFUSED") and "SCRIPT ERROR" in r, r
