"""The human approves before the Queen creates work (Phase 7 follow-up).

Measured in Phase 7: in 2 of 3 solo runs the Queen made one task and started without showing it to the human, which
/colony-task forbids. Kevin, 2026-10-16: "Enforce it with the guard". The guard refuses create_task and create_plan
until the session's transcript holds a human reply after the first message (typed, or an answer in the question
dialog). It checks that the human replied, not what they said.
"""
import json

import pytest

from apiary.cli import main
from apiary.hook import decide
from apiary.init import GUARD_MATCHER


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


ASK = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "q1", "name": "AskUserQuestion",
                                                      "input": {}}]}}
ANSWER = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "q1", "content": "Yes"}]}}
TOOL_RESULT = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "b1", "content": "ok"}]}}
REMINDER = _user("<system-reminder>the date changed</system-reminder>")


def _event(tmp_path, tool, lines):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(tmp_path),
            "transcript_path": str(transcript), "tool_input": {}}


@pytest.mark.parametrize("tool", ["mcp__colony__create_task", "mcp__colony__create_plan"])
def test_creating_work_before_the_human_replies_is_refused(tmp_path, tool):
    allowed, why = decide(_event(tmp_path, tool, [_user("Build the project described in SPEC.md."), TOOL_RESULT,
                                                  REMINDER]), tmp_path)
    assert not allowed and "Show the human" in why, why


@pytest.mark.parametrize("reply", [[ASK, ANSWER], [_user("yes, go ahead")]])
@pytest.mark.parametrize("tool", ["mcp__colony__create_task", "mcp__colony__create_plan"])
def test_a_reply_after_the_first_message_allows_it(tmp_path, tool, reply):
    allowed, why = decide(_event(tmp_path, tool, [_user("Build the project described in SPEC.md."), *reply]), tmp_path)
    assert allowed, why


def test_without_a_readable_transcript_the_guard_fails_closed(tmp_path):
    event = {"hook_event_name": "PreToolUse", "tool_name": "mcp__colony__create_plan", "cwd": str(tmp_path),
             "tool_input": {}}
    assert not decide(event, tmp_path)[0]
    assert not decide({**event, "transcript_path": str(tmp_path / "missing.jsonl")}, tmp_path)[0]


def test_other_colony_tools_need_no_approval(tmp_path):
    event = _event(tmp_path, "mcp__colony__claim_task", [_user("Build it.")])
    assert decide(event, tmp_path)[0]


def test_init_guards_task_creation_and_older_colonies_gain_it(tmp_path):
    assert {"mcp__colony__create_task", "mcp__colony__create_plan"} <= set(GUARD_MATCHER.split("|"))
    old = tmp_path / "old"
    (old / ".claude").mkdir(parents=True)
    hook = {"type": "command", "command": '"python" -m apiary.hook --root "x"'}
    mine = {"type": "command", "command": "echo mine"}
    (old / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell", "hooks": [hook]},
        {"matcher": "Bash", "hooks": [mine]}]}}), encoding="utf-8")
    main(["--root", str(old), "init", "--update-protocols"])
    entries = json.loads((old / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    assert entries[0]["matcher"] == GUARD_MATCHER and entries[0]["hooks"] == [hook]
    assert entries[1] == {"matcher": "Bash", "hooks": [mine]}            # the human's own hooks are left alone
