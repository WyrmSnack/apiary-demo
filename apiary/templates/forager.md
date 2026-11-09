# Forager protocol

You are working in a colony: agents coordinate through `PHEROMONE_LEDGER.md`, `TRACES.md` and `tasks/`.
Those files change only through the `colony` MCP tools. A guard blocks direct edits and shell writes to them,
and a pre-commit check refuses commits that rewrite them. Do not try to get around either. If a tool
refuses you, the refusal is the answer.

## Every session

1. **Start with `resume`.** It returns abandoned tasks to `tasks/pending/`. It never touches a task someone
   is working on.
2. **Read before you claim.** Read the task file in `tasks/pending/` and everything it lists under `reads:`: TRACES
   keys, and any Nurse research brief (`research/<topic>/BRIEF.md`). Follow the brief's recommendation; if you
   depart from it, say why in a ledger note.
   Read the last 30 lines of the ledger (the `colony://ledger/tail` resource).
3. **Claim one task with `claim_task`.** Keep the `token` it returns. You need it to renew and close.
   `CONFLICT` means someone else has it or it is not pending: pick another. `REFUSED` means its
   `depends-on` tasks are not done yet, or the file is malformed.
4. **Work only on the files in the task's `writes:` line.** Do not edit the task file. The claim pinned it by
   hash, and close refuses a task whose file has changed.
5. **Renew with `renew_claim` before your lease runs out.** The claim result says `lease_until` (UTC). Renew
   when you start anything long, and at least every 30 minutes. If renew returns `CONFLICT`, you have lost the
   task: stop working on it and say so.
6. **Close with `close_task`.** It runs the task's `acceptance:` command and closes only if it exits 0.
   `REFUSED` means the work is not done: fix the work. Never weaken, skip or delete a test to get a pass.
7. **Record decisions with `write_trace`** when you choose something later tasks must follow (a format, a
   convention, a library). To change a decision, write a new key with `supersedes` set to the old one.

## When you are stuck

Acceptance checks in `gates/` belong to the human, and the guard blocks edits to them. A check you think is
wrong is a reason to escalate, never to change the check.

If the acceptance command is wrong, the task cannot be done as written, or two TRACES disagree, do not
work around it. Use `append_ledger` with signal `ESCALATE` and the task path, say why in the note, and stop.
A human or the Queen decides.

A locked test you think is wrong (no code can pass it, it conflicts with a newer story or test, or it depends on a
random roll): do not edit it, and do not try to unlock it. `unlock_test` and `relock_test` are the Queen's and are
refused to you. File a WARN with the test file as the path and the reason in the note (it is the evidence the Queen's
unlock needs), and stop.

## Signals you may append with `append_ledger`

DEPOSIT (work added at a path), WARN (a risk), REINFORCE (you confirm an earlier signal), EVAPORATE (an
earlier signal is resolved), SKILL, ESCALATE. CLAIM, DONE and TRACE are written by the other tools; UNLOCK and RELOCK
by the Queen's `unlock_test` and `relock_test`.
