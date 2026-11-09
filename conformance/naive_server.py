"""The SASD textbook, implemented as written. The conformance suite must fail it.

- claim: Ch 0.7 tools/claim.py (os.rename, CONFLICT if missing), plus a Ch 5.2 CLAIM line.
- ledger: Ch 5.2 grammar and lint_ledger.py's checks (8 signals, notes up to 120 characters).
- close: Ch 20's substrate server, which runs the `acceptance:` line in a shell.
- resume: Ch 18.3 tools/resume.py: every active task that fails acceptance goes back to pending.
- TRACES: Ch 4's KEY / SUPERSEDES entries, appended.

There are no tokens, leases or locks, because the textbook does not define them.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
from pathlib import Path

from mcp.server import MCPServer

ROOT = Path(os.environ.get("COLONY_ROOT", ".")).resolve()
LEDGER, TRACES, TASKS = ROOT / "PHEROMONE_LEDGER.md", ROOT / "TRACES.md", ROOT / "tasks"
CASTES = "Queen|Forager|Nurse|Guardian|SignalSprite|Cartographer|Scribe"
SIGNALS = "DEPOSIT|REINFORCE|EVAPORATE|WARN|CLAIM|DONE|SKILL|TRACE"
LINE = re.compile(rf"^\d{{4}}-\d\d-\d\dT\d\d:\d\dZ \| ({CASTES}) +\| ({SIGNALS}) +\| \S+ \| .{{1,120}}$")
server = MCPServer("naive-textbook-colony")


def now() -> str:
    return os.environ.get("APIARY_CLOCK") or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def ledger(caste: str, signal: str, path: str, note: str) -> str:
    line = f"{now()} | {caste} | {signal} | {path} | {note}"
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


def accept(task: Path) -> int:
    cmd = re.search(r"^acceptance:\s*(.+)$", task.read_text(encoding="utf-8"), re.M).group(1)
    return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True).returncode


@server.tool()
def claim_task(task_file: str, caste: str = "Forager", lease_minutes: int = 60) -> str:
    try:
        os.rename(TASKS / "pending" / task_file, TASKS / "active" / task_file)
    except FileNotFoundError:
        return "CONFLICT: already claimed or missing"
    ledger(caste, "CLAIM", f"tasks/active/{task_file}", "claimed")
    return f"CLAIMED {task_file}"


@server.tool()
def close_task(task_file: str, token: str = "", caste: str = "Forager") -> str:
    task = TASKS / "active" / task_file
    if not task.exists():
        return f"CONFLICT: {task_file} is not active"
    if accept(task) != 0:
        ledger(caste, "WARN", f"tasks/active/{task_file}", "acceptance failed")
        return "REFUSED: acceptance failed"
    os.rename(task, TASKS / "done" / task_file)
    ledger(caste, "DONE", f"tasks/done/{task_file}", "acceptance passed")
    return f"DONE {task_file}"


@server.tool()
def resume(caste: str = "Nurse") -> str:
    returned = kept = 0
    for task in sorted((TASKS / "active").glob("*.task")):
        if accept(task) == 0:
            os.rename(task, TASKS / "done" / task.name)
            ledger("Nurse", "DONE", f"tasks/done/{task.name}", "recovered on resume: acceptance passed")
            kept += 1
            continue
        os.rename(task, TASKS / "pending" / task.name)
        ledger("Nurse", "EVAPORATE", f"tasks/pending/{task.name}", "orphan returned on resume")
        returned += 1
    return f"RESUMED returned={returned} kept={kept}"


@server.tool()
def append_ledger(caste: str, signal: str, path: str, note: str) -> str:
    line = f"{now()} | {caste} | {signal} | {path} | {note}"
    if not LINE.match(line):
        return "REFUSED: malformed ledger line"
    return "APPENDED " + ledger(caste, signal, path, note)


@server.tool()
def write_trace(caste: str, key: str, value: str, supersedes: str = "") -> str:
    entry = f"\n## KEY: {key}\n- by: {caste} at {now()}\n"
    if supersedes:
        entry += f"- SUPERSEDES: {supersedes}\n"
    with open(TRACES, "a", encoding="utf-8") as f:
        f.write(entry + f"- VALUE: {value}\n")
    ledger(caste, "TRACE", "TRACES.md", f"KEY {key}")
    return f"TRACED {key}"


if __name__ == "__main__":
    for d in ("pending", "active", "done"):
        (TASKS / d).mkdir(parents=True, exist_ok=True)
    server.run("stdio")
