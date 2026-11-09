"""The guard for Obsidian MCP tools (Phase 13 gate c, Forge decree 003, TRACEs obsidian-guard and obsidian-write-scope).

Found by reading apiary/hook.py (Forge, 2026-10-19): the guard's matcher named only file, shell and two colony tools,
and decide() allowed any tool it did not know, so an Obsidian MCP server rooted at a colony could rewrite the ledger.
Now every mcp__obsidian__* tool that is not on a read-only list counts as a write and fails closed: its path
arguments are resolved against the vault root (the guard's --root) and must name an unguarded file inside a folder
the human listed in .apiary/mcp-guard.json. Tool and argument names are the ones the Forge's Nurse found in the
servers' source (research/obsidian-mcp/ in the Forge: mcp-obsidian, obsidian-mcp-server, MCPVault, obsidian-mcp,
Local REST API).
"""
import json
import os

import pytest

from apiary.cli import main
from apiary.hook import decide
from apiary.init import GUARD_MATCHER


@pytest.fixture
def vault(tmp_path):
    return tmp_path.resolve()


def obs(vault, tool, /, **tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": f"mcp__obsidian__{tool}", "cwd": str(vault),
            "tool_input": tool_input}


def scope(vault, **cfg):
    (vault / ".apiary").mkdir(exist_ok=True)
    (vault / ".apiary" / "mcp-guard.json").write_text(json.dumps(cfg), encoding="utf-8")


INBOX = "realm/obsidian-inbox"


def test_the_bypass_an_obsidian_write_to_the_ledger_is_refused(vault):
    """Reproduces the bypass: on 0.8.0 decide() allowed this call."""
    allowed, why = decide(obs(vault, "obsidian_put_content", filepath="PHEROMONE_LEDGER.md", content="forged"), vault)
    assert not allowed and why


@pytest.mark.parametrize("tool,args", [
    ("obsidian_get_file_contents", {"filepath": "PHEROMONE_LEDGER.md"}),
    ("obsidian_batch_get_file_contents", {"filepaths": ["TRACES.md"]}),
    ("obsidian_list_files_in_vault", {}),
    ("obsidian_list_files_in_dir", {"dirpath": "tasks"}),
    ("obsidian_simple_search", {"query": "ledger"}),
    ("obsidian_get_note", {"target": {"type": "path", "path": "CLAUDE.md"}}),
    ("obsidian_search_notes", {"query": "x"}),
    ("read_note", {"path": "__workspace/plan.md"}),
    ("search_notes", {"query": "x"}),
    ("obsidian_read_note", {"vault": "forge", "path": "TRACES.md"}),
    ("vault_read", {"path": "TRACES.md"}),
])
def test_reads_are_allowed_anywhere_in_the_vault(vault, tool, args):
    assert decide(obs(vault, tool, **args), vault) == (True, "")


@pytest.mark.parametrize("tool,args", [
    ("obsidian_append_content", {"filepath": "notes/idea.md", "content": "x"}),
    ("write_note", {"path": "notes/idea.md", "content": "x"}),
    ("obsidian_create_note", {"vault": "forge", "path": "notes/idea.md"}),
    ("vault_write", {"path": "notes/idea.md"}),
])
def test_without_a_write_scope_every_write_is_refused(vault, tool, args):
    allowed, why = decide(obs(vault, tool, **args), vault)
    assert not allowed and "mcp-guard.json" in why, why


@pytest.mark.parametrize("rel", [f"{INBOX}/a.md", f"{INBOX}/boards/plan.md", f"{INBOX}\\boards\\plan.md"])
def test_writes_inside_a_listed_folder_are_allowed(vault, rel):
    scope(vault, write_folders=[INBOX])
    assert decide(obs(vault, "obsidian_put_content", filepath=rel, content="x"), vault) == (True, "")
    assert decide(obs(vault, "write_note", path=str(vault / rel.replace("\\", "/"))), vault) == (True, "")


@pytest.mark.parametrize("rel", ["realm/obsidian-inboxer/a.md", "realm/a.md", "__workspace/plan.md", "Home.md",
                                 f"{INBOX}/../../TRACES.md", f"{INBOX}/../proposals/x.md", "../outside.md",
                                 "/etc/passwd", "C:/Windows/x.md"])
def test_writes_outside_the_listed_folders_or_the_vault_are_refused(vault, rel):
    scope(vault, write_folders=[INBOX])
    allowed, why = decide(obs(vault, "obsidian_put_content", filepath=rel, content="x"), vault)
    assert not allowed and why, rel


@pytest.mark.parametrize("rel", ["PHEROMONE_LEDGER.md", "TRACES.md", "tasks/pending/009-x.task", "gates/check_1.py",
                                 "castes/queen.md", "CLAUDE.md", ".mcp.json", ".apiary/mcp-guard.json",
                                 ".claude/settings.json", "pheromone_ledger.md" if os.name == "nt" else "TRACES.md"])
def test_guarded_files_stay_guarded_even_when_the_whole_vault_is_listed(vault, rel):
    scope(vault, write_folders=["."])
    assert not decide(obs(vault, "obsidian_put_content", filepath=rel, content="x"), vault)[0], rel
    assert decide(obs(vault, "obsidian_put_content", filepath="notes/idea.md", content="x"), vault)[0]


def test_an_unknown_tool_counts_as_a_write(vault):
    scope(vault, write_folders=[INBOX])
    assert not decide(obs(vault, "frobnicate", filepath="TRACES.md"), vault)[0]
    assert decide(obs(vault, "frobnicate", filepath=f"{INBOX}/a.md"), vault)[0]


@pytest.mark.parametrize("tool,args", [
    ("obsidian_execute_command", {"commandId": "editor:delete-paragraph"}),
    ("obsidian_patch_note", {"target": {"type": "active"}, "content": "x"}),
    ("obsidian_append_to_note", {"target": {"type": "periodic", "period": "daily"}, "content": "x"}),
    ("obsidian_rename_tag", {"oldTag": "a", "newTag": "b"}),
    ("obsidian_put_content", {"filepath": ""}),
    ("obsidian_put_content", {"filepath": 7}),
])
def test_a_write_with_no_path_the_guard_can_check_is_refused(vault, tool, args):
    scope(vault, write_folders=["."])
    allowed, why = decide(obs(vault, tool, **args), vault)
    assert not allowed and why, (tool, args)


def test_every_path_argument_is_checked(vault):
    scope(vault, write_folders=[INBOX])
    move = lambda src, dst: decide(obs(vault, "obsidian_move_note", vault="f", source=src, destination=dst), vault)[0]
    assert move(f"{INBOX}/a.md", f"{INBOX}/b.md")
    assert not move(f"{INBOX}/a.md", "TRACES.md")
    assert not move("PHEROMONE_LEDGER.md", f"{INBOX}/ledger.md")
    assert not decide(obs(vault, "move_note", oldPath=f"{INBOX}/a.md", newPath="castes/queen.md"), vault)[0]
    assert not decide(obs(vault, "obsidian_delete_file", filepath="tasks", confirm=True), vault)[0]
    assert not decide(obs(vault, "obsidian_delete_note", vault="f", path=f"{INBOX}/a.md",
                          confirm_path="TRACES.md"), vault)[0]


def test_a_path_object_target_is_checked(vault):
    scope(vault, write_folders=[INBOX])
    ok = {"type": "path", "path": f"{INBOX}/a.md"}
    assert decide(obs(vault, "obsidian_write_note", target=ok, content="x"), vault)[0]
    assert not decide(obs(vault, "obsidian_write_note", target={"type": "path", "path": "CLAUDE.md"}), vault)[0]


def test_the_human_can_name_more_path_arguments_and_read_tools(vault):
    scope(vault, write_folders=[INBOX], path_args=["note_path"], read_tools=["peek"])
    assert decide(obs(vault, "custom_write", note_path=f"{INBOX}/a.md"), vault)[0]
    assert not decide(obs(vault, "custom_write", note_path="TRACES.md"), vault)[0]
    assert not decide(obs(vault, "custom_write", filepath="TRACES.md"), vault)[0]      # the defaults still count
    assert decide(obs(vault, "peek", note_path="TRACES.md"), vault)[0]


@pytest.mark.parametrize("text", ["{not json", "[]", '{"write_folders": "realm"}', '{"write_folders": [3]}'])
def test_an_unreadable_scope_file_fails_closed(vault, text):
    (vault / ".apiary").mkdir()
    (vault / ".apiary" / "mcp-guard.json").write_text(text, encoding="utf-8")
    allowed, why = decide(obs(vault, "obsidian_put_content", filepath=f"{INBOX}/a.md"), vault)
    assert not allowed and "mcp-guard.json" in why, why


def test_the_scope_file_is_the_humans(vault):
    for ev in ({"tool_name": "Write", "cwd": str(vault), "tool_input": {"file_path": str(vault / ".apiary/mcp-guard.json")}},
               obs(vault, "obsidian_put_content", filepath=".apiary/mcp-guard.json")):
        scope(vault, write_folders=["."])
        assert not decide(ev, vault)[0]


def test_init_guards_obsidian_tools_and_older_colonies_gain_it(tmp_path):
    assert "mcp__obsidian__.*" in GUARD_MATCHER.split("|")
    old = tmp_path / "old"
    (old / ".claude").mkdir(parents=True)
    hook = {"type": "command", "command": '"python" -m apiary.hook --root "x"'}
    (old / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell|mcp__colony__create_task|"
                    "mcp__colony__create_plan", "hooks": [hook]}]}}), encoding="utf-8")
    main(["--root", str(old), "init", "--update-protocols"])
    entry = json.loads((old / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == GUARD_MATCHER and entry["hooks"] == [hook]


@pytest.mark.parametrize("rel", [".", ".claude", ".git", "./", f"{INBOX}/../..", "knowledge", "Knowledge"])
def test_the_vault_root_and_folders_that_hold_guarded_files_are_not_writable(vault, rel):
    scope(vault, write_folders=["."])
    assert not decide(obs(vault, "obsidian_delete_file", filepath=rel, confirm=True), vault)[0], rel
    assert not decide(obs(vault, "move_file", oldPath=rel, newPath="attic/x"), vault)[0], rel


@pytest.mark.parametrize("rel", ["../outside.md", "notes/../../outside.md", "/etc/passwd", "C:/Windows/x.md"])
def test_an_escape_is_refused_even_when_the_whole_vault_is_listed(vault, rel):
    """Found by the mutation run: with write_folders ["."] only the escape check stops a path outside the vault."""
    scope(vault, write_folders=["."])
    allowed, why = decide(obs(vault, "obsidian_put_content", filepath=rel, content="x"), vault)
    assert not allowed and "outside the vault" in why, (rel, why)


# --- Amendment 1 (2026-10-19): the Forge Nurse's verified BRIEF recommends obsidian-mcp 2.0.1 (StevenStavrakis) ----

@pytest.mark.parametrize("raw", ["TRACES", "pheromone_ledger", "CLAUDE", "castes/QUEEN", "Tasks/pending/009-x.task"])
def test_a_path_the_server_completes_with_md_is_checked_as_completed(vault, raw):
    """obsidian-mcp appends .md to note paths, and Windows ignores case: TRACES becomes TRACES.md."""
    scope(vault, write_folders=["."])
    assert not decide(obs(vault, "obsidian_create_note", vault="forge", path=raw, content="x"), vault)[0], raw


def test_the_folder_scope_ignores_case(vault):
    scope(vault, write_folders=[INBOX])
    assert decide(obs(vault, "obsidian_create_note", vault="f", path="Realm/Obsidian-Inbox/a"), vault)[0]


def test_every_entry_of_a_paths_list_is_checked(vault):
    scope(vault, write_folders=[INBOX])
    ok = [f"{INBOX}/a.md", f"{INBOX}/b"]
    assert decide(obs(vault, "obsidian_add_tags", vault="f", paths=ok, tags=["x"]), vault)[0]
    assert not decide(obs(vault, "obsidian_add_tags", vault="f", paths=ok + ["notes/c.md"], tags=["x"]), vault)[0]
    assert not decide(obs(vault, "obsidian_remove_tags", vault="f", paths=[f"{INBOX}/a", "CLAUDE"]), vault)[0]


def test_rename_tag_is_refused_outright(vault):
    scope(vault, write_folders=["."])
    allowed, why = decide(obs(vault, "obsidian_rename_tag", vault="f", oldTag="a", newTag="b", path=f"{INBOX}/a"), vault)
    assert not allowed and "every note" in why, why


@pytest.mark.parametrize("flag", ["update_links", "updateLinks"])
def test_a_move_that_rewrites_backlinks_is_refused(vault, flag):
    scope(vault, write_folders=[INBOX])
    move = obs(vault, "obsidian_move_note", vault="f", source=f"{INBOX}/a", destination=f"{INBOX}/b")
    assert decide(move, vault)[0]
    move["tool_input"][flag] = True
    allowed, why = decide(move, vault)
    assert not allowed and "backlink" in why, why


@pytest.mark.parametrize("rel", [".obsidian-mcp/trash/x.md", ".obsidian/app.json", ".claude/skills/mine/SKILL.md",
                                 ".apiary/x.md", ".git/config", "notes/.obsidian/x.md", ".Claude/x.md"])
def test_the_servers_and_the_colonys_hidden_folders_are_not_write_targets(vault, rel):
    scope(vault, write_folders=["."])
    assert not decide(obs(vault, "obsidian_create_note", vault="f", path=rel), vault)[0], rel
    assert not decide(obs(vault, "obsidian_create_directory", vault="f", path=rel.rsplit("/", 1)[0]), vault)[0], rel


def test_search_with_a_scope_is_a_read(vault):
    assert decide(obs(vault, "obsidian_search_vault", vault="f", query="x", scope="tasks"), vault) == (True, "")


def test_the_human_can_name_more_tool_prefixes_and_deny_tools(vault):
    scope(vault, write_folders=[INBOX], tool_prefixes=["mcp__vault__"], deny_tools=["obsidian_append_content"])
    ev = {"hook_event_name": "PreToolUse", "tool_name": "mcp__vault__write_note", "cwd": str(vault),
          "tool_input": {"path": "TRACES.md"}}
    assert not decide(ev, vault)[0]
    ev["tool_input"]["path"] = f"{INBOX}/a.md"
    assert decide(ev, vault)[0]
    assert not decide(obs(vault, "obsidian_append_content", filepath=f"{INBOX}/a.md"), vault)[0]
