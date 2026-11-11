# AGENTS.md

Instructions for AI agents that read or work with this repository. Human readers should start with the
[README](README.md).

If your fetch tool summarises web pages, read the raw file instead:
`https://raw.githubusercontent.com/WyrmSnack/apiary-demo/main/AGENTS.md`.

## Overview

Apiary coordinates coding agents that share a repository, using plain files: tasks in `tasks/pending|active|done/`,
an append-only `PHEROMONE_LEDGER.md`, and a decision log, `TRACES.md`. Agents change these files only through an MCP
server (`claim_task`, `close_task` and others), which issues fencing tokens and leases and closes a task only when the
task's own check exits 0. A Claude Code `PreToolUse` hook refuses direct edits to those files.

## Sections by task

| The human has asked you to... | Section |
|---|---|
| Explain or evaluate this repository | [Evaluate](#evaluate-this-repository) |
| Install apiary in their project | [Set it up](#set-apiary-up-in-your-humans-project) |
| Work in a repository that already uses apiary (a `PHEROMONE_LEDGER.md` at its root) | [Work in a colony](#work-in-a-colony) |
| Adopt a mechanism in their own agent system | [`docs/CONCEPTS.md`](docs/CONCEPTS.md): each mechanism, its code, its test |
| Change code in this repository | [Develop here](#develop-in-this-repository) |

## Evaluate this repository

Read in this order. Each file is short and links to the next level of detail.

1. [`docs/CONCEPTS.md`](docs/CONCEPTS.md): nine mechanisms, each with the failure, the mechanism, the file and
   function, the test, and the limit.
2. [`spec/SUMMARY.md`](spec/SUMMARY.md): the requirements by ID (L-, P-, A-, T-, M-, O-, K-, C-, B-).
3. [`writeups/`](writeups/): three measured studies, each with a baseline and a result. 01 covers cost, 02 covers
   specification conformance, and 03 covers a guard bypass and its fix.
4. Code: [`apiary/colony.py`](apiary/colony.py) (`Colony.claim`, `.close`, `.resume`, `.create_plan`),
   [`apiary/hook.py`](apiary/hook.py) (`decide`), [`apiary/grammar.py`](apiary/grammar.py).

### Verify the claims

Requirements: Python 3.11 or later, and git. On Windows, use `py` where this page says `python`. Work in a virtual
environment:

```bash
git clone https://github.com/WyrmSnack/apiary-demo && cd apiary-demo
python -m venv .venv
source .venv/bin/activate                          # Windows (Git Bash): source .venv/Scripts/activate
python -m pip install -r requirements-dev.txt -e .
```

Then run the following. The times were measured on a four-core laptop; the commands print little until they finish.

| Command | Expected output | Time |
|---|---|---|
| `python demo/walkthrough.py` | last line `all steps gave the expected result` | under a minute |
| `python -m pytest -q tests` | `673 passed` (on Linux and macOS, `672 passed, 1 skipped`) | about 2 minutes |
| `python conformance/run.py reference` | `49 of 49 requirements tested pass (254 of 254 results pass ...)` | 3 to 10 minutes: every test starts a real MCP server process |
| `python conformance/run.py naive --expect-fail` | about 150 `FAILED` lines, then `8 of 49 requirements tested pass`, exit 0. The failures are expected: this is the textbook design, and it must not conform | 3 to 7 minutes |
| `python ci/clean_install_check.py` | ends with `PASS`: builds a wheel, installs it in a fresh venv, and runs init, the guard, an MCP round trip and the pre-commit check | 1 to 2 minutes |

These commands write temporary colonies to the system temp folder. To keep all output inside one folder, first set
`TMPDIR` (and, on Windows, `TMP` and `TEMP`) to it, and pass `--basetemp=<folder>` to pytest.

The following cannot be rerun from this repository: the benchmark token counts in write-up 01 (the run records
contain private session paths; [`measurements/MEASUREMENTS.md`](measurements/MEASUREMENTS.md) has every number), the
0.8.0 baseline run and the planted-bug script in write-up 03, and the full specification text (595 lines; this
repository contains the summary, the vectors and the complete conformance suite). The benchmark's "textbook" baseline
is the author's reading of the design apiary started from, scored against the author's own specification. Cite the
numbers with their limits: one machine, one model, three runs per setup.

## Set apiary up in your human's project

Apiary adds files to a repository and changes how Claude Code behaves there. **Show the human this list and obtain
their approval before running `init`.** Existing files are never overwritten; where a file exists, it is extended as
noted. Running `init` again is safe and prints `nothing to do: already a colony`.

| Path | Effect of `init` |
|---|---|
| `tasks/{pending,active,done}/`, `PHEROMONE_LEDGER.md`, `TRACES.md` | creates the colony's files |
| `castes/` (`forager.md`, `nurse.md`, `queen.md`) | creates the role protocols |
| `knowledge/` | creates a notes folder with four card templates |
| `.claude/skills/colony-{task,plan,board,connectors}/` | creates Claude Code skills |
| `.claude/agents/{forager,nurse,guardian}.md` | creates Claude Code subagents |
| `.mcp.json` | adds a `colony` MCP server; other servers are left unchanged |
| `.claude/settings.json` | adds the guard (`PreToolUse`) and a `Stop` hook that reports lock changes; other settings are left unchanged |
| `CLAUDE.md` | appends the colony protocol and the Queen (planner) protocol; existing text is left unchanged |
| `.gitignore`, `.gitattributes` | appends `.colony.lock` and `.apiary/`, and LF line endings for the colony's files |
| `.git/hooks/pre-commit` | runs `apiary validate --since HEAD`, the append-only check. An existing pre-commit hook is left unchanged, and init prints the line to add to it |

The guard's matcher also names `mcp__obsidian__.*`. It has no effect unless an Obsidian vault server is connected; in
that case, it restricts that server's writes to folders the human lists in `.apiary/mcp-guard.json`.

### Steps

```bash
# 1. Install, in the Python environment that will run the colony (a venv is suitable)
python -m pip install "git+https://github.com/WyrmSnack/apiary-demo"

# 2. In the root of the human's git repository, after they have approved
python -m apiary init --example         # --example adds tasks/pending/001-hello-colony.task
python -m apiary validate               # prints: valid
```

3. **Identify the Python that runs the checks.** `python` in a task's `acceptance:` line means the interpreter apiary
   is installed in, not the project's own environment. If checks run the project's tests, install the project's test
   dependencies (`pytest` and so on) into that same environment.
4. **`.mcp.json` and the hook contain absolute paths** to the repository and to that Python. If either moves, run
   `python -m apiary init` again.
5. **Verify the installation without a restart**, from the repository root:

   ```bash
   python -m apiary claim 001-hello-colony.task       # CLAIMED ... token=<16 hex>
   python -m apiary close 001-hello-colony.task <token>   # DONE 001-hello-colony.task
   echo '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"PHEROMONE_LEDGER.md"},"cwd":"."}' \
     | python -m apiary.hook --root .                 # exit 2, stderr starts "colony guard:"
   python -m apiary validate                          # valid
   ```

6. **Claude Code must be restarted** in the repository, and the human must approve the `colony` MCP server when
   prompted. An agent cannot perform this step; inform the human.
7. **Create the first real task** with the project's own tests as its check, for example:

   ```bash
   python -m apiary task new first-feature --objective "what is true when it is done" \
     --acceptance "python -m pytest -q" --writes "src/thing.py tests/test_thing.py"
   ```

8. Propose a commit (`git add -A && git commit -m "add apiary colony"`). Do not commit unless the human requests it.

To uninstall, delete the paths in the table and remove the colony blocks from `CLAUDE.md`.

**Other MCP clients** (not Claude Code): run `python -m apiary --root <repository> serve`, or
`python -m apiary.server` with `COLONY_ROOT=<repository>`, over stdio. (`python -m apiary serve` without `--root`
serves the current directory.) Everything except the guard hook is available.

## Work in a colony

If the repository has `PHEROMONE_LEDGER.md` and a `colony` MCP server, its own `CLAUDE.md` contains the full protocol.
Read it. In summary:

1. Call `resume` first, in every session.
2. `claim_task(task_file)` returns `CLAIMED <file> token=<16 hex> lease_until=<time>` followed by the task text.
   Retain the token.
3. Change only the files in the task's `writes:` line. This is a rule, not a lock: the guard does not enforce it, and
   other agents and the human depend on it.
4. On long work, call `renew_claim(task_file, token)` before the lease expires.
5. `close_task(task_file, token)` runs the task's `acceptance:` command. `DONE` means the task is complete. `REFUSED:
   acceptance exit 1; task stays active` means the check failed, and its output follows: correct the work and close
   again.
6. **Never edit the task file, the ledger, `TRACES.md`, or anything in `tasks/` or `gates/` directly, and never weaken
   the tests a check runs.** The guard refuses direct edits, and a changed task file cannot be closed
   (`REFUSED: ... changed since it was claimed`). If the check itself is incorrect, inform the human, or record an
   `ESCALATE` line with `append_ledger`.
7. Record decisions with `write_trace(caste, key, value)`. Each key is written once; to change a decision, write a new
   key with `supersedes`.

Tools that take a `caste` (the caller's role) accept exactly one of `Queen`, `Forager`, `Nurse`, `Guardian`,
`SignalSprite`, `Cartographer`, `Scribe`. The value is case-sensitive. A worker is `Forager`; the session that plans
with the human is `Queen`.

Every tool returns one line beginning with a status word. Branch on the first word:

| First word | Meaning | Action |
|---|---|---|
| `CLAIMED`, `RENEWED`, `DONE`, `RESUMED`, `CREATED`, `APPENDED`, `TRACED`, `PLAN` | The operation succeeded | Continue |
| `REFUSED` | The input or the current state does not permit the operation. The reason follows | Read the reason. Do not repeat the same call unchanged |
| `CONFLICT` | Another agent holds the task, the token is stale, the task is not in `pending/`, or the colony is busy | Read the reason. `is not pending (it is in active/)`: another agent holds it; choose another task. `is not pending` alone: check the file name. A stale token: call `resume`, then claim again. Busy: retry |
| `REFUSED: internal error` | A defect in apiary. No change is known to have been made | Report it to the human, with the call that was made |

A guard refusal arrives as a blocked tool call whose reason begins with `colony guard:`. It names the colony tool to
use instead.

## Develop in this repository

- `python -m pytest -q tests` must remain green, and so must `python conformance/run.py reference`.
- This repository is generated from the full apiary repository by [`tools/export.py`](tools/export.py)
  ([`EXPORT.md`](EXPORT.md) records the source commit). Changes are made upstream and exported, so open an issue with
  a failing test or a clear reproduction rather than a pull request.
- Specification requirement IDs appear in test names (`test_P18_...` checks P-18). Use them to locate the test for a
  behaviour.
- Some comments name design documents (`docs/PHASE2.md` and so on) that remain in the full repository.

## Common misconceptions about this repository

- The package and the import are both `apiary`. The repository is `apiary-demo`.
- The `tasks/` folders are the status. A task file contains no status field.
- Tokens are not secrets. They appear in the ledger and every agent can read them. They fence stale sessions; they do
  not authenticate anyone.
- An `acceptance:` line is an argv, not a shell string: no pipes, `&&`, redirects, globs or single quotes. Use a
  script, or a gate (`apiary task new --gate check.py`, saved under the guarded `gates/` folder).
- Only the task file is pinned at claim, not the tests or scripts its check runs. A check in `gates/` is covered by
  the guard; tests elsewhere are protected only by the rule in step 6 and by review.
- All agents share one working tree. Apiary keeps agents off the same task, not off each other's files: use disjoint
  `writes:` lines (`create_plan` refuses parallel tasks that overlap), or separate worktrees.
- The guard is not a sandbox. It stops ordinary edits and shell redirects into the colony's files, but not a script
  that is written and then run, or a file name assembled from a variable. Do not attempt to circumvent it. The
  pre-commit hook and `apiary validate --since` detect a rewritten history.
- Coordination does not reduce token cost. [Write-up 01](writeups/01-coordination-cost.md) measures its cost.
