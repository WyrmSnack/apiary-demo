"""`apiary connect add|list`: give a colony an outside program, and keep the colony-connectors skill current."""
from __future__ import annotations

from pathlib import Path

from . import connectors

SKILL_PATH = ".claude/skills/colony-connectors/SKILL.md"
SKILL_TEMPLATES = Path(__file__).parent / "templates" / "skills"     # one skill per program kind (Phase 10)


def skill_text(root: Path) -> str:
    names = connectors.names(root)
    lines = ["---", "name: colony-connectors",
             "description: Use the outside programs this colony is connected to (for example Blender) through the "
             "run_connector tool, so every run is recorded with the program's version and hashes of what it wrote. "
             "Use whenever a task needs a program other than Python.",
             "---", "", "# Outside programs in this colony", "",
             "Run them only with the `run_connector` tool, never from the shell. `run_connector` records the program,",
             "its version, the exact arguments, the exit code and a hash of every output in `runs/`, and logs it in the",
             "ledger, so the human and later agents can see where each file came from and rerun it.", "",
             "- `args`: the arguments, split like an acceptance line (no shell; double quotes around spaces).",
             "- `outputs`: every file the run should write, comma-separated. Hashes of these go into the record.",
             "- `task_file`: the task you are working on.",
             "- A failed run is still recorded. Read its `stderr` in the run record before trying again.",
             "- Put scripts you write for a program inside the task's `writes`. Never edit `connectors/` or `runs/`.",
             "- An acceptance command may start with a connector's name (`blender --background --python gates/x.py`).",
             ""]
    if not names:
        lines += ["This colony has no connectors yet. If a task needs one, escalate: a human adds it with",
                  "`py -m apiary connect add <name>`."]
    for name in names:
        try:
            c = connectors.load(root, name)
        except ValueError as e:
            lines += [f"## {name}", "", f"Broken connector file: {e}. Escalate.", ""]
            continue
        known = connectors.CATALOG.get(name)
        lines += [f"## `{name}`" + (f": {c.description}" if c.description else ""), "",
                  f"Version {c.version or 'unknown'} when connected."]
        if known and known.how:
            lines += ["", known.how]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_skill(root: Path) -> None:
    path = root / SKILL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(skill_text(root), encoding="utf-8", newline="\n")


def program_skills(root: Path) -> dict[str, str]:
    """The skills for the programs this colony is connected to: {colony-relative path: text}. None without connectors."""
    out: dict[str, str] = {}
    for name in connectors.names(root):
        known = connectors.CATALOG.get(name)
        for skill in known.skills if known else []:
            out[f".claude/skills/{skill}/SKILL.md"] = (SKILL_TEMPLATES / f"{skill}.md").read_text(encoding="utf-8")
    return out


def write_program_skills(root: Path) -> list[str]:
    """Install or refresh the connected programs' skills (apiary owns them, like colony-connectors)."""
    report = []
    for rel, text in program_skills(root).items():
        path = root / rel
        if path.exists() and path.read_text(encoding="utf-8").replace("\r\n", "\n") == text:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        report.append(f"installed the {rel.split('/')[2]} skill ({rel})")
    return report


def add(root: str | Path, name: str, program: str = "", version_args: list[str] | None = None,
        version_pattern: str = "", description: str = "") -> tuple[int, list[str]]:
    root = Path(root).resolve()
    if not connectors.NAME.match(name):
        return 1, [f"refused: connector name {name!r} must be lowercase letters, digits and '-' (2 to 31 characters)"]
    path = root / "connectors" / f"{name}.toml"
    if path.exists():
        return 1, [f"refused: connectors/{name}.toml already exists. Connectors are never overwritten; a human "
                   "edits or deletes the file to change it."]
    known = connectors.CATALOG.get(name)
    if not program:
        if not known:
            return 1, [f"refused: {name!r} is not a program apiary knows ({', '.join(sorted(connectors.CATALOG))}). "
                       "Pass --program <path>, --version-arg and --version-pattern to connect any other program."]
        program = connectors.find(name) or ""
        if not program:
            return 1, [f"{name} not found on PATH or in its usual install folders. If it is installed somewhere else, "
                       f"run: apiary connect add {name} --program <path to the program>"]
    c = connectors.Connector(
        name, Path(program).as_posix() if Path(program).exists() else program,
        version_args or (known.version_args if known else ["--version"]),
        version_pattern or (known.version_pattern if known else r"(\d+\.\d+(?:\.\d+)?)"),
        description=description or (known.description if known else ""),
        timeout_s=known.timeout_s if known else None, error_patterns=list(known.error_patterns) if known else [])
    if not c.resolve():
        return 1, [f"refused: {program!r} is not a program on this machine"]
    c.version = c.probe()
    if c.version == "unknown":
        return 1, [f"refused: ran {program} {' '.join(c.version_args)} but could not read a version with "
                   f"{c.version_pattern!r}. Pass --version-arg and --version-pattern that work for this program."]
    path.parent.mkdir(exist_ok=True)
    path.write_text(connectors.to_toml(c), encoding="utf-8", newline="\n")
    write_skill(root)
    installed = write_program_skills(root)
    return 0, [f"connected {name} {c.version} ({c.program})", f"wrote connectors/{name}.toml and {SKILL_PATH}",
               *installed, "start a new Claude Code session so it sees the connector"]


def list_lines(root: str | Path) -> list[str]:
    root = Path(root).resolve()
    out = []
    for name in connectors.names(root):
        try:
            c = connectors.load(root, name)
            now = c.probe()
            note = "" if now == c.version else f" (now reports {now})"
            out.append(f"{name:12} {c.version or '?':10} {c.program}{note}")
        except ValueError as e:
            out.append(f"{name:12} broken: {e}")
    return out or ["no connectors. Add one with: apiary connect add <name> (known: "
                   + ", ".join(sorted(connectors.CATALOG)) + ")"]
