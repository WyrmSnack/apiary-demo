---
name: vector-art
description: Make logos, icons, UI elements and title art as SVG and render them to PNG at exact sizes with Inkscape's command line, checked by the svg and png gates. Use when a task needs crisp 2D art at several resolutions.
---

# Vector art with Inkscape

Inkscape runs only through `run_connector` with `connector: inkscape`. Write the SVG yourself as text, then let
Inkscape render it.

## 1. Write the SVG

- Give it a `viewBox` (`viewBox="0 0 64 64"`) so it scales cleanly, and draw with `path`, `rect`, `circle`,
  `polygon` and `text`. Use a few flat colours with good contrast; check that text is readable at the smallest size.
- Prefer shapes to text for logos: fonts differ between machines. If you need text in the final art, convert it to
  paths: `args` `art/logo.svg --export-text-to-path --export-plain-svg --export-filename=art/logo-paths.svg`.

## 2. Render PNGs

`args`: `art/logo.svg --export-type=png --export-filename=art/logo-256.png -w 256`, `outputs`: `art/logo-256.png`.
Use `-w` or `-h` (pixels) per size: icons often need 16, 32, 64, 128, 256 and 512. `--export-background-opacity=0`
keeps transparency; `--export-area-drawing` crops to the drawing.

**Measured with Inkscape 1.4.4:** a missing file exits 0 and writes nothing, and a malformed SVG exits 0 and writes a
blank 300x150 PNG. The inkscape connector marks both `NOT OK` (spec C-6), and the gates below catch a blank render.
Rendering takes about 15 seconds on Kevin's machine, so make all sizes in as few runs as you can.

## 3. The gates

    python -m apiary.gates.assets svg art/logo.svg
    python -m apiary.gates.assets png art/logo-256.png --width 256 --height 256 --not-blank --min-colors 3

Godot imports `.svg` directly as a texture too, at a fixed scale set in its import options.
