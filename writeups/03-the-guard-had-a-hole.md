# The guard had a hole, and how I know the fix holds

*Kevin Wilkins, November 2026. The "before" numbers come from the run log of apiary 0.8.0 (private commit `2a07698`,
2026-10-19). The "after" numbers come from this repository, and you can rerun them.*

**In short:** a guard that lists the tools it checks lets through every tool it doesn't list. I found this by reading
the code before connecting a new MCP server (a notes vault) to the colony. The fix was written test-first, and the
tests were then checked by planting bugs in the fix to see whether they caught them.

## The guard, in one paragraph

Apiary's agents may change the colony's shared files (the ledger, `TRACES.md`, the task folders, the acceptance
checks) only through the colony's own tools, which write lines the protocol can check. A Claude Code `PreToolUse`
hook (`apiary/hook.py`) enforces that. It sees every edit, write and shell command before it runs, and refuses any
that would touch those files directly. [`demo/walkthrough.py`](../demo/walkthrough.py) shows it refusing a `Write` to
the ledger, an `Edit` to a claimed task and a shell redirect into the ledger, while allowing an edit to the file the
task is meant to change.

## The hole

I was about to give the agents an Obsidian MCP server, so that they could read and write notes in the same folder as
the colony. Reading `hook.py` before connecting it showed that the guard only looked at Claude Code's own file and
shell tools. **A tool from any MCP server went straight past it.** An `obsidian_put_content` call to
`PHEROMONE_LEDGER.md` could forge the ledger, and the guard would allow it.

## Before and after

| | Apiary 0.8.0 (before) | Apiary 0.9.0 (after, this repository) |
|---|---|---|
| `decide()` on an Obsidian write to the ledger | **allowed** | **refused** |
| The guard and checkpoint tests written for the fix | **42 failed, 16 could not start, 13 passed** (71) | **101 of 101 pass** (the 71, plus 30 added later in the same phase, most of them after the vault server's real behaviour was checked) |
| Planted bugs in the new guard, board and checkpoint code, caught by the tests | (no such code) | **30 of 30** |

How each "before" number was made: the new tests were written first and run against 0.8.0 with none of the fix
present (a "red" run). They failed for the right reasons: the bypass was allowed, and the new `by:` checkpoint field
was unknown. Then the fix was written until they passed.

How the planted-bug number was made: a script put one bug at a time into the new code (for example, "every Obsidian
tool counts as a read", "case is not ignored in paths", "`rename_tag` is allowed"), ran the tests, and restored the
file. **Two bugs were missed at first**: an escape from the vault when the whole vault was listed as writable, and a
folder that holds guarded templates. Each got a new test, and the rerun caught all 30.

## What the fix does

- Every tool of a vault server that is not known to be read-only counts as a write, and is refused outside the folders
  the human listed in `.apiary/mcp-guard.json`.
- Paths are compared case-insensitively, with the `.md` the server adds, for every path in a batch call.
- Hidden folders (`.claude`, `.git`, `.apiary`) and folders holding guarded files are never writable.
- Calls that change other notes (renaming a tag across the vault, moving with link updates) are always refused.

## Limits

The guard is a speed bump, not a sandbox, and the spec says so (section 12):

- A shell command is checked by pattern. A script the agent writes and then runs is invisible to the hook. The
  defence after the fact is `apiary validate --since <commit>`, which checks that nothing append-only changed.
- It protects only where it runs: in Claude Code, with the hook installed by `apiary init`.
- An agent with commit rights that sets out to cheat can be caught only afterwards, by a human or by a check it
  cannot edit, such as CI on a protected branch.

## Reproduce it

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m pytest -q tests/test_obsidian_guard.py tests/test_checkpoint.py   # the 101
python -m pytest -q tests/test_hook.py                                       # the rest of the guard
python demo/walkthrough.py                                                   # the guard refusing, live
```

The first test in `test_obsidian_guard.py` is the bypass itself. On 0.8.0 it fails. Here it passes.
