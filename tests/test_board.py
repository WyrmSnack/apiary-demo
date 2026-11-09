"""The Colony Coordination Board (Phase 13 gate b, Forge decree 003, TRACE board-home).

The board is made from the plan the Queen is about to pass to create_plan, before anything is in tasks/, and from a
live colony. It writes only boards/ (and, with --note, a note in the folder the human names). Editing the HTML board
only exports a revised plan.json for create_plan; it never writes tasks/ or the ledger.
"""
import json

import pytest

from apiary import board
from apiary.cli import main
from apiary.colony import Colony

OK = 'python -c "exit(0)"'
CLASSDEFS = [
    "classDef human fill:#f4c95d,stroke:#8a6a10,color:#3b2c00",
    "classDef checkpoint fill:#fff8e3,stroke:#d9a520,stroke-dasharray:5 4,color:#3b2c00",
    "classDef queen fill:#b9a3e3,stroke:#5c45a0,color:#271a45",
    "classDef forager fill:#8fd3b6,stroke:#2f7a5a,color:#0f3324",
    "classDef nurse fill:#f2a7a0,stroke:#a8473f,color:#4a1612",
    "classDef guardian fill:#9fb7de,stroke:#3b5e96,color:#13284a",
    "classDef check fill:#e2e5dc,stroke:#7a8273,color:#2a2f27",
]


def _t(slug, writes="", depends_on=(), **more):
    return {"slug": slug, "objective": f"{slug} done", "acceptance": OK, "writes": writes,
            "depends_on": list(depends_on), **more}


PLAN = {"decisions": [{"key": "units", "value": "metres"}],
        "tasks": [_t("research", "research/units/", by="Nurse", lane="research"),
                  _t("verify", "", ["research"], by="Guardian", lane="verify"),
                  _t("grid", "app/grid.py", ["verify"], lane="build", why="See [[Grid Notes]] and [[Units|the units]]."),
                  _t("cli", "app/cli.py", ["grid"], by="Forager", lane="build"),
                  _t("look", "", ["cli"], by="Human", objective="Kevin plays it")]}


@pytest.fixture
def colony(tmp_path):
    main(["--root", str(tmp_path), "init"])
    return tmp_path


def _snapshot(root, *rels):
    out = {}
    for rel in rels:
        p = root / rel
        for f in ([p] if p.is_file() else sorted(p.rglob("*")) if p.exists() else []):
            out[f.relative_to(root).as_posix()] = f.read_bytes() if f.is_file() else None
    return out


def test_the_model_has_a_card_per_task_and_a_link_per_dependency(colony):
    m = board.from_plan(Colony(colony), PLAN["tasks"], PLAN["decisions"], limit=3, name="units")
    kinds = {n["slug"]: n["kind"] for n in m["nodes"]}
    assert kinds == {"research": "nurse", "verify": "guardian", "grid": "forager", "cli": "forager",
                     "look": "checkpoint"}
    ids = {n["slug"]: n["id"] for n in m["nodes"]}
    assert {(e["from"], e["to"]) for e in m["edges"]} == {(ids["research"], ids["verify"]), (ids["verify"], ids["grid"]),
                                                          (ids["grid"], ids["cli"]), (ids["cli"], ids["look"])}
    assert len({(n["x"], n["y"]) for n in m["nodes"]}) == 5                 # no two cards on top of each other
    assert m["longest_run"] == 4 and m["limit"] == 3 and m["refusals"] == []
    assert [f for f in m["findings"] if f.startswith("RUN 4 > 3")], m["findings"]
    task = next(n for n in m["nodes"] if n["slug"] == "grid")["task"]
    assert task == PLAN["tasks"][2]                                         # the card keeps the task for the export


def test_board_files_are_written_to_boards(colony):
    before = _snapshot(colony, "tasks", "PHEROMONE_LEDGER.md", "TRACES.md")
    plan = colony / "units-plan.json"
    plan.write_text(json.dumps(PLAN), encoding="utf-8")
    assert main(["--root", str(colony), "board", "--plan", str(plan), "--name", "units", "--vault", "Forge"]) == 0
    assert _snapshot(colony, "tasks", "PHEROMONE_LEDGER.md", "TRACES.md") == before
    data = json.loads((colony / "boards/units.board.json").read_text(encoding="utf-8"))
    assert data["name"] == "units" and len(data["nodes"]) == 5
    mmd = (colony / "boards/units.mmd").read_text(encoding="utf-8")
    assert mmd.startswith("flowchart LR\n")
    for line in CLASSDEFS:
        assert f"  {line}" in mmd.splitlines(), line
    assert mmd.count("-->") == 4 and ":::checkpoint" in mmd and ":::nurse" in mmd
    html = (colony / "boards/units.html").read_text(encoding="utf-8")
    assert "localStorage.getItem" not in html and 'id="board-data"' in html and "Export plan.json" in html
    embedded = html.split('<script type="application/json" id="board-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(embedded)["name"] == "units"


def test_the_name_defaults_to_the_plan_files_name(colony, capsys):
    plan = colony / "big-goal.json"
    plan.write_text(json.dumps(PLAN["tasks"]), encoding="utf-8")                 # a bare task list works too
    assert main(["--root", str(colony), "board", "--plan", str(plan)]) == 0
    assert (colony / "boards/big-goal.board.json").is_file()
    out = capsys.readouterr().out
    assert out.startswith("BOARD tasks=5 human=1 longest_run=4 limit=3"), out


def test_a_plan_create_plan_would_refuse_prints_the_refusal_and_exits_1(colony, capsys):
    plan = colony / "bad.json"
    plan.write_text(json.dumps({"tasks": [_t("a", "app/"), _t("b", "app/b.py")]}), encoding="utf-8")
    assert main(["--root", str(colony), "board", "--plan", str(plan)]) == 1
    out = capsys.readouterr().out
    assert "\nREFUSED: " in out and "overlap" in out, out
    assert (colony / "boards/bad.html").is_file()                         # the board still shows what is wrong


def test_limit_changes_the_run_finding(colony, capsys):
    plan = colony / "p.json"
    plan.write_text(json.dumps(PLAN), encoding="utf-8")
    main(["--root", str(colony), "board", "--plan", str(plan), "--limit", "5"])
    out = capsys.readouterr().out
    assert "limit=5" in out.splitlines()[0] and "\nRUN " not in out, out


def test_obsidian_note_links_and_the_markdown_note(colony):
    plan = colony / "units.json"
    plan.write_text(json.dumps(PLAN), encoding="utf-8")
    assert main(["--root", str(colony), "board", "--plan", str(plan), "--vault", "Forge of WyrmSnack",
                 "--note", "realm/obsidian-inbox/boards"]) == 0
    grid = next(n for n in json.loads((colony / "boards/units.board.json").read_text(encoding="utf-8"))["nodes"]
                if n["slug"] == "grid")
    assert grid["notes"] == [{"note": "Grid Notes", "url": "obsidian://open?vault=Forge%20of%20WyrmSnack&file=Grid%20Notes"},
                             {"note": "Units", "url": "obsidian://open?vault=Forge%20of%20WyrmSnack&file=Units"}]
    mmd = (colony / "boards/units.mmd").read_text(encoding="utf-8")
    assert f'  click {grid["id"]} "obsidian://open?vault=Forge%20of%20WyrmSnack&file=Grid%20Notes" _blank' in mmd.splitlines()
    assert "obsidian://open?vault=Forge%20of%20WyrmSnack&file=Grid%20Notes" in \
        (colony / "boards/units.html").read_text(encoding="utf-8")
    note = (colony / "realm/obsidian-inbox/boards/units.md").read_text(encoding="utf-8")
    assert "```mermaid\nflowchart LR\n" in note and "RUN 4 > 3" in note and note.rstrip().endswith("```")


def test_the_vault_defaults_to_the_colony_folders_name(colony):
    m = board.from_plan(Colony(colony), PLAN["tasks"], limit=3, name="x")
    grid = next(n for n in m["nodes"] if n["slug"] == "grid")
    assert grid["notes"][0]["url"].startswith(f"obsidian://open?vault={colony.name}&file=")


def test_the_live_board_shows_status_and_ledger_badges(colony, monkeypatch):
    monkeypatch.setenv("APIARY_CLOCK", "2026-10-19T12:00Z")
    c = Colony(colony)
    assert c.create_plan("Queen", [_t("a", "a.py"), _t("b", "b.py"), _t("c", "c.py", ["a", "b"], by="Human"),
                                   _t("d", "d.py")]).startswith("CREATED")
    tok = c.claim("001-a.task", "Queen").split("token=")[1].split()[0]
    assert c.close("001-a.task", tok, "Queen").startswith("DONE")
    c.claim("002-b.task", "Forager")
    c.append_ledger("Forager", "WARN", "tasks/active/002-b.task", "the test looks wrong")
    c.append_ledger("Queen", "ESCALATE", "tasks/pending/003-c.task", "needs Kevin")
    c.append_ledger("Queen", "ESCALATE", "tasks/pending/003-c.task", "still needs Kevin")
    before = _snapshot(colony, "tasks", "PHEROMONE_LEDGER.md")
    assert main(["--root", str(colony), "board", "--live"]) == 0
    assert _snapshot(colony, "tasks", "PHEROMONE_LEDGER.md") == before
    data = json.loads((colony / "boards/live.board.json").read_text(encoding="utf-8"))
    by_slug = {n["slug"]: n for n in data["nodes"]}
    assert {s: n["status"] for s, n in by_slug.items()} == {"a": "done", "b": "active", "c": "blocked", "d": "ready"}
    assert by_slug["b"]["badges"] == {"WARN": 1} and by_slug["c"]["badges"] == {"ESCALATE": 2}
    assert by_slug["c"]["kind"] == "checkpoint" and by_slug["a"]["badges"] == {}
    mmd = (colony / "boards/live.mmd").read_text(encoding="utf-8")
    assert "ESCALATE 2" in mmd and "WARN 1" in mmd


def test_plan_board_with_a_name_writes_only_boards_and_counts_revisions(colony):
    before = _snapshot(colony, "tasks", "PHEROMONE_LEDGER.md", "TRACES.md", ".apiary")
    text = board.plan_board(Colony(colony), PLAN["tasks"], PLAN["decisions"], 3, "units")
    assert text.startswith("BOARD tasks=5"), text
    board.plan_board(Colony(colony), PLAN["tasks"][:3], PLAN["decisions"], 3, "units")
    assert _snapshot(colony, "tasks", "PHEROMONE_LEDGER.md", "TRACES.md", ".apiary") == before
    revisions = (colony / "boards/units.revisions.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(r)["tasks"] for r in revisions] == [5, 3]
    assert {"timestamp", "plan_sha256", "findings", "refusals"} <= set(json.loads(revisions[0]))
    assert (colony / "boards/units.html").is_file()
    assert board.plan_board(Colony(colony), PLAN["tasks"], None, 3, "").startswith("BOARD")
    assert sorted(p.name for p in (colony / "boards").iterdir()) == [
        "units.board.json", "units.html", "units.mmd", "units.revisions.jsonl"]


@pytest.mark.parametrize("name", ["../escape", "a/b", "Bad Name", ""])
def test_a_board_name_cannot_leave_boards(colony, name):
    text = board.plan_board(Colony(colony), PLAN["tasks"], None, 3, name)
    if name:
        assert text.startswith("REFUSED"), text
    assert not (colony / "escape.board.json").exists() and not (colony / "boards" / "a").exists()
