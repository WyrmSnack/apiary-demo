"""Asset gates (Phase 10 gate c): every check passes a good file and fails each kind of bad one."""
import json
import math
import struct
import wave
import zlib

import pytest

from apiary.gates import assets


# --- builders: real files, made with the standard library ---------------------------

def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def _filter(rows: list[bytes], bpp: int, ftype: int) -> bytes:
    out, prev = bytearray(), bytes(len(rows[0]))
    for row in rows:
        line = bytearray([ftype])
        for i, x in enumerate(row):
            a = row[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ftype == 0:
                pred = 0
            elif ftype == 1:
                pred = a
            elif ftype == 2:
                pred = b
            elif ftype == 3:
                pred = (a + b) // 2
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
            line.append((x - pred) & 0xFF)
        out += line
        prev = row
    return bytes(out)


def png_bytes(pixels: list[list[tuple]], ftype: int = 0) -> bytes:
    """An RGBA PNG from rows of (r, g, b, a) tuples."""
    h, w = len(pixels), len(pixels[0])
    rows = [bytes(v for px in row for v in px) for row in pixels]
    return (assets.PNG_SIG + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(_filter(rows, 4, ftype))) + _chunk(b"IEND", b""))


CLEAR, RED, BLUE, GREEN = (0, 0, 0, 0), (255, 0, 0, 255), (0, 0, 255, 255), (0, 255, 0, 255)


def image(w, h, fn):
    return [[fn(x, y) for x in range(w)] for y in range(h)]


def write(tmp_path, name, data):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data) if isinstance(data, bytes) else p.write_text(data, encoding="utf-8")
    return p


def glb_bytes(doc: dict, binary: bytes, version: int = 2, length_fix: int = 0) -> bytes:
    j = json.dumps(doc).encode()
    j += b" " * (-len(j) % 4)
    binary += b"\0" * (-len(binary) % 4)
    body = struct.pack("<I4s", len(j), b"JSON") + j + (struct.pack("<I4s", len(binary), b"BIN\0") + binary
                                                       if binary else b"")
    return struct.pack("<4sII", b"glTF", version, 12 + len(body) + length_fix) + body


def triangle_doc(count: int = 3, extra: dict | None = None) -> tuple[dict, bytes]:
    binary = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(binary)}],
           "bufferViews": [{"buffer": 0, "byteLength": len(binary)}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3"}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
           "materials": [{"name": "m"}], "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}]}
    doc.update(extra or {})
    return doc, binary


def wav_file(path, seconds=0.25, rate=44100, channels=1, amplitude=0.5, width=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        frames = bytearray()
        full = (1 << (8 * width - 1)) - 1
        for i in range(int(seconds * rate)):
            v = int(full * amplitude * math.sin(2 * math.pi * 440 * i / rate))
            sample = (v + 128).to_bytes(1, "little") if width == 1 else v.to_bytes(width, "little", signed=True)
            frames += sample * channels
        w.writeframes(bytes(frames))
    return path


def ogg_page(body: bytes, granule: int, header_type: int = 0) -> bytes:
    segs = [255] * (len(body) // 255) + [len(body) % 255]
    return (b"OggS" + bytes([0, header_type]) + struct.pack("<qIII", granule, 1, 0, 0) + bytes([len(segs)])
            + bytes(segs) + body)


def vorbis_ogg(rate=44100, channels=1, seconds=0.5) -> bytes:
    ident = b"\x01vorbis" + struct.pack("<IBIiiiBB", 0, channels, rate, 0, 0, 0, 0xB8, 1)
    return ogg_page(ident, 0, 2) + ogg_page(b"\x05audio", int(rate * seconds), 4)


def opus_ogg(seconds=0.5, preskip=312) -> bytes:
    head = b"OpusHead" + bytes([1, 2]) + struct.pack("<HIhB", preskip, 44100, 0, 0)
    return ogg_page(head, 0, 2) + ogg_page(b"audio", int(48000 * seconds) + preskip, 4)


# --- PNG --------------------------------------------------------------------------

@pytest.mark.parametrize("ftype", [0, 1, 2, 3, 4])
def test_png_pixels_decode_under_every_filter(tmp_path, ftype):
    pixels = image(5, 4, lambda x, y: (x * 40, y * 60, (x * y) % 256, 255))
    p = write(tmp_path, "a.png", png_bytes(pixels, ftype))
    png = assets.read_png(p)
    assert png.pixels() == [bytes(px) for row in pixels for px in row]


def test_png_passes_with_the_right_size_and_content(tmp_path):
    p = write(tmp_path, "logo.png", png_bytes(image(8, 6, lambda x, y: RED if x < 4 else BLUE)))
    assert assets.check_png(p, 8, 6, not_blank=True, min_colors=2) == []


@pytest.mark.parametrize("kw,why", [({"width": 9}, "width"), ({"height": 5}, "height"),
                                    ({"min_colors": 3}, "colours")])
def test_png_wrong_size_or_too_few_colours_fails(tmp_path, kw, why):
    p = write(tmp_path, "logo.png", png_bytes(image(8, 6, lambda x, y: RED if x < 4 else BLUE)))
    problems = assets.check_png(p, **kw)
    assert len(problems) == 1 and why in problems[0], problems


def test_png_blank_image_fails_not_blank(tmp_path):
    """Inkscape 1.4.4 renders a malformed SVG as one flat colour and exits 0 (Measured)."""
    p = write(tmp_path, "blank.png", png_bytes(image(30, 15, lambda x, y: (255, 255, 255, 0))))
    assert assets.check_png(p) == []
    assert any("blank" in x for x in assets.check_png(p, not_blank=True))


@pytest.mark.parametrize("mangle,why", [
    (lambda b: b"GIF89a" + b[6:], "signature"),
    (lambda b: b[:-12], "IEND"),
    (lambda b: b[:40] + bytes([b[40] ^ 0xFF]) + b[41:], "CRC"),
    (lambda b: b[:30], "cut short"),
])
def test_png_damaged_files_fail(tmp_path, mangle, why):
    p = write(tmp_path, "bad.png", mangle(png_bytes(image(4, 4, lambda x, y: RED))))
    problems = assets.check_png(p)
    assert problems and why in problems[0], problems


def test_png_missing_file_fails(tmp_path):
    assert "does not exist" in assets.check_png(tmp_path / "none.png")[0]


# --- sprite sheets ---------------------------------------------------------------------

def sheet(cols, rows, fw=4, fh=4, empty=()):
    def px(x, y):
        i = y // fh * cols + x // fw
        if i in empty:
            return CLEAR
        return RED if (x + y + i) % 2 else BLUE
    return png_bytes(image(cols * fw, rows * fh, px))


def aseprite_json(n, fw=4, fh=4, cols=None, size=None, as_map=False):
    cols = cols or n
    frames = [{"filename": f"hero {i}.aseprite", "frame": {"x": i % cols * fw, "y": i // cols * fh,
                                                           "w": (size or (fw, fh))[0], "h": (size or (fw, fh))[1]},
               "duration": 100} for i in range(n)]
    return json.dumps({"frames": {f["filename"]: f for f in frames} if as_map else frames, "meta": {}})


@pytest.mark.parametrize("as_map", [False, True])
def test_sheet_passes_with_its_aseprite_data(tmp_path, as_map):
    p = write(tmp_path, "hero.png", sheet(4, 1))
    d = write(tmp_path, "hero.json", aseprite_json(4, as_map=as_map))
    assert assets.check_sheet(p, (4, 4), 4, d, frames_drawn=True) == []


def test_sheet_with_frames_in_rows_passes(tmp_path):
    p = write(tmp_path, "hero.png", sheet(2, 2))
    assert assets.check_sheet(p, (4, 4), 4, write(tmp_path, "h.json", aseprite_json(4, cols=2)), True) == []


@pytest.mark.parametrize("args,why", [
    (((5, 4), 4), "whole grid"),
    (((4, 4), 5), "room for 4"),
])
def test_sheet_wrong_grid_fails(tmp_path, args, why):
    p = write(tmp_path, "hero.png", sheet(4, 1))
    problems = assets.check_sheet(p, *args)
    assert any(why in x for x in problems), problems


@pytest.mark.parametrize("data,why", [
    (aseprite_json(3), "3 frames, expected 4"),
    (aseprite_json(4, size=(4, 5)), "is 4x5"),
    (aseprite_json(4, fw=5), "outside"),
    (json.dumps({"meta": {}}), "no 'frames'"),
    ("{not json", "not readable"),
])
def test_sheet_data_that_disagrees_fails(tmp_path, data, why):
    p = write(tmp_path, "hero.png", sheet(4, 1))
    problems = assets.check_sheet(p, (4, 4), 4, write(tmp_path, "hero.json", data))
    assert any(why in x for x in problems), problems


def test_sheet_with_an_empty_frame_fails_frames_drawn(tmp_path):
    p = write(tmp_path, "hero.png", sheet(4, 1, empty={2}))
    assert assets.check_sheet(p, (4, 4), 4) == []
    problems = assets.check_sheet(p, (4, 4), 4, frames_drawn=True)
    assert len(problems) == 1 and "frame 2" in problems[0], problems


# --- glTF binary ---------------------------------------------------------------------

def test_glb_triangle_passes(tmp_path):
    p = write(tmp_path, "tri.glb", glb_bytes(*triangle_doc()))
    assert assets.check_glb(p, min_meshes=1, min_materials=1, max_triangles=1) == []


@pytest.mark.parametrize("make,why", [
    (lambda: b"PK\x03\x04" + glb_bytes(*triangle_doc())[4:], "magic"),
    (lambda: glb_bytes(*triangle_doc(), version=1), "version 1"),
    (lambda: glb_bytes(*triangle_doc(), length_fix=8), "truncated"),
    (lambda: glb_bytes(triangle_doc(extra={"asset": {"version": "1.0"}})[0], triangle_doc()[1]), "asset.version"),
    (lambda: glb_bytes(triangle_doc(count=4)[0], triangle_doc()[1]), "reads past"),
    (lambda: glb_bytes(triangle_doc()[0], b""), "BIN chunk has 0"),
    (lambda: glb_bytes(triangle_doc(extra={"meshes": [{"primitives": [{"attributes": {"POSITION": 7}}]}]})[0],
                       triangle_doc()[1]), "accessor 7"),
    (lambda: glb_bytes(triangle_doc(extra={"bufferViews": [{"buffer": 3, "byteLength": 36}]})[0],
                       triangle_doc()[1]), "buffer 3"),
    (lambda: glb_bytes(triangle_doc(extra={"meshes": []})[0], triangle_doc()[1]), "0 meshes"),
])
def test_glb_broken_files_fail(tmp_path, make, why):
    problems = assets.check_glb(write(tmp_path, "bad.glb", make()))
    assert any(why in x for x in problems), problems


@pytest.mark.parametrize("kw,why", [({"min_animations": 1}, "animations"), ({"min_materials": 2}, "materials"),
                                    ({"max_triangles": 0}, "budget")])
def test_glb_requirements_fail_when_not_met(tmp_path, kw, why):
    problems = assets.check_glb(write(tmp_path, "tri.glb", glb_bytes(*triangle_doc())), **kw)
    assert len(problems) == 1 and why in problems[0], problems


def test_glb_triangle_count_uses_indices(tmp_path):
    doc, binary = triangle_doc()
    idx = struct.pack("<6H", 0, 1, 2, 2, 1, 0)
    doc["buffers"][0]["byteLength"] = len(binary) + len(idx)
    doc["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(idx)})
    doc["accessors"].append({"bufferView": 1, "componentType": 5123, "count": 6, "type": "SCALAR"})
    doc["meshes"][0]["primitives"][0]["indices"] = 1
    p = write(tmp_path, "quad.glb", glb_bytes(doc, binary + idx))
    assert assets.check_glb(p, max_triangles=2) == []
    assert "2 triangles" in assets.check_glb(p, max_triangles=1)[0]


# --- audio -------------------------------------------------------------------------

@pytest.mark.parametrize("width", [1, 2, 3])
def test_wav_passes(tmp_path, width):
    p = wav_file(tmp_path / "jump.wav", width=width)
    assert assets.check_audio(p, rate=44100, channels=1, min_seconds=0.2, max_seconds=0.3, not_silent=True) == []


@pytest.mark.parametrize("kw,why", [({"rate": 22050}, "sample rate"), ({"channels": 2}, "channels"),
                                    ({"min_seconds": 1}, "at least"), ({"max_seconds": 0.1}, "at most")])
def test_wav_wrong_format_fails(tmp_path, kw, why):
    problems = assets.check_audio(wav_file(tmp_path / "jump.wav"), **kw)
    assert len(problems) == 1 and why in problems[0], problems


def extensible_wav(path, rate=44100, bits=32):
    """What SoX 14.4.2 writes by default for a synthesised sound (Measured): WAVE_FORMAT_EXTENSIBLE, 32-bit."""
    frames = b"".join(int(2 ** (bits - 2) * math.sin(i / 10)).to_bytes(bits // 8, "little", signed=True)
                      for i in range(rate // 4))
    fmt = struct.pack("<HHIIHH", 0xFFFE, 1, rate, rate * bits // 8, bits // 8, bits) + struct.pack(
        "<HHI", 22, bits, 4) + b"\x01\x00\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(frames)) + frames
    path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


def test_wav_in_extensible_format_fails_because_godot_cannot_import_it(tmp_path):
    """Measured: Godot 4.7.2 refuses SoX's default WAV ("Format not supported for WAVE file (not PCM)")."""
    problems = assets.check_audio(extensible_wav(tmp_path / "jump.wav"))
    assert len(problems) == 1 and "EXTENSIBLE" in problems[0] and "-b 16" in problems[0], problems


def test_silent_wav_fails_not_silent(tmp_path):
    p = wav_file(tmp_path / "quiet.wav", amplitude=0.001)
    assert assets.check_audio(p) == []
    assert "silent" in assets.check_audio(p, not_silent=True)[0]


@pytest.mark.parametrize("make,rate,seconds", [(vorbis_ogg, 44100, 0.5),
                                               (lambda: opus_ogg(seconds=0.5, preskip=3840), 44100, 0.5)])
def test_ogg_vorbis_and_opus_pass(tmp_path, make, rate, seconds):
    """Opus counts at 48 kHz after its pre-skip, whatever the input rate in its header."""
    p = write(tmp_path, "music.ogg", make())
    assert assets.check_audio(p, rate=rate, min_seconds=seconds - 0.01, max_seconds=seconds + 0.01) == []


@pytest.mark.parametrize("data,kw,why", [
    (b"RIFF0000WAVE", {}, "not an Ogg"),
    (ogg_page(b"\x01theora" + b"\0" * 30, 0, 2), {}, "neither Vorbis nor Opus"),
    (vorbis_ogg(seconds=0.5), {"min_seconds": 2}, "at least"),
    (vorbis_ogg(channels=2), {"channels": 1}, "2 channels"),
    (vorbis_ogg(), {"not_silent": True}, "needs a .wav"),
])
def test_ogg_bad_or_wrong_fails(tmp_path, data, kw, why):
    problems = assets.check_audio(write(tmp_path, "x.ogg", data), **kw)
    assert any(why in x for x in problems), problems


def test_audio_wrong_type_or_missing_fails(tmp_path):
    assert "unsupported" in assets.check_audio(write(tmp_path, "x.mp3", b"ID3"))[0]
    assert "does not exist" in assets.check_audio(tmp_path / "none.wav")[0]
    assert assets.check_audio(write(tmp_path, "bad.wav", b"RIFF\0\0\0\0WAVEjunk"))


# --- Tiled maps --------------------------------------------------------------------

def tmx(data="1,2,2,1,\n3,0,0,3,\n4,4,4,4", tilecount=4, w=4, h=3, extra=""):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" orientation="orthogonal" width="{w}" height="{h}" tilewidth="16" tileheight="16">
 <tileset firstgid="1" name="t" tilewidth="16" tileheight="16" tilecount="{tilecount}" columns="2">
  <image source="tiles.png" width="32" height="32"/>
 </tileset>
 <layer id="1" name="ground" width="{w}" height="{h}"><data encoding="csv">{data}</data></layer>
 <objectgroup id="2" name="spawns"/>{extra}
</map>"""


def map_json(data=None, tilecount=4, source=None):
    ts = {"firstgid": 1, "source": source} if source else {"firstgid": 1, "tilecount": tilecount}
    return json.dumps({"width": 4, "height": 3, "tilewidth": 16, "tileheight": 16, "tilesets": [ts],
                       "layers": [{"name": "ground", "type": "tilelayer",
                                   "data": data if data is not None else [1, 2, 2, 1, 3, 0, 0, 3, 4, 4, 4, 4]},
                                  {"name": "spawns", "type": "objectgroup", "objects": []}]})


def test_tiled_tmx_and_json_pass(tmp_path):
    for p in (write(tmp_path, "m.tmx", tmx()), write(tmp_path, "m.json", map_json())):
        assert assets.check_tiled(p, 4, 3, (16, 16), ["ground", "spawns"]) == [], p


def test_tiled_base64_zlib_layer_and_flipped_tiles_pass(tmp_path):
    import base64
    gids = [1, 2, 2, 1, 3, 0, 0, 3, 4 | 0x80000000, 4, 4, 4]
    data = base64.b64encode(zlib.compress(struct.pack("<12I", *gids))).decode()
    p = write(tmp_path, "m.tmx", tmx().replace('<data encoding="csv">1,2,2,1,\n3,0,0,3,\n4,4,4,4</data>',
                                               f'<data encoding="base64" compression="zlib">{data}</data>'))
    assert assets.check_tiled(p, 4, 3) == []


def test_tiled_external_tileset_is_read(tmp_path):
    write(tmp_path, "tiles.tsx", '<tileset name="t" tilewidth="16" tileheight="16" tilecount="2" columns="2"/>')
    problems = assets.check_tiled(write(tmp_path, "m.json", map_json(source="tiles.tsx")))
    assert problems and "[3, 4]" in problems[0], problems


@pytest.mark.parametrize("make,kw,why", [
    (lambda: tmx(), {"width": 5}, "wide"),
    (lambda: tmx(), {"height": 4}, "high"),
    (lambda: tmx(), {"tile_size": (32, 32)}, "16x16"),
    (lambda: tmx(), {"layers": ["walls"]}, "no layer named 'walls'"),
    (lambda: tmx(tilecount=3), {}, "[4]"),
    (lambda: tmx(data="1,2,2,1"), {}, "4 cells"),
    (lambda: map_json(data=[1, 9, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), {}, "[9]"),
    (lambda: "<map", {}, ""),
    (lambda: "<notmap/>", {}, "not a Tiled map"),
])
def test_tiled_wrong_maps_fail(tmp_path, make, kw, why):
    text = make()
    name = "m.json" if text.startswith("{") else "m.tmx"
    problems = assets.check_tiled(write(tmp_path, name, text), **kw)
    assert problems and any(why in x for x in problems), problems


# --- SVG ----------------------------------------------------------------------------

GOOD_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="20"/></svg>'


def test_svg_passes(tmp_path):
    assert assets.check_svg(write(tmp_path, "logo.svg", GOOD_SVG)) == []


@pytest.mark.parametrize("text,why", [
    ("<svg", "well-formed"),
    ('<html xmlns="http://www.w3.org/1999/xhtml"><circle/></html>', "not <svg>"),
    ('<svg xmlns="http://www.w3.org/2000/svg"><rect width="5" height="5"/></svg>', "no size"),
    ('<svg xmlns="http://www.w3.org/2000/svg" width="5" height="5"><g/></svg>', "draws nothing"),
])
def test_svg_bad_files_fail(tmp_path, text, why):
    problems = assets.check_svg(write(tmp_path, "logo.svg", text))
    assert any(why in x for x in problems), problems


# --- Godot projects -----------------------------------------------------------------

def godot_project(tmp_path, scene_ref="res://art/hero.png", config_version=5):
    root = tmp_path / "game"
    write(root, "project.godot", f'config_version={config_version}\n\n[application]\n'
                                 'config/name="demo"\nrun/main_scene="res://main.tscn"\n')
    write(root, "main.tscn", f'[gd_scene format=3]\n\n[ext_resource type="Texture2D" path="{scene_ref}" id="1"]\n'
                             '[ext_resource type="Script" path="res://player.gd" id="2"]\n\n[node name="Main" type="Node2D"]\n')
    write(root, "player.gd", 'extends Node2D\nconst JUMP = preload("res://sfx/jump.ogg")\n')
    write(root, "art/hero.png", png_bytes(image(2, 2, lambda x, y: RED)))
    write(root, "sfx/jump.ogg", vorbis_ogg())
    write(root, ".godot/imported/stale.tscn", '[ext_resource path="res://gone.png"]')    # cache: ignored
    return root


def test_godot_project_passes(tmp_path):
    assert assets.check_godot(godot_project(tmp_path)) == []


def test_godot_missing_reference_fails(tmp_path):
    problems = assets.check_godot(godot_project(tmp_path, scene_ref="res://art/missing.png"))
    assert len(problems) == 1 and "res://art/missing.png" in problems[0] and "main.tscn" in problems[0], problems


def test_godot_old_or_absent_project_fails(tmp_path):
    assert "config_version" in assets.check_godot(godot_project(tmp_path, config_version=4))[0]
    assert "no project.godot" in assets.check_godot(tmp_path / "nowhere")[0]


# --- command line -------------------------------------------------------------------

def test_cli_exit_codes(tmp_path, capsys):
    good = write(tmp_path, "logo.svg", GOOD_SVG)
    bad = write(tmp_path, "bad.svg", "<svg")
    assert assets.main(["svg", str(good)]) == 0 and "PASS" in capsys.readouterr().out
    assert assets.main(["svg", str(bad)]) == 1 and "FAIL" in capsys.readouterr().out
    hero = write(tmp_path, "hero.png", sheet(4, 1))
    assert assets.main(["sheet", str(hero), "--frame", "4x4", "--frames", "4", "--frames-drawn"]) == 0
    with pytest.raises(SystemExit) as e:
        assets.main(["sheet", str(hero), "--frame", "4by4", "--frames", "4"])
    assert e.value.code == 2
