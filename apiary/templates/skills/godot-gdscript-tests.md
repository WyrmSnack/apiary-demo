---
name: godot-gdscript-tests
description: Write and run GDScript unit tests for a Godot 4 project headless, with apiary's add-on-free test runner, as a task's acceptance gate. Use when a task changes game logic in GDScript or needs a Godot behaviour checked.
---

# GDScript tests

## Set up once per project

    py -m apiary gamedev godot-tests game

writes `game/tests/case.gd` (checks) and `game/tests/run_tests.gd` (the runner). It never overwrites a changed file.
Needs Godot 4.5 or later. If the human has not run it, you may run it yourself: it only writes into the project.

## Write tests

One file per area, `game/tests/test_<area>.gd`:

```gdscript
extends "res://tests/case.gd"

func test_jump_reaches_64_pixels():
    var p := preload("res://player.gd").new()
    check_eq(p.jump_height(), 64.0, "jump height")

func test_hero_sheet_loads():
    var tex := check_loads("res://art/hero.png") as Texture2D
    check(tex != null and tex.get_width() == 64, "hero sheet is 64 px wide")
```

- Every method named `test_*` runs once, in a fresh instance. Checks: `check(cond, msg)`, `check_eq(actual, expected,
  msg)`, `check_near(a, b, tolerance, msg)`, `check_loads("res://...")`.
- Test files may sit in subfolders (`tests/unit/`, `tests/feature/`); `-- --files res://tests/a.gd,...` runs only
  those. Reach code under test with `make("res://src/x.gd", [args])` or `script_at(path)` rather than `preload` or a
  `class_name`, so a test written before its code fails when run instead of failing to parse.
- Test behaviour (numbers, state changes, signals), not that code exists. Write the test first and see it fail.
- A runtime error inside a test fails that test (the runner counts errors with a `Logger`; Measured with Godot 4.7.2:
  without that, the error aborts the method and the runner would count a pass).
- Tests that load assets need them imported first: run `--headless --path game --import` through `run_connector`.

## Run them

Through `run_connector`: connector `godot`, args `--headless --path game --script res://tests/run_tests.gd`.
The output has one `PASS`/`FAIL` line per test and `APIARY-TESTS: <n> passed, <m> failed`; exit 0 only if at least one
test ran and none failed.

As a task's acceptance line (the colony runs it with the godot connector's timeout and error patterns, spec C-2 and C-6):

    acceptance: godot --headless --path game --script res://tests/run_tests.gd

Before closing, also check that every `res://` path the project uses exists:
`python -m apiary.gates.assets godot game`.

Never edit `tests/case.gd` or `tests/run_tests.gd` to make a test pass, and never delete or weaken a failing test:
fix the game, or escalate with a WARN saying why the test is wrong.
