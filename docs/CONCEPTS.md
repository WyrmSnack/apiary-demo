# How apiary keeps coding agents honest

Nine mechanisms, each written up the same way: **the failure** it prevents, **the mechanism**, **where it is** in the
code, **the proof** (the tests, named after the spec requirements they check), and, where there is one, **the limit**. None of them needs a database, a
daemon or a network service. They're files, one lock, and checks that run before anything is written.

You can borrow any of these for your own multi-agent system. Each one stands on its own.

| # | Mechanism | Prevents |
|---|---|---|
| 1 | [The folder is the status](#1-the-folder-is-the-status) | Two agents taking the same task |
| 2 | [Fencing tokens and leases](#2-fencing-tokens-and-leases) | A dead or stale session closing work it no longer owns |
| 3 | [The check closes the task, not the agent](#3-the-check-closes-the-task-not-the-agent) | "Done" without evidence |
| 4 | [The task is pinned at claim](#4-the-task-is-pinned-at-claim) | Rewriting the check so it passes |
| 5 | [Acceptance is an argv, not a shell string](#5-acceptance-is-an-argv-not-a-shell-string) | A check that passes on one OS and fails on another |
| 6 | [Append-only ledger with reserved signals](#6-append-only-ledger-with-reserved-signals) | Forged history |
| 7 | [Whole plans or nothing](#7-whole-plans-or-nothing) | Parallel tasks that overwrite each other |
| 8 | [A guard hook in front of the agent](#8-a-guard-hook-in-front-of-the-agent) | Agents editing the shared files directly |
| 9 | [Wait for the human, enforced from the transcript](#9-wait-for-the-human-enforced-from-the-transcript) | Agents creating work before the human has seen it |

---

## 1. The folder is the status

**Failure.** Two agents read a "status: open" field at the same moment, both set it to "taken", and both do the work.
Any status kept *inside* a file needs a read, then a write, and something else can happen between the two.

**Mechanism.** A task's status is the folder it sits in: `tasks/pending/`, `tasks/active/` or `tasks/done/`. Claiming
is one `rename` from `pending/` to `active/`. The operating system makes a rename atomic, so if two agents try at
once, one rename succeeds and the other finds the file gone. Every read-then-change step also holds one advisory lock
(`.colony.lock`). Operations move task files and never change their text.

**Where.** `Colony.claim` in [`apiary/colony.py`](../apiary/colony.py); the lock is a `filelock.FileLock` on
`.colony.lock`.

**Proof.** `test_P6_concurrent_claims_have_exactly_one_winner`,
`test_P1_no_change_while_another_process_holds_the_colony_lock`, `test_T6_operations_never_change_task_content`
([`conformance/test_conformance.py`](../conformance/test_conformance.py)).

## 2. Fencing tokens and leases

**Failure.** An agent claims a task, then its session dies or stalls. If the claim lasts forever, the work is stuck. If
another agent takes it over, the first agent may wake up and close it with stale work.

**Mechanism.** A claim writes a `CLAIM` line with a fresh random **token** (16 hex digits) and a **lease** end time.
Renew and close require the *current* token. `resume` returns expired leases and orphaned tasks to `pending/`, and the
next claim gets a new token, so the old one is *fenced*: anything holding it is refused. This is the fencing token
pattern from distributed locking, applied to agents.

```
2026-11-09T05:54Z | Forager | CLAIM | tasks/active/001-fix-add.task | token=d384aaa6679667b4 lease_until=2026-11-09T06:54Z task_sha256=68de...
```

**Where.** `Colony.claim`, `Colony.renew`, `Colony.resume`; the current token is read back from the ledger by
`Colony.claim_state`.

**Proof.** `test_P8_renew_with_a_wrong_token_is_a_conflict`,
`test_P14_resume_returns_an_expired_lease_and_fences_the_old_token`, `test_P15_resume_leaves_a_live_claim_alone`.
Lease tests don't wait in real time: the `APIARY_CLOCK` environment variable sets the clock.

## 3. The check closes the task, not the agent

**Failure.** An agent says it's done. It may believe so, but nothing checked.

**Mechanism.** Every task has one `acceptance:` command, written when the task is created. `close_task` runs it in the
colony root. Exit 0 moves the task to `done/` with a `DONE` line. Anything else leaves it active, writes a `WARN`
line with the reason, and returns the check's output to the agent. Nothing is held locked while the check runs. After
the check, close re-takes the lock and re-checks the token, because another agent may have taken the task in the
meantime.

**Where.** `Colony.close` in [`apiary/colony.py`](../apiary/colony.py).

**Proof.** `test_P12_failing_acceptance_warns_and_keeps_the_task_active`,
`test_P13_passing_acceptance_moves_to_done_with_one_done_line`,
`test_P11_close_rechecks_the_claim_after_acceptance_runs`,
`test_P9_close_requires_the_current_token_and_does_not_run_acceptance_without_it`.

## 4. The task is pinned at claim

**Failure.** The check fails, so the agent edits the task's `acceptance:` line to something that passes (`python
--version`). This isn't hypothetical. It's the easiest way to get to "done", and agents under pressure to finish find
it.

**Mechanism.** The `CLAIM` line records the SHA-256 of the task file. Close recomputes it and refuses if it changed,
before running anything. The fix is to restore the task, or escalate to a human. Separately, the guard hook (8) blocks
direct edits to an active task.

**Where.** `Colony._require_unchanged` (called under the lock, both before and after the check runs);
`grammar.task_digest`.

**Proof.** `test_P18_claim_pins_the_task_file_by_hash`, `test_P18_editing_the_task_after_claiming_cannot_pass_the_gate`.
Step 5 of [`demo/walkthrough.py`](../demo/walkthrough.py) shows it.

**Limit.** Only the task file is pinned, not the tests or script its check runs. An agent that weakens
`tests/test_calc.py` until it passes isn't stopped here. Two defences: put the check in `gates/` (`apiary task new
--gate`), a folder the guard covers, and run the same tests in CI where agents can't edit them.

## 5. Acceptance is an argv, not a shell string

**Failure.** `python -c 'exit(1)'` is a check that must fail. Under `cmd.exe`, single quotes don't group, so Python gets
the string `'exit(1)'`, evaluates it as an expression, and **exits 0**. A check that passes on Windows and fails on
Linux (or the reverse) isn't a check.

**Mechanism.** An acceptance line is split into an argument list by one small tokenizer that behaves the same on every
OS. Only double quotes group. A line containing any character that means something to some shell (`' # | & ; < > ( )
$`, backtick, `% * ?`) outside quotes is refused before anything runs. The program is looked up on `PATH` (a missing
one is refused), `python` means the Python 3.11+ that runs apiary, and the check must exit 0 within 600 seconds.

**Where.** `grammar.tokenize_acceptance` in [`apiary/grammar.py`](../apiary/grammar.py); `Colony._resolve_connector`.

**Proof.** `test_P10_A2_invalid_acceptance_is_refused_and_never_run`,
`test_A1_A4_acceptance_argv_is_exact_and_runs_in_the_colony_root`, `test_A3_python_means_python_311_or_later`.
[Write-up 02](../writeups/02-the-textbook-design-fails-its-own-spec.md) shows the textbook design failing this.

## 6. Append-only ledger with reserved signals

**Failure.** An agent appends `DONE` for a task it never closed, or rewrites an old line. A log any writer can fill
with anything isn't evidence.

**Mechanism.** `PHEROMONE_LEDGER.md` takes one line per event, `timestamp | caste | SIGNAL | path | note`, with a
strict grammar (a fixed set of signals and roles, relative paths, notes up to 160 characters). Lines are never changed
or removed. A torn last line from a crash is quarantined before the next append. `CLAIM` and `DONE`, and the
attributes `token=`, `lease_until=` and `task_sha256=`, can be written only by the protocol's own operations. The general `append_ledger` tool
refuses them. Decisions go to `TRACES.md`, where a key is written once and later replaced by a new entry that names it
in `supersedes`, never by editing. `apiary validate` checks the whole colony against the grammar.

**Where.** `grammar.parse_ledger_line`, `grammar.make_ledger_line`, `Colony.append_ledger`, `Colony.write_trace`,
[`apiary/validate.py`](../apiary/validate.py).

**Proof.** `test_L10_a_claim_cannot_be_forged_through_append`, `test_L10_done_and_reserved_attributes_are_refused`,
`test_L9_partial_last_line_is_quarantined_before_append`, `test_R3_a_key_is_written_once`; the shared grammar vectors
in [`spec/vectors/`](../spec/vectors/) (`tests/test_grammar_vectors.py`).

## 7. Whole plans or nothing

**Failure.** A planner creates five parallel tasks. Two of them write the same file, one depends on a task that
doesn't exist, and the problem only shows up after three agents have spent tokens on it.

**Mechanism.** `create_plan` takes the whole plan in one call: decisions plus tasks with `writes:`, `depends-on:` and
`lane:`. It refuses all of it if any task is invalid, two tasks that could run at the same time list the same file in
`writes:`, a dependency is unknown, or there's a cycle. `plan_board` returns the same verdict without writing anything,
along with a board (Mermaid) of the plan: who does each task, and the longest run of agent work before a human sees
it. `plan_status` says what can start now.

**Where.** `Colony.create_plan`, `Colony.task_refusals`, `Colony.plan_status`; [`apiary/board.py`](../apiary/board.py).

**Proof.** `test_O5_all_or_nothing`, `test_O3_two_tasks_that_can_run_at_once_never_write_the_same_file`,
`test_O3_overlap_is_allowed_when_one_task_waits_for_the_other`, `test_O4_plan_status_says_what_can_start_now`.

## 8. A guard hook in front of the agent

**Failure.** Mechanisms 1 to 7 only hold if agents go through the tools. An agent that hits a refusal can open the
ledger in its editor instead.

**Mechanism.** Claude Code calls a `PreToolUse` hook before every tool call. Apiary's hook reads the call and refuses
(exit code 2, with a reason the agent sees) any `Edit`, `Write` or `NotebookEdit` of a guarded file, and any shell
command that redirects into one, edits it in place, moves or deletes one, skips the commit gates with `--no-verify`,
or turns hooks off. The guarded files are the ledger,
`TRACES.md`, the task folders, the acceptance gates and the colony's own settings. Each refusal names the colony tool
to use instead, so the agent recovers instead of retrying. The hook *fails closed*: input it can't read is refused.
It also covers other MCP servers that write files (a notes vault, for example). They may write only inside the folders
the human listed.

**Where.** `decide` in [`apiary/hook.py`](../apiary/hook.py) (one function, one entry point per tool kind).
`apiary init` installs it in `.claude/settings.json`.

**Proof.** [`tests/test_hook.py`](../tests/test_hook.py) (`test_shell_writes_to_guarded_files_are_blocked`,
`test_hook_fails_closed_on_input_it_cannot_read`, `test_disabling_hooks_from_the_shell_is_blocked`, and more);
[`tests/test_obsidian_guard.py`](../tests/test_obsidian_guard.py). [Write-up 03](../writeups/03-the-guard-had-a-hole.md)
is the story of a hole in it and how the fix was proven.

**Limit.** It's a speed bump, not a sandbox. Shell commands are checked by pattern, so a script the agent writes and
then runs isn't inspected, and neither is a file name built from a variable (`F=PHEROMONE_LEDGER; echo x >> $F.md`).
It also guards only the colony's own files: a task's `writes:` line says which project files the task may change, but
nothing stops an edit outside it. The defence afterwards is the pre-commit hook `apiary init` installs, which runs
`apiary validate --since HEAD` and refuses a commit that changed any append-only line.

## 9. Wait for the human, enforced from the transcript

**Failure.** Told to "show the plan and wait for approval", an agent shows the plan and creates the tasks in the same
turn. Measured: **2 of 3** solo runs did this.

**Mechanism.** Before `create_task` or `create_plan` runs, the hook reads the session's transcript and refuses unless
the human has replied since their first message. A task marked `by: Human` is a checkpoint. It closes only on the
human's own words, and its `DONE` line records `human approved`. A rule written in a prompt asks the agent to wait.
A hook makes waiting the only thing that works.

**Where.** `_check_approval` and `_check_checkpoint` in [`apiary/hook.py`](../apiary/hook.py).

**Proof.** [`tests/test_approval.py`](../tests/test_approval.py), [`tests/test_checkpoint.py`](../tests/test_checkpoint.py),
`test_K2_closing_a_checkpoint_records_that_the_human_approved`. After the hook (apiary 0.6.1), **6 of 6** colony runs
asked first ([`measurements/`](../measurements/README.md)).

**Limit.** The hook checks *that* the human replied, not *what* they said. A "no" unlocks it just as a "yes" does,
and one reply unlocks the rest of the session. What it guarantees is that the human saw the plan before any task
existed. Reading consent from free text is a judgement, and that stays with the agent and the human.

---

## The pattern underneath

Each mechanism moves a rule out of the prompt and into something that runs. A prompt says "don't edit the check".
The hash pin makes editing the check useless. A prompt says "only one agent per task". The rename makes it so. A
prompt says "wait for approval". The hook refuses until the human has answered.

Agents follow rules they can't break more reliably than rules they're asked to keep.
