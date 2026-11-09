# The design I started from fails the spec I wrote for it

*Kevin Wilkins, November 2026. Every number here comes from running the conformance suite in this repository; the
command to rerun it is at the end.*

**Nobody outside this project uses apiary or its spec.** This is a measurement of my own code against my own
specification, which I wrote before building the reference implementation and changed only by recorded amendments.

## What is being compared

- **Before:** `conformance/naive_server.py`, the colony design from the textbook I started from, implemented as
  written: claim is a file rename, close runs the task's `acceptance:` line in a shell, resume sends every active task
  that fails its check back to pending. It has no tokens, leases or locks, because the textbook defines none.
- **After:** the reference implementation in `apiary/`, built to the Colony Substrate Specification
  ([summary](../spec/SUMMARY.md)).

The conformance suite (`conformance/`) imports nothing from either. It starts each one as an MCP stdio server, calls
its tools against a temporary colony, and inspects the files left on disk. Each test is named after the requirements
it checks.

## Before and after

Spec 0.9.0, Windows, Python 3.14:

| | Requirements passed | Results passed |
|---|---|---|
| Textbook design, as written | **8 of 49** | 63 of 254 |
| Reference implementation | **49 of 49** | 254 of 254 |

The 49 include 11 requirements for features the textbook never had (connectors to outside programs, the plan board,
human checkpoints, `plan_status`, P-19's claim text). Leaving those out, so the textbook is judged only on what it does
describe, it passes **8 of 38**.

## What the failures mean in practice

Each of these is a way a colony built from the textbook loses or fakes work. Each has a test in `conformance/`.

| Requirement | What goes wrong in the textbook design |
|---|---|
| **A-2**, acceptance commands | The check runs in a shell, and shells disagree. Under `cmd.exe`, the check `python -c 'exit(1)'`, which must fail, exits 0, so the task closes as passed. `;`, `&`, redirects and `$(...)` all run. The spec runs an argv with no shell and refuses shell syntax before running anything. |
| **P-14**, resume | Resume sends *every* active task whose check fails back to pending, including tasks another agent is working on right now. That is live work taken away. The spec resumes only orphans and expired leases. |
| **P-1, P-5, P-8**, locks, tokens, leases | Two agents can both believe they hold a task, and a session that crashed can close a task it no longer holds. |
| **L-10**, forged claims | A `CLAIM` or `DONE` line can be written through the general ledger tool, so a task can look claimed or finished without being so. |
| **P-18**, the task file | An agent can edit its own task's acceptance line, after claiming it, into one that passes, and close. (In a review of the reference implementation's version 0.1.0, an agent did this, and it worked. P-18 was added after.) |
| **E-3**, encoding | A ledger written as UTF-16 (PowerShell 5's default) is accepted and then corrupted, instead of reported. |

The 8 it passes are the simple cases: the task folders are made when missing, CRLF is read as LF, claiming a missing
task is a conflict, one of two simultaneous claims wins, a failing check leaves the task active with a warning, TRACES
entries have the right shape and each gets its ledger line, and moving a task does not change its text.

## Why this is the "before" that matters

The cost write-up ([01](01-it-lost-on-cost.md)) found that a colony does not save tokens. What the colony is for, then,
is a record you can trust and rules that hold. This table is the measure of that: the design as first written held
8 of the 38 rules it needed, and the version I ship holds all of them, on Windows and (as of spec 0.2.0, the last time
CI could run on Linux) on Linux.

## Limits

- The suite was written by the same person as the reference implementation. A suite written by someone else could
  find failures this one does not. Every new requirement's test was run **red first** (failing on the version before
  it), and 30 planted bugs in the 0.9.0 work were all caught (see [03](03-the-guard-had-a-hole.md)).
- The textbook server is my reading of the textbook. Its source names the chapter each behaviour comes from, so the
  reading can be checked.
- The table is from Windows. This repository's CI runs the same suite on Linux; see the Actions tab for its results.

## Reproduce it

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python conformance/run.py reference                # must conform
python conformance/run.py naive --expect-fail      # must not conform
```

Each run writes a per-requirement table to `evidence/conformance-<name>-<platform>.md`. To test your own
implementation in any language: `python conformance/run.py "<command that starts your MCP stdio server>"`.
