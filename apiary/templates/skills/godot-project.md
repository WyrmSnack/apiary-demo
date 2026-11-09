---
name: godot-project
description: Build or change a Godot 4 game project from Claude Code without the editor GUI - project.godot, text scenes (.tscn), GDScript, importing assets made by other programs, and running it headless through the colony's godot connector. Use for any task that creates or edits a Godot project.
---

# Godot projects, headless

Godot runs only through `run_connector` with `connector: godot` (never from the shell; the guard refuses it).
Every run gets a run record in `runs/`. Always pass `--headless --path <project folder>`.

## Make the project as text

Godot 4 project files are plain text; write them with your file tools inside the task's `writes`.

- `project.godot` needs at least:
  ```
  config_version=5

  [application]
  config/name="My Game"
  run/main_scene="res://main.tscn"
  ```
- Scenes (`.tscn`, `[gd_scene format=3]`) reference files as `[ext_resource type="Texture2D" path="res://art/hero.png" id="1"]`
  and nodes as `[node name="Hero" type="Sprite2D" parent="."]`. Leave out `uid=` attributes: Godot adds them on import.
- Scripts are GDScript 2 (`extends Node2D`, typed `var speed: float = 120.0`, `@export`, `func _physics_process(delta):`).
  Use `TileMapLayer`, not the removed `TileMap`.
- Put assets from other programs under the project (`art/`, `sfx/`, `models/`): Godot imports `.png`, `.svg`, `.glb`,
  `.ogg` and `.wav` natively.

## Run it

| Step | `args` for run_connector |
|---|---|
| Parse one script | `--headless --path game --check-only --script res://player.gd` |
| Import assets (do this before tests that load them) | `--headless --path game --import` |
| Run a script | `--headless --path game --script res://tools/make_level.gd` |
| Tests | `--headless --path game --script res://tests/run_tests.gd` (skill `godot-gdscript-tests`) |

A `--script` must `extends SceneTree` and end with `quit(<exit code>)`. **Measured with Godot 4.7.2:** a runtime error
before `quit()` leaves Godot running forever, and with `--quit-after` it exits 0. The godot connector therefore stops a
run at its `timeout_s` and marks it `NOT OK` when the output has `SCRIPT ERROR` or `ERROR:` (spec C-6). Read the run
record's `stderr` and `errors` before trying again.

**Measured with Godot 4.7.2 (Steam, Windows):** `--import` crashed with exit 3221225477 (0xC0000005, an access
violation) in 2 of 26 runs, both on a busy machine, at the start of reimporting. An interrupted import is safe to
run again: if the run record shows that exit code, rerun the import once before looking for a cause.

Exporting a build (`--export-release "<preset>" <out>`) needs `export_presets.cfg` and Godot's export templates
installed for that version; if they are missing, say so in a WARN instead of guessing.

## The gate

Before closing, the project must pass the structural check (every `res://` path in scenes, resources and scripts
exists):

    python -m apiary.gates.assets godot game

and, for behaviour, the GDScript tests (skill `godot-gdscript-tests`). A good task's acceptance line is the tests;
run the structural check as well and report both.
