"""Connectors: outside programs a colony may drive (spec section 13)."""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
MAX_TIMEOUT_S = 3600                                               # C-6


@dataclass
class Connector:
    name: str
    program: str
    version_args: list[str]
    version_pattern: str
    version: str = ""
    description: str = ""
    timeout_s: int | None = None                                   # C-6
    error_patterns: list[str] = field(default_factory=list)       # C-6

    def errors(self, text: str) -> list[str]:
        """C-6: the output lines that match an error pattern (at most 20)."""
        found = [ln.strip() for ln in text.splitlines() if any(re.search(p, ln) for p in self.error_patterns)]
        return found[:20]

    def resolve(self) -> str | None:
        p = Path(self.program)
        if p.is_absolute() or "/" in self.program or "\\" in self.program:
            return str(p) if p.exists() else None
        return shutil.which(self.program)

    def probe(self) -> str:
        """The program's version as it reports it now, or "unknown"."""
        exe = self.resolve()
        if not exe:
            return "unknown"
        try:
            # 120 s: Inkscape 1.4.4's --version took 29 s on a busy machine, and over 60 s once (Measured)
            r = subprocess.run([exe, *self.version_args], capture_output=True, stdin=subprocess.DEVNULL, timeout=120)
            m = re.search(self.version_pattern, (r.stdout + r.stderr).decode("utf-8", "replace"))
        except (OSError, subprocess.TimeoutExpired):
            m = None
        if not m:
            # Windows GUI programs may print nothing (Measured: Tiled 1.12.2's --version); use the file's own version.
            m = re.search(self.version_pattern, file_version(exe))
        return m.group(1) if m else "unknown"


def file_version(path: str) -> str:
    """The product version in a Windows program's version resource ("1.12.2.0"), or "" elsewhere or if none."""
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes
    try:
        ver = ctypes.WinDLL("version")
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return ""
        info, n = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(info), ctypes.byref(n)) or n.value < 52:
            return ""
        words = ctypes.cast(info, ctypes.POINTER(wintypes.DWORD * 13)).contents
        ms, ls = words[4], words[5]                     # VS_FIXEDFILEINFO.dwProductVersionMS and LS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except (OSError, AttributeError):
        return ""


def load(root: Path, name: str) -> Connector | None:
    """The connector `name`, or None if there is none. Raises ValueError if its file is malformed (C-1)."""
    if not NAME.match(name):
        return None
    path = root / "connectors" / f"{name}.toml"
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"connectors/{name}.toml is not valid UTF-8 TOML: {e}") from None
    missing = [k for k in ("program", "version_args", "version_pattern") if k not in data]
    if missing or not isinstance(data.get("version_args"), list):
        raise ValueError(f"connectors/{name}.toml needs program, version_args (a list) and version_pattern")
    try:
        re.compile(data["version_pattern"])
    except re.error as e:
        raise ValueError(f"connectors/{name}.toml: version_pattern is not a regular expression ({e})") from None
    timeout = data.get("timeout_s")
    if timeout is not None and (type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT_S):
        raise ValueError(f"connectors/{name}.toml: timeout_s must be a whole number of seconds, 1 to {MAX_TIMEOUT_S}")
    patterns = data.get("error_patterns", [])
    if not isinstance(patterns, list) or not all(isinstance(x, str) for x in patterns):
        raise ValueError(f"connectors/{name}.toml: error_patterns must be a list of strings")
    for x in patterns:
        try:
            re.compile(x)
        except re.error as e:
            raise ValueError(f"connectors/{name}.toml: error pattern {x!r} is not a regular expression ({e})") from None
    return Connector(name, str(data["program"]), [str(a) for a in data["version_args"]], data["version_pattern"],
                     str(data.get("version", "")), str(data.get("description", "")), timeout, patterns)


def names(root: Path) -> list[str]:
    d = root / "connectors"
    return sorted(p.stem for p in d.glob("*.toml") if NAME.match(p.stem)) if d.is_dir() else []


def to_toml(c: Connector) -> str:
    def q(s: str) -> str:                     # a JSON string is a valid TOML basic string
        return json.dumps(s)
    lines = [f"# Connector: an outside program this colony may run (spec section 13). Human-owned.",
             f"program = {q(c.program)}",
             f"version_args = [{', '.join(q(a) for a in c.version_args)}]",
             f"version_pattern = {q(c.version_pattern)}"]
    if c.version:
        lines.append(f"version = {q(c.version)}")
    if c.description:
        lines.append(f"description = {q(c.description)}")
    if c.timeout_s:
        lines.append(f"timeout_s = {c.timeout_s}")
    if c.error_patterns:
        lines.append(f"error_patterns = [{', '.join(q(x) for x in c.error_patterns)}]")
    return "\n".join(lines) + "\n"


# --- the catalog of programs `apiary connect add` knows how to find ----------------

@dataclass
class Known:
    description: str
    commands: list[str]                                  # names to look up on PATH
    places: list[str] = field(default_factory=list)      # glob patterns of install locations (~ is expanded)
    version_args: list[str] = field(default_factory=lambda: ["--version"])
    version_pattern: str = r"(\d+\.\d+(?:\.\d+)?)"
    how: str = ""                                        # how an agent drives it headlessly (for the skill)
    timeout_s: int | None = None                         # C-6, written into the connector
    error_patterns: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)      # skills `connect add` installs (templates/skills/<name>.md)


WINGET = "~/AppData/Local/Microsoft/WinGet"
STEAM = "C:/Program Files (x86)/Steam/steamapps/common"

CATALOG: dict[str, Known] = {
    "blender": Known(
        "Blender: 3D modelling, rendering and export",
        ["blender"],
        ["C:/Program Files/Blender Foundation/Blender */blender.exe", f"{STEAM}/Blender/blender.exe",
         "/Applications/Blender.app/Contents/MacOS/Blender", "/usr/bin/blender", "/snap/bin/blender"],
        ["--version"], r"Blender (\d+\.\d+(?:\.\d+)?)",
        "Never open the GUI. Run `--background --factory-startup --python-exit-code 1 --python <script.py> -- <args>`. "
        "Always pass `--python-exit-code 1`: without it Blender exits 0 even when your script crashes (measured with "
        "Blender 4.4.3), so a failed run looks like a success. Put the work in a Python script (bpy) inside the task's "
        "`writes`, read your own arguments after `--` from `sys.argv`, create output folders with `os.makedirs`, and "
        "save or export to the paths you pass as `outputs`. Check the run record says every output was written. "
        "Rendering: set the engine, resolution and output path in the script, then "
        "`bpy.ops.render.render(write_still=True)`. Export: `bpy.ops.export_scene.gltf(...)`. "
        "Skill: `blender-asset-pipeline`.",
        900, [r"^Traceback \(most recent call last\)", r"^Error: "], ["blender-asset-pipeline"]),
    "node": Known("Node.js: JavaScript runtime", ["node"], [], ["--version"], r"v(\d+\.\d+\.\d+)",
                  "Run a script: `args` = `path/to/script.mjs <args>`."),
    "git": Known("Git: version control", ["git"], [], ["--version"], r"git version (\S+)",
                 "Read-only use only (log, show, diff). Commits are the human's."),
    "ffmpeg": Known(
        "FFmpeg: audio and video conversion", ["ffmpeg"], [f"{WINGET}/Links/ffmpeg.exe"], ["-version"],
        r"ffmpeg version (\d+\.\d+(?:\.\d+)?)",
        "Always pass `-nostdin -y -loglevel error`; list the output file in `outputs`. Skill: `game-audio`.",
        600, [], ["game-audio"]),
    "sox": Known(
        "SoX: sound synthesis and audio effects", ["sox"],
        [f"{WINGET}/Packages/ChrisBagwell.SoX*/sox-*/sox.exe", "C:/Program Files (x86)/sox-*/sox.exe"],
        ["--version"], r"SoX v(\d+\.\d+(?:\.\d+)?)",
        "Make a sound from nothing with `-n <out.wav> synth <seconds> <wave> <freq>`, then effects "
        "(`fade`, `vol`, `reverb`, `pitch`). Skill: `game-audio`.",
        120, [r"\bFAIL\b"], ["game-audio"]),
    "godot": Known(
        "Godot: game engine", ["godot", "godot4"],
        ["C:/Program Files/Godot*/Godot*console.exe", "C:/Program Files/Godot*/Godot*.exe",
         f"{STEAM}/Godot Engine/godot*.exe", "/Applications/Godot.app/Contents/MacOS/Godot", "/usr/bin/godot"],
        ["--version"], r"(\d+\.\d+(?:\.\d+)?)",
        "Always `--headless --path <project>`. Import assets: `--headless --path <project> --import`. Run a script: "
        "`--headless --path <project> --script res://<script>.gd`; the script must extend SceneTree and call "
        "`quit(<code>)`. Measured with Godot 4.7.2: a runtime error before `quit()` never exits, and with "
        "`--quit-after` it exits 0, so this connector stops runs at its `timeout_s` and fails on `SCRIPT ERROR`. "
        "Skills: `godot-project`, `godot-gdscript-tests`.",
        300, [r"^SCRIPT ERROR", r"^ERROR: ", r"Parse Error"], ["godot-project", "godot-gdscript-tests"]),
    "aseprite": Known(
        "Aseprite: pixel art and sprite sheets", ["aseprite"],
        [f"{STEAM}/Aseprite/Aseprite.exe", "C:/Program Files/Aseprite/Aseprite.exe",
         "/Applications/Aseprite.app/Contents/MacOS/aseprite"],
        ["--version"], r"Aseprite (\d+\.\d+(?:\.\d+)*)",
        "Always `-b` (batch). Draw with a Lua script: `-b --script-param out=<file.aseprite> --script <make.lua>`. "
        "Export a sheet: `-b <in.aseprite> --sheet <out.png> --data <out.json> --format json-array --sheet-type rows`. "
        "Measured with Aseprite 1.3.18.3: a missing input file exits 0 and writes nothing, so list every output in "
        "`outputs`. Skill: `sprite-pipeline`.",
        120, [r"No documents to export", r"File not found", r"\.lua:\d+:"], ["sprite-pipeline"]),
    "tiled": Known(
        "Tiled: tile map editor", ["tiled"],
        ["C:/Program Files/Tiled/tiled.exe", "/Applications/Tiled.app/Contents/MacOS/Tiled", "/usr/bin/tiled"],
        ["--version"], r"(\d+\.\d+(?:\.\d+)?)",
        "Convert a map: `--export-map json <map.tmx> <map.json>` (or `lua`, `tmx`). Write maps as TMX (XML) or "
        "JSON yourself; Tiled checks and converts them. On Linux it needs a display (`xvfb-run`). Skill: `tilemaps`.",
        120, [r"^Failed to", r"[Ee]rror (?:reading|loading|opening)"], ["tilemaps"]),
    "inkscape": Known(
        "Inkscape: vector art and SVG export", ["inkscape"],
        ["C:/Program Files/Inkscape/bin/inkscape.com", "C:/Program Files/Inkscape/bin/inkscape.exe",
         "/Applications/Inkscape.app/Contents/MacOS/inkscape", "/usr/bin/inkscape"],
        ["--version"], r"Inkscape (\d+\.\d+(?:\.\d+)?)",
        "Render SVG to PNG: `<in.svg> --export-type=png --export-filename=<out.png> -w <width>`. Measured with "
        "Inkscape 1.4.4: a missing file exits 0 and writes nothing, and a malformed SVG exits 0 and writes a blank "
        "300x150 PNG; this connector fails on those messages. Skill: `vector-art`.",
        180, [r"Can't open file", r"Failed to open", r"cannot be opened", r"parser error"], ["vector-art"]),
}


def find(name: str) -> str | None:
    known = CATALOG[name]
    for cmd in known.commands:
        found = shutil.which(cmd)
        if found:
            return Path(found).as_posix()
    for pattern in known.places:
        hits = sorted(glob.glob(os.path.expanduser(pattern)), reverse=True)   # the newest version folder first
        if hits:
            return Path(hits[0]).as_posix()
    return None
