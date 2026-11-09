"""The Colony Coordination Board (spec 0.9.0 B-1; Forge decree 003, TRACE board-home).

A plan, in exactly the shape create_plan takes (tasks and decisions), becomes a board model: one card per task,
coloured by who does it (`by:`, K-1), one link per dependency. The model is checked the way create_plan would check
it (a dry run that writes nothing) and for coordination findings:

  RUN <n> > <limit>   the longest chain of agent tasks, along depends_on, with no `by: Human` task in it
  NO-HUMAN            no task in the plan is `by: Human`, so the human sees nothing until it ends
  VERIFY-BY <slug>    a task in a verify lane that is not by a Guardian, or by the caste of a task it verifies

It is written to boards/<name>.board.json, boards/<name>.mmd (Mermaid) and boards/<name>.html (the Council of Agents'
board page, with the board embedded). Editing the HTML board only exports a revised plan.json for the Queen to pass
to create_plan: nothing here writes tasks/, the ledger or TRACES. A live board (`apiary board --live`) is drawn from
the task folders and the ledger instead: done, active, ready and blocked, with WARN and ESCALATE counts per task.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

from . import grammar as g

BOARDS = "boards"
DEFAULT_LIMIT = 3
KIND = {"Queen": "queen", "Forager": "forager", "Nurse": "nurse", "Guardian": "guardian", "Human": "checkpoint"}
SHAPE = {"human": ('(["', '"])'), "checkpoint": ('{{"', '"}}'), "check": ('{"', '"}')}
CLASSDEFS = [
    "classDef human fill:#f4c95d,stroke:#8a6a10,color:#3b2c00",
    "classDef checkpoint fill:#fff8e3,stroke:#d9a520,stroke-dasharray:5 4,color:#3b2c00",
    "classDef queen fill:#b9a3e3,stroke:#5c45a0,color:#271a45",
    "classDef forager fill:#8fd3b6,stroke:#2f7a5a,color:#0f3324",
    "classDef nurse fill:#f2a7a0,stroke:#a8473f,color:#4a1612",
    "classDef guardian fill:#9fb7de,stroke:#3b5e96,color:#13284a",
    "classDef check fill:#e2e5dc,stroke:#7a8273,color:#2a2f27",
]
NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
NOTE_FIELDS = ("objective", "why", "reads", "out_of_scope")
TEMPLATE = Path(__file__).parent / "templates" / "board.html"
X_STEP, Y_STEP = 240, 140


def is_verify_lane(lane: str) -> bool:
    return lane == "verify" or lane.startswith("verify-") or lane.endswith("-verify")


def note_links(task: dict, vault: str) -> list[dict]:
    """[[Note]] links in a card's text, as obsidian:// links (first appearance, in order)."""
    out, seen = [], set()
    for key in NOTE_FIELDS:
        value = task.get(key)
        for m in WIKILINK.finditer(value if isinstance(value, str) else ""):
            note = m.group(1).strip()
            if note and note not in seen:
                seen.add(note)
                out.append({"note": note, "url": f"obsidian://open?vault={quote(vault, safe='')}"
                                                  f"&file={quote(note, safe='')}"})
    return out


# --- findings ----------------------------------------------------------------------------

def findings(tasks: list[dict], limit: int) -> tuple[int, list[str], list[str]]:
    """(longest unwatched run, the run's slugs, findings) for well-formed plan tasks (dicts with a slug)."""
    by_slug = {t["slug"]: t for t in tasks}
    deps = {s: [d for d in _deps(t) if d in by_slug and d != s] for s, t in by_slug.items()}
    best: dict[str, list[str]] = {}

    def run(slug: str, open_: set) -> list[str]:
        """The longest chain of agent tasks ending at slug (cycles are create_plan's refusal, and cut here)."""
        if by_slug[slug].get("by") == "Human":
            return []
        if slug in best:
            return best[slug]
        open_.add(slug)
        longest: list[str] = []
        for d in deps[slug]:
            if d not in open_:
                r = run(d, open_)
                if len(r) > len(longest):
                    longest = r
        open_.discard(slug)
        best[slug] = longest + [slug]
        return best[slug]

    chain: list[str] = []
    for s in by_slug:
        r = run(s, set())
        if len(r) > len(chain):
            chain = r
    out = []
    if len(chain) > limit:
        out.append(f"RUN {len(chain)} > {limit}: {' -> '.join(chain)} run with no human task between them. "
                   "Add a by: Human checkpoint in this chain, or raise the limit")
    if tasks and not any(t.get("by") == "Human" for t in tasks):
        out.append("NO-HUMAN: no task is by: Human, so the human sees nothing until the plan ends")
    for s, t in by_slug.items():
        if not is_verify_lane(str(t.get("lane") or "")):
            continue
        who = t.get("by") or ""
        same = [d for d in deps[s] if who and by_slug[d].get("by") == who]
        if who != "Guardian":
            out.append(f"VERIFY-BY {s}: a verify task is by: Guardian, a different agent from the one whose work it "
                       f"checks; it is by: {who or 'unset'}")
        elif same:
            out.append(f"VERIFY-BY {s}: by: Guardian, the same caste as {', '.join(same)}, which it verifies")
    return len(chain), chain, out


def _deps(task: dict) -> list[str]:
    d = task.get("depends_on", [])
    if isinstance(d, str):
        d = [x.strip() for x in d.split(",")]
    return [str(x).strip() for x in d if str(x).strip()] if isinstance(d, list) else []


# --- the model ---------------------------------------------------------------------------

def _layout(nodes: list[dict], parents: dict[str, list[str]]) -> None:
    """Columns by dependency depth, rows in plan order: left to right like the Mermaid flowchart."""
    depth: dict[str, int] = {}

    def d(nid: str, open_: set) -> int:
        if nid in depth:
            return depth[nid]
        open_.add(nid)
        depth[nid] = 1 + max((d(p, open_) for p in parents.get(nid, []) if p not in open_), default=-1)
        open_.discard(nid)
        return depth[nid]
    rows: dict[int, int] = {}
    for n in nodes:
        col = d(n["id"], set())
        n["x"], n["y"] = 40 + col * X_STEP, 40 + rows.get(col, 0) * Y_STEP
        rows[col] = rows.get(col, 0) + 1


def _node_id(slug: str, i: int) -> str:
    return "t_" + slug.replace("-", "_") if isinstance(slug, str) and g.TASK_SLUG.fullmatch(slug) else f"t_{i + 1}"


def from_plan(colony, tasks, decisions=None, limit: int = DEFAULT_LIMIT, name: str = "", vault: str = "") -> dict:
    """The board model of a plan create_plan has not created yet. Reads the colony; writes nothing."""
    refusals = []
    raw_tasks, raw_decisions = tasks, decisions
    try:
        tasks = json.loads(tasks) if isinstance(tasks, str) else tasks
        decisions = json.loads(decisions) if isinstance(decisions, str) and decisions else decisions
    except json.JSONDecodeError:
        tasks, decisions = [], None
    refusal = colony.check_plan("Queen", raw_tasks, raw_decisions)
    if refusal:
        refusals += refusal.splitlines()[:1]
    good = [t for t in (tasks if isinstance(tasks, list) else []) if isinstance(t, dict)
            and isinstance(t.get("slug"), str) and t["slug"]]
    seen, unique = set(), []
    for t in good:                                    # a repeated slug is refused above; draw the first one
        if t["slug"] not in seen:
            seen.add(t["slug"])
            unique.append(t)
    for r in colony.task_refusals("Queen", tasks):       # every task's own problem at once, not only the first
        if r.splitlines()[0] not in refusals:
            refusals.append(r.splitlines()[0])
    vault = vault or colony.root.name
    ids = {t["slug"]: _node_id(t["slug"], i) for i, t in enumerate(unique)}
    nodes, edges, parents = [], [], {}
    for i, t in enumerate(unique):
        nid = ids[t["slug"]]
        plan_deps = [d for d in _deps(t) if d in ids]
        old = [d for d in _deps(t) if d not in ids]
        note = str(t.get("objective") or "")
        nodes.append({"id": nid, "slug": t["slug"], "kind": KIND.get(t.get("by"), "forager"),
                      "by": t.get("by") if t.get("by") in KIND else "", "title": t["slug"], "note": note,
                      "lane": str(t.get("lane") or ""), "acceptance": str(t.get("acceptance") or "") or
                      ("gate_code" if t.get("gate_code") else ""), "writes": str(t.get("writes") or ""),
                      "after_existing": old, "notes": note_links(t, vault), "task": copy.deepcopy(t)})
        parents[nid] = [ids[d] for d in plan_deps]
        for d in plan_deps:
            edges.append({"id": f"e{len(edges) + 1}", "from": ids[d], "to": nid, "label": ""})
    _layout(nodes, parents)
    run, chain, found = findings(unique, limit)
    return {"name": name, "source": "plan", "vault": vault, "limit": limit, "longest_run": run,
            "run": [ids[s] for s in chain], "human": sum(1 for t in unique if t.get("by") == "Human"),
            "tasks": len(tasks) if isinstance(tasks, list) else 0, "refusals": refusals, "findings": found,
            "decisions": decisions if isinstance(decisions, list) else [], "nodes": nodes, "edges": edges,
            "view": {"x": 20, "y": 20, "z": 0.8}}


def from_colony(colony, limit: int = DEFAULT_LIMIT, vault: str = "") -> dict:
    """The live board: every task in the colony, with its status and its WARN and ESCALATE lines. Reads only."""
    index = colony._task_index() if colony.tasks.is_dir() else {}
    done = {tid for tid, (_, status, _t) in index.items() if status == "done"}
    badges: dict[str, dict[str, int]] = {}
    for line in colony._ledger_lines():
        if line.signal in ("WARN", "ESCALATE"):
            name = line.path.rsplit("/", 1)[-1]
            if g.TASK_NAME.match(name):
                badges.setdefault(name, {}).setdefault(line.signal, 0)
                badges[name][line.signal] += 1
    vault = vault or colony.root.name
    nodes, edges, parents, plan_like = [], [], {}, []
    for tid, (rel, status, task) in sorted(index.items()):
        name = rel.rsplit("/", 1)[-1]
        slug = name[len(name.split("-", 1)[0]) + 1:-len(".task")]
        fields = task.fields if task else {}
        if task is None:
            state = "malformed"
        elif status == "pending":
            state = "blocked" if [d for d in task.depends_on if d not in done] else "ready"
        else:
            state = status
        by = fields.get("by", "")
        t = {"slug": slug, "objective": fields.get("objective", ""), "acceptance": fields.get("acceptance", ""),
             "writes": fields.get("writes", ""), "why": fields.get("why", ""), "reads": fields.get("reads", ""),
             "out_of_scope": fields.get("out-of-scope", ""), "lane": fields.get("lane", ""),
             "depends_on": [f"{d:03d}" for d in (task.depends_on if task else [])]}
        if by in KIND:
            t["by"] = by
        nid = f"t_{tid}"
        parents[nid] = [f"t_{d}" for d in (task.depends_on if task else []) if d in index]
        for d in parents[nid]:
            edges.append({"id": f"e{len(edges) + 1}", "from": d, "to": nid, "label": ""})
        nodes.append({"id": nid, "slug": slug, "file": name, "kind": KIND.get(by, "forager"), "by": by if by in KIND
                      else "", "title": name[:-len(".task")], "note": t["objective"], "lane": t["lane"],
                      "acceptance": t["acceptance"], "writes": t["writes"], "after_existing": [],
                      "status": state, "badges": badges.get(name, {}), "notes": note_links(t, vault), "task": t})
        if state != "done":
            plan_like.append({**t, "slug": name[:-len(".task")], "node": nid, "depends_on": [
                index[d][0].rsplit("/", 1)[-1][:-len(".task")] for d in (task.depends_on if task else []) if d in index]})
    _layout(nodes, parents)
    run, chain, found = findings(plan_like, limit)
    ids = {t["slug"]: t["node"] for t in plan_like}
    return {"name": "live", "source": "live", "vault": vault, "limit": limit, "longest_run": run,
            "run": [ids[s] for s in chain],
            "human": sum(1 for n in nodes if n["by"] == "Human" and n["status"] != "done"),
            "tasks": len(nodes), "refusals": [], "findings": found, "decisions": [], "nodes": nodes, "edges": edges,
            "view": {"x": 20, "y": 20, "z": 0.8}}


# --- text, Mermaid, files ----------------------------------------------------------------

def _esc(s) -> str:
    """Mermaid label text, as the board page's esc(): no quotes or brackets, one line."""
    s = str(s or "").replace('"', "'")
    s = re.sub(r"[\[\]{}()<>|]", " ", s)
    return " ".join(s.split())


def _card_text(n: dict) -> str:
    extra = [n["note"][:90]] if n.get("note") else []
    if n.get("status"):
        extra.insert(0, " · ".join([n["status"], *(f"{k} {v}" for k, v in sorted(n.get("badges", {}).items()))]))
    return _esc(n["title"]) + "".join(f"<br/><small>{_esc(x)}</small>" for x in extra)


def mermaid(model: dict) -> str:
    lines = ["flowchart LR"]
    for n in model["nodes"]:
        o, c = SHAPE.get(n["kind"], ('["', '"]'))
        lines.append(f"  {n['id']}{o}{_card_text(n)}{c}:::{n['kind']}")
    for e in model["edges"]:
        lines.append(f"  {e['from']} --> {e['to']}")
    for n in model["nodes"]:
        if n.get("notes"):
            lines.append(f'  click {n["id"]} "{n["notes"][0]["url"]}" _blank')
    lines += [f"  {c}" for c in CLASSDEFS]
    return "\n".join(lines)


def text(model: dict) -> str:
    """The plan_board result (B-1): BOARD head, refusals, findings, then the Mermaid flowchart."""
    head = (f"BOARD tasks={model['tasks']} human={model['human']} longest_run={model['longest_run']} "
            f"limit={model['limit']} refusals={len(model['refusals'])}")
    return "\n".join([head, *model["refusals"], *model["findings"], mermaid(model)])


def html(model: dict) -> str:
    data = json.dumps(model, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("__BOARD_DATA__", data)


def note(model: dict, stamp: str) -> str:
    found = model["refusals"] + model["findings"]
    lines = ["---", f"board: {model['name']}", f"source: {model['source']}", f"generated: {stamp}",
             f"tasks: {model['tasks']}", f"human: {model['human']}", f"longest_run: {model['longest_run']}",
             f"limit: {model['limit']}", "---", "", f"# Board: {model['name']}", "",
             f"Drawn by `apiary board` at {stamp}. The HTML board is `{BOARDS}/{model['name']}.html` in the colony.",
             "", "## Findings", ""] + ([f"- {f}" for f in found] or ["- none"])
    return "\n".join(lines + ["", "```mermaid", mermaid(model), "```", ""])


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def write(root: Path, model: dict, note_folder: str = "", stamp: str = "", revision: bool = True) -> list[str]:
    """Write boards/<name>.{board.json,mmd,html}, a revisions line for a plan, and optionally a vault note."""
    name = model["name"]
    out = root / BOARDS
    _write(out / f"{name}.board.json", json.dumps(model, indent=2, ensure_ascii=False) + "\n")
    _write(out / f"{name}.mmd", mermaid(model) + "\n")
    _write(out / f"{name}.html", html(model))
    written = [f"{BOARDS}/{name}.board.json", f"{BOARDS}/{name}.mmd", f"{BOARDS}/{name}.html"]
    if revision and model["source"] == "plan":
        plan = {"tasks": [n["task"] for n in model["nodes"]], "decisions": model["decisions"]}
        record = {"timestamp": stamp, "tasks": model["tasks"], "human": model["human"],
                  "longest_run": model["longest_run"], "limit": model["limit"],
                  "plan_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8")).hexdigest(),
                  "refusals": model["refusals"], "findings": [f.split(":")[0] for f in model["findings"]]}
        with open(out / f"{name}.revisions.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record) + "\n")
        written.append(f"{BOARDS}/{name}.revisions.jsonl")
    if note_folder:
        target = root / note_folder / f"{name}.md"
        _write(target, note(model, stamp))
        written.append(target.relative_to(root).as_posix() if target.is_relative_to(root) else str(target))
    return written


def _stamp(colony) -> str:
    return g.format_timestamp(colony.now())


def check_limit(limit) -> int | None:
    if isinstance(limit, bool):
        return None
    if isinstance(limit, str) and limit.strip().isdigit():
        limit = int(limit)
    return limit if isinstance(limit, int) and 1 <= limit <= 99 else None


def plan_board(colony, tasks, decisions=None, limit=DEFAULT_LIMIT, name: str = "", vault: str = "") -> str:
    """B-1, as the reference server runs it: the board text; with a name, also the files in boards/."""
    n = check_limit(limit)
    if n is None:
        return "REFUSED: limit is a whole number from 1 to 99 (the most agent tasks in a row before a human one)"
    if name and not (NAME.fullmatch(name) and len(name) <= 60):
        return "REFUSED: name must be lowercase words joined by '-' (it names the files in boards/)"
    model = from_plan(colony, tasks, decisions, n, name, vault)
    if name:
        write(colony.root, model, stamp=_stamp(colony))
    return text(model)


def live_board(colony, limit=DEFAULT_LIMIT, vault: str = "", note_folder: str = "") -> tuple[str, list[str]]:
    model = from_colony(colony, limit, vault)
    return text(model), write(colony.root, model, note_folder, _stamp(colony), revision=False)


def plan_file(path: Path) -> tuple[object, object]:
    """A plan.json: {"tasks": [...], "decisions": [...]}, or a bare list of tasks."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("tasks"), data.get("decisions")
    return data, None

