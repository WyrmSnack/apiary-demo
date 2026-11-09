"""The Claude Code guard (Phase 2 gate a). Inputs are the PreToolUse JSON Claude Code sends."""
import json
import os
import subprocess
import sys

import pytest

from apiary.hook import decide


@pytest.fixture
def root(tmp_path):
    return tmp_path.resolve()


def edit(root, rel, tool="Edit"):
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(root),
            "tool_input": {key: str(root / rel)}}


def shell(root, command, tool="Bash"):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(root), "tool_input": {"command": command}}


PROTECTED = ["PHEROMONE_LEDGER.md", "TRACES.md", "tasks/active/001-a.task", "tasks/pending/002-new.task",
             "tasks/done/001-a.task", ".colony.lock", ".apiary/quarantine.log", ".mcp.json",
             ".claude/settings.json", ".claude/settings.local.json", "CLAUDE.md", "AGENTS.md",
             "castes/forager.md", ".git/hooks/pre-commit",
             "gates/check_rea_guide.py"]     # human-owned acceptance checks: a Forager must not edit its own grader


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
@pytest.mark.parametrize("rel", PROTECTED)
def test_file_tools_cannot_touch_substrate_or_gate_files(root, tool, rel):
    allowed, why = decide(edit(root, rel, tool), root)
    assert not allowed and why


def test_notebook_edit_is_guarded_too(root):
    assert not decide(edit(root, "tasks/active/001-a.ipynb", "NotebookEdit"), root)[0]


@pytest.mark.parametrize("rel", ["engine/save.py", "tests/test_save.py", "README.md", "notes/TRACES.md",
                                 "docs/PHEROMONE_LEDGER.md", "taskstuff/x.py", ".claude/agents/x.md"])
def test_ordinary_files_are_editable(root, rel):
    assert decide(edit(root, rel, "Write"), root) == (True, "")


def test_relative_and_backslash_paths_are_resolved(root):
    ev = {"tool_name": "Edit", "cwd": str(root / "engine"), "tool_input": {"file_path": "..\\PHEROMONE_LEDGER.md"
                                                                         if os.name == "nt" else "../PHEROMONE_LEDGER.md"}}
    assert not decide(ev, root)[0]


def test_case_variants_are_guarded_where_the_filesystem_ignores_case(root):
    allowed = decide(edit(root, "pheromone_ledger.md"), root)[0]
    assert allowed is (os.name != "nt")


def test_files_outside_the_colony_are_not_its_business(root, tmp_path_factory):
    other = tmp_path_factory.mktemp("elsewhere") / "PHEROMONE_LEDGER.md"
    ev = {"tool_name": "Write", "cwd": str(root), "tool_input": {"file_path": str(other)}}
    assert decide(ev, root)[0]


BLOCKED_SHELL = [
    ("Bash", "echo 'x' >> PHEROMONE_LEDGER.md"),
    ("Bash", "printf x > TRACES.md"),
    ("Bash", "mv tasks/pending/001-a.task tasks/active/"),
    ("Bash", "cp ../x.task tasks/done/"),
    ("Bash", "rm -rf tasks"),
    ("Bash", "sed -i 's/exit(1)/exit(0)/' tasks/active/001-a.task"),
    ("Bash", "python -c \"open('PHEROMONE_LEDGER.md','a').write('x')\""),
    ("Bash", "git checkout -- PHEROMONE_LEDGER.md"),
    ("Bash", "git restore tasks/active/001-a.task"),
    ("Bash", "git commit --no-verify -m wip"),
    ("Bash", "cat x | tee -a PHEROMONE_LEDGER.md"),
    ("Bash", "bash -c \"echo x >> PHEROMONE_LEDGER.md\""),
    ("Bash", "rm tests/test_save.py"),
    ("Bash", "true && echo '{}' > .claude/settings.json"),
    ("Bash", "HUMAN_GATE_CHANGE=1 git commit -m x"),
    ("PowerShell", "Add-Content PHEROMONE_LEDGER.md 'x'"),
    ("PowerShell", "'x' | Out-File -Append TRACES.md"),
    ("PowerShell", "Set-Content .claude\\settings.json '{}'"),
    ("PowerShell", "Move-Item tasks\\pending\\001-a.task tasks\\active\\"),
    ("PowerShell", "Copy-Item x.json .mcp.json"),
    ("PowerShell", "Remove-Item .git\\hooks\\pre-commit"),
    ("PowerShell", "ac PHEROMONE_LEDGER.md 'x'"),
    ("PowerShell", "powershell -Command \"Add-Content TRACES.md x\""),
    ("PowerShell", "cmd /c \"echo x >> PHEROMONE_LEDGER.md\""),
]


@pytest.mark.parametrize("tool,command", BLOCKED_SHELL)
def test_shell_writes_to_guarded_files_are_blocked(root, tool, command):
    allowed, why = decide(shell(root, command, tool), root)
    assert not allowed and why, command


ALLOWED_SHELL = [
    ("Bash", "cat PHEROMONE_LEDGER.md"),
    ("Bash", "tail -n 30 PHEROMONE_LEDGER.md"),
    ("Bash", "grep CLAIM PHEROMONE_LEDGER.md"),
    ("Bash", "git add PHEROMONE_LEDGER.md tasks/ && git commit -m \"close 001; move on to tasks/002\""),
    ("Bash", "git diff tasks/ && git log -- TRACES.md"),
    ("Bash", "ls tasks/pending"),
    ("Bash", "python -m pytest -q tests"),
    ("Bash", "echo hello > out.txt"),
    ("Bash", "cat PHEROMONE_LEDGER.md > /tmp/ledger-copy.txt"),
    ("Bash", "apiary validate --since HEAD"),
    ("PowerShell", "Get-Content PHEROMONE_LEDGER.md -Tail 30"),
    ("PowerShell", "Get-ChildItem tasks\\pending"),
    ("PowerShell", "Select-String CLAIM PHEROMONE_LEDGER.md"),
    ("PowerShell", "'x' | Out-File notes.txt"),
]


@pytest.mark.parametrize("tool,command", ALLOWED_SHELL)
def test_reads_commits_and_ordinary_commands_are_allowed(root, tool, command):
    assert decide(shell(root, command, tool), root) == (True, ""), command


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "WebFetch", "mcp__colony__claim_task"])
def test_other_tools_pass(root, tool):
    assert decide({"tool_name": tool, "cwd": str(root), "tool_input": {"file_path": str(root / "TRACES.md")}}, root)[0]


def run_hook(root, payload: str):
    return subprocess.run([sys.executable, "-m", "apiary.hook", "--root", str(root)], input=payload,
                          capture_output=True, text=True, encoding="utf-8")


def test_hook_process_exits_2_with_reason_when_blocking(root):
    r = run_hook(root, json.dumps(edit(root, "PHEROMONE_LEDGER.md")))
    assert r.returncode == 2 and "colony tools" in r.stderr, r.stderr


def test_hook_process_exits_0_when_allowing(root):
    r = run_hook(root, json.dumps(edit(root, "engine/save.py")))
    assert r.returncode == 0 and r.stderr == "", r.stderr


def test_hook_fails_closed_on_input_it_cannot_read(root):
    r = run_hook(root, "{ not json")
    assert r.returncode == 2 and r.stderr


def test_a_shell_refusal_names_the_guarded_file(root):
    """Gate (d): the message cut the command at 80 characters and lost the file name ('...PHEROMONE_LEDG')."""
    long = f'echo hello >> "{(root / "PHEROMONE_LEDGER.md").as_posix()}"'
    allowed, why = decide(shell(root, long), root)
    assert not allowed and "PHEROMONE_LEDGER.md" in why, why


@pytest.mark.parametrize("name", ["settings.json", "settings.local.json"])
def test_user_level_claude_settings_are_guarded_too(root, monkeypatch, tmp_path_factory, name):
    """Outside the colony, but an agent could set disableAllHooks there and switch the guard off."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr("apiary.hook.Path.home", lambda: home)
    ev = {"tool_name": "Write", "cwd": str(root), "tool_input": {"file_path": str(home / ".claude" / name)}}
    assert not decide(ev, root)[0]


def test_disabling_hooks_from_the_shell_is_blocked(root):
    assert not decide(shell(root, "echo '{\"disableAllHooks\": true}' > ~/.claude/settings.json"), root)[0]
    assert not decide(shell(root, "jq '.disableAllHooks=true' s.json > t.json", "Bash"), root)[0]


def test_shell_writes_to_gates_are_blocked(root):
    assert not decide(shell(root, "echo 'import sys; sys.exit(0)' > gates/check_rea_guide.py"), root)[0]
    assert not decide(shell(root, "Set-Content gates\\check_rea_guide.py 'exit 0'", "PowerShell"), root)[0]


# Phase 5 gate (c) false positives, from the REA website session's transcript (2026-10-16).
SCRATCH_EDIT = ('cd "C:/Users/dev/AppData/Local/Temp/scratch/demo"\npython - <<\'EOF\'\n'
                'p="index.html"; s=open(p,encoding="utf-8").read()\n'
                's=s.replace("record it with the colony\'s <code>write_trace</code> so later tasks follow it",'
                '"record it in your decisions log so later work follows it")\n'
                'open(p,"w",encoding="utf-8",newline="\n").write(s)\nEOF')


@pytest.mark.parametrize("command", [
    SCRATCH_EDIT,                                                                   # "tasks" was English prose
    "python -c \"import json; print(json.load(open('runs/20261016T0058Z-blender-37b8.json'))['exit_code'])\"",
    "python -c \"print(open('PHEROMONE_LEDGER.md', encoding='utf-8').read()[-500:])\"",
    "grep -rn 'tasks follow' docs/",
])
def test_reading_and_prose_are_not_mistaken_for_writes(root, command):
    assert decide(shell(root, command), root) == (True, ""), command


@pytest.mark.parametrize("command", [
    "rm -rf tasks",
    "python -c \"open('PHEROMONE_LEDGER.md','a').write('x')\"",
    "python -c \"import pathlib; pathlib.Path('tasks/pending/009-x.task').write_text('')\"",
    "python -c \"open('runs/x.json', 'w').write('{}')\"",
    "python - <<'EOF'\nimport os\nos.remove('tasks/done/001-a.task')\nEOF",
    "python -c \"import shutil; shutil.copy('x.task', 'tasks/done/')\"",
])
def test_writes_in_code_are_still_blocked(root, command):
    assert not decide(shell(root, command), root)[0], command


@pytest.mark.parametrize("command", ["echo x > .claude/skills/colony-task/SKILL.md",
                                     "cp mine.md .claude/skills/colony-plan/SKILL.md",
                                     "echo x >> .claude/skills/colony-connectors/SKILL.md"])
def test_shell_writes_to_the_colony_skills_are_blocked(root, command):
    # Found in Phase 9: file tools were blocked from these skills, shell redirects were not.
    allowed, why = decide(shell(root, command), root)
    assert not allowed and why
