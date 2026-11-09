"""Creating tasks properly (spec O-3): the CLI for humans and the skill `apiary init` installs for Claude Code.

Kevin, 2026-10-15: "Took less than 15 minutes until I failed to create my own task. There should be a
skill/tool that claude code can use to create .task files properly."
"""
import re

from apiary.cli import main
from apiary.colony import Colony
from apiary.hook import decide
from apiary.validate import validate


def test_cli_task_new_writes_a_task_that_validates_and_closes(tmp_path, capsys):
    main(["--root", str(tmp_path), "init"])
    capsys.readouterr()
    code = main(["--root", str(tmp_path), "task", "new", "save-slots", "--objective", "Player can save.",
                 "--acceptance", 'python -c "exit(0)"', "--writes", "engine/save.py"])
    out = capsys.readouterr().out
    assert code == 0 and out.startswith("CREATED 001-save-slots.task"), out
    assert validate(tmp_path) == []
    col = Colony(tmp_path)
    tok = re.search(r"token=(\w+)", col.claim("001-save-slots.task")).group(1)
    assert col.close("001-save-slots.task", tok).startswith("DONE")


def test_cli_task_new_explains_a_prose_acceptance(tmp_path, capsys):
    main(["--root", str(tmp_path), "init"])
    capsys.readouterr()
    code = main(["--root", str(tmp_path), "task", "new", "guide", "--objective", "Write a guide.",
                 "--acceptance", "A fully sourced, actionable textbook"])
    out = capsys.readouterr().out
    assert code == 1 and "REFUSED" in out and "not a program" in out, out


def test_cli_task_new_reads_a_gate_from_a_file(tmp_path, capsys):
    main(["--root", str(tmp_path), "init"])
    gate = tmp_path / "draft_gate.py"
    gate.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    capsys.readouterr()
    code = main(["--root", str(tmp_path), "task", "new", "guide", "--objective", "Write a guide.",
                 "--gate", str(gate), "--gate-args", "docs/guide"])
    out = capsys.readouterr().out
    assert code == 0 and "gate=gates/check_001.py" in out, out
    assert (tmp_path / "gates" / "check_001.py").read_text(encoding="utf-8") == "import sys\nsys.exit(0)\n"


def test_init_installs_the_task_skill_and_guards_it(tmp_path):
    main(["--root", str(tmp_path), "init"])
    skill = tmp_path / ".claude" / "skills" / "colony-task" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\nname: colony-task\ndescription: ")
    for word in ("create_task", "acceptance", "gate_code", "Show the human", "writes"):
        assert word in text, word
    # Phase 4 gate (d): a session split task 004 into 005 and 006 after creating it, so 004 could not depend on them.
    assert "Create the parts first" in text and "depends_on" in text
    ev = {"tool_name": "Edit", "cwd": str(tmp_path), "tool_input": {"file_path": str(skill)}}
    assert not decide(ev, tmp_path)[0]
