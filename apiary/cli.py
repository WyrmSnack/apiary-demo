"""apiary command line: validate a colony, run the MCP server, or run one operation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import SPEC_VERSION, __version__
from . import grammar as g
from .colony import Colony
from .validate import history, validate


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="apiary", description=f"Colony substrate tools (spec {SPEC_VERSION})")
    p.add_argument("--root", default=".", help="colony root (default: current directory)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version")
    i = sub.add_parser("init", help="make this directory a colony (safe to run again)")
    i.add_argument("--example", action="store_true", help="also add a first task to claim and close")
    i.add_argument("--tdd", action="store_true",
                   help="work test-first: install the story-ladder skill and tell the Queen to use it")
    i.add_argument("--update-protocols", action="store_true",
                   help="refresh apiary's own protocol and skill files after upgrading apiary")
    i.add_argument("--realm", metavar="PATH", help="make this colony a vassal of the realm at PATH (the folder "
                   "holding realm/decrees/); its Queen then reads the decrees sealed for it (ADR 0005)")
    i.add_argument("--realm-id", default="", help="this colony's vassal id in the realm (default: its folder name "
                   "under <realm>/projects/, in lower case)")
    v = sub.add_parser("validate", help="check the colony against the spec; exit 1 on any finding")
    v.add_argument("--since", metavar="REV", help="also check that nothing append-only or closed changed since this git commit (spec L-7)")
    sub.add_parser("serve", help="run the MCP stdio server for this colony")
    sub.add_parser("decrees", help="the realm's decrees for this colony: open, acknowledged or fulfilled (read only)")
    mg = sub.add_parser("migrate", help="report what stops an existing colony working under the spec")
    mg.add_argument("--check", action="store_true", required=True, help="read-only report (the only mode)")
    cn = sub.add_parser("connect", help="connect outside programs (spec section 13)")
    csub = cn.add_subparsers(dest="connect_cmd", required=True)
    ca = csub.add_parser("add", help="give this colony an outside program")
    ca.add_argument("name")
    ca.add_argument("--program", default="", help="path to the program (default: find a known program)")
    ca.add_argument("--version-arg", action="append", default=None, help="argument that makes it print its version")
    ca.add_argument("--version-pattern", default="", help="regex whose first group is the version")
    ca.add_argument("--description", default="")
    csub.add_parser("list", help="list connectors and the versions they report now")
    tk = sub.add_parser("task", help="task commands")
    tsub = tk.add_subparsers(dest="task_cmd", required=True)
    tn = tsub.add_parser("new", help="create a valid task in tasks/pending/ (spec O-3)")
    tn.add_argument("slug", help="lowercase words joined by '-', e.g. save-slots")
    tn.add_argument("--objective", required=True, help="one sentence: what is true when the task is done")
    tn.add_argument("--acceptance", default="", help="one command that exits 0 when done (no shell syntax)")
    tn.add_argument("--gate", default="", help="a Python check script to save as gates/check_NNN.py instead")
    tn.add_argument("--gate-args", default="", help="arguments for the gate")
    for opt in ("writes", "why", "reads", "depends-on", "out-of-scope"):
        tn.add_argument(f"--{opt}", default="")
    tn.add_argument("--caste", default="Queen")
    tn.add_argument("--lane", default="", help="the stream of work this task belongs to")
    tn.add_argument("--by", default="", help="who does it: Queen, Forager, Nurse, Guardian, or Human (a checkpoint)")
    sub.add_parser("plan", help="what can start now: ready, blocked and active tasks by lane (spec O-4)")
    bd = sub.add_parser("board", help="draw a plan (before create_plan) or the live colony as a board in boards/ "
                                      "(spec B-1); writes no task or ledger line")
    which = bd.add_mutually_exclusive_group(required=True)
    which.add_argument("--plan", metavar="PLAN_JSON", help="a plan in create_plan's shape: {tasks, decisions}, or a list")
    which.add_argument("--live", action="store_true", help="the colony as it stands: status, WARN and ESCALATE per task")
    bd.add_argument("--name", default="", help="names the files in boards/ (default: the plan file's name)")
    bd.add_argument("--limit", type=int, default=3, help="most agent tasks in a row before a human one (default 3)")
    bd.add_argument("--note", default="", metavar="FOLDER",
                    help="also write <FOLDER>/<name>.md, a Markdown note with a mermaid block (relative to --root)")
    bd.add_argument("--vault", default="", help="Obsidian vault name for [[Note]] links (default: the colony folder)")
    kn = sub.add_parser("knowledge", help="the colony's knowledge base (Concept, Tool, Workflow, Playbook cards)")
    kn.add_subparsers(dest="knowledge_cmd", required=True).add_parser("index", help="write knowledge/INDEX.md")
    c = sub.add_parser("claim"); c.add_argument("task_file"); c.add_argument("--caste", default="Forager")
    c.add_argument("--lease-minutes", type=int, default=60)
    r = sub.add_parser("renew"); r.add_argument("task_file"); r.add_argument("token")
    r.add_argument("--caste", default="Forager"); r.add_argument("--lease-minutes", type=int, default=60)
    cl = sub.add_parser("close"); cl.add_argument("task_file"); cl.add_argument("token")
    cl.add_argument("--caste", default="Forager")
    rs = sub.add_parser("resume"); rs.add_argument("--caste", default="Nurse")
    a = sub.add_parser("log", help="append one ledger line")
    for name in ("caste", "signal", "path", "note"):
        a.add_argument(name)
    gd = sub.add_parser("gamedev", help="game-development helpers (Phase 10)")
    gt = gd.add_subparsers(dest="gamedev_cmd", required=True).add_parser(
        "godot-tests", help="write apiary's GDScript test runner into a Godot 4 project (tests/run_tests.gd)")
    gt.add_argument("project")
    t = sub.add_parser("trace", help="record a decision in TRACES.md")
    t.add_argument("caste"); t.add_argument("key"); t.add_argument("value")
    t.add_argument("--supersedes", default="")
    args = p.parse_args(argv)

    if args.cmd == "version":
        print(f"apiary {__version__} (spec {SPEC_VERSION})")
        return 0
    if args.cmd == "init":
        from .init import init
        from . import realm
        if args.realm:                                     # refuse before init changes anything
            refused = realm.check_realm(args.realm) or (args.realm_id and realm.check_id(args.realm_id.strip().lower()))
            if refused:
                print(refused)
                return 1
        code, report = init(args.root, args.example, args.tdd)
        if code == 0 and args.update_protocols:
            from .init import update_protocols
            report = [ln for ln in report if not ln.startswith(("nothing to do", "next:"))]
            report += update_protocols(args.root)[1]
        if code == 0 and args.realm:
            code, lines = realm.set_realm(args.root, args.realm, args.realm_id)
            if lines:
                report = [ln for ln in report if not ln.startswith("nothing to do")] + lines
        print("\n".join(report))
        return code
    if args.cmd == "decrees":
        from .realm import report
        text = report(args.root)
        print(text)
        return 1 if "\nWARN " in text else 0
    if args.cmd == "connect":
        from . import connect
        if args.connect_cmd == "list":
            print("\n".join(connect.list_lines(args.root)))
            return 0
        code, lines = connect.add(args.root, args.name, args.program, args.version_arg, args.version_pattern,
                                  args.description)
        print("\n".join(lines))
        return code
    if args.cmd == "gamedev":
        from .gamedev import godot_tests
        code, lines = godot_tests(args.project)
        print("\n".join(lines))
        return code
    if args.cmd == "knowledge":
        from .knowledge import index
        code, lines = index(args.root)
        print("\n".join(lines))
        return code
    if args.cmd == "board":
        from . import board
        col = Colony(args.root)
        if board.check_limit(args.limit) is None:
            print("refused: --limit is a whole number from 1 to 99")
            return 1
        if args.live:
            out, written = board.live_board(col, args.limit, args.vault, args.note)
            print(out + "\n" + "\n".join(f"wrote {w}" for w in written))
            return 0
        name = args.name or Path(args.plan).stem.lower()
        if not (board.NAME.fullmatch(name) and len(name) <= 60):
            print(f"refused: board name {name!r} must be lowercase words joined by '-'; pass --name")
            return 1
        try:
            tasks, decisions = board.plan_file(Path(args.plan))
        except (OSError, ValueError) as e:
            print(f"refused: cannot read {args.plan} as JSON ({e})")
            return 1
        model = board.from_plan(col, tasks, decisions, args.limit, name, args.vault)
        written = board.write(col.root, model, args.note, g.format_timestamp(col.now()))
        print(board.text(model) + "\n" + "\n".join(f"wrote {w}" for w in written))
        return 1 if model["refusals"] else 0
    if args.cmd == "migrate":
        from .migrate import report
        code, text = report(args.root)
        print(text)
        return code
    if args.cmd == "validate":
        root = Path(args.root).resolve()
        if not (root / "tasks").is_dir() and not (root / "PHEROMONE_LEDGER.md").exists():
            print(f"not a colony: {root} has no tasks/ folder and no PHEROMONE_LEDGER.md. "
                  "Run this in the colony's folder, pass --root <colony>, or run `apiary init` to make one.")
            return 1
        findings = validate(args.root)
        if args.since:
            findings += history(args.root, args.since)
        for f in findings:
            print(f)
        print(f"{len(findings)} finding(s)" if findings else "valid")
        return 1 if findings else 0
    if args.cmd == "serve":
        import os
        os.environ["COLONY_ROOT"] = args.root
        from .server import main as serve
        serve()
        return 0

    col = Colony(args.root)
    result = {
        "claim": lambda: col.claim(args.task_file, args.caste, args.lease_minutes),
        "renew": lambda: col.renew(args.task_file, args.token, args.caste, args.lease_minutes),
        "close": lambda: col.close(args.task_file, args.token, args.caste),
        "resume": lambda: col.resume(args.caste),
        "log": lambda: col.append_ledger(args.caste, args.signal, args.path, args.note),
        "trace": lambda: col.write_trace(args.caste, args.key, args.value, args.supersedes),
        "task": lambda: col.create_task(
            args.caste, args.slug, args.objective, args.acceptance, args.writes, args.why, args.reads,
            args.depends_on, args.out_of_scope,
            Path(args.gate).read_text(encoding="utf-8") if args.gate else "", args.gate_args, args.lane, args.by),
        "plan": lambda: col.plan_status(),
    }[args.cmd]()
    print(result)
    return 0 if result.split(" ", 1)[0].split("\n")[0] in {
        "CLAIMED", "RENEWED", "DONE", "RESUMED", "APPENDED", "TRACED", "CREATED", "RAN", "PLAN"} else 1


if __name__ == "__main__":
    sys.exit(main())
