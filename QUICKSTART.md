# Quickstart

This guide takes a new repository to its first task claimed and closed by Claude Code, in about five minutes, on
Linux, macOS or Windows.

## Requirements

- **Python 3.11 or later.** On Windows, use `py` wherever this page says `python` (bare `python` can be the
  Microsoft Store stub).
- **Git**, with your name and email set.
- **Claude Code** (the CLI, or the Code tab of the Claude desktop app).

## Alternative: delegate the setup to an agent

In Claude Code, in the target repository, send:

> *Set up apiary in this repository by following the "Set apiary up" section of
> https://github.com/WyrmSnack/apiary-demo/blob/main/AGENTS.md. Show me what it will add before you run init.*

The steps below perform the same setup manually, in a new folder.

## 1. Install

```bash
python -m pip install "git+https://github.com/WyrmSnack/apiary-demo"
```

A virtual environment is suitable. Install apiary into the environment that contains the project's test tools: a
task's check runs `python` as the interpreter apiary is installed in.

## 2. Make a colony

```bash
mkdir my-colony
cd my-colony
git init
python -m apiary init --example
git add -A
git commit -m "colony"
```

`init` writes the colony's files, the `colony` MCP server (`.mcp.json`), the guard hook (`.claude/settings.json`), the
agent protocol (`CLAUDE.md`) and a pre-commit check. `--example` adds a first task, `001-hello-colony.task`.
`.mcp.json` and the hook use absolute paths to this folder and to the Python that has apiary installed, so make the
colony in its permanent location.

## 3. Close a task from Claude Code

1. Start Claude Code in the `my-colony` folder. Approve the `colony` MCP server when it asks.
2. Send: *"Follow the colony protocol: resume, claim 001-hello-colony.task, and close it."*
3. To observe the guard, send: *"Now append a DONE line to PHEROMONE_LEDGER.md with the Edit tool."* The hook
   refuses the edit and names the colony tool the agent should use instead.

## 4. Check

```bash
python -m apiary validate
cat PHEROMONE_LEDGER.md
```

`validate` prints `valid`. The ledger shows one `CLAIM` and one `DONE` with the same token.

## Creating tasks

Describe the task to Claude Code in the colony, for example *"/colony-task add a --json flag to the export command,
with a test"*. The skill drafts the task and its check. On approval, the `create_task` tool writes a task that the
colony can claim. From a terminal:

```bash
python -m apiary task new json-flag --objective "export --json prints valid JSON" --acceptance "python -m pytest -q tests/test_export.py" --writes "src/export.py tests/test_export.py"
```

## Removal

A colony consists only of files. To remove it, delete `CLAUDE.md`'s colony block, `.mcp.json`, `.claude/`, `castes/`,
`knowledge/`, `tasks/`, `PHEROMONE_LEDGER.md` and `TRACES.md`, and `.git/hooks/pre-commit`.
