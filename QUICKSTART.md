# Quickstart

From nothing to a task claimed and closed by Claude Code, in about five minutes. Linux, macOS or Windows.

## You need

- **Python 3.11 or later.** On Windows, use `py` wherever this page says `python` (bare `python` can be the
  Microsoft Store stub).
- **Git**, with your name and email set.
- **Claude Code** (the CLI, or the Code tab of the Claude desktop app).

## Or let your agent do it

In Claude Code, in the repository you want to use, send:

> *Set up apiary in this repository by following the "Set apiary up" section of
> https://github.com/WyrmSnack/apiary-demo/blob/main/AGENTS.md. Show me what it will add before you run init.*

The steps below are the same thing done by hand, in a fresh folder.

## 1. Install

```bash
python -m pip install "git+https://github.com/WyrmSnack/apiary-demo"
```

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
colony where it will stay.

## 3. Close a task from Claude Code

1. Start Claude Code in the `my-colony` folder. Approve the `colony` MCP server when it asks.
2. Send: *"Follow the colony protocol: resume, claim 001-hello-colony.task, and close it."*
3. To see the guard, also send: *"Now append a DONE line to PHEROMONE_LEDGER.md with the Edit tool."* The hook
   refuses it and tells the agent which colony tool to use instead.

## 4. Check

```bash
python -m apiary validate
cat PHEROMONE_LEDGER.md
```

`validate` prints `valid`. The ledger shows one `CLAIM` and one `DONE` with the same token.

## Your own tasks

Ask Claude Code in the colony, in your own words, for example *"/colony-task add a --json flag to the export
command, with a test"*. The skill drafts the task and its check. Approve it, and the `create_task` tool writes a task
the colony can claim. From a terminal:

```bash
python -m apiary task new json-flag --objective "export --json prints valid JSON" --acceptance "python -m pytest -q tests/test_export.py" --writes "src/export.py tests/test_export.py"
```

## Undo

A colony is just files. To remove it, delete `CLAUDE.md`'s colony block, `.mcp.json`, `.claude/`, `castes/`,
`knowledge/`, `tasks/`, `PHEROMONE_LEDGER.md` and `TRACES.md`, and `.git/hooks/pre-commit`.
