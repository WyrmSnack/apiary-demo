# Write-up 02: Conformance of the original colony design to the specification

*Kevin Wilkins, November 2026. Every number here comes from running the conformance suite in this repository; the
commands to rerun it are at the end.*

**Summary.** The agent-colony design apiary started from reads as complete in prose. Implemented exactly as written
and tested against the specification, it satisfies 8 of 49 requirements. The gaps are the familiar ones of concurrent
systems: no tokens, no leases, no lock, and a check that passes on Windows when it should fail. The specification was
written before the reference implementation and has since changed only through recorded amendments.

## Subjects of comparison

- **Baseline:** `conformance/naive_server.py`, the colony design from the source textbook, implemented as written.
  Claiming is a file rename, close runs the task's `acceptance:` line in a shell, and resume returns every active task
  that fails its check to pending. It has no tokens, leases or locks, because the textbook defines none.
- **Reference:** the implementation in `apiary/`, built to the Colony Substrate Specification
  ([summary](../spec/SUMMARY.md)).

The conformance suite (`conformance/`) imports nothing from either. It starts each one as an MCP stdio server, calls
its tools against a temporary colony, and inspects the files left on disk. Each test is named after the requirements
it checks.

## Results

Specification 0.9.0, Windows, Python 3.14:

| | Requirements passed | Results passed |
|---|---|---|
| Textbook design, as written | **8 of 49** | 63 of 254 |
| Reference implementation | **49 of 49** | 254 of 254 |

The 49 include 11 requirements for features the textbook does not define (connectors to outside programs, the plan
board, human checkpoints, `plan_status`, P-19's claim text). With those excluded, so that the textbook is judged only
on what it describes, it passes **8 of 38**.

## Consequences of the failures

Each failure below is a way in which a colony built from the textbook loses work or records work that was not done.
Each has a test in `conformance/`.

| Requirement | Failure in the textbook design |
|---|---|
| **A-2**, acceptance commands | The check runs in a shell, and shells disagree. Under `cmd.exe`, the check `python -c 'exit(1)'`, which must fail, exits 0, and the task closes as passed. `;`, `&`, redirects and `$(...)` are all executed. The specification runs an argv without a shell and refuses shell syntax before anything runs. |
| **P-14**, resume | Resume returns *every* active task whose check fails to pending, including tasks another agent is working on. Live work is taken away. The specification resumes only orphaned tasks and expired leases. |
| **P-1, P-5, P-8**, locks, tokens, leases | Two agents can each believe they hold the same task, and a session that has crashed can close a task it no longer holds. |
| **L-10**, forged claims | A `CLAIM` or `DONE` line can be written through the general ledger tool, so a task can appear claimed or finished when it is not. |
| **P-18**, the task file | After claiming a task, an agent can edit its acceptance line into one that passes, and close it. (In a review of the reference implementation's version 0.1.0, an agent did this and the close succeeded. P-18 was added in response.) |
| **E-3**, encoding | A ledger written as UTF-16 (the default of PowerShell 5) is accepted and then corrupted, rather than reported. |

The 8 requirements it passes are the simple cases: task folders are created when missing, CRLF is read as LF,
claiming a missing task is a conflict, one of two simultaneous claims wins, a failing check leaves the task active
with a warning, TRACES entries have the correct shape and each receives its ledger line, and moving a task does not
change its text.

## Relevance of this baseline

[Write-up 01](01-coordination-cost.md) found that a colony does not reduce token cost. The colony's value therefore
lies in a trustworthy record and in rules that hold. This table measures that value: the design as first written
satisfied 8 of the 38 rules it required, and the shipped implementation satisfies all of them, on Windows and, as of
specification 0.2.0 (the last Linux CI run before this repository), on Linux.

## Limits

- The suite was written by the author of the reference implementation. An independently written suite could find
  failures that this one does not. Every new requirement's test was first run **red** (failing against the preceding
  version), and all 30 bugs planted in the 0.9.0 work were detected (see [write-up 03](03-guard-bypass.md)).
- The textbook server is one reading of the textbook. Its source names the chapter each behaviour comes from, so the
  reading can be checked.
- The table above is from Windows. This repository's CI runs the same suite on Linux; the Actions tab shows its
  results.

## Reproduction

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python conformance/run.py reference                # must conform
python conformance/run.py naive --expect-fail      # must not conform
```

Each run writes a per-requirement table to `evidence/conformance-<name>-<platform>.md`. To test another
implementation, in any language: `python conformance/run.py "<command that starts your MCP stdio server>"`.
