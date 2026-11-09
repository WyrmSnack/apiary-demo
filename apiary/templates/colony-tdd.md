---
name: colony-tdd
description: This colony builds test-first through a story ladder - source document to user stories to feature stories to feature tests to unit tests, then code. Use for planning any feature, writing stories or tests, or implementing code in this colony; every task's gate enforces the ladder.
---

# The story ladder (test-first)

This colony works test-first, and its gates enforce it. A test is written and **seen failing** before the code it
tests, then **locked**; the code is done only when the locked tests pass and nothing else broke. Nobody edits a
locked test to make it pass: if a test is wrong, file a WARN and stop; the Queen unlocks it, fixes it and relocks it
through the colony tools, and reports every change to the human (see "Changing a locked test").

## The rungs

| Rung | Written by | File | Its task's acceptance gate |
|---|---|---|---|
| 1. User stories | Queen or Forager | `docs/stories/user/US-nnn.md` | `python -m apiary.gates.stories docs/stories --stage user --manual docs/source/manual.html` |
| 2. Feature stories | Forager | `docs/stories/feature/FS-nnn.md` | `python -m apiary.gates.stories docs/stories --stage feature --slice S1` |
| 3+4. Feature tests and the unit tests they are made of | Forager (test task) | `game/tests/feature/test_*.gd`, `game/tests/unit/test_*.gd` | `python -m apiary.gates.tdd red --project game --tests <all its test files> --story FS-nnn --lock` |
| 5. Code that makes unit tests pass | Forager (code task) | `game/src/...` | `python -m apiary.gates.tdd green --project game --tests <those unit test files>` |
| 6. The feature works | Forager (feature task) | `game/src/...` glue | `python -m apiary.gates.tdd green --project game --tests <the feature test files>` |

The story format, front matter and all, is in `python -m apiary.gates.stories --help`. In short: a user story has
`id: US-nnn`, `kind: user`, `title`, `slice: S1`, `source:` (the manual headings it covers, `;`-separated), the line
"As a <player>, I want <goal>, so that <reason>." and an `## Acceptance criteria` list. A feature story has
`id: FS-nnn`, `kind: feature`, `parent: US-nnn`, its acceptance criteria, and once its tests exist
`feature_tests:` and `unit_tests:` (comma-separated paths).

## Planning (Queen)

1. **User stories for the whole source first.** Every `##` and `###` heading of the manual must be the `source` of at
   least one user story. Split the manual by chapter into parallel lanes (each lane writes its own `US-` number
   range, so their `writes` never overlap); each lane's gate is `--stage user` without `--manual`, and one final
   task, depending on all of them, checks full coverage with `--manual`. Assign every user story a `slice`: S1 is the
   smallest playable core, and later slices build on earlier ones.
2. **One slice at a time.** For the current slice: a task for its feature stories (gate `--stage feature --slice
   S<n>`); then, per feature story, a **test task** (rungs 3 and 4 together: the feature tests and the unit tests
   that make them up, all failing, gate `tdd red ... --story FS-nnn --lock`); then **code tasks**, each depending on
   its test task, each turning a group of unit tests green; then a **feature task** turning the feature tests green.
   Finish with a Guardian review task (a different agent checks that the tests test the acceptance criteria, not
   just that code exists) and a boot check: `godot --headless --path game --quit-after 300` (the godot connector
   fails it on any script error).
3. Use `create_plan` so dependencies are exact: code tasks `depends_on` the test task, the feature task depends on
   the code tasks. A task never both writes a test and makes it pass.

## Writing tests (test task)

- `py -m apiary gamedev godot-tests game` once per project (the runner and `tests/case.gd`).
- Reach the code under test with `make("res://src/city/zone_grid.gd", [args])` or `script_at(path)`, never
  `preload` or a `class_name`: code that does not exist yet must make the test **fail when run**, not fail to parse.
  The red gate refuses a test file that does not load, a test that already passes, and a file with no tests.
- Test behaviour from the story's acceptance criteria (numbers, state, signals), one behaviour per test, with
  messages that say what was expected. The simulation should be plain GDScript classes (`extends RefCounted`) that a
  test can drive without a scene tree; scenes and drawing come last and stay thin.
- Run `python -m apiary.gates.tdd red --project game --tests <files>` (no `--lock`) as often as you like while
  writing; only the task's acceptance locks them.

## Writing code (code and feature tasks)

- Read the locked tests first; make them pass with the simplest code that fits the story; refactor while green.
- `python -m apiary.gates.tdd green --project game --tests <files>` runs the whole suite: a file that was green and
  now fails is a regression and fails your gate too. Tests of later features that are locked but not yet green may
  fail; unlocked failing tests may not.
- If a locked test is wrong, do not touch it. Close nothing; file a WARN naming the test and why, and stop.

## Changing a locked test (Queen)

Only the Queen, the session talking with the human, may do this; the guard refuses it to subagents.

1. A WARN or ESCALATE for the file is in the ledger since it was locked (a Guardian finding, a Forager's WARN, or
   the Queen's own, naming the story criterion).
2. `unlock_test(path, reason, evidence)`: reason `impassable`, `conflict`, `requirement_change` or `nondeterministic`.
   While a file is unlocked, its failures do not block other green gates; a gate that names it waits.
3. Edit only what the evidence needs: an expected value, setup, ordering, or added checks. Keep test names and checks:
   a rename reads as a deletion, and a check rewritten into another shape as a removed check.
4. `relock_test(paths, story)` runs the files and records the hash: changed tests may fail (pending) or pass, and an
   unchanged test that was green must still pass. Nobody types a hash.
5. `lock_report()`: its block goes, unchanged, at the top of the Queen's next message to the human. A Stop hook
   enforces it.

An edit that weakens a test (a deleted test or check, a looser tolerance, `check_eq` to `check_near`, a value to a
range, the file dropped from its story) is refused until the human writes "approve weakening <file name>" in chat.

## Sources

Read only `docs/source/` (the manual and design documents) and this colony's files. Do not read other projects'
code for the same game: the colony builds it from the documents.
