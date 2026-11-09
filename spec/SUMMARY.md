# Colony Substrate Specification 0.9.0: summary

© 2026 Kevin (WyrmSnack). Licensed under [CC BY-SA 4.0](LICENSE). You may implement the specification in software
under any license.

This is a summary. The full text (595 lines, with every requirement's exact wording) is not in this repository. The
conformance suite in [`../conformance/`](../conformance/README.md) and the test vectors in [`vectors/`](vectors/) are
here in full, and they are what decide whether an implementation conforms. Each test is named after the requirement
IDs it checks (for example `test_P10_A2_...` checks P-10 and A-2).

## What it covers

The files coding agents use to coordinate, the grammar of each, and the operations that change them, over MCP stdio.
It does not cover how agents are prompted.

## The files

| Path | What | Written by |
|---|---|---|
| `PHEROMONE_LEDGER.md` | append-only log, one line per event | the operations only |
| `TRACES.md` | append-only decision log: `## KEY:` entries, superseded rather than edited | the operations only |
| `tasks/pending/`, `tasks/active/`, `tasks/done/` | one task file per task; **the folder is the status** | the operations only |
| `.colony.lock` | an OS advisory lock | the operations only |

Files are UTF-8 without a BOM, with LF line ends. Readers accept CRLF, and report (never guess) UTF-16, a BOM or
invalid UTF-8. **(E-1 to E-3)**

## The ledger (L-1 to L-11)

One line per event: `timestamp | caste | SIGNAL | path | note`, for example

```
2026-11-09T05:54Z | Forager | CLAIM | tasks/active/001-fix-add.task | token=d384aaa6679667b4 lease_until=2026-11-09T06:54Z task_sha256=68de...
```

Eleven signals (`DEPOSIT`, `REINFORCE`, `EVAPORATE`, `WARN`, `CLAIM`, `DONE`, `SKILL`, `TRACE`, `ESCALATE`, and
`UNLOCK` and `RELOCK` for locked tests), a fixed set of castes, relative paths only, notes up to 160 characters. Lines are never changed or removed; a partial last line is moved to a
quarantine file. `CLAIM` and `DONE` can be written only by claim and close, never through the general append tool
**(L-10)**.

## Task files (T-1 to T-6)

`NNN-slug.task`, with fields such as `objective:`, `acceptance:` (one command), `writes:` (the files the task may
change), `depends-on:`, `lane:` and `by:` (who does it; `Human` makes it a checkpoint). Operations move a task file
between folders and never change its text.

## The protocol (P-1 to P-19)

- **Lock.** Every read-then-change step holds `.colony.lock`. No lock is held while a check runs.
- **Claim** moves the task from `pending/` to `active/` with one atomic rename, and writes a `CLAIM` line with a fresh
  16-hex-digit **token**, a **lease** end, and the SHA-256 of the task file. Of two simultaneous claims, exactly one
  wins. A task whose dependencies are not done is refused. The result carries the task's text.
- **Renew** extends the lease, only with the current token.
- **Close** needs the current token. It refuses if the task file changed since the claim **(P-18)**, runs the
  acceptance check outside the lock, re-checks the token under the lock, and then either moves the task to `done/`
  with a `DONE` line (check exited 0) or leaves it active with a `WARN` line saying why.
- **Resume** returns orphans and expired leases to `pending/`. It never takes a task whose lease is live.
- A test clock (`APIARY_CLOCK`) exists so leases can be tested without waiting.

## Acceptance commands (A-1 to A-5)

An acceptance line is an argv, not a shell string. Only double quotes group, the same way on Windows and POSIX, and
a line holding any character that means something to some shell (`' # | & ; < > ( ) $` and backtick, `% * ?`) outside
quotes is refused before anything runs. A missing program is refused, `python` means a Python 3.11 or later chosen by
the implementation, the command runs in the colony root, and it passes only by exiting 0 within 600 seconds. This is
the textbook departure with the most practical effect: under `cmd.exe`, the check `python -c 'exit(1)'`, which must
fail, exits 0.

## Tools over MCP (M-1 to M-4)

`claim_task`, `renew_claim`, `close_task`, `resume`, `append_ledger`, `write_trace`, `create_task`, `create_plan`,
`plan_status`, `plan_board`, `run_connector`. Each returns one text result whose first word is a status (`CLAIMED`,
`DONE`, `REFUSED`, `CONFLICT` and so on); no input may cause an unhandled error. The colony root is `COLONY_ROOT`.

## Planning, connectors and checkpoints

- **`create_plan`** takes a whole plan in one call and refuses it whole if any task is invalid, two tasks that can run
  at once share a write, a dependency is unknown, or there is a cycle. **`plan_board`** shows what `create_plan`
  would say without writing anything. **(O-3 to O-5, B-1)**
- **Connectors** let a task run an outside program and leave a run record with the program's version and hashes of
  what it wrote. A run that exits 0 but prints a known error is not OK. **(C-1 to C-6)**
- **Checkpoints:** a `by: Human` task closes only on the human's own words, where a guard can read them. **(K-1, K-2)**

## What it does not protect against

Tokens are not credentials: they are in the ledger, which every agent reads. They protect against mistakes and stale
sessions, not against an agent that sets out to cheat and can write the repository. Such an agent can edit files
directly; a guard hook is a speed bump, and the defence after the fact is checking the ledger's history against the last
commit. The full text lists each attack and what notices it.
