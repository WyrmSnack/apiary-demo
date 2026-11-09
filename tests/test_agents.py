"""Dedicated agents for the castes the Queen dispatches (Phase 9 gate b).

Measured in Phase 8: a Forager started as Claude Code's general-purpose agent held 55k to 60k tokens of context on its
first call, and about a quarter of its calls did only colony bookkeeping. Sourced (code.claude.com/docs/en/sub-agents, read
2026-10-17): a defined agent's body "is the subagent's system prompt", `tools` is an allowlist that may name
`mcp__colony__*`, and `omitClaudeMd: true` skips CLAUDE.md.
"""
import re

import pytest

from apiary.cli import main
from apiary.hook import decide


def _front(text: str) -> dict:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, text[:80]
    return dict(line.split(": ", 1) for line in m.group(1).splitlines())


@pytest.mark.parametrize("name,needs", [("forager", {"Read", "Write", "Edit", "Bash", "mcp__colony__*"}),
                                        ("nurse", {"WebSearch", "WebFetch", "Write", "mcp__colony__*"}),
                                        ("guardian", {"WebFetch", "Read", "Edit", "mcp__colony__*"})])
def test_init_installs_lean_agents(tmp_path, name, needs):
    main(["--root", str(tmp_path), "init"])
    text = (tmp_path / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
    front = _front(text)
    assert front["name"] == name and front["description"]
    tools = {t.strip() for t in front["tools"].split(",")}
    assert needs <= tools and "Agent" not in tools          # an agent the Queen starts does not start others
    assert front["omitClaudeMd"] == "true"                  # the Queen's protocol is not loaded into every agent
    assert "claim_task" in text and "close_task" in text


def test_the_forager_skips_bookkeeping_it_does_not_need(tmp_path):
    # Kevin, 2026-10-17, after the Phase 9 probe: "Give the foragers toolsearch and resume calls, actually."
    main(["--root", str(tmp_path), "init"])
    text = (tmp_path / ".claude" / "agents" / "forager.md").read_text(encoding="utf-8")
    tools = {t.strip() for t in _front(text)["tools"].split(",")}
    assert "ToolSearch" in tools
    assert "Start with `resume`" in text and "Do not call `resume`" not in text
    assert "the rest of the claim result is the task" in text
    assert "one message" in text and "never the check" in text and "ESCALATE" in text
    body = text.split("\n---\n", 1)[1]
    assert len(body.split()) < 450                         # a short system prompt is the point


def test_the_guard_protects_the_agent_definitions(tmp_path):
    root = tmp_path.resolve()
    event = {"tool_name": "Edit", "cwd": str(root), "tool_input": {"file_path": str(root / ".claude/agents/forager.md")}}
    assert not decide(event, root)[0]
    shell = {"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": "echo x > .claude/agents/forager.md"}}
    assert not decide(shell, root)[0]


def test_older_colonies_gain_the_agents(tmp_path):
    main(["--root", str(tmp_path), "init"])
    for name in ("forager", "nurse", "guardian"):
        (tmp_path / ".claude" / "agents" / f"{name}.md").unlink()
    main(["--root", str(tmp_path), "init", "--update-protocols"])
    assert (tmp_path / ".claude" / "agents" / "forager.md").is_file()


def test_the_queen_dispatches_the_agents_and_keeps_solo_plans_small(tmp_path):
    main(["--root", str(tmp_path), "init"])
    queen = (tmp_path / "castes" / "queen.md").read_text(encoding="utf-8")
    assert "subagent_type: forager" in queen and "subagent_type: guardian" in queen
    assert "fewer, larger tasks" in queen and "one message" in queen
    skill = (tmp_path / ".claude/skills/colony-plan/SKILL.md").read_text(encoding="utf-8")
    assert "subagent_type: forager" in skill and "subagent_type: nurse" in skill


def test_dispatch_names_the_task_file_without_its_folder(tmp_path):
    # Phase 9 probe: every Forager first claimed "tasks/pending/001-foundation.task", was refused (T-1), and retried.
    main(["--root", str(tmp_path), "init"])
    queen = (tmp_path / "castes" / "queen.md").read_text(encoding="utf-8")
    forager = (tmp_path / ".claude" / "agents" / "forager.md").read_text(encoding="utf-8")
    skill = (tmp_path / ".claude/skills/colony-plan/SKILL.md").read_text(encoding="utf-8")
    for text in (queen, forager, skill):
        assert "001-core.task" in text and "no folder" in text
