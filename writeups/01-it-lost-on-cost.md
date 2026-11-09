# I benchmarked my multi-agent framework, and it lost on cost

*Kevin Wilkins, November 2026. Every number below comes from [`measurements/MEASUREMENTS.md`](../measurements/MEASUREMENTS.md),
which a script generated from the run records. The plans, hypotheses and decision rules were committed before the first
run of each phase: [`PHASE6.md`](../measurements/method/PHASE6.md), [`PHASE7.md`](../measurements/method/PHASE7.md),
[`PHASE8.md`](../measurements/method/PHASE8.md).*

**In short:** a colony of agents coordinating through shared files cost 7.7 times what one plain session cost, for the
same score. Cutting the colony's overhead brought it down to about one session's cost, but never below it. If you're
building a multi-agent system, measure it against one agent working alone, and decide before the first run what result
would count as a win.

## The claim I set out to test

The design apiary started from (a textbook on stigmergic agent colonies) says a colony of agents that coordinate
through shared files, working in parallel lanes, beats one agent working alone on speed and cost. I built that design
as faithfully as I could, wrote down in advance what result would count as "clearly better", and measured it.

## Before and after, in one table

Median total tokens per build (input, cache and output), three runs per arm, Claude Opus, one Windows machine. Every
build was graded by hidden tests the agents never saw.

| Project | Plain session (one agent, no colony) | Colony as the textbook describes it (every task to a Forager subagent, several at once when ready) | Colony after my redesign (solo Queen, `create_plan`) |
|---|---|---|---|
| Small game, 8 modules, 38 hidden tests | **0.93M** tokens, 4.1 min, 38/38 | **7.19M** tokens (7.7x), 13.1 min, 38/38 | **0.90M** tokens (about the same as plain; 1.1x Phase 7's own plain runs), 4.0 min, 38/38 |
| Spreadsheet engine, 317 hidden tests | **3.09M** tokens, 13.6 min, 316/317 | **9.34M** tokens (3.0x), 22.9 min, 316/317 | **4.62M** tokens (1.5x), 13.5 min, 316/317 |

- **Before the redesign:** the textbook colony used 7.7 times plain's tokens and 3.2 times its time on the small
  project, for the same score. The pre-registered verdict was "parallel shows no clear saving over plain". Parallel
  lanes did not beat one Forager at a time either (7.19M against 5.43M).
- **After the redesign:** the same colony, with its planning overhead cut, used **87% fewer tokens** than before
  (7.19M to 0.90M) and was 3.3 times faster (13.1 to 4.0 minutes), with no loss of score. That moved it to roughly a
  plain session's cost. It still did not *beat* plain: the pre-registered verdict for solo against plain was "no clear
  saving".
- **On the bigger project**, nothing bought quality. Plain, solo and foragers all scored a median of 316 of 317. The
  colony cost 1.5 times (solo) to 3.0 times (foragers) plain's tokens.

So the claim lost. A colony did not make building cheaper or better on either project. The best I could do was make
its overhead small.

## What the redesign changed

From the transcripts of the Phase 6 runs:

1. **Planning was a conversation, not a call.** The Queen created tasks one at a time and re-read the ledger between
   them. `create_plan` takes the whole plan in one call and refuses it whole if any task is bad (overlapping write sets,
   unknown dependencies, a cycle).
2. **Every Forager paid a start-up tax.** Each subagent began with 55k to 60k tokens of context (Claude Code's full
   system prompt, every tool, and the project's CLAUDE.md, which loads the Queen's protocol too), and re-read it on
   every call. About a quarter of Forager calls did only colony bookkeeping.
3. **Solo mode.** When the plan has no work that can run at once, the Queen does the tasks herself (claim, work,
   close) instead of starting a Forager per task.

The Phase 9 follow-up (a dedicated Forager agent with a short protocol and only the tools it needs) cut a Forager's
first-call context from 55k to 60k tokens to about 14k in a probe run. **That probe is not counted**: the Phase 9 runs
that would measure it have not been done, so I make no claim about it yet.

## What I kept the colony for

If it does not save tokens, why keep it? Because of what it does that a plain session does not:

- **Every claim, refusal and close is a line in an append-only ledger.** You can see who did what, and what was refused
  and why. A plain session leaves a transcript at best.
- **A task closes only when its own check passes**, and the check is pinned by a hash at claim time, so an agent
  cannot rewrite it into one that passes (spec P-18; in a review of version 0.1.0 an agent did exactly that, and the
  close went through).
- **A guard hook stops agents editing the colony's files directly.** See
  [the guard write-up](03-the-guard-had-a-hole.md).
- **Work waits for the human where the plan says it should.**

I have **not measured** whether these are worth their cost to a team. That is the honest gap: the runs show the price
(1.1 to 1.5 times plain, as shipped), not the value.

## Limits

- Two projects, both **exactly specified**. A single session built both almost perfectly, so there was little room for
  any arm to score higher. Vaguer or much larger work is untested, and that is where a colony could still earn its
  keep.
- One machine (Windows 10), one model, three runs per arm.
- Output tokens are a lower bound for colony runs (some calls are logged before their reply finishes). Total tokens
  move by under 0.3%.
- Three hidden tests in the spreadsheet benchmark were corrected or removed after runs began, by a rule recorded in
  `PHASE8.md` before it was used. The spec the agents built from never changed.
- The raw run records hold private paths, so they are not in this repository. Each run's numbers are in the "Every run"
  table of `MEASUREMENTS.md`; the benchmark specs and hidden tests are in [`bench/`](../bench/).

## Reproduce it

You can grade your own build of either benchmark with the same hidden tests. Build `bench/skirmish/SPEC.md` (or
`bench/tally/SPEC.md`) in a folder of your own, with any agent setup you like, and keep the hidden tests out of that
folder. Then:

```bash
python -m pip install pytest
SKIRMISH_IMPL=<your build folder> python -m pytest -q bench/skirmish/hidden/tests   # 38 tests
TALLY_IMPL=<your build folder> python -m pytest -q bench/tally/hidden/tests         # 317 tests
```

`bench/*/hidden/reference/` is a build that passes every test. The token counts came from Claude Code's own
transcripts, read by `apiary/measure.py`.
