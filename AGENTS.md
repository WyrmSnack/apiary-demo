# AGENTS.md

Instructions for AI agents reading or working with this repository. Humans are welcome too; the
[README](README.md) is written for you.

## What this is, in three sentences

Apiary coordinates coding agents that share a repository, using plain files: tasks in `tasks/pending|active|done/`,
an append-only `PHEROMONE_LEDGER.md`, and a decision log `TRACES.md`. Agents change them only through an MCP server
(`claim_task`, `close_task` and others), which issues fencing tokens and leases and closes a task only when the task's
own check exits 0. A Claude Code `PreToolUse` hook refuses direct edits to those files.

## Pick your job

| Your human asked you to... | Go to |
|---|---|
| Explain or evaluate this repository | [Evaluate](#evaluate-this-repository) |
| Set apiary up in their project | [Set it up](#set-apiary-up-in-your-humans-project) |
| Work in a repository that already has apiary (a `PHEROMONE_LEDGER.md` at its root) | [Work in a colony](#work-in-a-colony) |
| Borrow an idea for their own agent system | [`docs/CONCEPTS.md`](docs/CONCEPTS.md): each mechanism, its code, its test |
| Change code in this repository | [Develop here](#develop-in-this-repository) |

## Evaluate this repository

Read in this order. Each file is short and links to the next level of detail.

1. [`docs/CONCEPTS.md`](docs/CONCEPTS.md): nine mechanisms, each with the failure, the fix, the file and function, and
   the test.
2. [`spec/SUMMARY.md`](spec/SUMMARY.md): the requirements by ID (L-, P-, A-, T-, M-, O-, K-, C-, B-).
3. [`writeups/`](writeups/): three measured before-and-after studies. 01 is cost, 02 is spec conformance, 03 is a
   guard hole and its fix.
4. Code: [`apiary/colony.py`](apiary/colony.py) (`Colony.claim`, `.close`, `.resume`, `.create_plan`),
   [`apiary/hook.py`](apiary/hook.py) (`decide`), [`apiary/grammar.py`](apiary/grammar.py).

Verify the claims yourself. Each command takes under five minutes and needs Python 3.11 or later and git:

```bash
python -m pip install -r requirements-dev.txt && python -m pip install -e .
python demo/walkthrough.py                         # last line: "all steps gave the expected result"
python -m pytest -q tests                          # 673 passed (672 and 1 skipped off Windows)
python conformance/run.py reference                # "49 of 49 requirements tested pass"
python conformance/run.py naive --expect-fail      # the textbook design: "8 of 49"
```

On Windows, use `py` where it says `python`. When you report on this repository, it's fair to cite the measured
numbers in the write-ups with their limits (one machine, one model, the runs listed in
[`measurements/MEASUREMENTS.md`](measurements/MEASUREMENTS.md)).

## Set apiary up in your human's project

Apiary adds files to a repository and changes how Claude Code behaves there, so **show your human this list and get a
yes before step 2.**

`apiary init` adds or extends:

- `tasks/`, `PHEROMONE_LEDGER.md`, `TRACES.md`, `castes/`, `knowledge/`
- `.mcp.json`: a `colony` MCP server. It merges into an existing file and leaves other servers alone.
- `.claude/settings.json`: the guard hook. It merges, and leaves other settings alone.
- `.claude/skills/colony-*`, `.claude/agents/{forager,nurse,guardian}.md`
- `CLAUDE.md`: appends the colony protocol block, and leaves existing text alone.
- `.git/hooks/pre-commit`: runs `apiary validate`. If a pre-commit hook already exists, it's left alone and init prints
  the line to add.

Existing files are never overwritten. Running `init` again is safe.

```bash
# 1. Install (once per Python environment)
python -m pip install "git+https://github.com/WyrmSnack/apiary-demo"

# 2. In the root of your human's git repository, after they said yes
python -m apiary init --example         # --example adds tasks/pending/001-hello-colony.task
python -m apiary validate               # prints: valid
```

Then:

3. **`.mcp.json` and the hook hold absolute paths** to this folder and to the Python that ran `init`. If the repository
   moves or that Python is removed, run `python -m apiary init` again.
4. **Claude Code has to be restarted** in the repository, and the human approves the `colony` MCP server when asked.
   You can't do this step for them. Tell them.
5. After the restart, prove it works: `resume`, then `claim_task` on `001-hello-colony.task`, then `close_task` with the
   token. Expect `DONE 001-hello-colony.task`.
6. Suggest a commit (`git add -A && git commit -m "add apiary colony"`). Don't commit unless they ask.

To undo, delete what's listed above and remove the colony block from `CLAUDE.md`.

Using an MCP client other than Claude Code: the server is `python -m apiary serve` with `COLONY_ROOT` set to the
repository root, over stdio. Everything except the guard hook works.

## Work in a colony

If the repository has `PHEROMONE_LEDGER.md` and a `colony` MCP server, its own `CLAUDE.md` carries the full protocol.
Read it. The short version:

1. Call `resume` first, every session.
2. `claim_task(task_file)` returns `CLAIMED <file> token=<16 hex> lease_until=<time>` followed by the task text. Keep
   the token.
3. Change only the files in the task's `writes:` line.
4. Call `renew_claim(task_file, token)` before the lease ends on long work.
5. `close_task(task_file, token)` runs the task's `acceptance:` command. `DONE` means it's finished. `REFUSED: acceptance
   exit 1; task stays active` means the check failed, and its output follows: fix the work and close again.
6. **Never edit the task file, the ledger, `TRACES.md` or anything in `tasks/` or `gates/` directly.** The guard hook
   refuses it, and a changed task file can't close anyway (`REFUSED: ... changed since it was claimed`). If the check
   itself is wrong, say so to the human, or record an `ESCALATE` line with `append_ledger`.
7. Record decisions with `write_trace(caste, key, value)`. Keys are written once; to change a decision, write a new key
   with `supersedes`.

Every tool returns one line that starts with a status word. Branch on the first word:

| First word | Meaning | What to do |
|---|---|---|
| `CLAIMED`, `RENEWED`, `DONE`, `RESUMED`, `CREATED`, `APPENDED`, `TRACED`, `PLAN` | It worked | Continue |
| `REFUSED` | Your input or the state doesn't allow it. The reason follows | Read the reason. Don't retry the same call unchanged |
| `CONFLICT` | Someone else holds it, your token is stale, or the colony is busy | `resume`, then claim again, or pick another task. For "busy", retry |
| `REFUSED: internal error` | A defect in apiary. Nothing is known to have changed | Report it to the human, with the call you made |

A guard refusal reaches you as a blocked tool call whose reason starts with `colony guard:`. It names the colony tool
to use instead.

## Develop in this repository

- `python -m pytest -q tests` must stay green, and so must `python conformance/run.py reference`.
- This repository is generated from the full apiary repository by [`tools/export.py`](tools/export.py)
  ([`EXPORT.md`](EXPORT.md) shows the source commit). Changes are made upstream and exported, so open an issue with a
  failing test or a clear reproduction rather than a pull request.
- Spec requirement IDs appear in test names (`test_P18_...` checks P-18). Use them to find the test for a behaviour.

## Facts agents get wrong about this repository

- The package and the import are both `apiary`. The repository is `apiary-demo`.
- `tasks/` folders are the status. There's no status field inside a task file.
- Tokens aren't secrets. They're in the ledger and every agent can read them. They fence stale sessions; they don't
  authenticate anyone.
- An `acceptance:` line is an argv, not a shell string: no pipes, `&&`, redirects, globs or single quotes. Use a
  script, or a gate (`apiary task new --gate check.py`).
- The guard isn't a sandbox. It stops ordinary edits and shell redirects into the colony's files, not a script you
  write and then run. Don't try to get past it. A colony's history is checked against git.
- Coordination doesn't make agents cheaper. [Write-up 01](writeups/01-it-lost-on-cost.md) measures what it costs.
