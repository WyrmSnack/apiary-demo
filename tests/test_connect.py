"""`apiary connect add` and the connectors skill (Phase 4 gate b), plus guarding and history for runs (C-4)."""
import json
import os
import re
import subprocess
import sys

import pytest

from apiary import connectors
from apiary.cli import main
from apiary.colony import Colony
from apiary.hook import decide
from apiary.validate import history, validate


@pytest.fixture
def fake_blender(tmp_path, monkeypatch):
    """A program named blender on PATH that reports a Blender version, like the real one."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "fake_blender.py"
    script.write_text("import sys\nif '--version' in sys.argv: print('Blender 4.4.3')\n"
                      "else:\n    import pathlib; o = pathlib.Path(sys.argv[-1])\n"
                      "    o.parent.mkdir(parents=True, exist_ok=True); o.write_text('mesh')\n", encoding="utf-8")
    if os.name == "nt":
        launcher = bindir / "blender.bat"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="ascii")
    else:
        launcher = bindir / "blender"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="ascii")
        launcher.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setitem(connectors.CATALOG["blender"].__dict__, "places", [])   # only PATH, not this machine's install
    return launcher


@pytest.fixture
def colony(tmp_path):
    root = tmp_path / "colony"
    root.mkdir()
    main(["--root", str(root), "init"])
    return root


def test_connect_add_finds_a_known_program_and_records_its_version(colony, fake_blender, capsys):
    capsys.readouterr()
    assert main(["--root", str(colony), "connect", "add", "blender"]) == 0
    out = capsys.readouterr().out
    assert "blender" in out and "4.4.3" in out, out
    c = connectors.load(colony, "blender")
    assert c.version == "4.4.3" and c.probe() == "4.4.3"
    skill = (colony / ".claude/skills/colony-connectors/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: colony-connectors\n") and "run_connector" in skill and "blender" in skill
    assert "--background" in skill                         # the catalog's how-to for Blender
    # Measured with Blender 4.4.3: a crashing --python script still exits 0 unless --python-exit-code is set.
    assert "--python-exit-code 1" in skill
    assert validate(colony) == []


def test_connect_add_never_overwrites(colony, fake_blender, capsys):
    main(["--root", str(colony), "connect", "add", "blender"])
    before = (colony / "connectors/blender.toml").read_bytes()
    capsys.readouterr()
    assert main(["--root", str(colony), "connect", "add", "blender"]) == 1
    assert "already" in capsys.readouterr().out
    assert (colony / "connectors/blender.toml").read_bytes() == before


def test_connect_add_says_plainly_when_a_program_is_missing(colony, monkeypatch, capsys):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setitem(connectors.CATALOG["blender"].__dict__, "places", [])
    capsys.readouterr()
    assert main(["--root", str(colony), "connect", "add", "blender"]) == 1
    out = capsys.readouterr().out
    assert "not found" in out and "--program" in out, out
    assert not (colony / "connectors").exists()


def test_connect_add_any_program_with_explicit_details(colony, capsys):
    code = main(["--root", str(colony), "connect", "add", "py-tool", "--program", sys.executable,
                 "--version-arg=-c", "--version-arg=print('Tool 9.1')", "--version-pattern", r"Tool (\S+)"])
    assert code == 0, capsys.readouterr().out
    assert connectors.load(colony, "py-tool").version == "9.1"


def test_a_real_run_through_the_connector(colony, fake_blender):
    main(["--root", str(colony), "connect", "add", "blender"])
    r = Colony(colony).run_connector("Forager", "blender", "--background out/model.blend", "out/model.blend")
    path = re.match(r"RAN (\S+) exit=0", r).group(1)
    rec = json.loads((colony / path).read_text(encoding="utf-8"))
    assert rec["version"] == "4.4.3" and rec["outputs"][0]["sha256"]


def test_connectors_and_runs_are_guarded(colony):
    for rel in ("connectors/blender.toml", "runs/20261015T2300Z-blender-ab12.json",
                ".claude/skills/colony-connectors/SKILL.md"):
        ev = {"tool_name": "Write", "cwd": str(colony), "tool_input": {"file_path": str(colony / rel)}}
        assert not decide(ev, colony)[0], rel


def test_a_changed_run_record_is_caught_by_the_history_check(colony, fake_blender):
    subprocess.run(["git", "-C", str(colony), "init", "-q"], check=True)
    main(["--root", str(colony), "init"])
    main(["--root", str(colony), "connect", "add", "blender"])
    r = Colony(colony).run_connector("Forager", "blender", "out/m.blend", "out/m.blend")
    path = colony / re.match(r"RAN (\S+)", r).group(1)
    for args in (("add", "-A"), ("-c", "user.name=t", "-c", "user.email=t@e", "commit", "-q", "--no-verify", "-m", "run")):
        subprocess.run(["git", "-C", str(colony), *args], check=True, capture_output=True)
    assert history(colony, "HEAD") == []
    path.write_text(path.read_text(encoding="utf-8").replace('"exit_code": 0', '"exit_code": 1'), encoding="utf-8")
    assert [f.rule for f in history(colony, "HEAD")] == ["C-4"]


def test_validate_reports_a_broken_connector(colony):
    (colony / "connectors").mkdir()
    (colony / "connectors" / "bad.toml").write_text("program = \n", encoding="utf-8")
    assert [f.rule for f in validate(colony)] == ["C-1"]


def test_init_installs_the_connectors_skill_before_any_connector(colony):
    skill = (colony / ".claude/skills/colony-connectors/SKILL.md").read_text(encoding="utf-8")
    assert "no connectors yet" in skill and "escalate" in skill
    attrs = (colony / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "runs/** text eol=lf" in attrs and "connectors/** text eol=lf" in attrs


@pytest.mark.parametrize("command", [
    "blender --background --python scripts/x.py",
    '"C:/Program Files/Blender Foundation/Blender 4.4/blender.exe" --background',
    "echo go && blender -b scene.blend",
])
def test_the_guard_sends_connector_programs_through_run_connector(colony, fake_blender, command):
    main(["--root", str(colony), "connect", "add", "blender"])
    ev = {"tool_name": "Bash", "cwd": str(colony), "tool_input": {"command": command}}
    allowed, why = decide(ev, colony)
    assert not allowed and "run_connector" in why, (command, why)


def test_programs_without_a_connector_are_not_blocked(colony):
    ev = {"tool_name": "Bash", "cwd": str(colony), "tool_input": {"command": "blender --version"}}
    assert decide(ev, colony)[0]
