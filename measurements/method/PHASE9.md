# Phase 9: cut the Forager's start-up cost (pre-registered)

**This plan is committed before the first Phase 9 run. Its hypotheses, rules and exclusions do not change after data
exists.** Changes are recorded below as dated amendments.

Kevin, 2026-10-17: "adapt the colony the best you can to make it as efficient as possible from the findings, cut the
forager's start up costs, and then absorb the Digital-ToolBox". (The Toolbox is Phase 10.) He also said the colony needs
explicitly multi-agent benchmarks to be tested properly; that comes after Phase 10.

## Why (Measured, Phase 8)

On the spreadsheet benchmark the Foragers arm used a median of 9.34M tokens, 3.0 times a plain session, for the same
score. From the transcripts of foragers runs 2 and 3:

- Foragers account for about 85% of the arm's tokens (9.37M of 11.07M; 7.43M of 9.34M).
- Every Forager's first call already holds **55k to 60k tokens** of context, and every later call re-reads it. That is
  Claude Code's general-purpose agent: its full system prompt, every tool definition, and the project's `CLAUDE.md`,
  which loads the Queen's protocol too.
- **About a quarter of Forager calls do only colony bookkeeping** (28 of 119, 26 of 93: loading the colony tools,
  `resume`, `claim_task`, `close_task`, the hand-back; counted by `apiary.measure`), and reading the task file costs
  another call each.

The solo colony used 1.5 times plain's tokens; most of its extra calls are a claim and a close per task (6 tasks).

## The cuts

1. **A dedicated Forager agent** (`.claude/agents/forager.md`, installed by `apiary init`). *Sourced:* Claude Code's
   subagent docs (code.claude.com/docs/en/sub-agents, read 2026-10-17): a defined agent's body "is the subagent's
   system prompt", replacing the Claude Code system prompt; `tools` is an allowlist that can name `mcp__colony__*`;
   `omitClaudeMd: true` skips `CLAUDE.md`. The agent carries a short Forager protocol and only the tools a Forager
   needs. The same for the Nurse and the Guardian.
2. **Fewer bookkeeping calls:** a dispatched Forager does not call `resume` (the Queen already did), and `claim_task`
   returns the task file's text (spec 0.7.0, **P-19**), so the Forager does not read it separately.
3. **The Queen working solo makes fewer, larger tasks** (each task costs her a claim and a close), and both castes put
   independent calls in one message.

## Design

- **Project:** `bench/tally/SPEC.md` and the 317 hidden tests of Phase 8 (after its amendments), unchanged.
- **Arms:** `foragers` and `solo`, as in Phase 8, with the colony as it ships after this phase (apiary 0.7.x). No new
  plain runs: the plain arm does not change, and Phase 8's plain runs are shown beside, as a cross-phase reference.
- **One probe run first** (`foragers`, run 0), not counted: it checks that the Queen dispatches the new agent and that
  the agent has the colony tools. If it shows a defect, the defect is fixed and recorded as an amendment, and the
  probe is repeated. No probe counts toward a verdict.
- **Order:** foragers 4, solo 4, foragers 5, solo 5, foragers 6, solo 6 (numbers carry on from Phase 8 so folders do
  not clash). Same machine, model, prompt and human rule as Phase 8.

## Expectations, stated before the data

My prior (Claude's): a Forager's first call drops from 55k to 60k tokens to 10k to 25k; the Foragers arm drops 40% to
60% (to about 4M to 5.5M) and is clearly better than Phase 8's; solo drops 10% to 25% and is **not** clearly better
than Phase 8's (its ranges overlap); quality is unchanged.

## Decision rules

Same rule as before: A is clearly better than B only if A's worst run is better than B's best run.

1. **Did the cuts work for Foragers?** Phase 9 foragers against Phase 8 foragers on total tokens, with the guardrail
   that its median score is within 2 tests of Phase 8's. Also reported: minutes, median first-call context of a
   Forager, share of bookkeeping-only calls.
2. **For solo?** Phase 9 solo against Phase 8 solo, the same way.
3. Reported, not a verdict: each arm's median tokens and minutes as multiples of Phase 8 plain's.

## Exclusions

As Phases 6 to 8: contamination, a missing transcript, or a colony run not started in its own folder (amendment 1 of
Phase 6). An excluded run is replaced by a new run of the same arm. No run is excluded for its result.

## Exit gate

| Item | Passes when |
|---|---|
| (a) Spec 0.7.0 | P-19 (a claim returns the task's text) is in the spec, tested by conformance on the reference; the textbook-as-written server still fails; CI green. |
| (b) Agents | `apiary init` installs `forager`, `nurse` and `guardian` agent definitions; the guard protects them; `--update-protocols` brings older colonies up to date; the Queen's protocol dispatches them and works solo with fewer tasks (`tests/`). |
| (c) Runs | The probe shows the agent in use, then six runs, three per arm, graded, none excluded or each replaced. |
| (d) Published | `MEASUREMENTS.md` has a Phase 9 section from `bench/report.py` with both answers, and README and STATUS match them, whatever they are. |

## Amendments

**1. (2026-10-17, after the probe, before any counted run.)** The probe worked as designed: all six Foragers were the
new `forager` agent, each first call held about 14,000 tokens of context (Phase 8: 55,000 to 60,000), none called
`ToolSearch` or `resume`, and the run used 5.18M tokens (Phase 8's cheapest Foragers run: 8.12M). It found one defect:
the Queen's prompt named the task by its path (`tasks/pending/001-foundation.task`), so every Forager's first claim was
refused (T-1) and retried with the file name, one wasted call each. The Queen's protocol, `/colony-plan` and the three
agents now say the prompt carries the file name only, such as `001-core.task`, no folder (`tests/test_agents.py`). As
this plan says, the probe is repeated (`--probe 2`); neither probe counts.

**2. (2026-10-17, after probe 1, before any counted run.)** Kevin: "Give the foragers toolsearch and resume calls,
actually." The `forager` agent now has the `ToolSearch` tool (used only when a tool it needs is not loaded) and starts
each task with `resume` again, as the general-purpose Forager did. Measured on probe 1, a `resume` call re-reads about
14,000 tokens of context, so this adds roughly one such call per Forager. Cut 2 above now covers only the task text
that a claim returns. The decision rules do not change.

