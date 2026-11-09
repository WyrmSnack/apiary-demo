---
name: sprite-pipeline
description: Make pixel-art sprites and animation sprite sheets with Aseprite in batch mode (Lua scripts, sheet export with JSON frame data) and check them with the sprite-sheet gate. Use when a task needs 2D characters, tiles, icons or animations.
---

# Sprites with Aseprite, headless

Aseprite runs only through `run_connector` with `connector: aseprite`. Always pass `-b` (batch: no window).

## 1. Draw with a Lua script

Write the script inside the task's `writes` (for example `art/src/make_hero.lua`):

```lua
local out = app.params["out"]                       -- passed with --script-param out=...
local spr = Sprite(16, 16, ColorMode.RGB)
local pal = { Color{r=40, g=40, b=60}, Color{r=230, g=180, b=90}, Color{r=200, g=60, b=60} }
for f = 1, 4 do                                      -- a 4-frame walk cycle
  if f > 1 then spr:newFrame() end
  local img = spr.cels[f].image
  for y = 4, 12 do img:drawPixel(6 + (f % 2), y, pal[2]) end
  spr.frames[f].duration = 0.1                       -- seconds
end
spr:saveAs(out)
```

`args`: `-b --script-param out=art/src/hero.aseprite --script art/src/make_hero.lua`,
`outputs`: `art/src/hero.aseprite`.

Lua API (aseprite.org/api): `Sprite(w, h)`, `spr:newFrame()`, `spr:newLayer()`, `spr.cels`, `cel.image`,
`image:drawPixel(x, y, color)`, `image:clear()`, `app.useTool{...}` for lines and fills, `spr:saveAs(path)`. Keep sizes
on a grid (16, 24, 32 px) and a small palette.

## 2. Export the sheet

`args`: `-b art/src/hero.aseprite --sheet art/hero.png --data art/hero.json --format json-array --sheet-type rows`
(add `--split-layers` or `--tag <name>` when needed), `outputs`: `art/hero.png, art/hero.json`.

**Measured with Aseprite 1.3.18.3:** a missing input file exits 0 and writes nothing. The aseprite connector marks
that run `NOT OK` (spec C-6), and listing both outputs makes the run record show what is missing.

## 3. The gate

    python -m apiary.gates.assets sheet art/hero.png --frame 16x16 --frames 4 --data art/hero.json --frames-drawn

checks the grid, that Aseprite's JSON agrees with it, and that no frame is empty. For a single image:
`python -m apiary.gates.assets png art/icon.png --width 32 --height 32 --not-blank`.

In Godot, use the sheet as a `SpriteFrames` resource or an `AtlasTexture` per frame (skill `godot-project`).
