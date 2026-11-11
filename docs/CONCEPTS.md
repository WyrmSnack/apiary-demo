# Coordination mechanisms

Apiary's guarantees rest on nine mechanisms. Each is described in the same form: **the failure** it prevents, **the
mechanism**, **where it is** in the code, **the proof** (the tests, named after the spec requirements they check), and,
where one applies, **the limit**. None requires a database, a daemon or a network service. They consist of files, one
lock, and checks that run before anything is written.

Each mechanism is self-contained and can be adopted independently in other multi-agent systems.

| # | Mechanism | Prevents |
|---|---|---|
| 1 | [The folder is the status](#1-the-folder-is-the-status) | Two agents taking the same task |
| 2 | [Fencing tokens and leases](#2-fencing-tokens-and-leases) | A dead or stale session closing work it no longer owns |
| 3 | [The check closes the task, not the agent](#3-the-check-closes-the-task-not-the-agent) | Completion claimed without evidence |
| 4 | [The task is pinned at claim](#4-the-task-is-pinned-at-claim) | Rewriting the check so that it passes |
| 5 | [Acceptance is an argv, not a shell string](#5-acceptance-is-an-argv-not-a-shell-string) | A check that passes on one OS and fails on another |
| 6 | [Append-only ledger with reserved signals](#6-append-only-ledger-with-reserved-signals) | Forged history |
| 7 | [Whole plans or nothing](#7-whole-plans-or-nothing) | Parallel tasks that overwrite each other |
| 8 | [A guard hook in front of the agent](#8-a-guard-hook-in-front-of-the-agent) | Agents editing the shared files directly |
| 9 | [Human approval, enforced from the transcript](#9-human-approval-enforced-from-the-transcript) | Agents creating work before the human has reviewed it |

---

## 1. The folder is the status

**Failure.** Two agents read a "status: open" field at the same moment, both set it to "taken", and both do the work.
Any status kept *inside* a file requires a read followed by a write, and another process can act between the two.

**Mechanism.** A task's status is the folder that contains it: `tasks/pending/`, `tasks/active/` or `tasks/done/`.
Claiming is one `rename` from `pending/` to `active/`. The operating system performs a rename atomically, so when two
agents attempt it at once, one rename succeeds and the other finds the file absent. Every read-then-change step also
holds one advisory lock (`.colony.lock`). Operations move task files and never change their text.

**Where.** `Colony.claim` in [`apiary/colony.py`](../apiary/colony.py); the lock is a `filelock.FileLock` on
`.colony.lock`.

**Proof.** `test_P6_concurrent_claims_have_exactly_one_winner`,
`test_P1_no_change_while_another_process_holds_the_colony_lock`, `test_T6_operations_never_change_task_content`
([`conformance/test_conformance.py`](../conformance/test_conformance.py)).

## 2. Fencing tokens and leases

**Failure.** An agent claims a task, and its session then terminates or stalls. If the claim never expires, the work
is blocked. If another agent takes it over, the first agent may resume and close it with stale work.

**Mechanism.** A claim writes a `CLAIM` line with a fresh random **token** (16 hex digits) and a **lease** end time.
Renew and close require the *current* token. `resume` returns expired leases and orphaned tasks to `pending/`, and the
next claim receives a new token, so the old one is *fenced*: any caller presenting it is refused. This is the fencing
token pattern from distributed locking, applied to agents.

```
2026-11-09T05:54Z | Forager | CLAIM | tasks/active/001-fix-add.task | token=d384aaa6679667b4 lease_until=2026-11-09T06:54Z task_sha256=68de...
```

**Where.** `Colony.claim`, `Colony.renew`, `Colony.resume`; the current token is read back from the ledger by
`Colony.claim_state`.

**Proof.** `test_P8_renew_with_a_wrong_token_is_a_conflict`,
`test_P14_resume_returns_an_expired_lease_and_fences_the_old_token`, `test_P15_resume_leaves_a_live_claim_alone`.
Lease tests do not wait in real time: the `APIARY_CLOCK` environment variable sets the clock.

## 3. The check closes the task, not the agent

**Failure.** An agent reports that its work is complete. It may believe so, but nothing has verified it.

**Mechanism.** Every task has one `acceptance:` command, written when the task is created. `close_task` runs it in the
colony root. Exit 0 moves the task to `done/` with a `DONE` line. Any other result leaves the task active, writes a
`WARN` line with the reason, and returns the check's output to the agent. No lock is held while the check runs. After
the check, close re-acquires the lock and re-checks the token, because another agent may have taken the task in the
meantime.

**Where.** `Colony.close` in [`apiary/colony.py`](../apiary/colony.py).

**Proof.** `test_P12_failing_acceptance_warns_and_keeps_the_task_active`,
`test_P13_passing_acceptance_moves_to_done_with_one_done_line`,
`test_P11_close_rechecks_the_claim_after_acceptance_runs`,
`test_P9_close_requires_the_current_token_and_does_not_run_acceptance_without_it`.

## 4. The task is pinned at claim

**Failure.** The check fails, and the agent edits the task's `acceptance:` line to something that passes (`python
--version`). This failure has been observed in practice: it is the shortest path to a closed task, and agents directed
to finish will take it.

**Mechanism.** The `CLAIM` line records the SHA-256 of the task file. Close recomputes it and refuses, before running
anything, if it has changed. The remedy is to restore the task or escalate to a human. Separately, the guard hook
(mechanism 8) blocks direct edits to an active task.

**Where.** `Colony._require_unchanged` (called under the lock, both before and after the check runs);
`grammar.task_digest`.

**Proof.** `test_P18_claim_pins_the_task_file_by_hash`, `test_P18_editing_the_task_after_claiming_cannot_pass_the_gate`.
Step 5 of [`demo/walkthrough.py`](../demo/walkthrough.py) demonstrates it.

**Limit.** Only the task file is pinned, not the tests or script its check runs. An agent that weakens
`tests/test_calc.py` until it passes is not stopped by this mechanism. Two controls apply: place the check in `gates/`
(`apiary task new --gate`), a folder the guard covers, and run the same tests in CI, where agents cannot edit them.

## 5. Acceptance is an argv, not a shell string

**Failure.** `python -c 'exit(1)'` is a check that must fail. Under `cmd.exe`, single quotes do not group, so Python
receives the string `'exit(1)'`, evaluates it as an expression, and **exits 0**. A check whose result depends on the
operating system does not function as a check.

**Mechanism.** An acceptance line is split into an argument list by one small tokenizer that behaves identically on
every OS. Only double quotes group. A line containing, outside quotes, any character with meaning to some shell
(`' # | & ; < > ( ) $`, backtick, `% * ?`) is refused before anything runs. The program is resolved on `PATH` (a
missing program is refused), `python` means the Python 3.11+ that runs apiary, and the check must exit 0 within 600
seconds.

**Where.** `grammar.tokenize_acceptance` in [`apiary/grammar.py`](../apiary/grammar.py); `Colony._resolve_connector`.

**Proof.** `test_P10_A2_invalid_acceptance_is_refused_and_never_run`,
`test_A1_A4_acceptance_argv_is_exact_and_runs_in_the_colony_root`, `test_A3_python_means_python_311_or_later`.
[Write-up 02](../writeups/02-specification-conformance.md) shows the textbook design failing this requirement.

## 6. Append-only ledger with reserved signals

**Failure.** An agent appends `DONE` for a task it never closed, or rewrites an earlier line. A log that any writer
can fill with arbitrary content is not evidence.

**Mechanism.** `PHEROMONE_LEDGER.md` holds one line per event, `timestamp | caste | SIGNAL | path | note`, under a
strict grammar (a fixed set of signals and roles, relative paths, notes of at most 160 characters). Lines are never
changed or removed. A torn last line left by a crash is quarantined before the next append. `CLAIM` and `DONE`, and
the attributes `token=`, `lease_until=` and `task_sha256=`, can be written only by the protocol's own operations; the
general `append_ledger` tool refuses them. Decisions go to `TRACES.md`, where each key is written once and is later
replaced by a new entry that names it in `supersedes`, never by editing. `apiary validate` checks the whole colony
against the grammar.

**Where.** `grammar.parse_ledger_line`, `grammar.make_ledger_line`, `Colony.append_ledger`, `Colony.write_trace`,
[`apiary/validate.py`](../apiary/validate.py).

**Proof.** `test_L10_a_claim_cannot_be_forged_through_append`, `test_L10_done_and_reserved_attributes_are_refused`,
`test_L9_partial_last_line_is_quarantined_before_append`, `test_R3_a_key_is_written_once`; the shared grammar vectors
in [`spec/vectors/`](../spec/vectors/) (`tests/test_grammar_vectors.py`).

## 7. Whole plans or nothing

**Failure.** A planner creates five parallel tasks. Two of them write the same file, one depends on a task that does
not exist, and the problem surfaces only after three agents have spent tokens on it.

**Mechanism.** `create_plan` accepts the whole plan in one call: decisions, plus tasks with `writes:`, `depends-on:`
and `lane:`. It refuses all of it if any task is invalid, if two tasks that could run concurrently list the same file
in `writes:`, if a dependency is unknown, or if there is a cycle. `plan_board` returns the same verdict without
writing anything, together with a board (Mermaid) of the plan: who performs each task, and the longest run of agent
work before a human reviews it. `plan_status` reports which tasks can start now.

**Where.** `Colony.create_plan`, `Colony.task_refusals`, `Colony.plan_status`; [`apiary/board.py`](../apiary/board.py).

**Proof.** `test_O5_all_or_nothing`, `test_O3_two_tasks_that_can_run_at_once_never_write_the_same_file`,
`test_O3_overlap_is_allowed_when_one_task_waits_for_the_other`, `test_O4_plan_status_says_what_can_start_now`.

## 8. A guard hook in front of the agent

**Failure.** Mechanisms 1 to 7 hold only if agents use the tools. An agent that receives a refusal can instead open
the ledger in its editor.

**Mechanism.** Claude Code calls a `PreToolUse` hook before every tool call. Apiary's hook inspects the call and
refuses (exit code 2, with a reason the agent receives) any `Edit`, `Write` or `NotebookEdit` of a guarded file, and
any shell command that redirects into one, edits it in place, moves or deletes one, bypasses the commit gates with
`--no-verify`, or disables hooks. The guarded files are the ledger, `TRACES.md`, the task folders, the acceptance
gates and the colony's own settings. Each refusal names the colony tool to use instead, so that the agent can proceed
correctly rather than retry. The hook *fails closed*: input it cannot parse is refused. It also covers other MCP
servers that write files (a notes vault, for example), which may write only inside the folders the human has listed.

**Where.** `decide` in [`apiary/hook.py`](../apiary/hook.py) (one function, one entry point per tool kind).
`apiary init` installs it in `.claude/settings.json`.

**Proof.** [`tests/test_hook.py`](../tests/test_hook.py) (`test_shell_writes_to_guarded_files_are_blocked`,
`test_hook_fails_closed_on_input_it_cannot_read`, `test_disabling_hooks_from_the_shell_is_blocked`, and others);
[`tests/test_obsidian_guard.py`](../tests/test_obsidian_guard.py). [Write-up 03](../writeups/03-guard-bypass.md)
documents a bypass of the hook and the verification of its fix.

**Limit.** The hook guards against ordinary mistakes; it is not a sandbox. Shell commands are checked by pattern, so a
script the agent writes and then runs is not inspected, nor is a file name assembled from a variable
(`F=PHEROMONE_LEDGER; echo x >> $F.md`). It also guards only the colony's own files: a task's `writes:` line states
which project files the task may change, but nothing prevents an edit outside it. The after-the-fact control is the
pre-commit hook that `apiary init` installs, which runs `apiary validate --since HEAD` and refuses a commit that
changed any append-only line.

## 9. Human approval, enforced from the transcript

**Failure.** Instructed to present the plan and wait for approval, an agent presents the plan and creates the tasks
in the same turn. Measured: **2 of 3** solo runs did this.

**Mechanism.** Before `create_task` or `create_plan` runs, the hook reads the session's transcript and refuses unless
the human has replied since their first message. A task marked `by: Human` is a checkpoint: it closes only on the
human's own words, and its `DONE` line records `human approved`. An instruction in a prompt asks the agent to wait; a
hook makes waiting the only path that succeeds.

**Where.** `_check_approval` and `_check_checkpoint` in [`apiary/hook.py`](../apiary/hook.py).

**Proof.** [`tests/test_approval.py`](../tests/test_approval.py), [`tests/test_checkpoint.py`](../tests/test_checkpoint.py),
`test_K2_closing_a_checkpoint_records_that_the_human_approved`. After the hook was introduced (apiary 0.6.1), **6 of
6** colony runs requested approval first ([`measurements/`](../measurements/README.md)).

**Limit.** The hook verifies *that* the human replied, not *what* they said. A refusal unlocks it in the same way as an
approval, and one reply unlocks the remainder of the session. It guarantees that the human saw the plan before any
task existed. Interpreting consent from free text is a judgement, and that judgement remains with the agent and the
human.

---

## The common principle

Each mechanism moves a rule out of the prompt and into code that executes. A prompt says "do not edit the check"; the
hash pin makes editing the check ineffective. A prompt says "one agent per task"; the atomic rename enforces it. A
prompt says "wait for approval"; the hook refuses until the human has answered.

A rule enforced by the system is followed more reliably than a rule an agent is asked to observe.
