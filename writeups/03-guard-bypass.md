# Write-up 03: An MCP bypass of the guard hook, and verification of the fix

*Kevin Wilkins, November 2026. The baseline numbers come from the run log of apiary 0.8.0 (private commit `2a07698`,
2026-10-19). Of the post-fix numbers, the 101 tests can be rerun from this repository (the commands are at the end).
The planted-bug run used a script in the full repository, which is not included here.*

**Summary.** A guard that enumerates the tools it checks admits every tool it does not enumerate. The defect was found
by code review before a new MCP server (a notes vault) was connected to the colony. The fix was developed test-first,
and the tests were then validated by planting bugs in the fix and confirming that the tests detected them.

## The guard

Apiary's agents may change the colony's shared files (the ledger, `TRACES.md`, the task folders, the acceptance
checks) only through the colony's own tools, which write lines that the protocol can verify. A Claude Code
`PreToolUse` hook (`apiary/hook.py`) enforces this. It inspects every edit, write and shell command before it runs,
and refuses any that would modify those files directly. [`demo/walkthrough.py`](../demo/walkthrough.py) shows it
refusing a `Write` to the ledger, an `Edit` to a claimed task and a shell redirect into the ledger, while permitting an
edit to the file the task is meant to change.

## The defect

An Obsidian MCP server was about to be connected, so that agents could read and write notes in the same folder as the
colony. A review of `hook.py` before connection showed that the guard inspected only Claude Code's own file and shell
tools. **A tool from any other MCP server was not inspected.** An `obsidian_put_content` call targeting
`PHEROMONE_LEDGER.md` could forge the ledger, and the guard would permit it.

## Results

| | Apiary 0.8.0 (before) | Apiary 0.9.0 (after, this repository) |
|---|---|---|
| `decide()` on an Obsidian write to the ledger | **allowed** | **refused** |
| Guard and checkpoint tests written for the fix | **42 failed, 16 could not start, 13 passed** (71) | **101 of 101 pass** (the 71, plus 30 added later in the same phase, most after the vault server's actual behaviour was verified) |
| Planted bugs in the new guard, board and checkpoint code detected by the tests | (no such code) | **30 of 30** |

Method for the baseline: the new tests were written first and run against 0.8.0 with none of the fix present (a
"red" run). They failed for the expected reasons: the bypass was permitted, and the new `by:` checkpoint field was
unknown. The fix was then written until they passed.

Method for the planted-bug figure: a script introduced one bug at a time into the new code (for example, "every
Obsidian tool counts as a read", "case is not ignored in paths", "`rename_tag` is allowed"), ran the tests, and
restored the file. **Two bugs were initially missed**: an escape from the vault when the whole vault was listed as
writable, and a folder containing guarded templates. Each received a new test, and the rerun detected all 30.

## The fix

- Every tool of a vault server that is not known to be read-only is treated as a write, and is refused outside the
  folders the human listed in `.apiary/mcp-guard.json`.
- Paths are compared case-insensitively, including the `.md` suffix the server appends, for every path in a batch
  call.
- Hidden folders (`.claude`, `.git`, `.apiary`) and folders containing guarded files are never writable.
- Calls that modify other notes (renaming a tag across the vault, moving a note with link updates) are always refused.

## Limits

The guard is a safeguard against ordinary mistakes, not a sandbox, and the specification states this (section 12):

- Shell commands are checked by pattern. A script the agent writes and then runs is not visible to the hook, nor is a
  file name assembled from a variable (`F=PHEROMONE_LEDGER; echo x >> $F.md`). The after-the-fact control is
  `apiary validate --since <commit>`, which verifies that nothing append-only has changed. `apiary init` installs it
  as a pre-commit hook.
- It protects only where it runs: in Claude Code, with the hook installed by `apiary init`.
- An agent with commit rights that deliberately circumvents the rules can be detected only afterwards, by a human or
  by a check it cannot edit, such as CI on a protected branch.

## Reproduction

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m pytest -q tests/test_obsidian_guard.py tests/test_checkpoint.py   # the 101
python -m pytest -q tests/test_hook.py                                       # the rest of the guard
python demo/walkthrough.py                                                   # the guard refusing, live
```

The first test in `test_obsidian_guard.py` reproduces the bypass. It fails on 0.8.0 and passes here.
