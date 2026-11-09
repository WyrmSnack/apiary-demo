"""Claude Code PreToolUse guard: agents change the substrate only through the colony tools.

.claude/settings.json (written by `apiary init`):
  {"hooks": {"PreToolUse": [{"matcher": "Edit|Write|...|PowerShell|mcp__colony__create_task|mcp__colony__create_plan",
     "hooks": [{"type": "command", "command": "\"<python>\" -m apiary.hook --root \"<colony>\""}]}]}}

Claude Code sends the tool call as JSON on stdin. Exit 2 blocks it and shows stderr to the agent.
File tools are checked exactly, by resolved path. Shell commands are checked by pattern, which is a
speed bump: a script the agent writes and runs is invisible here. `apiary validate --since` catches that
at commit time (docs/PHASE2.md).

Creating work (create_task, create_plan) also waits for the human: it is refused until the session's transcript holds a
reply from the human after their first message. That checks that the human replied, not what they said.

The Queen's lock tools (unlock_test, relock_test, lock_report) are refused to subagents, and a relock that weakens a
test needs the human's words "approve weakening <file name>". As a Stop hook it keeps the Queen from ending a turn
while a lock change is unreported (apiary.locktools).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

GUARDED_FILES = {"PHEROMONE_LEDGER.md", "TRACES.md", ".colony.lock", ".mcp.json", ".claude/settings.json",
                 ".claude/settings.local.json", "CLAUDE.md", "AGENTS.md",
                 # the castes' agent definitions; a person's own agents in .claude/agents/ stay editable
                 ".claude/agents/forager.md", ".claude/agents/nurse.md", ".claude/agents/guardian.md"}
GUARDED_DIRS = ("tasks", ".apiary", "castes", "gates", ".git/hooks",   # gates/: human-owned acceptance checks
                ".claude/skills/colony-task", ".claude/skills/colony-plan",   # the protocols for tasks and plans
                ".claude/skills/colony-tdd",                                # the test-first ladder (apiary init --tdd)
                ".claude/skills/colony-board",                              # the board before create_plan (0.9.0)
                "connectors", "runs", ".claude/skills/colony-connectors",   # spec section 13
                "knowledge/_templates",                                     # the card formats
                ".claude/skills/godot-project", ".claude/skills/godot-gdscript-tests",   # programs' skills (Phase 10)
                ".claude/skills/sprite-pipeline", ".claude/skills/blender-asset-pipeline",
                ".claude/skills/game-audio", ".claude/skills/tilemaps", ".claude/skills/vector-art")
_PROGRAM_SKILLS = r"godot-project|godot-gdscript-tests|sprite-pipeline|blender-asset-pipeline|game-audio|tilemaps|vector-art"
FILE_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
SHELL_TOOLS = {"Bash", "PowerShell"}
CREATE_TOOLS = {"mcp__colony__create_task", "mcp__colony__create_plan"}
LOCK_TOOLS = {"mcp__colony__unlock_test", "mcp__colony__relock_test", "mcp__colony__lock_report"}
REPORT_BLOCKS = Path(".apiary/tdd/report_blocks")
MAX_REPORT_BLOCKS = 3
CLOSE_TOOL = "mcp__colony__close_task"                 # a by: Human checkpoint closes on the human's words (K-2)
OBSIDIAN = "mcp__obsidian__"
MCP_GUARD = ".apiary/mcp-guard.json"                    # the human's write scope for MCP vault tools (guarded)
# Obsidian MCP tools that only read, by the names the Forge's Nurse found in each server's source (2026-10-19:
# mcp-obsidian, obsidian-mcp-server, MCPVault, obsidian-mcp, Local REST API). Every other tool counts as a write.
OBSIDIAN_READ_TOOLS = frozenset({
    "obsidian_get_file_contents", "obsidian_batch_get_file_contents", "obsidian_list_files_in_vault",
    "obsidian_list_files_in_dir", "obsidian_simple_search", "obsidian_complex_search", "obsidian_get_periodic_note",
    "obsidian_get_recent_periodic_notes", "obsidian_get_recent_changes",                        # mcp-obsidian
    "obsidian_get_note", "obsidian_list_notes", "obsidian_list_tags", "obsidian_search_notes",
    "obsidian_list_commands",                                                                   # obsidian-mcp-server
    "read_note", "read_multiple_notes", "list_directory", "search_notes", "get_frontmatter", "get_notes_info",
    "list_all_tags", "get_vault_stats",                                                         # MCPVault
    "obsidian_list_vaults", "obsidian_read_note", "obsidian_search_vault",                      # obsidian-mcp
    "vault_list", "vault_read", "search_query", "search_simple", "tag_list"})                   # Local REST API
# Argument names that carry a vault path. A write tool must carry at least one; mcp-guard.json may add more.
OBSIDIAN_PATH_ARGS = ("path", "filepath", "filename", "file", "target", "destination", "source", "dirpath",
                      "confirm_path", "filepaths", "paths", "oldPath", "newPath")
# Refused whatever their arguments: obsidian-mcp's rename_tag edits every note carrying the tag (Forge BRIEF, 2026-10-19).
OBSIDIAN_DENY_TOOLS = frozenset({"obsidian_rename_tag"})
# Never a vault write target, at any depth: the servers' own state (.obsidian-mcp/ holds obsidian-mcp's trash and
# journal), Obsidian's settings, and the colony's hidden folders. obsidian-mcp reserves only some, on the first segment.
OBSIDIAN_RESERVED = frozenset({".obsidian-mcp", ".obsidian", ".claude", ".apiary", ".git", ".trash", ".backup"})
ADVICE = ("Use the colony tools (claim_task, renew_claim, close_task, append_ledger, write_trace). "
          "Gate and protocol files are edited by a human.")

_FOLD = (lambda s: s.lower()) if os.name == "nt" else (lambda s: s)


def guarded(rel: str) -> bool:
    rel = _FOLD(rel.replace("\\", "/").strip("/"))
    if rel in {_FOLD(f) for f in GUARDED_FILES}:
        return True
    return any(rel == _FOLD(d) or rel.startswith(_FOLD(d) + "/") for d in GUARDED_DIRS)


def _check_file(tool_input: dict, key: str, cwd: Path, root: Path) -> tuple[bool, str]:
    raw = tool_input.get(key)
    if not isinstance(raw, str) or not raw:
        return False, f"colony guard: {key} is missing, so the edit cannot be checked. {ADVICE}"
    p = Path(raw.replace("\\", "/") if os.name != "nt" else raw)
    p = (p if p.is_absolute() else cwd / p).resolve()
    user_settings = Path.home() / ".claude"
    if _FOLD(str(p)) in {_FOLD(str((user_settings / n).resolve())) for n in ("settings.json", "settings.local.json")}:
        return False, (f"colony guard: {p} is your user-level Claude Code settings, which can switch the guard "
                       f"off. {ADVICE}")
    try:
        rel = p.relative_to(root)
    except ValueError:
        if os.name == "nt" and _FOLD(str(p)).startswith(_FOLD(str(root)) + "\\"):
            rel = Path(str(p)[len(str(root)) + 1:])
        else:
            return True, ""                       # outside the colony: not ours to guard
    if guarded(rel.as_posix()):
        return False, f"colony guard: {rel.as_posix()} is a substrate or gate file. {ADVICE}"
    return True, ""


# --- shell commands ----------------------------------------------------------

_MENTION = re.compile(
    r"(?:^|[\s\"'=/\\(:])(?:PHEROMONE_LEDGER\.md|TRACES\.md|\.colony\.lock|\.mcp\.json|"
    r"\.claude[/\\]settings(?:\.local)?\.json|CLAUDE\.md|AGENTS\.md|tasks(?![\w.-])|\.apiary(?![\w.-])|"
    r"castes(?![\w.-])|gates[/\\]|connectors[/\\]|runs[/\\]|\.git[/\\]hooks|"
    r"\.claude[/\\](?:agents[/\\](?:forager|nurse|guardian)\.md|skills[/\\](?:colony-(?:task|plan|connectors|tdd|board)|"
    + _PROGRAM_SKILLS + r"))(?![\w-]))", re.I)
_MENTION_LEAD = " \t\"'=/\\(:"          # characters _MENTION may match before the file name
# Inside code or prose, a guarded folder counts only as a path ("tasks/..."): "so later tasks follow it" is English.
# A bare folder name counts only as a whole shell argument ("rm -rf tasks").
_MENTION_PATH = re.compile(
    r"(?:^|[\s\"'=/\\(:])(?:PHEROMONE_LEDGER\.md|TRACES\.md|\.colony\.lock|\.mcp\.json|"
    r"\.claude[/\\]settings(?:\.local)?\.json|CLAUDE\.md|AGENTS\.md|tasks[/\\]|\.apiary[/\\]|castes[/\\]|"
    r"gates[/\\]|connectors[/\\]|runs[/\\]|\.git[/\\]hooks|"
    r"\.claude[/\\](?:agents[/\\](?:forager|nurse|guardian)\.md|skills[/\\](?:colony-(?:task|plan|connectors|tdd|board)|"
    + _PROGRAM_SKILLS + r"))(?![\w-]))", re.I)
BARE_DIRS = {"tasks", ".apiary", "castes", "gates", "connectors", "runs"}
# Code that writes, moves or deletes files. A plain open() for reading is not a write; neither is str.replace().
_WRITE_CODE = re.compile(
    r"open\s*\([^)]*?,\s*(?:mode\s*=\s*)?[\"'][rbt]*[wax+]|\.open\s*\(\s*(?:mode\s*=\s*)?[\"'][rbt]*[wax+]|"
    r"write_text|write_bytes|WriteAllText|AppendAllText|WriteAllBytes|\bos\.(?:remove|unlink|rename|replace|rmdir)\b|"
    r"\bshutil\.(?:copy\w*|move|rmtree)\b|\.unlink\s*\(|\.touch\s*\(", re.I)


def _mentions(seg: str, words: list[str]) -> bool:
    return bool(_MENTION_PATH.search(seg)) or any(w.strip("/\\").lower() in BARE_DIRS for w in words[1:])
_TESTS = re.compile(r"(?:^|[\s\"'/\\])(?:tests?[/\\]|test_\w+\.py)", re.I)
WRITERS = {"mv", "move", "move-item", "mi", "ren", "rename", "rename-item", "rni", "cp", "copy", "copy-item",
           "cpi", "xcopy", "robocopy", "rm", "del", "erase", "rd", "rmdir", "remove-item", "ri", "tee",
           "tee-object", "add-content", "ac", "set-content", "sc", "out-file", "new-item", "ni",
           "clear-content", "clc", "truncate", "touch", "dd", "install", "ln", "unlink", "shred"}
DELETERS = {"rm", "del", "erase", "rd", "rmdir", "remove-item", "ri", "unlink", "shred", "git"}
INPLACE = {"sed", "perl", "gawk", "awk"}
INTERPRETERS = {"python", "python3", "py", "node", "ruby", "perl", "php", "deno", "bun", "pythonw"}
SHELLS = {"bash", "sh", "zsh", "dash", "cmd", "powershell", "pwsh"}
GIT_REWRITERS = {"checkout", "restore", "reset", "rm", "mv", "clean", "stash", "apply", "am", "cherry-pick",
                 "revert", "read-tree", "update-index", "switch", "merge", "rebase", "pull"}


def _segments(command: str) -> list[str]:
    """Split on ; && || | & and newlines, outside quotes."""
    out, cur, quote, i = [], [], "", 0
    while i < len(command):
        c = command[i]
        if quote:
            cur.append(c)
            if c == quote:
                quote = ""
        elif c in "'\"":
            quote = c
            cur.append(c)
        elif c in ";|&\n":
            out.append("".join(cur))
            cur = []
            while i + 1 < len(command) and command[i + 1] in "|&":
                i += 1
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def _words(segment: str) -> list[str]:
    s = segment.lstrip()
    if s[:1] in "\"'" and s[1:].find(s[0]) >= 0:     # a quoted first word may hold spaces: "C:/Program Files/x.exe"
        end = s.index(s[0], 1)
        return [s[1:end]] + [w.strip("\"'") for w in s[end + 1:].split()]
    return [w.strip("\"'") for w in s.split()]


def _connector_programs(root: Path) -> set[str]:
    """Names a connector program can be called by: the connector's name and its program's file name."""
    from . import connectors
    out: set[str] = set()
    for name in connectors.names(root):
        out.add(name)
        try:
            c = connectors.load(root, name)
        except ValueError:
            continue
        if c:
            out.add(re.sub(r"\.(exe|cmd|bat|ps1)$", "", re.split(r"[/\\]", c.program)[-1].lower()))
    return out


def _program(words: list[str]) -> tuple[str, list[str]]:
    while words and (re.match(r"^[A-Za-z_]\w*=", words[0]) or words[0] in {"&", ".", "sudo", "env", "command",
                                                                           "exec", "nohup", "time"}):
        words = words[1:]
    if not words:
        return "", []
    name = re.split(r"[/\\]", words[0])[-1].lower()
    name = re.sub(r"\.(exe|cmd|bat|ps1)$", "", name)
    return name, words[1:]


def _redirect_targets(segment: str) -> list[str]:
    return [m.group(2) for m in re.finditer(r"(?:\d|\*)?>>?\s*([\"']?)([^\s\"'|&;<>]+)", segment)]


def _check_segment(seg: str) -> str | None:
    words = _words(seg)
    prog, args = _program(words)
    mentions = _mentions(seg, words)
    if any(_MENTION.search(" " + t) for t in _redirect_targets(seg)):
        return "redirects output into a substrate or gate file"
    if prog == "git" and args:
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in {"-C", "-c"} else 1
        sub = args[i].lower() if i < len(args) else ""
        if sub in {"commit", "push", "merge", "rebase", "cherry-pick", "am"} and any(
                a == "--no-verify" or re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*", a) for a in args[i + 1:]):
            return "skips the commit gates (--no-verify)"
        if sub in GIT_REWRITERS and mentions:
            return f"git {sub} would rewrite a substrate or gate file"
        if sub == "rm" and _TESTS.search(seg):
            return "deleting tests is a weakening; ask the human"
        return None
    if prog in WRITERS and mentions:
        return f"{prog} would write, move or delete a substrate or gate file"
    if prog in DELETERS and _TESTS.search(seg):
        return "deleting tests is a weakening; ask the human"
    if prog in INPLACE and mentions and any(re.match(r"^-\w*i", a) or a.startswith("--in-place") for a in args):
        return f"{prog} -i would edit a substrate or gate file in place"
    if prog in INTERPRETERS and mentions and _WRITE_CODE.search(seg) and \
            any(a in {"-c", "-e", "--eval", "-", "-p"} for a in args):
        return "inline code that writes a substrate or gate file"
    if prog in SHELLS:
        if any(a.lower().startswith(("-enc", "-e ")) or a.lower() in {"-e", "-ec", "-encodedcommand"} for a in args):
            return "encoded commands cannot be checked"
        if mentions:
            return "a nested shell command that names a substrate or gate file"
    return None


def _check_shell(command: str, root: Path | None = None) -> tuple[bool, str]:
    if not isinstance(command, str):
        return False, f"colony guard: the command cannot be read. {ADVICE}"
    if re.search(r"HUMAN_GATE_CHANGE\s*=|\$env:HUMAN_GATE_CHANGE", command, re.I):
        return False, "colony guard: the gate override is for the human, not the agent."
    if re.search(r"disableAllHooks", command, re.I):
        return False, "colony guard: switching hooks off is for the human, not the agent."
    if _MENTION_PATH.search(command) and _WRITE_CODE.search(command):
        return False, f"colony guard: code that writes files names a substrate or gate file. {ADVICE}"
    via_connector = _connector_programs(root) if root else set()
    for seg in _segments(command):
        prog = _program(_words(seg))[0]
        if prog and prog in via_connector:
            return False, (f"colony guard: `{prog}` has a connector in this colony. Run it with the run_connector "
                           "tool, which records its version, arguments and outputs (see the colony-connectors skill).")
        why = _check_segment(seg)
        if why:
            m = _MENTION.search(seg)
            name = m.group(0).lstrip(_MENTION_LEAD) if m else ""
            target = f" ({name})" if name else ""
            return False, f"colony guard: blocked `{seg[:200]}`{target}: {why}. {ADVICE}"
    return True, ""


def decide(event: dict, root: str | os.PathLike) -> tuple[bool, str]:
    """(allowed, reason). Reason is empty when allowed."""
    root = Path(root).resolve()
    if event.get("hook_event_name") == "Stop":
        return _check_report(event, root)
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    cwd = Path(event.get("cwd") or root)
    if tool in LOCK_TOOLS:
        return _check_lock_tool(event, tool.rsplit("__", 1)[1])
    if tool in FILE_TOOLS:
        return _check_file(tool_input, FILE_TOOLS[tool], cwd, root)
    if tool in SHELL_TOOLS:
        return _check_shell(tool_input.get("command", ""), root)
    if tool in CREATE_TOOLS:
        return _check_approval(event, tool.rsplit("__", 1)[1])
    if tool == CLOSE_TOOL:
        return _check_checkpoint(event, root)
    if tool.startswith(OBSIDIAN):
        return _check_obsidian(tool, OBSIDIAN, tool_input, root)
    if tool.startswith("mcp__") and not tool.startswith("mcp__colony__"):
        prefix = next((x for x in _mcp_scope(root)[0].get("tool_prefixes", []) if x and tool.startswith(x)), "")
        if prefix:                                   # another vault server the human named in mcp-guard.json
            return _check_obsidian(tool, prefix, tool_input, root)
    return True, ""


# --- human checkpoints (spec K-2) --------------------------------------------

def _check_checkpoint(event: dict, root: Path) -> tuple[bool, str]:
    """A by: Human task closes only after the human's own typed message, written at or after its CLAIM, says
    "approve <id>". Answers in the question dialog do not count: their words are options the agent wrote."""
    from . import grammar as g
    from .colony import Colony
    from .measure import human_messages_since
    task_file = (event.get("tool_input") or {}).get("task_file")
    if not isinstance(task_file, str) or not g.TASK_NAME.match(task_file):
        return True, ""                                   # close_task refuses it itself
    active = root / "tasks" / "active" / task_file
    try:
        task = g.parse_task(g.read_strict(active))
    except (OSError, g.GrammarError):
        return True, ""                                   # not active, or malformed: close_task refuses it
    if task.fields.get("by", "").strip().lower() != "human":
        return True, ""
    tid = g.task_id(task_file)
    ask = (f"Show the human the work and wait for them to write \"approve {tid:03d}\"; then call close_task again.")
    claims = [ln for ln in Colony(root)._ledger_lines() if ln.signal == "CLAIM" and ln.path == f"tasks/active/{task_file}"]
    path = event.get("transcript_path")
    if not claims or not path or not Path(path).is_file():
        return False, (f"colony guard: blocked close_task: {task_file} is a human checkpoint (by: Human), and "
                       f"{'its claim is not in the ledger' if not claims else 'this session transcript cannot be read'}"
                       f", so the human's approval cannot be checked; blocked to be safe. {ask}")
    since = g.parse_timestamp(claims[-1].timestamp)
    said = re.compile(rf"\bapprove\s+0*{tid}(?!\d)", re.I)
    if any(said.search(t) for t in human_messages_since(path, since)):
        return True, ""
    return False, (f"colony guard: blocked close_task: {task_file} is a human checkpoint (by: Human). It closes only "
                   f"after the human's own message, written since it was claimed, says \"approve {tid:03d}\". {ask}")


# --- Obsidian MCP tools -------------------------------------------------------

def _mcp_scope(root: Path) -> tuple[dict, str]:
    """The human's .apiary/mcp-guard.json: ({write_folders, path_args, read_tools, deny_tools, tool_prefixes}, error).
    A tool prefix other than mcp__obsidian__ also needs the guard's matcher in .claude/settings.json to name it."""
    keys = ("write_folders", "path_args", "read_tools", "deny_tools", "tool_prefixes")
    path = root / MCP_GUARD
    if not path.exists():
        return {k: [] for k in keys}, ""
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            raise ValueError("it is not a JSON object")
        out = {}
        for key in keys:
            value = cfg.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"{key} is not a list of text")
            out[key] = value
        return out, ""
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return {}, f"{MCP_GUARD} cannot be read ({e})"


def _vault_rel(raw: str, root: Path) -> str | None:
    """A vault path resolved against the vault root, as a root-relative posix path; None if it leaves the vault."""
    p = Path(raw.replace("\\", "/") if os.name != "nt" else raw)
    p = (p if p.is_absolute() else root / p).resolve()
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        if os.name == "nt" and _FOLD(str(p)).startswith(_FOLD(str(root)) + "\\"):
            return Path(str(p)[len(str(root)) + 1:]).as_posix()
        return None


def _obsidian_paths(tool_input: dict, names: list[str]) -> tuple[list[str], str]:
    """The path arguments of a call, or why one cannot be checked."""
    paths: list[str] = []
    for key in names:
        if key not in tool_input:
            continue
        value = tool_input[key]
        if isinstance(value, dict):                      # obsidian-mcp-server: target = {type: path, path: ...}
            if value.get("type", "path") != "path" or "path" not in value:
                return [], f"{key} names no file (type {value.get('type')!r}), so the guard cannot check it"
            value = value["path"]
        items = value if isinstance(value, list) else [value]
        for v in items:
            if not isinstance(v, str) or not v.strip():
                return [], f"{key} is not a path"
            paths.append(v.strip())
    if not paths:
        return [], f"it carries no path argument the guard knows ({', '.join(names)})"
    return paths, ""


def _check_obsidian(tool: str, prefix: str, tool_input: dict, root: Path) -> tuple[bool, str]:
    """Every vault MCP tool not on the read-only list writes, and fails closed (Forge TRACE obsidian-guard). Paths are
    compared ignoring case (Windows does), and also as the server may complete them, with .md appended."""
    name = tool[len(prefix):]
    cfg, error = _mcp_scope(root)
    if name in OBSIDIAN_READ_TOOLS or name in cfg.get("read_tools", []):
        return True, ""
    head = f"colony guard: blocked {tool}"
    if error:
        return False, f"{head}: {error}; vault writes are blocked until the human fixes it."
    if name in OBSIDIAN_DENY_TOOLS or name in cfg["deny_tools"]:
        return False, (f"{head}: this tool can change every note at once (renaming a tag edits every note that carries "
                       "it), so it is never run for an agent. Ask the human.")
    if any(tool_input.get(k) not in (None, False, "false", "False", 0) for k in ("update_links", "updateLinks")):
        return False, (f"{head}: update_links rewrites backlinks in notes outside the folders the human named. Move "
                       "the note without it, and tell the human which links to fix.")
    paths, why = _obsidian_paths(tool_input, list(OBSIDIAN_PATH_ARGS) + cfg["path_args"])
    if why:
        return False, f"{head}: it counts as a write and {why}. Path argument names go in {MCP_GUARD} (path_args)."
    folders = []
    for f in cfg["write_folders"]:
        rel = _vault_rel(f.strip() or ".", root)
        if rel is None:
            return False, f"{head}: {MCP_GUARD} lists {f!r}, which is outside the vault; vault writes are blocked."
        folders.append("" if rel == "." else rel.lower())
    protected = [x.lower() for x in (*GUARDED_FILES, *GUARDED_DIRS)]
    for raw in paths:
        rel = _vault_rel(raw, root)
        if rel is None:
            return False, f"{head}: {raw} is outside the vault ({root})."
        low = rel.lower()
        forms = [low] if low.endswith(".md") or low == "." else [low, low + ".md"]
        if low == "." or any(x == form or form.startswith(x + "/") or x.startswith(form + "/")
                             for x in protected for form in forms):
            return False, f"{head}: {rel} is, or holds, a substrate, gate or protocol file. {ADVICE}"
        if OBSIDIAN_RESERVED & set(low.split("/")):
            return False, (f"{head}: {rel} is inside a hidden folder that belongs to the vault server, Obsidian or the "
                           f"colony ({', '.join(sorted(OBSIDIAN_RESERVED))}).")
        if not any(f == "" or low == f or low.startswith(f + "/") for f in folders):
            listed = ", ".join(cfg["write_folders"]) or "none yet"
            return False, (f"{head}: {rel} is not inside a folder listed in {MCP_GUARD} (write_folders: {listed}). "
                           "Agents write into the vault only where the human named a folder; ask the human.")
    return True, ""


def _check_approval(event: dict, op: str) -> tuple[bool, str]:
    """Measured in Phase 7: in 2 of 3 solo runs the Queen created work without showing it to the human first."""
    from .measure import human_replies
    path = event.get("transcript_path")
    if not path or not Path(path).is_file():
        return False, (f"colony guard: blocked {op}: cannot read this session's transcript to see whether the human "
                       "has approved; blocked to be safe.")
    if human_replies(path) == 0:
        return False, (f"colony guard: blocked {op}: the human has not replied since their first message. Show the "
                       "human the plan (or the task draft) and wait for a yes, then call it again.")
    return True, ""


def _check_lock_tool(event: dict, op: str) -> tuple[bool, str]:
    """Only the session talking with the human (the Queen) changes locks. Sourced (code.claude.com/docs/en/hooks,
    2026-10-17): a hook that fires inside a subagent carries agent_id."""
    if event.get("agent_id"):
        return False, (f"colony guard: blocked {op}: only the Queen, the session talking with the human, unlocks, "
                       "relocks or reports locked tests. File a WARN for the test with append_ledger and stop.")
    tool_input = event.get("tool_input") or {}
    if op != "relock_test" or str(tool_input.get("approve_weakening", "")).lower() not in {"true", "1", "yes"}:
        return True, ""
    from .locktools import APPROVAL
    from .measure import human_reply_texts
    path = event.get("transcript_path")
    if not path or not Path(path).is_file():
        return False, ("colony guard: blocked relock_test: cannot read this session's transcript to see the human's "
                       "approval of a weakening; blocked to be safe.")
    said = [t.lower() for t in human_reply_texts(path)]
    names = sorted({Path(p.strip().replace("\\", "/")).name for p in str(tool_input.get("paths", "")).split(",")
                    if p.strip()})
    missing = [n for n in names if not any(f"{APPROVAL} {n}".lower() in t for t in said)]
    if missing:
        return False, ("colony guard: blocked relock_test with approve_weakening: the human has not written "
                       + " and ".join(f'"{APPROVAL} {n}"' for n in missing)
                       + ". Show them what weakens and wait for their reply.")
    return True, ""


def _turn_texts(transcript: str | None) -> str:
    """The main session's assistant text since the human's last message."""
    from .measure import _is_human
    if not transcript or not Path(transcript).is_file():
        return ""
    texts: list[str] = []
    for raw in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(m, dict) or m.get("isSidechain"):
            continue
        if _is_human(m):
            texts = []
        elif m.get("type") == "assistant":
            content = (m.get("message") or {}).get("content")
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "text":
                    texts.append(c.get("text", ""))
    return "\n".join(texts)


def _check_report(event: dict, root: Path) -> tuple[bool, str]:
    """Stop hook: the Queen does not end a turn while a lock change is unreported. Her text this turn must carry the
    lock_report() block, every [L<n>] token in it. Sourced (code.claude.com/docs/en/hooks, 2026-10-17): Stop gets
    last_assistant_message, and exit 2 keeps Claude going. After MAX_REPORT_BLOCKS blocks in a row the turn may end,
    with an ESCALATE in the ledger, so a turn cannot loop forever; the change stays owed to the next turn."""
    from . import locktools
    counter = root / REPORT_BLOCKS
    pending = locktools.unreported(root)
    if not pending:
        counter.unlink(missing_ok=True)
        return True, ""
    text = (event.get("last_assistant_message") or "") + "\n" + _turn_texts(event.get("transcript_path"))
    if locktools.reported_in(text, pending):
        locktools.mark_reported(root)
        counter.unlink(missing_ok=True)
        return True, ""
    try:
        blocks = int(counter.read_text(encoding="utf-8")) + 1
    except (OSError, ValueError):
        blocks = 1
    if blocks > MAX_REPORT_BLOCKS:
        counter.unlink(missing_ok=True)
        from .colony import Colony
        ids = " ".join(f"[{p['id']}]" for p in pending)
        note = f"lock changes not reported to the human after {MAX_REPORT_BLOCKS} reminders: {ids}"
        Colony(root).append_ledger("Queen", "ESCALATE", ".apiary/tdd/locks.json", note[:160])
        return True, ""
    counter.parent.mkdir(parents=True, exist_ok=True)
    counter.write_text(str(blocks), encoding="utf-8")
    return False, ("colony guard: test locks changed and the human has not been told. Put this block, unchanged, at "
                   "the top of your message to the human, then finish:\n\n" + locktools.report(root))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="apiary.hook")
    ap.add_argument("--root", required=True)
    args = ap.parse_args(argv)
    event: dict = {}
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        allowed, why = decide(event, args.root)
    except Exception as e:  # noqa: BLE001 -- the guard fails closed
        allowed, why = False, f"colony guard: could not check this tool call ({type(e).__name__}: {e}); blocked to be safe."
        if isinstance(event, dict) and event.get("hook_event_name") == "Stop":
            sys.stderr.write(why + " (Stop is not blocked on an error, so the session cannot loop)\n")
            return 0
    if allowed:
        return 0
    sys.stderr.write(why + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
