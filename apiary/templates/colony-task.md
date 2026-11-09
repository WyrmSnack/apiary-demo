---
name: colony-task
description: Turn what the human wants done into a colony task file that can be claimed and closed. Use when the human asks to add, create, write or plan a task for the colony, or says a task is malformed. Creates tasks only through the colony create_task tool, never by writing files in tasks/.
---

# Creating a colony task

A task is a contract: one outcome, one command that proves it, and the files it may change. The colony refuses
tasks that break the format, and a Forager cannot fix a task after the fact, so get it right here.
Tasks are the human's decisions. You draft; the human approves.

## 1. Pin down the outcome

Ask until you can write **one sentence saying what is true when the task is done** (the `objective`). Not the
activity ("research X") but the result ("a guide in docs/x/ that ..."). If the request is really several
outcomes, propose several tasks, each with its own check.

**Create the parts first, then the whole.** A task can never be edited after it is created, so it cannot gain a
dependency later. If the work splits into parts that run in parallel and a task that combines them, create the
parts, then create the combining task with `depends_on` naming their ids. The colony then refuses to let anyone
claim the whole before its parts are done.

## 2. Find the command that proves it (`acceptance`)

The acceptance line is **one command, run without a shell**, that exits 0 when the task is done and non-zero
otherwise. It never runs through cmd.exe or bash, so `&&`, `|`, `;`, `>`, `$VAR`, `%VAR%`, `*` and single quotes do
not work. Use double quotes.

- Code: a test. `python -m pytest -q tests/test_save_slots.py`. If the test does not exist yet, the task
  writes it, so list it under `writes`.
- Several steps: `npm --prefix app test` rather than `cd app && npm test`, or a script that does the steps.
- Writing, research or anything prose: **no existing command can judge it, so write a gate.** Pass `gate_code`
  (and leave `acceptance` empty): a Python script, standard library only, that exits 0 only when the
  deliverable meets checks a script can make. Examples: required files exist; each has a minimum length; each
  has a `## Sources` section with N links from at least 2 sites; required topics appear; no `TODO`. Print
  every problem before exiting 1. It is saved as a new `gates/check_NNN.py`, run with `gate_args`, and
  guarded from later edits.
- Be honest about what the check cannot judge (truth, quality), and say so in `why` so the human reads the work.

## 3. Bound it

- `writes`: the files or folders the task may change (`docs/guide/`, `engine/save.py, tests/test_save.py`).
- `reads`: TRACES keys or files to read first.
- `depends_on`: ids of tasks that must be done first.
- `out_of_scope`: what the Forager must not do. For anything near security, reverse engineering or other people's
  software, say what is off limits (no bypassing licence checks or DRM, no running tools against software you
  do not own).
- `why`: one or two sentences of intent, so a Forager with no memory of this conversation can make good calls.

## 4. Show the human, then create

**Show the human the draft** (every field, and the gate code if any) and ask for a yes. Then call the The guard refuses `create_task` until the human has replied, so a draft nobody saw cannot be created.
`create_task` tool with `caste` set to `Queen`. It refuses anything a claim or close would refuse and says
why; fix the draft and try again. Never write or edit files in `tasks/` or `gates/` yourself. The guard blocks
it, and the refusal is the answer.

Do not create a task in order to claim it yourself in the same breath. Creating work and grading it are
separate jobs.

## Example

> Human: Research the 'Reverse Engineer Anything' repo and write documentation on competing with Adobe.

- slug: `rea-competitive-guide`
- objective: A sourced guide in docs/rea-guide/ teaching a solo developer how tools like REA
  (https://github.com/morluto/rea) can help compete with subscription software such as Adobe, legally, with a
  plan they can act on.
- writes: `docs/rea-guide/`
- out_of_scope: Do not run REA against third-party software. Do not give steps to bypass DRM or licence checks.
- gate_code: a script checking six named chapters exist, at least 600 words each, a `## Sources` section with
  3+ links from 2+ sites in each, the legal chapter mentions DMCA 1201 and clean-room design, and the plan has
  12+ dated steps. gate_args: `docs/rea-guide`.
- why: Passing the gate is necessary, not sufficient: the human reads the guide before it counts.
