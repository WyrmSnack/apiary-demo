"""The realm: a colony that is a vassal of a realm reads the decrees its Supreme Queen seals (ADR 0005).

A realm root holds `realm/decrees/NNN-slug.decree`, each with the fields `to` (a vassal id, or `*` for every vassal),
`objective`, `why`, `priority` and `issued`. A colony learns its realm from `apiary init --realm <path>`, stored in
`.apiary/realm.json` (guarded: an agent cannot repoint its colony), or from the environment variable APIARY_REALM.

A vassal answers only in its own ledger. Any line naming a decree acknowledges it; a DONE line naming it fulfils
it. DONE lines come only from close_task (L-10), so the task that finishes a decree has the slug `decree-<id>`.
Reading decrees writes nothing.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

REALM_FILE = Path(".apiary/realm.json")
ENV = "APIARY_REALM"
DECREES = Path("realm/decrees")
_FIELD = re.compile(r"^(\w+):[ \t]*(.*)$", re.M)


@dataclass(frozen=True)
class Decree:
    id: str
    to: str
    objective: str
    why: str
    priority: str
    issued: str
    state: str = "open"                       # open, acknowledged or fulfilled, from this colony's ledger


@dataclass(frozen=True)
class Realm:
    root: Path | None
    vassal_id: str
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class View:
    realm: Realm
    decrees: list[Decree]
    problems: list[str]


def ack_path(decree_id: str) -> str:
    """The ledger path of an acknowledgement: what the Throne Room and the realm survey match."""
    return f"{DECREES.as_posix()}/{decree_id}.decree"


def task_slug(decree_id: str) -> str:
    """The slug of the task that finishes a decree. Closing it writes the DONE line that names the decree."""
    return "decree-" + decree_id.strip("-")


def names(line: str, decree_id: str) -> bool:
    """Whether a ledger line names a decree: its id, not a longer id that starts or ends with it."""
    key = re.escape(decree_id.strip("-"))
    return re.search(rf"(?<![0-9a-z]){key}(?![0-9a-z]|-[0-9a-z])", line) is not None


def default_id(colony_root: Path, realm_root: Path) -> str:
    """A vassal's id is its folder name in lower case: the first folder under <realm>/projects/, else the colony's."""
    root = colony_root.resolve()
    try:
        parts = root.relative_to((realm_root / "projects").resolve()).parts
    except ValueError:
        parts = ()
    return (parts[0] if parts else root.name).lower()


def check_realm(realm_root: str | Path) -> str:
    """'' if the folder is a realm root, else why not."""
    path = Path(realm_root).resolve()
    if (path / "realm").is_dir():
        return ""
    hint = f" Did you mean {path.parent}?" if path.name == "realm" and path.is_dir() else ""
    return f"refused: {path} is not a realm root: it has no realm/ folder.{hint} Nothing was changed."


def check_id(vassal_id: str) -> str:
    if not vassal_id or vassal_id == "*" or re.search(r"[\s|]", vassal_id):
        return f"refused: {vassal_id!r} is not a vassal id (a folder name: no spaces, no '|', not '*')"
    return ""


def set_realm(colony_root: str | Path, realm_root: str | Path, vassal_id: str = "") -> tuple[int, list[str]]:
    """Record this colony's realm in .apiary/realm.json. Returns (exit status, report lines); no lines = no change."""
    root, realm = Path(colony_root).resolve(), Path(realm_root).resolve()
    vid = vassal_id.strip().lower() or default_id(root, realm)
    problem = check_realm(realm) or check_id(vid)
    if problem:
        return 1, [problem]
    data = {"root": realm.as_posix(), "id": vid}
    path = root / REALM_FILE
    try:
        if json.loads(path.read_text(encoding="utf-8")) == data:
            return 0, []
    except (OSError, ValueError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0, [f"this colony is vassal {vid} of the realm at {realm.as_posix()} ({REALM_FILE.as_posix()}); "
               "its Queen reads that realm's decrees on waking"]


def realm_of(colony_root: str | Path) -> Realm:
    """This colony's realm: APIARY_REALM if set, else .apiary/realm.json, else none."""
    root = Path(colony_root).resolve()
    stored: dict = {}
    problems: list[str] = []
    path = root / REALM_FILE
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(stored, dict):
                raise ValueError("expected an object")
        except (OSError, ValueError) as e:
            stored = {}
            problems.append(f"{REALM_FILE.as_posix()} is not readable ({e}); run `apiary init --realm <path>` again")
    env = os.environ.get(ENV, "").strip()
    where = env or str(stored.get("root", "")).strip()
    if not where:
        return Realm(None, "", problems)
    realm = Path(where).resolve()
    vid = str(stored.get("id", "")).strip().lower() or default_id(root, realm)
    if not (realm / "realm").is_dir():
        problems.append(f"the realm at {realm.as_posix()} has no realm/ folder (moved?)")
    return Realm(realm, vid, problems)


def _decree(path: Path) -> Decree:
    text = path.read_bytes().decode("utf-8")                # strict: a decree in another encoding is reported
    fields = dict(_FIELD.findall(text.replace("\r\n", "\n")))
    pr = fields.get("priority", "").strip()
    return Decree(path.stem, fields.get("to", "*").strip().lower() or "*", fields.get("objective", "").strip(),
                  fields.get("why", "").strip(), pr if pr in ("low", "high") else "normal",
                  fields.get("issued", "").strip())


def decrees_for(colony_root: str | Path) -> View:
    """The decrees addressed to this colony (its id or '*'), each with its state from this colony's ledger."""
    root = Path(colony_root).resolve()
    where = realm_of(root)
    problems = list(where.problems)
    if where.root is None:
        return View(where, [], problems)
    ledger = root / "PHEROMONE_LEDGER.md"
    lines = [ln for ln in (ledger.read_text(encoding="utf-8", errors="replace").splitlines() if ledger.exists() else [])
             if ln.strip() and not ln.startswith("#")]
    out: list[Decree] = []
    folder = where.root / DECREES
    for path in sorted(folder.glob("*.decree")) if folder.is_dir() else []:
        try:
            d = _decree(path)
        except (OSError, UnicodeDecodeError) as e:
            problems.append(f"{ack_path(path.stem)} is not readable UTF-8 ({type(e).__name__}); skipped")
            continue
        if d.to not in (where.vassal_id, "*"):
            continue
        hits = [ln for ln in lines if names(ln, d.id)]
        done = any(ln.split(" | ")[2:3] == ["DONE"] for ln in hits)
        out.append(Decree(d.id, d.to, d.objective, d.why, d.priority, d.issued,
                          "fulfilled" if done else "acknowledged" if hits else "open"))
    return View(where, out, problems)


def report(colony_root: str | Path) -> str:
    """What `apiary decrees` and the realm_decrees tool print. The first word is DECREES."""
    view = decrees_for(colony_root)
    warns = [f"WARN {p}" for p in view.problems]
    if view.realm.root is None:
        return "\n".join(["DECREES none: this colony has no realm. The human sets one with "
                          "`apiary init --realm <path>`."] + warns)
    count = {s: sum(d.state == s for d in view.decrees) for s in ("open", "acknowledged", "fulfilled")}
    out = [f"DECREES vassal {view.realm.vassal_id} of the realm at {view.realm.root.as_posix()}: "
           + ", ".join(f"{n} {s}" for s, n in count.items())]
    for d in view.decrees:
        head = f"{d.state.upper()} {d.id} ({d.priority}, to {d.to}, issued {d.issued or '?'}): {d.objective}"
        if d.state == "open":
            out += [head, f"  why: {d.why or '(not given)'}",
                    f'  acknowledge: append_ledger(caste="Queen", signal="DEPOSIT", path="{ack_path(d.id)}", '
                    'note="acknowledged")',
                    f"  then plan it with the human; the task that finishes it has the slug {task_slug(d.id)}"]
        elif d.state == "acknowledged":
            out += [head, f"  finish: close the task with the slug {task_slug(d.id)}; its DONE line fulfils the decree"]
        else:
            out.append(head)
    return "\n".join(out + warns)
