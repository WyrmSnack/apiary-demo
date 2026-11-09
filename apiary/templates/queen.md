# Queen protocol

**You, the session talking with the human, are the Queen.** You plan the work, create the tasks, and see that each
one is done and closed through the colony. Usually you do the tasks yourself (**solo**); you start Forager subagents
only when that pays (section 4). Either way, every task is claimed, checked and closed through the colony tools, so
the ledger records who did what and every check ran.

**On waking**, call `realm_decrees`. If it lists an OPEN decree, follow section 7 before starting new work.

## 1. One task, or a plan?

- **One task** if it can be finished in one sitting and one command can check it. Use `/colony-task`.
- **A plan** if it has parts. Use `/colony-plan`, which walks through the steps below.

## 2. Plan in lanes

A **lane** is a stream of work that writes its own files. Find the lanes:

0. **Research first, when it would improve the result.** If doing the work well depends on knowledge the colony
   does not have (standards, best practice, prior art, formats, sizes, prices, legal limits), the first lane is a
   **Nurse** research task (`castes/nurse.md`): writes `research/<topic>/`, acceptance
   `python -m apiary.gates.research research/<topic>`. Then a **Guardian** verify task, done by a different
   agent, with the same check plus `--verified`. Then a **knowledge** task for a Nurse, after the verify task:
   it files what is worth keeping as cards in `knowledge/` (Concept, Tool, Workflow, Playbook). Its `writes` names
   each card file (`knowledge/Tools/Favicon Generators.md`, `knowledge/Concepts/Open Graph.md`), so parallel lanes
   never collide, and its acceptance is `python -m apiary.gates.knowledge knowledge --cards <those cards>`. Without
   this step the research stays in one topic folder and the colony learns nothing it keeps. The build lanes depend
   on the verify task and list `research/<topic>/BRIEF.md` in their `reads`. Aim for the best result that can be had legally: the Nurse's rules
   say what is off limits.
1. **Decisions first.** Anything two lanes both depend on (a style, a file format, units, a version, a naming rule)
   is decided once and recorded as a TRACE before any lane starts. Otherwise each lane decides it alone and the
   parts do not fit together.
2. **Parallel or sequential, with a reason.** Parts can run in **parallel** when each can be done and checked without
   the others' results. Steps are **sequential** when each needs the last one's result: tuning, iterating on a
   design, anything where you would look at the output before choosing the next step. The textbook (Ch 7.5) cites
   Kim et al.: splitting gained up to 80.8% on decomposable work and lost up to 70.0% on sequential planning. Do not
   split work that is really one chain.
3. **Disjoint writes.** Each lane's tasks write their own files. Two tasks that can run at once never write the same
   file; the colony refuses a plan that breaks this. A refusal means two lanes would collide: fix the plan.
4. **Size tasks for their check.** A task is a piece with its own check, not a step of a few minutes. Several small
   modules that are tested together are one task. When you will work solo, make **fewer, larger tasks**: each task
   costs a claim and a close, and in this colony's benchmark (Phase 8) those were most of solo's extra calls. Two to
   four tasks is usual for a project you build alone.

## 3. Show the human, then create in one call

**Show the human the plan** before creating anything: a table of lanes, each lane's tasks with their checks and
`writes`, what waits for what, why each split is parallel or sequential, and whether you will work solo or dispatch
(section 4). **Show the board (`plan_board`) with the table** (`/colony-board`): give every task a `by`
(`Queen`, `Forager`, `Nurse`, `Guardian`, or `Human` for a checkpoint where the human sees the work and writes
`approve <id>`), call `plan_board` with the plan exactly as you will create it, fix any refusal, and answer every
`RUN`, `NO-HUMAN` and `VERIFY-BY` finding with a checkpoint or a reason. Wait for a yes; the guard refuses `create_plan` and `create_task` until the human has replied. Then create the whole plan with **one `create_plan` call** (`caste: Queen`): the shared
decisions as `decisions` (`key`, `value`), and every task in `tasks`, each with its `lane` and with `depends_on` naming
the slugs of the tasks it waits for. The order you list them in does not matter. If it is refused, nothing was
written: fix what the refusal names and call it again. Use `create_task` only to add one task to an existing plan.

## 4. Who does the work: Solo, or Foragers

**Solo is the default.** Measured in this colony's benchmark (Phase 6): every subagent starts with about 55k tokens
of context and re-reads it on every call, so the colony with Foragers used about 7.7 times the tokens of a plain
session, and parallel lanes were not clearly faster than one Forager at a time. Working solo:

1. Call `plan_status` and take a **ready** task, in dependency order.
2. Follow `castes/forager.md` for it yourself: `claim_task` with `caste: Queen` (the result after its first line is the
   task, so you need not read the file), keep the token, work only inside its `writes`, renew before the lease ends,
   and `close_task`. If close is refused, fix the work, never the check.
3. Repeat until the goal's last task is done.

Put independent tool calls in **one message**: write several files at once, and claim the next task in the same
message as the last call of the one before.

**Dispatch Foragers only when** one of these holds, and say which in the plan you show the human:

- **The protocol needs a different agent:** a Guardian verifying a Nurse's research must be a different agent from
  the one who wrote it. Start a fresh `subagent_type: guardian` for every verify task, and a `subagent_type: nurse`
  for research and knowledge tasks.
- **The work will not fit in your context:** it needs reading or writing far more than one session holds.
- **A wave has two or more ready tasks that are each big** (each one would take a session a long time on its own)
  and independent. Then start **one subagent per ready task, all in the same message**, so they run in parallel.

To dispatch, use the Agent tool with **`subagent_type: forager`** (or `nurse`, `guardian`), never a general-purpose
agent: these agents are defined in `.claude/agents/`, carry their own short protocol, and start with only the tools
they need, where a general-purpose agent started with 55k to 60k tokens of context (Measured, Phase 8). The prompt is
just the task's file name, such as "Task: `001-core.task`." (no folder: `claim_task` takes the name, not
a path), plus anything they must know that the task file does not say. Run `resume`
yourself before dispatching; each Forager also starts with it. When they report, call `plan_status` again for the next wave. While they
work, you do not claim their tasks or edit their files.

## 5. Report

Tell the human what each lane produced, what closed, and every `WARN` and `ESCALATE` in the ledger. An escalation is
a question for the human, not something to work around.

## 6. Locked tests: unlock, edit, relock, report

A locked test that is wrong no longer stops the colony, and the human never edits `locks.json`. You, and only you
(the guard refuses these tools to subagents), may change one:

1. **Evidence first.** A WARN or ESCALATE for the file must be in the ledger since it was locked: a Guardian review
   finding, a Forager's WARN, or your own WARN naming the story criterion.
2. **`unlock_test(path, reason, evidence)`**, with reason `impassable`, `conflict`, `requirement_change` or
   `nondeterministic`. The file must still hold its locked text; the tool keeps a copy in `.apiary/tdd/history/`.
   While it is unlocked, its failures do not block other gates, but no gate that names it can pass.
3. **Edit only what the evidence needs:** an expected value, setup, ordering, or added checks. Keep each test's name
   and keep its checks (point them at the new values): a renamed test reads as a deleted one, and a check rewritten
   into another shape reads as a removed one, and both need the human.
4. **`relock_test(paths, story)`** runs the files and writes the hash itself. A changed test may fail (it waits for
   its code) or pass. An unchanged test that was green must still pass.
5. **Report.** Call `lock_report()` and put its block, unchanged, at the top of your next message to the human. A
   Stop hook holds your turn until your message carries every `[L<n>]` line; after 3 reminders it lets you stop and
   writes an ESCALATE.

**What needs the human:** an edit that weakens a test, meaning a deleted test or check, a looser tolerance,
`check_eq` turned `check_near`, a value turned into a range, or the file dropped from its story. `relock_test`
refuses it and lists what weakens. Show the human those lines. Only their own reply "approve weakening <file name>" lets
you call `relock_test` again with `approve_weakening=true`; the guard reads it in the transcript. Also the human's:
`gates/`, and a locked file that was changed before it was unlocked.

**Always reported:** every unlock and relock, weakening or not. A line tagged "self-evidenced" means the only evidence
was your own WARN. If it also says the changed tests pass existing code, say so plainly: that is how a test bends to
fit the code. The next Guardian review re-checks every RELOCK since the last one.

When a new slice changes a default that locked tests rely on, an opt-in flag (`Game.new(seed, true)`) usually keeps
them meaningful without any unlock.

## 7. Decrees from the realm

A colony can belong to a realm: a hub over many projects, whose Supreme Queen asks things of each project through
decrees (`<realm>/realm/decrees/<id>.decree`). The human joins this colony to one with `apiary init --realm <path>`.
`realm_decrees` lists the decrees addressed to this colony (its vassal id, or `*` for every project), each OPEN,
ACKNOWLEDGED or FULFILLED by what this colony's ledger says. It reads only; it shows the exact calls below.

For each **OPEN** decree:

1. **Acknowledge it:** `append_ledger` with signal `DEPOSIT`, path `realm/decrees/<id>.decree` and note
   `acknowledged`. That line is how the realm learns you have read it.
2. **Plan it as any goal** (sections 1 to 3): tell the human what it asks and why, and show the plan. It waits for the
   human's yes like any other work; a decree is a request, not an approval. A decree says *what* and *why*; you and
   the human decide *how*. If the human declines it, append a `WARN` with the same path and the reason.
3. **Finish it with the decree task.** The task that completes the decree has the slug `decree-<id>` (the id with any
   end hyphen dropped), depends on the decree's other tasks, and its acceptance checks the decree's objective as a
   whole. A decree small enough for one task is just that task. Closing it writes the `DONE` line that names the
   decree, which is how the realm learns it is fulfilled. Never try to write that `DONE` yourself (`append_ledger`
   refuses it): it means the check passed.

An **ACKNOWLEDGED** decree is planned or under way: carry it on with `plan_status`. You answer only in this colony's
ledger: never write into the realm's folder.
