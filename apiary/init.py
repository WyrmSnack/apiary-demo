"""`apiary init`: turn a directory into a colony. Idempotent: it only adds what is missing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

LEDGER_HEADER = "# PHEROMONE_LEDGER: append-only. Written only through the colony tools (spec/SUBSTRATE_SPEC.md).\n"
TRACES_HEADER = "# TRACES: decisions every later agent inherits. Written only through write_trace.\n"
EXAMPLE_TASK = """# A first task, to check the colony works end to end. Claim it, then close it.
objective:  The colony substrate claims and closes a task.
acceptance: python -c "print('colony works')"
why:        Proves the claim/close round trip before real work starts.
"""
GITIGNORE = (".colony.lock", ".apiary/")
# Spec E-1: colony files are LF. Under core.autocrlf=true git would check them out CRLF.
GITATTRIBUTES = tuple(f"{p} text eol=lf" for p in ("PHEROMONE_LEDGER.md", "TRACES.md", "tasks/**", "castes/**",
                                                    "runs/**", "connectors/**"))
CLAUDE_CODE_CONFIG = ".mcp.json"            # Claude Code's project-scoped MCP servers
CLAUDE_SETTINGS = ".claude/settings.json"
GUARD_MATCHER = ("Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell"
                 "|mcp__colony__create_task|mcp__colony__create_plan"     # creating work waits for the human
                 "|mcp__colony__unlock_test|mcp__colony__relock_test|mcp__colony__lock_report"   # the Queen's
                 "|mcp__colony__close_task"                               # a by: Human checkpoint waits for them (K-2)
                 "|mcp__obsidian__.*")                                    # vault writes stay in the human's folders
PROTOCOL_MARK = "<!-- apiary:colony-protocol -->"
CLAUDE_MD_BLOCK = f"""{PROTOCOL_MARK}
## Colony protocol

This repository is a colony. Agents change `PHEROMONE_LEDGER.md`, `TRACES.md` and `tasks/` only through the
`colony` MCP tools. Follow the Forager protocol:

@castes/forager.md
"""
QUEEN_MARK = "<!-- apiary:queen-protocol -->"
QUEEN_BLOCK = f"""{QUEEN_MARK}
## You are the Queen

The session talking with the human plans and dispatches; the subagents it starts are Foragers. For any goal with
several parts, plan it as parallel lanes and dispatch them, as the Queen protocol says:

@castes/queen.md
"""
TDD_MARK = "<!-- apiary:tdd -->"
TDD_SKILL_PATH = ".claude/skills/colony-tdd/SKILL.md"
TDD_BLOCK = f"""{TDD_MARK}
## This colony works test-first

Plan and build everything through the story ladder (user stories, feature stories, feature tests, unit tests, then
code). Its gates refuse a test that was never seen failing, and a locked test that changed:

@{TDD_SKILL_PATH}
"""
PRE_COMMIT_MARK = "# apiary: append-only check"
TEMPLATES = Path(__file__).parent / "templates"
FORAGER = (TEMPLATES / "forager.md").read_text(encoding="utf-8")
QUEEN = (TEMPLATES / "queen.md").read_text(encoding="utf-8")
NURSE = (TEMPLATES / "nurse.md").read_text(encoding="utf-8")
TDD_SKILL = (TEMPLATES / "colony-tdd.md").read_text(encoding="utf-8")
TASK_SKILL = (TEMPLATES / "colony-task.md").read_text(encoding="utf-8")
TASK_SKILL_PATH = ".claude/skills/colony-task/SKILL.md"
PLAN_SKILL = (TEMPLATES / "colony-plan.md").read_text(encoding="utf-8")
BOARD_SKILL = (TEMPLATES / "colony-board.md").read_text(encoding="utf-8")
BOARD_SKILL_PATH = ".claude/skills/colony-board/SKILL.md"
# Dedicated agents for the castes the Queen dispatches (Phase 9): a short system prompt and only the tools needed.
AGENTS = {f".claude/agents/{n}.md": (TEMPLATES / "agents" / f"{n}.md").read_text(encoding="utf-8")
          for n in ("forager", "nurse", "guardian")}
PLAN_SKILL_PATH = ".claude/skills/colony-plan/SKILL.md"


def _posix(p: str | Path) -> str:
    """Forward slashes work in Git Bash, which runs hooks on Windows, and in cmd.exe."""
    return Path(p).as_posix()


def _read_config(path: Path) -> dict:
    if not path.exists():
        return {}
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict) or not isinstance(cfg.get("mcpServers", {}), dict):
        raise ValueError("expected an object with an mcpServers object")
    return cfg


def _read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    cfg = json.loads(path.read_text(encoding="utf-8"))
    hooks = cfg.get("hooks", {}) if isinstance(cfg, dict) else None
    if not isinstance(hooks, dict) or not isinstance(hooks.get("PreToolUse", []), list):
        raise ValueError("expected an object whose hooks.PreToolUse is a list")
    return cfg


def _widen_guard(root: Path, settings: dict) -> list[str]:
    """Colonies made before 0.6.1 run the guard on file and shell tools only; add what GUARD_MATCHER adds."""
    changed, command, report = False, None, []
    for e in settings.get("hooks", {}).get("PreToolUse", []):
        guards = [h.get("command", "") for h in e.get("hooks", []) if "apiary.hook" in h.get("command", "")]
        if not guards:
            continue
        command = guards[0]
        have = [m for m in str(e.get("matcher", "")).split("|") if m]
        missing = [m for m in GUARD_MATCHER.split("|") if m not in have]
        if missing:
            e["matcher"] = "|".join(have + missing)
            changed = True
    if changed:
        report.append(f"widened the colony guard in {CLAUDE_SETTINGS} (task creation and human checkpoints wait for "
                      "the human; only the Queen changes test locks; Obsidian MCP writes stay in the folders the "
                      "human lists)")
    if command and _add_stop_hook(settings, command):
        report.append(f"added the lock-report Stop hook to {CLAUDE_SETTINGS} (the human hears of every lock change)")
    if not report:
        return []
    (root / ".claude").mkdir(exist_ok=True)
    (root / CLAUDE_SETTINGS).write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def _add_stop_hook(settings: dict, command: str) -> bool:
    """The guard, run when the Queen ends a turn: it holds the turn until her message carries lock_report()."""
    stops = settings.setdefault("hooks", {}).setdefault("Stop", [])
    if any("apiary.hook" in h.get("command", "") for e in stops for h in e.get("hooks", [])):
        return False
    stops.append({"hooks": [{"type": "command", "command": command}]})
    return True


def update_protocols(root: str | Path) -> tuple[int, list[str]]:
    """Refresh apiary's own protocol and skill files from this version's templates. Touches nothing else."""
    root = Path(root).resolve()
    from .connect import SKILL_PATH as CONNECTORS_SKILL, program_skills, skill_text
    from .knowledge import TEMPLATES as KNOWLEDGE_TEMPLATES, TEMPLATE_NAMES
    templates = {f"knowledge/_templates/{k} Card Template.md":
                 (KNOWLEDGE_TEMPLATES / f"{k} Card Template.md").read_text(encoding="utf-8") for k in TEMPLATE_NAMES}
    owned = {**templates, "castes/forager.md": FORAGER, "castes/queen.md": QUEEN, "castes/nurse.md": NURSE,
             TASK_SKILL_PATH: TASK_SKILL, PLAN_SKILL_PATH: PLAN_SKILL, BOARD_SKILL_PATH: BOARD_SKILL,
             CONNECTORS_SKILL: skill_text(root), **AGENTS,
             **program_skills(root)}
    if TDD_MARK in ((root / "CLAUDE.md").read_text(encoding="utf-8") if (root / "CLAUDE.md").exists() else ""):
        owned[TDD_SKILL_PATH] = TDD_SKILL                  # only in a colony made with `apiary init --tdd`
    report = []
    for rel, text in owned.items():
        path = root / rel
        if path.exists() and path.read_text(encoding="utf-8").replace("\r\n", "\n") == text:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        report.append(f"updated {rel}")
    try:
        report += _widen_guard(root, _read_settings(root / CLAUDE_SETTINGS))
    except (ValueError, UnicodeDecodeError) as e:
        report.append(f"not changed: {CLAUDE_SETTINGS} is not readable ({e})")
    return 0, report or ["protocols already current"]


def init(root: str | Path, example: bool = False, tdd: bool = False) -> tuple[int, list[str]]:
    """Returns (exit status, report lines)."""
    root = Path(root).resolve()
    report: list[str] = []

    configs = [CLAUDE_CODE_CONFIG]
    loaded: dict[str, dict] = {}
    for rel in configs:                     # read every config before changing anything
        try:
            loaded[rel] = _read_config(root / rel)
        except (ValueError, UnicodeDecodeError) as e:
            return 1, [f"refused: {rel} is not readable JSON ({e}); fix it, then run init again. "
                       "Nothing was changed."]
    try:
        settings = _read_settings(root / CLAUDE_SETTINGS)
    except (ValueError, UnicodeDecodeError) as e:
        return 1, [f"refused: {CLAUDE_SETTINGS} is not readable ({e}); fix it, then run init again. "
                   "Nothing was changed."]

    def write_new(path: Path, text: str) -> None:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        report.append(f"created {path.relative_to(root).as_posix()}")

    for d in ("pending", "active", "done"):
        write_new(root / "tasks" / d / ".gitkeep", "")
    write_new(root / "PHEROMONE_LEDGER.md", LEDGER_HEADER)
    write_new(root / "TRACES.md", TRACES_HEADER)
    if example and not any((root / "tasks" / d / "001-hello-colony.task").exists()
                           for d in ("pending", "active", "done")):
        write_new(root / "tasks" / "pending" / "001-hello-colony.task", EXAMPLE_TASK)

    for rel, cfg in loaded.items():
        servers = cfg.setdefault("mcpServers", {})
        if "colony" in servers:
            continue
        # Absolute paths: the interpreter running init has apiary installed (bare "python" may be the
        # Microsoft Store stub), and the server must find this colony whatever directory it is started in.
        servers["colony"] = {"type": "stdio", "command": sys.executable, "args": ["-m", "apiary.server"],
                             "env": {"COLONY_ROOT": str(root)}}
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8", newline="\n")
        report.append(f"added the colony server to {rel}")

    # The guard: Claude Code runs it before every file edit and shell command (docs/PHASE2.md).
    entries = settings.setdefault("hooks", {}).setdefault("PreToolUse", [])
    if not any("apiary.hook" in h.get("command", "") for e in entries for h in e.get("hooks", [])):
        command = f'"{_posix(sys.executable)}" -m apiary.hook --root "{_posix(root)}"'
        entries.append({"matcher": GUARD_MATCHER, "hooks": [{"type": "command", "command": command}]})
        _add_stop_hook(settings, command)
        (root / ".claude").mkdir(exist_ok=True)
        (root / CLAUDE_SETTINGS).write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8", newline="\n")
        report.append(f"added the colony guard hook to {CLAUDE_SETTINGS}")
    else:
        report += _widen_guard(root, settings)

    write_new(root / "castes" / "forager.md", FORAGER)
    write_new(root / "castes" / "queen.md", QUEEN)
    write_new(root / "castes" / "nurse.md", NURSE)
    from .knowledge import TEMPLATES as KNOWLEDGE_TEMPLATES, TEMPLATE_NAMES
    for folder in ("Concepts", "Tools", "Workflows", "Playbooks"):         # the Digital-ToolBox layout
        write_new(root / "knowledge" / folder / ".gitkeep", "")
    for kind in TEMPLATE_NAMES:
        name = f"{kind} Card Template.md"
        write_new(root / "knowledge" / "_templates" / name, (KNOWLEDGE_TEMPLATES / name).read_text(encoding="utf-8"))
    write_new(root / TASK_SKILL_PATH, TASK_SKILL)          # Claude Code's /colony-task skill (spec O-3)
    write_new(root / PLAN_SKILL_PATH, PLAN_SKILL)          # /colony-plan: lanes and parallel dispatch
    write_new(root / BOARD_SKILL_PATH, BOARD_SKILL)        # /colony-board: the plan as a board (spec B-1)
    for rel, text in AGENTS.items():                      # forager, nurse, guardian (Phase 9)
        write_new(root / rel, text)
    from .connect import SKILL_PATH as CONNECTORS_SKILL, skill_text
    write_new(root / CONNECTORS_SKILL, skill_text(root))   # rewritten by `apiary connect add` (spec section 13)
    claude_md = root / "CLAUDE.md"
    blocks = [(PROTOCOL_MARK, CLAUDE_MD_BLOCK, "the colony protocol"), (QUEEN_MARK, QUEEN_BLOCK, "the Queen protocol")]
    if tdd:                                                # the story ladder (Phase 10 amendment 2)
        write_new(root / TDD_SKILL_PATH, TDD_SKILL)
        blocks.append((TDD_MARK, TDD_BLOCK, "the test-first ladder"))
    for mark, block, what in blocks:
        current = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
        if mark not in current:
            sep = "" if not current else ("\n" if current.endswith("\n") else "\n\n")
            claude_md.write_text(current + sep + block, encoding="utf-8", newline="\n")
            report.append(f"added {what} to CLAUDE.md" if current else "created CLAUDE.md")

    if (root / ".git").is_dir():
        hook = root / ".git" / "hooks" / "pre-commit"
        line = f'"{_posix(sys.executable)}" -m apiary.cli --root "{_posix(root)}" validate --since HEAD'
        if not hook.exists():
            hook.parent.mkdir(parents=True, exist_ok=True)
            hook.write_text(f"#!/bin/sh\n{PRE_COMMIT_MARK} (spec L-7), installed by apiary init.\n"
                            f"# Refuses commits that rewrite the ledger, TRACES or a closed task.\nexec {line}\n",
                            encoding="utf-8", newline="\n")
            hook.chmod(0o755)
            report.append("installed .git/hooks/pre-commit (append-only check)")
        elif PRE_COMMIT_MARK not in hook.read_text(encoding="utf-8", errors="replace"):
            report.append(f"left the existing .git/hooks/pre-commit alone; add this line to it: {line}")
    else:
        report.append("no .git folder here, so no pre-commit check: run `git init` and then init again")

    for name, wanted in ((".gitignore", GITIGNORE), (".gitattributes", GITATTRIBUTES)):
        path = root / name
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [x for x in wanted if x not in text.splitlines()]
        if missing:
            if text and not text.endswith("\n"):
                text += "\n"
            path.write_text(text + "\n".join(missing) + "\n", encoding="utf-8", newline="\n")
            report.append(f"added {', '.join(missing)} to {name}")

    report.append("nothing to do: already a colony" if not report else
                  "next: start Claude Code in this folder, approve the 'colony' MCP server when asked, "
                  "and ask it to claim and close a task")
    return 0, report
