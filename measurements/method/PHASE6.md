# Phase 6: the measurement (pre-registered)

**This plan was committed before the first run. Its hypotheses, rules and exclusions do not change after data exists.**
If a rule turns out to be wrong, the change is recorded below as an amendment with its date and reason, and the
report shows results under both the original and the amended rule.

Kevin, 2026-10-16: 3 runs per arm, 9 runs; the project is a small game tested by hidden tests.
`docs/PROBLEM_STATEMENT.md` committed to publishing the result whatever it is: "If Phase 4 shows no token or time
saving over a plain single session, the SDK's value shrinks to auditability ... Decide now that this result gets
published if it comes."

## The two questions

1. **Is the colony worth it?** Textbook Ch 3.5: the same project built by a plain Claude Code session and by the full
   colony. Compare billable tokens, as Cairn did.
2. **Does parallelism help?** Textbook Ch 11.6: the same project with one Forager at a time and with parallel lanes.
   Record wall-clock time, tokens, first-try acceptance passes and integration defects. "Run each condition three
   times. One run of each is an anecdote."

## Design

- **Project:** `bench/skirmish/SPEC.md`, a turn-based tactics game core in 8 modules. Graded by **38 hidden tests**
  (30 unit, 8 integration through the command line) that no run can see. A reference implementation passes all 38,
  and three deliberate bugs are each caught, so the suite tests something.
- **Arms** (`bench/setup_arm.py`): `plain` (SPEC.md and a 3-line CLAUDE.md, no colony); `serial` (a colony whose Queen
  dispatches one Forager at a time); `parallel` (the colony as it ships, apiary 0.5.x).
- **Same everywhere:** the same machine, the same model (whatever Claude Code uses; the transcripts record it), the
  same prompt, "Build the project described in SPEC.md.", and the same human rule: answer questions with the
  recommended option, approve plans, give no other instructions.
- **Order:** interleaved, so time of day and service load fall on every arm alike: plain 1, serial 1, parallel 1,
  plain 2, serial 2, parallel 2, plain 3, serial 3, parallel 3.
- **Measured from the transcripts** (`apiary.measure`): every model call counted once, across the session and its
  subagents. Tokens are reported by category; "total tokens" is input + cache writes + cache reads + output.
  Wall-clock time runs from the first to the last transcript entry. Interventions are human messages after the
  first.
- **Graded** by `bench/grade.py`: hidden tests (unit and integration separately), the colony ledger (tasks closed,
  first-try closes, refusals, escalations, claims that overlapped in time), and a contamination scan of every tool
  call for the hidden tests' paths.

## Expectations, stated before the data

My prior (Claude's): the colony uses **more** tokens than a plain session, because of protocol overhead and subagents
re-reading context; parallel lanes finish **sooner** in wall-clock time than serial; quality is about the same in all
three arms. Cairn measured a 54% input-token saving for its design; this colony is different enough that I do not expect
to reproduce it. These are guesses, written down so that being wrong is visible.

## Decision rules

- With three runs, there are no significance tests. **Arm A is clearly better than arm B on a metric only if A's worst
  run is better than B's best run** (their ranges do not overlap). Otherwise the result is "no clear difference".
- **Quality guardrail:** a saving counts only if A's median hidden-test score is within 2 tests of B's.
- **Verdict for question 1:** if the parallel colony is not clearly better than the plain session on tokens or on time
  (with the guardrail met), the result is **"no clear saving"**, and README, STATUS and PROBLEM_STATEMENT say that the
  SDK's value is auditability and enforcement, not efficiency.
- Integration defects (integration tests failing in a run whose unit tests mostly pass) and first-try closes are
  reported, not used for the verdict.

## Exclusions

A run is excluded only if (a) the contamination scan finds a read of the hidden tests, or (b) no transcript exists. An
excluded run is listed with its reason and **replaced by a new run of the same arm**. No run is excluded for its result.

## Amendments

**1. (2026-10-16, after plain run 1, before any colony run.)** Plain run 1 was started one folder up, in
`skirmish-bench`, then worked in `skirmish-plain-1`. It read the arm's `SPEC.md` and `CLAUDE.md` itself, so it ran
under the plain arm's conditions and is kept, with the deviation recorded (decided from the process, before its score
was seen). A **colony** run started outside its run folder would have no colony tools, guard or Queen protocol, so it
would not be a colony run: such a run is **excluded and redone**. `bench/report.py` applies this; the grader records
the deviation.

**2. (2026-10-16, after serial run 1, before any parallel run.)** `apiary.measure` counted each model call from its
first transcript line. Claude Code can write that line while the reply is still streaming, with a partial
`output_tokens` (one Forager call that wrote a 5.9 KB file logged 4). Measured: plain run 1 is unaffected (25,403 either
way); serial run 1's output was undercounted, 15,819 instead of 30,262 (total 5,393,399 instead of 5,407,842). Fix:
keep the largest count logged for each call (`tests/test_measure.py`, RED then GREEN in `evidence/`). Both runs were
regraded. Known limit: 13 calls in serial run 1 still log under 50 output tokens while writing over 1,000 characters,
so **output tokens are a lower bound** for colony runs. Total tokens (the verdict's metric) move by under 0.3%, since
input and cache counts are the same on every line. Also noted: a colony run asks the human to approve its plan, so it
records 1 intervention where a plain run records 0; interventions are reported, not used for the verdict.

**3. (2026-10-16, after all nine runs; affects no verdict.)** Interventions counted only typed messages. In parallel
run 3 Kevin approved the plan in Claude Code's question dialog, which returns a tool result, so the count said 0 and
STATUS wrongly said the run skipped approval. `apiary.measure` now also counts answers to `AskUserQuestion`
(`question_answers`; `tests/test_measure.py`). All nine runs were regraded: every colony run records 1 intervention
(the plan approval), every plain run 0. Tokens and times are unchanged.

## Exit gate

| Item | Passes when |
|---|---|
| (a) Instruments | `apiary.measure`, `bench/grade.py` and `bench/report.py` work: tests, a dry run grading the reference at 38 of 38, and a contamination scan that flags a planted read. |
| (b) Nine runs | Three per arm, graded, none excluded or each exclusion replaced. |
| (c) Published | `MEASUREMENTS.md` generated by `bench/report.py`, with every run, and README/STATUS updated to match the verdict, whatever it is. |
