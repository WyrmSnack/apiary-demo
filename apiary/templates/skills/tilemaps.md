---
name: tilemaps
description: Make 2D game levels as Tiled maps (TMX or JSON), convert them with Tiled's command line, check them with the tile-map gate, and load them into Godot. Use when a task needs a level, room, world map or tileset.
---

# Tile maps with Tiled

Tiled runs only through `run_connector` with `connector: tiled`. Write the map yourself as text; Tiled checks it and
converts it.

## 1. Write the map (TMX)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" orientation="orthogonal" renderorder="right-down" width="20" height="12"
     tilewidth="16" tileheight="16" infinite="0">
 <tileset firstgid="1" name="terrain" tilewidth="16" tileheight="16" tilecount="16" columns="4">
  <image source="../art/terrain.png" width="64" height="64"/>
 </tileset>
 <layer id="1" name="ground" width="20" height="12">
  <data encoding="csv">
1,1,1,...
</data>
 </layer>
 <objectgroup id="2" name="spawns">
  <object id="1" name="player" x="32" y="160"/>
 </objectgroup>
</map>
```

- The CSV has exactly width x height numbers, row by row. 0 is empty; tile ids count from the tileset's `firstgid`,
  left to right, top to bottom in the tileset image.
- Make the tileset image first (skill `sprite-pipeline`), on the same tile grid.
- Keep level design readable: a ground layer, a walls or collision layer, and an object layer for spawns and items.

## 2. Convert and preview

- To JSON (what a game loads): `args` `--export-map json maps/level1.tmx maps/level1.json`, `outputs` `maps/level1.json`.
- Tiled exits 1 for a map it cannot read. On Linux it needs a display (`xvfb-run`); on Windows it runs without one.
- Tiled 1.12.2 prints no version on Windows; apiary reads the program file's version instead.

## 3. The gate

    python -m apiary.gates.assets tiled maps/level1.json --width 20 --height 12 --tile-size 16x16 --layers ground,spawns

checks size, layers, cell counts and that every tile id belongs to a tileset (flip flags allowed).

## 4. Into Godot

Godot does not import TMX itself. Either load the JSON in GDScript and fill a `TileMapLayer`
(`layer.set_cell(Vector2i(x, y), source_id, Vector2i(id % columns, id / columns))` for each non-zero `id - firstgid`),
or ask the human before adding a third-party importer add-on. Test the loader with a GDScript test (skill
`godot-gdscript-tests`).
