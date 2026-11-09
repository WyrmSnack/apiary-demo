"""The Queen plans and dispatches parallel lanes (Phase 5 gate b).

Kevin, 2026-10-16: "the queen that we are interacting with should plan out the tasking and then assign subagents to
subtasks in parallel, organized into lanes of effort." In Phase 4 the session "did attempt to do it in one go and I
made it use subagents", so the Queen protocol is loaded into every session through CLAUDE.md, not left to a skill
the session might not reach for.
"""
from apiary.cli import main
from apiary.hook import decide
from apiary.init import PROTOCOL_MARK


def test_init_installs_the_queen_protocol_and_loads_it_every_session(tmp_path):
    main(["--root", str(tmp_path), "init"])
    queen = (tmp_path / "castes" / "queen.md").read_text(encoding="utf-8")
    for phrase in ("plan_status", "subagent", "parallel", "lane", "depends_on", "same message", "Show the human",
                   "TRACE", "sequential"):
        assert phrase in queen, phrase
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "@castes/queen.md" in claude and "@castes/forager.md" in claude
    skill = (tmp_path / ".claude/skills/colony-plan/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: colony-plan\ndescription: ") and "plan_status" in skill


def test_a_colony_made_before_phase_5_gains_the_queen_once(tmp_path):
    (tmp_path / "CLAUDE.md").write_text(f"# Mine\n\n{PROTOCOL_MARK}\n## Colony protocol\n\n@castes/forager.md\n",
                                        encoding="utf-8")
    main(["--root", str(tmp_path), "init"])
    main(["--root", str(tmp_path), "init"])
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# Mine") and text.count("@castes/queen.md") == 1 and text.count("@castes/forager.md") == 1


def test_the_guard_protects_the_queen_protocol_and_plan_skill(tmp_path):
    main(["--root", str(tmp_path), "init"])
    for rel in ("castes/queen.md", ".claude/skills/colony-plan/SKILL.md"):
        ev = {"tool_name": "Edit", "cwd": str(tmp_path), "tool_input": {"file_path": str(tmp_path / rel)}}
        assert not decide(ev, tmp_path)[0], rel


def test_cli_plan_and_task_lanes(tmp_path, capsys):
    main(["--root", str(tmp_path), "init"])
    ok = 'python -c "exit(0)"'
    for slug, lane, writes, deps in (("geometry", "geometry", "art/g.py", ""), ("look", "look", "art/l.py", ""),
                                     ("combine", "final", "art/final.png", "1, 2")):
        assert main(["--root", str(tmp_path), "task", "new", slug, "--objective", "x", "--acceptance", ok,
                     "--lane", lane, "--writes", writes, "--depends-on", deps]) == 0
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "plan"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("PLAN ready=2 blocked=1 active=0"), out
    assert "waits for 001, 002" in out


def test_update_protocols_refreshes_only_apiarys_own_files(tmp_path, capsys):
    main(["--root", str(tmp_path), "init"])
    stale = tmp_path / "castes" / "queen.md"
    stale.write_text("# old queen\n", encoding="utf-8")
    (tmp_path / "castes" / "my-own-caste.md").write_text("# mine\n", encoding="utf-8")
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "init", "--update-protocols"]) == 0
    out = capsys.readouterr().out
    assert "updated castes/queen.md" in out and "castes/forager.md" not in out, out
    assert "Nurse" in stale.read_text(encoding="utf-8")
    assert (tmp_path / "castes" / "my-own-caste.md").read_text(encoding="utf-8") == "# mine\n"
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == claude


def test_the_queen_works_solo_by_default_and_plans_in_one_call(tmp_path):
    """Phase 7 (Kevin, 2026-10-16: "plan in one call" and "solo mode"). Measured in Phase 6: every subagent starts
    with about 55k tokens of context and re-reads it on every call; the colony used 7.7 times a plain session's
    tokens, and parallel lanes were not clearly faster than one Forager at a time."""
    main(["--root", str(tmp_path), "init"])
    queen = (tmp_path / "castes" / "queen.md").read_text(encoding="utf-8")
    for phrase in ("create_plan", "Solo", "claim_task", "close_task", "caste: Queen", "Guardian", "different agent",
                   "Dispatch Foragers only when"):
        assert phrase in queen, phrase
    assert "do not take on a multi-part goal yourself" not in queen          # the Phase 5 rule this replaces
    skill = (tmp_path / ".claude/skills/colony-plan/SKILL.md").read_text(encoding="utf-8")
    assert "create_plan" in skill and "solo" in skill.lower()
    assert "`create_task` for every part" not in skill


def test_init_installs_the_colony_board_skill_and_the_queen_shows_the_board(tmp_path):
    """Phase 13 gate d (Forge decree 003): every plan is shown as a board before create_plan."""
    main(["--root", str(tmp_path), "init"])
    skill = (tmp_path / ".claude/skills/colony-board/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: colony-board\ndescription: ")
    for phrase in ("plan_board", "RUN", "NO-HUMAN", "VERIFY-BY", "by: Human", "approve <id>", "boards/",
                   "apiary board --live", "create_plan"):
        assert phrase in skill, phrase
    queen = (tmp_path / "castes" / "queen.md").read_text(encoding="utf-8")
    section3 = queen.split("## 3.", 1)[1].split("## 4.", 1)[0]
    assert "show the board (`plan_board`) with the table" in section3.lower(), section3


def test_update_protocols_adds_the_board_skill_to_an_older_colony(tmp_path, capsys):
    main(["--root", str(tmp_path), "init"])
    (tmp_path / ".claude/skills/colony-board/SKILL.md").unlink()
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "init", "--update-protocols"]) == 0
    assert ".claude/skills/colony-board/SKILL.md" in capsys.readouterr().out          # created by init itself
    assert (tmp_path / ".claude/skills/colony-board/SKILL.md").is_file()


def test_the_guard_protects_the_board_skill(tmp_path):
    main(["--root", str(tmp_path), "init"])
    rel = ".claude/skills/colony-board/SKILL.md"
    for ev in ({"tool_name": "Edit", "cwd": str(tmp_path), "tool_input": {"file_path": str(tmp_path / rel)}},
               {"tool_name": "Bash", "cwd": str(tmp_path), "tool_input": {"command": f"echo x >> {rel}"}}):
        assert not decide(ev, tmp_path)[0], ev
