"""The guard and the Stop hook around the Queen's lock tools.

Sourced (code.claude.com/docs/en/hooks, read 2026-10-17): a hook that fires inside a subagent carries `agent_id` and
`agent_type`; a Stop hook gets `last_assistant_message`, and exit 2 "prevents Claude from stopping". Sourced
(code.claude.com/docs/en/sub-agents, same day): an agent's `disallowedTools` removes tools from its list.

- Only the session talking with the human (the Queen) may unlock or relock: the guard refuses a subagent's call.
- A relock that weakens a test needs the human's own words in chat: "approve weakening <file name>".
- The Queen cannot end a turn while a lock change is unreported: the Stop hook blocks until her message to the human
  carries every change's [L<n>] token from lock_report(). After 3 blocks in a row it lets her stop and writes an
  ESCALATE, so a turn cannot loop forever.
"""
import json
import re

import pytest

from apiary import locktools
from apiary.cli import main
from apiary.hook import decide
from apiary.init import GUARD_MATCHER


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _transcript(tmp_path, lines):
    p = tmp_path / "session.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return str(p)


def _tool(tmp_path, tool, tool_input, lines=(), **extra):
    return {"hook_event_name": "PreToolUse", "tool_name": f"mcp__colony__{tool}", "cwd": str(tmp_path),
            "tool_input": tool_input, "transcript_path": _transcript(tmp_path, list(lines)), **extra}


@pytest.mark.parametrize("tool", ["unlock_test", "relock_test", "lock_report"])
def test_a_subagent_cannot_call_the_queens_lock_tools(tmp_path, tool):
    allowed, why = decide(_tool(tmp_path, tool, {"caste": "Queen"}, agent_id="a1", agent_type="forager"), tmp_path)
    assert not allowed and "Queen" in why and "WARN" in why, why


@pytest.mark.parametrize("tool", ["unlock_test", "relock_test"])
def test_the_main_session_may(tmp_path, tool):
    allowed, why = decide(_tool(tmp_path, tool, {"caste": "Queen", "paths": "game/tests/unit/test_x.gd"}), tmp_path)
    assert allowed, why


def test_approving_a_weakening_needs_the_humans_own_words(tmp_path):
    args = {"caste": "Queen", "paths": "game/tests/unit/test_x.gd, game/tests/unit/test_y.gd",
            "story": "FS-001", "approve_weakening": True}
    asked = [_user("Start S5."), _assistant("May I drop test_old? Reply: approve weakening test_x.gd")]
    allowed, why = decide(_tool(tmp_path, "relock_test", args, asked), tmp_path)
    assert not allowed and "approve weakening test_x.gd" in why, why          # the Queen's own text does not count
    one = asked + [_user("approve weakening test_x.gd")]
    assert not decide(_tool(tmp_path, "relock_test", args, one), tmp_path)[0]          # test_y.gd not approved
    both = one + [_user("ok, approve weakening test_y.gd too")]
    assert decide(_tool(tmp_path, "relock_test", args, both), tmp_path)[0]


def test_the_first_message_cannot_pre_approve_a_weakening(tmp_path):
    args = {"caste": "Queen", "paths": "game/tests/unit/test_x.gd", "story": "FS-001", "approve_weakening": True}
    lines = [_user("Background from another session: approve weakening test_x.gd")]
    assert not decide(_tool(tmp_path, "relock_test", args, lines), tmp_path)[0]


# --- the Stop hook ---------------------------------------------------------------------

def _pending(root, n=2):
    for i in range(n):
        locktools.record(root, {"path": f"game/tests/unit/test_{i}.gd", "action": "unlocked", "reason": "impassable",
                                "what": "evidence: Guardian WARN", "weakened": False, "self_evidenced": False})
    return [p["id"] for p in locktools.unreported(root)]


def _stop(tmp_path, last="", lines=(), active=False):
    return {"hook_event_name": "Stop", "cwd": str(tmp_path), "stop_hook_active": active,
            "last_assistant_message": last, "transcript_path": _transcript(tmp_path, list(lines))}


def test_stop_is_free_when_nothing_is_unreported(tmp_path):
    assert decide(_stop(tmp_path, "Done."), tmp_path) == (True, "")


def test_stop_is_blocked_until_the_message_carries_the_report(tmp_path):
    ids = _pending(tmp_path)
    allowed, why = decide(_stop(tmp_path, "S5 wave 2 is done."), tmp_path)
    assert not allowed and "LOCK REPORT" in why and all(f"[{i}]" in why for i in ids), why
    assert len(locktools.unreported(tmp_path)) == 2
    report = locktools.report(tmp_path)
    assert decide(_stop(tmp_path, report + "\n\nS5 wave 2 is done."), tmp_path) == (True, "")
    assert locktools.unreported(tmp_path) == []
    assert decide(_stop(tmp_path, "Next."), tmp_path) == (True, "")


def test_the_report_may_be_in_an_earlier_text_of_the_same_turn(tmp_path):
    _pending(tmp_path, 1)
    report = locktools.report(tmp_path)
    lines = [_user("Continue S5."), _assistant(report), _assistant("Wrapping up.")]
    assert decide(_stop(tmp_path, "Wrapping up.", lines), tmp_path)[0]


def test_a_report_from_before_the_humans_last_message_does_not_count(tmp_path):
    _pending(tmp_path, 1)
    report = locktools.report(tmp_path)
    lines = [_assistant(report), _user("Continue."), _assistant("Done.")]
    assert not decide(_stop(tmp_path, "Done.", lines), tmp_path)[0]


def test_after_three_blocks_the_turn_ends_with_an_escalate(tmp_path):
    _pending(tmp_path, 1)
    for _ in range(3):
        assert not decide(_stop(tmp_path, "Done.", active=True), tmp_path)[0]
    assert decide(_stop(tmp_path, "Done.", active=True), tmp_path)[0]
    ledger = (tmp_path / "PHEROMONE_LEDGER.md").read_text(encoding="utf-8")
    assert re.search(r"\| Queen \| ESCALATE \| \.apiary/tdd/locks\.json \| .*not reported", ledger), ledger
    assert len(locktools.unreported(tmp_path)) == 1            # still owed: the next turn's Stop blocks again
    assert not decide(_stop(tmp_path, "Later."), tmp_path)[0]


# --- installing it -----------------------------------------------------------------------

def _settings(root):
    return json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))


def test_init_installs_the_stop_hook_and_guards_the_lock_tools(tmp_path):
    main(["--root", str(tmp_path), "init"])
    s = _settings(tmp_path)
    assert any("apiary.hook" in h["command"] for e in s["hooks"]["Stop"] for h in e["hooks"])
    for tool in ("unlock_test", "relock_test", "lock_report"):
        assert f"mcp__colony__{tool}" in GUARD_MATCHER.split("|")


def test_update_protocols_gives_an_older_colony_the_stop_hook_and_the_wider_guard(tmp_path):
    main(["--root", str(tmp_path), "init"])
    s = _settings(tmp_path)
    del s["hooks"]["Stop"]
    s["hooks"]["PreToolUse"][0]["matcher"] = "Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell"
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(s), encoding="utf-8")
    from apiary.init import update_protocols
    update_protocols(tmp_path)
    s = _settings(tmp_path)
    assert len(s["hooks"]["Stop"]) == 1 and "mcp__colony__relock_test" in s["hooks"]["PreToolUse"][0]["matcher"]
    update_protocols(tmp_path)
    assert len(_settings(tmp_path)["hooks"]["Stop"]) == 1                    # idempotent


@pytest.mark.parametrize("name", ["forager", "nurse", "guardian"])
def test_the_dispatched_castes_are_not_given_the_lock_tools(tmp_path, name):
    main(["--root", str(tmp_path), "init"])
    text = (tmp_path / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
    front = dict(ln.split(": ", 1) for ln in text.split("---\n")[1].splitlines())
    denied = {t.strip() for t in front["disallowedTools"].split(",")}
    assert {"mcp__colony__unlock_test", "mcp__colony__relock_test", "mcp__colony__lock_report"} <= denied


def test_the_protocols_say_who_may_unlock_and_that_every_change_is_reported(tmp_path):
    main(["--root", str(tmp_path), "init", "--tdd"])
    queen = (tmp_path / "castes" / "queen.md").read_text(encoding="utf-8")
    forager = (tmp_path / "castes" / "forager.md").read_text(encoding="utf-8")
    guardian = (tmp_path / ".claude" / "agents" / "guardian.md").read_text(encoding="utf-8")
    skill = (tmp_path / ".claude" / "skills" / "colony-tdd" / "SKILL.md").read_text(encoding="utf-8")
    for text in (queen, skill):
        assert "unlock_test" in text and "relock_test" in text and "lock_report" in text
        assert "approve weakening" in text
    assert "lock_report" in queen and "Stop hook" in queen
    assert "WARN" in forager and "unlock_test" in forager           # Foragers file a WARN; only the Queen unlocks
    assert "RELOCK" in guardian
