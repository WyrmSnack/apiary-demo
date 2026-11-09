"""Acceptance checks for game assets (Phase 10). Standard library only, so they run in CI and in any colony.

  python -m apiary.gates.assets png    art/logo.png [--width 128 --height 128] [--not-blank] [--min-colors 3]
  python -m apiary.gates.assets sheet  art/hero.png --frame 16x16 --frames 4 [--data art/hero.json] [--frames-drawn]
  python -m apiary.gates.assets glb    models/crate.glb [--min-meshes 1] [--min-animations 0] [--max-triangles 5000]
  python -m apiary.gates.assets audio  sfx/jump.wav [--rate 44100] [--channels 1] [--min-seconds 0.1]
                                       [--max-seconds 2] [--not-silent]      (.wav; .ogg Vorbis or Opus, no --not-silent)
  python -m apiary.gates.assets tiled  maps/level1.json [--width 20 --height 15] [--tile-size 16x16] [--layers ground,walls]
  python -m apiary.gates.assets svg    art/logo.svg
  python -m apiary.gates.assets godot  game/

Each check exits 0 if the file passes and 1 with one line per problem if it does not (2 for a usage error). Why
these exist (Measured, docs/PHASE10.md): Inkscape 1.4.4 turns a malformed SVG into a blank PNG and exits 0, and
Aseprite 1.3.18.3 exits 0 with nothing written, so a program's exit code is not evidence that an asset is right.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import re
import struct
import sys
import wave
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

PNG_SIG = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}            # PNG colour type -> samples per pixel


# --- PNG ------------------------------------------------------------------------------

class Png:
    def __init__(self, width: int, height: int, depth: int, ctype: int, interlace: int, data: bytes,
                 palette: bytes, trns: bytes):
        self.width, self.height, self.depth, self.ctype, self.interlace = width, height, depth, ctype, interlace
        self.data, self.palette, self.trns = data, palette, trns

    @property
    def bytes_per_pixel(self) -> int:
        return max(1, CHANNELS[self.ctype] * self.depth // 8)

    def rows(self) -> list[bytes]:
        """The unfiltered scanlines (non-interlaced images only)."""
        if self.interlace:
            raise ValueError("interlaced PNG: pixels cannot be checked (save it without interlacing)")
        raw = zlib.decompress(self.data)
        stride = (self.width * CHANNELS[self.ctype] * self.depth + 7) // 8
        bpp = self.bytes_per_pixel
        if len(raw) != (stride + 1) * self.height:
            raise ValueError(f"pixel data is {len(raw)} bytes, expected {(stride + 1) * self.height}")
        rows, prev = [], bytearray(stride)
        for y in range(self.height):
            ftype = raw[y * (stride + 1)]
            line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                if ftype == 1:
                    line[i] = (line[i] + a) & 0xFF
                elif ftype == 2:
                    line[i] = (line[i] + b) & 0xFF
                elif ftype == 3:
                    line[i] = (line[i] + (a + b) // 2) & 0xFF
                elif ftype == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 0xFF
                elif ftype != 0:
                    raise ValueError(f"row {y} has unknown filter type {ftype}")
            rows.append(bytes(line))
            prev = line
        return rows

    def pixels(self, x0: int = 0, y0: int = 0, w: int | None = None, h: int | None = None) -> list[bytes]:
        """Each pixel in the region as bytes (sub-byte depths: one byte per pixel value)."""
        w = self.width - x0 if w is None else w
        h = self.height - y0 if h is None else h
        rows = self.rows()
        out = []
        for y in range(y0, y0 + h):
            row = rows[y]
            if self.depth < 8:
                per = 8 // self.depth
                for x in range(x0, x0 + w):
                    byte = row[x // per]
                    shift = 8 - self.depth * (x % per + 1)
                    out.append(bytes([(byte >> shift) & ((1 << self.depth) - 1)]))
            else:
                bpp = self.bytes_per_pixel
                out += [row[x * bpp:(x + 1) * bpp] for x in range(x0, x0 + w)]
        return out

    def transparent(self, px: bytes) -> bool:
        if self.ctype == 6:
            return px[-(self.depth // 8):] == b"\x00" * (self.depth // 8)
        if self.ctype == 4:
            return px[-(self.depth // 8):] == b"\x00" * (self.depth // 8)
        if self.ctype == 3 and self.trns:
            return px[0] < len(self.trns) and self.trns[px[0]] == 0
        return False


def read_png(path: Path) -> Png:
    data = path.read_bytes()
    if not data.startswith(PNG_SIG):
        raise ValueError("not a PNG file (wrong signature)")
    pos, header, idat, palette, trns, ended = 8, None, [], b"", b"", False
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        crc = data[pos + 8 + length:pos + 12 + length]
        if len(body) != length or len(crc) != 4:
            raise ValueError(f"chunk {ctype!r} is cut short (file truncated?)")
        if struct.unpack(">I", crc)[0] != zlib.crc32(ctype + body) & 0xFFFFFFFF:
            raise ValueError(f"chunk {ctype.decode('latin-1')} has a bad CRC (file corrupt)")
        if ctype == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"PLTE":
            palette = body
        elif ctype == b"tRNS":
            trns = body
        elif ctype == b"IEND":
            ended = True
            break
        pos += 12 + length
    if not header:
        raise ValueError("no IHDR chunk")
    if not ended:
        raise ValueError("no IEND chunk (file truncated?)")
    if not idat:
        raise ValueError("no image data (IDAT)")
    w, h, depth, ctype, _, _, interlace = header
    if ctype not in CHANNELS:
        raise ValueError(f"unknown PNG colour type {ctype}")
    return Png(w, h, depth, ctype, interlace, b"".join(idat), palette, trns)


def check_png(path: str | Path, width: int | None = None, height: int | None = None, not_blank: bool = False,
              min_colors: int = 0) -> list[str]:
    path = Path(path)
    if not path.is_file():
        return [f"{path} does not exist"]
    try:
        png = read_png(path)
    except (ValueError, struct.error) as e:
        return [f"{path}: {e}"]
    problems = []
    if width is not None and png.width != width:
        problems.append(f"{path}: width is {png.width}, expected {width}")
    if height is not None and png.height != height:
        problems.append(f"{path}: height is {png.height}, expected {height}")
    if not_blank or min_colors:
        try:
            colors = set(png.pixels())
        except (ValueError, zlib.error) as e:
            return problems + [f"{path}: {e}"]
        if not_blank and len(colors) < 2:
            problems.append(f"{path}: blank (every pixel is the same colour)")
        if min_colors and len(colors) < min_colors:
            problems.append(f"{path}: {len(colors)} distinct colours, expected at least {min_colors}")
    return problems


# --- sprite sheets --------------------------------------------------------------------

def _size(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+)x(\d+)", text.strip())
    if not m or int(m[1]) < 1 or int(m[2]) < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a size like 16x16")
    return int(m[1]), int(m[2])


def check_sheet(path: str | Path, frame: tuple[int, int], frames: int, data: str | Path | None = None,
                frames_drawn: bool = False) -> list[str]:
    path = Path(path)
    if not path.is_file():
        return [f"{path} does not exist"]
    try:
        png = read_png(path)
    except (ValueError, struct.error) as e:
        return [f"{path}: {e}"]
    fw, fh = frame
    problems = []
    if png.width % fw or png.height % fh:
        problems.append(f"{path}: {png.width}x{png.height} is not a whole grid of {fw}x{fh} frames")
    cols, rows = png.width // fw, png.height // fh
    if cols * rows < frames:
        problems.append(f"{path}: room for {cols * rows} frames of {fw}x{fh}, expected {frames}")
    rects = [(i % cols * fw, i // cols * fh) for i in range(min(frames, cols * rows))] if cols else []
    if data is not None:
        data = Path(data)
        try:
            meta = json.loads(data.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return problems + [f"{data}: not readable JSON ({e})"]
        listed = meta.get("frames") if isinstance(meta, dict) else None
        listed = list(listed.values()) if isinstance(listed, dict) else listed
        if not isinstance(listed, list):
            return problems + [f"{data}: no 'frames' list or map (Aseprite --data output)"]
        if len(listed) != frames:
            problems.append(f"{data}: {len(listed)} frames, expected {frames}")
        rects = []
        for i, f in enumerate(listed):
            r = f.get("frame", {}) if isinstance(f, dict) else {}
            x, y, w, h = (r.get(k) for k in ("x", "y", "w", "h"))
            if not all(isinstance(v, int) for v in (x, y, w, h)):
                problems.append(f"{data}: frame {i} has no x, y, w, h")
                continue
            if (w, h) != (fw, fh):
                problems.append(f"{data}: frame {i} is {w}x{h}, expected {fw}x{fh}")
            if x < 0 or y < 0 or x + w > png.width or y + h > png.height:
                problems.append(f"{data}: frame {i} at {x},{y} lies outside the {png.width}x{png.height} sheet")
            else:
                rects.append((x, y))
    if frames_drawn and not problems:
        try:
            for i, (x, y) in enumerate(rects):
                px = png.pixels(x, y, fw, fh)
                if all(png.transparent(p) for p in px) or len(set(px)) < 2:
                    problems.append(f"{path}: frame {i} at {x},{y} is empty (one colour or fully transparent)")
        except (ValueError, zlib.error) as e:
            problems.append(f"{path}: {e}")
    return problems


# --- glTF binary ----------------------------------------------------------------------

COMPONENT_BYTES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


def read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    if len(data) < 20:
        raise ValueError("too short to be a .glb")
    magic, version, length = struct.unpack("<4sII", data[:12])
    if magic != b"glTF":
        raise ValueError("not a glTF binary (no 'glTF' magic)")
    if version != 2:
        raise ValueError(f"glTF binary version {version}, expected 2")
    if length != len(data):
        raise ValueError(f"header says {length} bytes, file has {len(data)} (truncated?)")
    clen, ctype = struct.unpack("<I4s", data[12:20])
    if ctype != b"JSON":
        raise ValueError("first chunk is not JSON")
    doc = json.loads(data[20:20 + clen].decode("utf-8"))
    pos, binary = 20 + clen, b""
    if pos + 8 <= len(data):
        blen, btype = struct.unpack("<I4s", data[pos:pos + 8])
        if btype == b"BIN\x00":
            binary = data[pos + 8:pos + 8 + blen]
            if len(binary) != blen:
                raise ValueError("BIN chunk is cut short")
    return doc, binary


def triangles(doc: dict) -> int:
    count = 0
    accessors = doc.get("accessors", [])
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            if prim.get("mode", 4) != 4:
                continue
            idx = prim.get("indices")
            src = idx if idx is not None else prim.get("attributes", {}).get("POSITION")
            if isinstance(src, int) and 0 <= src < len(accessors):
                count += accessors[src].get("count", 0) // 3
    return count


def check_glb(path: str | Path, min_meshes: int = 1, min_animations: int = 0, min_materials: int = 0,
              max_triangles: int | None = None) -> list[str]:
    path = Path(path)
    if not path.is_file():
        return [f"{path} does not exist"]
    try:
        doc, binary = read_glb(path)
    except (ValueError, struct.error, UnicodeDecodeError) as e:
        return [f"{path}: {e}"]
    problems = []
    if str(doc.get("asset", {}).get("version")) != "2.0":
        problems.append(f"{path}: asset.version is {doc.get('asset', {}).get('version')!r}, expected '2.0'")
    buffers = doc.get("buffers", [])
    for i, b in enumerate(buffers):
        if "uri" not in b and b.get("byteLength", 0) > len(binary):
            problems.append(f"{path}: buffer {i} needs {b.get('byteLength')} bytes, the BIN chunk has {len(binary)}")
    views = doc.get("bufferViews", [])
    for i, v in enumerate(views):
        b = v.get("buffer")
        if not isinstance(b, int) or not 0 <= b < len(buffers):
            problems.append(f"{path}: bufferView {i} names buffer {b!r}, which does not exist")
        elif v.get("byteOffset", 0) + v.get("byteLength", 0) > buffers[b].get("byteLength", 0):
            problems.append(f"{path}: bufferView {i} runs past the end of buffer {b}")
    for i, a in enumerate(doc.get("accessors", [])):
        v = a.get("bufferView")
        if v is None:
            continue
        if not isinstance(v, int) or not 0 <= v < len(views):
            problems.append(f"{path}: accessor {i} names bufferView {v!r}, which does not exist")
            continue
        size = COMPONENT_BYTES.get(a.get("componentType"), 0) * TYPE_COUNT.get(a.get("type"), 0)
        stride = views[v].get("byteStride", size)
        need = a.get("byteOffset", 0) + (stride * (a.get("count", 0) - 1) + size if a.get("count", 0) else 0)
        if not size:
            problems.append(f"{path}: accessor {i} has an unknown componentType or type")
        elif need > views[v].get("byteLength", 0):
            problems.append(f"{path}: accessor {i} reads past the end of bufferView {v}")
    accessors = doc.get("accessors", [])
    for mi, mesh in enumerate(doc.get("meshes", [])):
        for pi, prim in enumerate(mesh.get("primitives", [])):
            for name, ref in list(prim.get("attributes", {}).items()) + [("indices", prim.get("indices"))]:
                if ref is not None and (not isinstance(ref, int) or not 0 <= ref < len(accessors)):
                    problems.append(f"{path}: mesh {mi} primitive {pi} {name} names accessor {ref!r}, "
                                    "which does not exist")
    meshes, anims, mats = (len(doc.get(k, [])) for k in ("meshes", "animations", "materials"))
    if meshes < min_meshes:
        problems.append(f"{path}: {meshes} meshes, expected at least {min_meshes}")
    if anims < min_animations:
        problems.append(f"{path}: {anims} animations, expected at least {min_animations}")
    if mats < min_materials:
        problems.append(f"{path}: {mats} materials, expected at least {min_materials}")
    if max_triangles is not None and triangles(doc) > max_triangles:
        problems.append(f"{path}: {triangles(doc)} triangles, budget is {max_triangles}")
    return problems


# --- audio ----------------------------------------------------------------------------

def ogg_info(path: Path) -> tuple[str, int, int, float]:
    """(codec, channels, sample rate, seconds) of an Ogg Vorbis or Opus file."""
    data = path.read_bytes()
    if not data.startswith(b"OggS"):
        raise ValueError("not an Ogg file (no 'OggS' page)")
    nseg = data[26]
    body = data[27 + nseg:27 + nseg + sum(data[27:27 + nseg])]
    if body.startswith(b"\x01vorbis"):
        codec, channels, rate = "vorbis", body[11], struct.unpack("<I", body[12:16])[0]
        preskip, clock = 0, rate
    elif body.startswith(b"OpusHead"):
        codec, channels, rate = "opus", body[9], struct.unpack("<I", body[12:16])[0]
        preskip, clock = struct.unpack("<H", body[10:12])[0], 48000
    else:
        raise ValueError("Ogg stream is neither Vorbis nor Opus")
    last = data.rfind(b"OggS")
    granule = struct.unpack("<q", data[last + 6:last + 14])[0]
    if channels < 1 or clock < 1 or granule < 0:
        raise ValueError("Ogg headers are not valid")
    return codec, channels, rate, max(0, granule - preskip) / clock


def wav_format_tag(path: Path) -> int | None:
    """The WAVE format tag from the fmt chunk (1 PCM, 3 float, 0xFFFE extensible), or None if there is none."""
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos = 12
    while pos + 8 <= len(data):
        kind, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if kind == b"fmt " and size >= 2:
            return struct.unpack("<H", data[pos + 8:pos + 10])[0]
        pos += 8 + size + (size & 1)
    return None


def wav_peak(w: wave.Wave_read) -> float:
    """Peak amplitude as a fraction of full scale."""
    width, raw = w.getsampwidth(), w.readframes(w.getnframes())
    if width == 1:
        return max((abs(b - 128) for b in raw), default=0) / 128
    full = float(1 << (8 * width - 1))
    peak = 0
    for i in range(0, len(raw) - width + 1, width):
        peak = max(peak, abs(int.from_bytes(raw[i:i + width], "little", signed=True)))
    return peak / full


def check_audio(path: str | Path, rate: int | None = None, channels: int | None = None,
                min_seconds: float | None = None, max_seconds: float | None = None, not_silent: bool = False,
                silence: float = 0.01) -> list[str]:
    path = Path(path)
    if not path.is_file():
        return [f"{path} does not exist"]
    problems = []
    try:
        if path.suffix.lower() == ".wav":
            if wav_format_tag(path) == 0xFFFE:
                # Measured: Godot 4.7.2 refuses it ("Format not supported for WAVE file (not PCM)"), and SoX 14.4.2
                # writes it by default for synthesised sound (32-bit). Python's wave module reads it, so check here.
                return [f"{path}: WAVE_FORMAT_EXTENSIBLE, which Godot cannot import; write plain 16-bit PCM "
                        "(sox: -b 16 before the output file; ffmpeg: -c:a pcm_s16le)"]
            with wave.open(str(path), "rb") as w:
                r, ch, secs = w.getframerate(), w.getnchannels(), w.getnframes() / w.getframerate()
                if not_silent and wav_peak(w) < silence:
                    problems.append(f"{path}: silent (peak below {silence:.0%} of full scale)")
        elif path.suffix.lower() in (".ogg", ".oga", ".opus"):
            if not_silent:
                return [f"{path}: --not-silent needs a .wav (check the WAV before encoding it)"]
            _, ch, r, secs = ogg_info(path)
        else:
            return [f"{path}: unsupported audio type (use .wav or .ogg)"]
    except (wave.Error, EOFError, ValueError, struct.error, IndexError, ZeroDivisionError) as e:
        return [f"{path}: {e}"]
    if rate is not None and r != rate:
        problems.append(f"{path}: sample rate {r}, expected {rate}")
    if channels is not None and ch != channels:
        problems.append(f"{path}: {ch} channels, expected {channels}")
    if min_seconds is not None and secs < min_seconds:
        problems.append(f"{path}: {secs:.3f}s long, expected at least {min_seconds}s")
    if max_seconds is not None and secs > max_seconds:
        problems.append(f"{path}: {secs:.3f}s long, expected at most {max_seconds}s")
    return problems


# --- Tiled maps -----------------------------------------------------------------------

FLIP_BITS = 0xF0000000


def _tmx_layer_data(el: ET.Element, n: int) -> list[int]:
    data = el.find("data")
    if data is None:
        raise ValueError(f"layer {el.get('name')!r} has no data")
    enc, comp, text = data.get("encoding"), data.get("compression"), (data.text or "").strip()
    if enc == "csv":
        return [int(x) for x in text.replace("\n", "").split(",") if x.strip()]
    if enc == "base64":
        raw = base64.b64decode(text)
        raw = zlib.decompress(raw) if comp == "zlib" else gzip.decompress(raw) if comp == "gzip" else raw
        if comp not in (None, "zlib", "gzip"):
            raise ValueError(f"layer {el.get('name')!r} uses {comp} compression, which this check cannot read")
        return list(struct.unpack(f"<{len(raw) // 4}I", raw))
    return [int(t.get("gid", 0)) for t in data.findall("tile")]


def read_map(path: Path) -> dict:
    """A Tiled map as {width, height, tilewidth, tileheight, layers: [(name, kind, data|None)], tilesets: [(first, count)]}"""
    if path.suffix.lower() == ".json" or path.suffix.lower() == ".tmj":
        m = json.loads(path.read_text(encoding="utf-8"))
        tilesets = []
        for ts in m.get("tilesets", []):
            if "source" in ts:
                src = path.parent / ts["source"]
                ext = json.loads(src.read_text(encoding="utf-8")) if src.suffix in (".json", ".tsj") else \
                    {"tilecount": int(ET.parse(src).getroot().get("tilecount", 0))}
                tilesets.append((ts["firstgid"], ext.get("tilecount", 0)))
            else:
                tilesets.append((ts["firstgid"], ts.get("tilecount", 0)))
        layers = []
        for la in m.get("layers", []):
            data = la.get("data")
            if isinstance(data, str):
                raw = base64.b64decode(data)
                comp = la.get("compression", "")
                raw = zlib.decompress(raw) if comp == "zlib" else gzip.decompress(raw) if comp == "gzip" else raw
                data = list(struct.unpack(f"<{len(raw) // 4}I", raw))
            layers.append((la.get("name", ""), la.get("type", ""), data))
        return {"width": m.get("width"), "height": m.get("height"), "tilewidth": m.get("tilewidth"),
                "tileheight": m.get("tileheight"), "layers": layers, "tilesets": tilesets}
    root = ET.parse(path).getroot()
    if root.tag != "map":
        raise ValueError("not a Tiled map (root element is not <map>)")
    w, h = int(root.get("width", 0)), int(root.get("height", 0))
    tilesets = []
    for ts in root.findall("tileset"):
        count = ts.get("tilecount")
        if ts.get("source"):
            count = ET.parse(path.parent / ts.get("source")).getroot().get("tilecount")
        tilesets.append((int(ts.get("firstgid", 1)), int(count or 0)))
    layers = []
    for el in root:
        if el.tag == "layer":
            layers.append((el.get("name", ""), "tilelayer", _tmx_layer_data(el, w * h)))
        elif el.tag in ("objectgroup", "imagelayer", "group"):
            layers.append((el.get("name", ""), el.tag, None))
    return {"width": w, "height": h, "tilewidth": int(root.get("tilewidth", 0)),
            "tileheight": int(root.get("tileheight", 0)), "layers": layers, "tilesets": tilesets}


def check_tiled(path: str | Path, width: int | None = None, height: int | None = None,
                tile_size: tuple[int, int] | None = None, layers: list[str] | None = None) -> list[str]:
    path = Path(path)
    if not path.is_file():
        return [f"{path} does not exist"]
    try:
        m = read_map(path)
    except (OSError, ValueError, KeyError, ET.ParseError, struct.error, zlib.error) as e:
        return [f"{path}: {e}"]
    problems = []
    if width is not None and m["width"] != width:
        problems.append(f"{path}: {m['width']} tiles wide, expected {width}")
    if height is not None and m["height"] != height:
        problems.append(f"{path}: {m['height']} tiles high, expected {height}")
    if tile_size and (m["tilewidth"], m["tileheight"]) != tile_size:
        problems.append(f"{path}: tiles are {m['tilewidth']}x{m['tileheight']}, expected {tile_size[0]}x{tile_size[1]}")
    names = [n for n, _, _ in m["layers"]]
    for want in layers or []:
        if want not in names:
            problems.append(f"{path}: no layer named {want!r} (has: {', '.join(names) or 'none'})")
    if not m["tilesets"]:
        problems.append(f"{path}: no tilesets")
    for name, kind, data in m["layers"]:
        if kind != "tilelayer" or data is None:
            continue
        if len(data) != (m["width"] or 0) * (m["height"] or 0):
            problems.append(f"{path}: layer {name!r} has {len(data)} cells, expected {m['width']}x{m['height']}")
        bad = sorted({gid & ~FLIP_BITS for gid in data if gid & ~FLIP_BITS and not any(
            first <= gid & ~FLIP_BITS < first + count for first, count in m["tilesets"])})
        if bad:
            problems.append(f"{path}: layer {name!r} uses tile ids no tileset has: {bad[:10]}")
    return problems


# --- SVG ------------------------------------------------------------------------------

DRAWN = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "image", "use"}


def check_svg(path: str | Path) -> list[str]:
    path = Path(path)
    if not path.is_file():
        return [f"{path} does not exist"]
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        return [f"{path}: not well-formed XML ({e})"]
    problems = []
    if root.tag.rsplit("}", 1)[-1] != "svg":
        problems.append(f"{path}: root element is <{root.tag}>, not <svg>")
    if not root.get("viewBox") and not (root.get("width") and root.get("height")):
        problems.append(f"{path}: no viewBox and no width and height, so it has no size")
    if not any(el.tag.rsplit("}", 1)[-1] in DRAWN for el in root.iter()):
        problems.append(f"{path}: draws nothing (no path, shape, text or image)")
    return problems


# --- Godot projects -------------------------------------------------------------------

RES = re.compile(r"""res://[^"'\s)\]]+""")


def check_godot(project: str | Path) -> list[str]:
    project = Path(project)
    cfg = project / "project.godot"
    if not cfg.is_file():
        return [f"{project}: no project.godot (not a Godot project)"]
    text = cfg.read_text(encoding="utf-8", errors="replace")
    problems = []
    m = re.search(r"^config_version=(\d+)", text, re.M)
    if not m or int(m[1]) < 5:
        problems.append(f"{cfg}: config_version is {m[1] if m else 'missing'}, expected 5 (Godot 4)")
    sources = [cfg] + [p for p in project.rglob("*") if p.suffix in (".tscn", ".tres", ".gd", ".gdshader")
                       and ".godot" not in p.relative_to(project).parts]
    seen = set()
    for src in sources:
        for ref in RES.findall(src.read_text(encoding="utf-8", errors="replace")):
            ref = ref.rstrip(".,;")
            if ref in seen or "*" in ref or "%" in ref or ref.endswith("/"):
                continue
            seen.add(ref)
            if not (project / ref[len("res://"):]).exists():
                problems.append(f"{src.relative_to(project).as_posix()}: refers to {ref}, which does not exist")
    return problems


# --- command line ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m apiary.gates.assets", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="kind", required=True)
    p = sub.add_parser("png")
    p.add_argument("file"); p.add_argument("--width", type=int); p.add_argument("--height", type=int)
    p.add_argument("--not-blank", action="store_true"); p.add_argument("--min-colors", type=int, default=0)
    p = sub.add_parser("sheet")
    p.add_argument("file"); p.add_argument("--frame", type=_size, required=True)
    p.add_argument("--frames", type=int, required=True); p.add_argument("--data")
    p.add_argument("--frames-drawn", action="store_true")
    p = sub.add_parser("glb")
    p.add_argument("file"); p.add_argument("--min-meshes", type=int, default=1)
    p.add_argument("--min-animations", type=int, default=0); p.add_argument("--min-materials", type=int, default=0)
    p.add_argument("--max-triangles", type=int)
    p = sub.add_parser("audio")
    p.add_argument("file"); p.add_argument("--rate", type=int); p.add_argument("--channels", type=int)
    p.add_argument("--min-seconds", type=float); p.add_argument("--max-seconds", type=float)
    p.add_argument("--not-silent", action="store_true")
    p = sub.add_parser("tiled")
    p.add_argument("file"); p.add_argument("--width", type=int); p.add_argument("--height", type=int)
    p.add_argument("--tile-size", type=_size); p.add_argument("--layers")
    p = sub.add_parser("svg")
    p.add_argument("file")
    p = sub.add_parser("godot")
    p.add_argument("project")
    a = ap.parse_args(argv)
    if a.kind == "png":
        problems = check_png(a.file, a.width, a.height, a.not_blank, a.min_colors)
    elif a.kind == "sheet":
        problems = check_sheet(a.file, a.frame, a.frames, a.data, a.frames_drawn)
    elif a.kind == "glb":
        problems = check_glb(a.file, a.min_meshes, a.min_animations, a.min_materials, a.max_triangles)
    elif a.kind == "audio":
        problems = check_audio(a.file, a.rate, a.channels, a.min_seconds, a.max_seconds, a.not_silent)
    elif a.kind == "tiled":
        problems = check_tiled(a.file, a.width, a.height, a.tile_size,
                               [x.strip() for x in a.layers.split(",")] if a.layers else None)
    elif a.kind == "svg":
        problems = check_svg(a.file)
    else:
        problems = check_godot(a.project)
    for line in problems:
        print(f"FAIL {line}")
    if not problems:
        print(f"PASS {a.kind} {getattr(a, 'file', None) or a.project}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
