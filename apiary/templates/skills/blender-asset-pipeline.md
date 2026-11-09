---
name: blender-asset-pipeline
description: Model, render and export 3D game assets with Blender in the background (bpy scripts), export glTF binary (.glb) for game engines, render sprites or previews, and check the result with the glb and png gates. Use for any 3D model, prop, render or 3D-to-2D sprite task.
---

# 3D assets with Blender, headless

Blender runs only through `run_connector` with `connector: blender`. Every run's args start with

    --background --factory-startup --python-exit-code 1 --python <script.py> -- <your args>

**Always `--python-exit-code 1`**: without it Blender 4.4.3 exits 0 when the script crashes (Measured, Phase 4). The
blender connector also fails a run whose output has a Python `Traceback` or an `Error:` line (spec C-6).

## Script shape

```python
import os, sys, bpy
out = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=1)
crate = bpy.context.active_object
crate.name = "Crate"
mat = bpy.data.materials.new("Wood"); mat.use_nodes = True
mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.55, 0.35, 0.15, 1)
crate.data.materials.append(mat)
os.makedirs(os.path.dirname(out), exist_ok=True)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_apply=True)
```

- Keep the script inside the task's `writes`; pass every output path after `--` and list it in `outputs`.
- Game budgets: low poly (hundreds to a few thousand triangles per prop), apply modifiers on export
  (`export_apply=True`), real-world scale (1 unit = 1 m), origin at the base, +Y up is handled by the exporter.
- Animation: keyframe with `obj.keyframe_insert("location", frame=n)`; actions export as glTF animations.
- Renders (previews, or 2D sprites from 3D): set `scene.render.engine = "BLENDER_EEVEE_NEXT"` (or `"CYCLES"` with few
  samples), `scene.render.resolution_x/y`, `scene.render.film_transparent = True`, `scene.render.filepath`, a camera,
  a light, then `bpy.ops.render.render(write_still=True)`. For a sprite sheet, render each frame and assemble it with
  Aseprite (skill `sprite-pipeline`) or render an orthographic camera per frame.

## The gates

    python -m apiary.gates.assets glb models/crate.glb --min-meshes 1 --min-materials 1 --max-triangles 2000
    python -m apiary.gates.assets png renders/crate.png --width 256 --height 256 --not-blank

`--min-animations 1` for an animated model. Godot imports `.glb` directly (skill `godot-project`).
