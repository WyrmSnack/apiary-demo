"""MCP stdio server exposing the colony operations (spec section 10).

Claude Code (.mcp.json, written by `apiary init`):
  {"mcpServers": {"colony": {"type": "stdio", "command": "python", "args": ["-m", "apiary.server"],
                             "env": {"COLONY_ROOT": "."}}}}
"""
from __future__ import annotations

from typing import Any

import os
import sys
import traceback

from mcp.server import MCPServer

from . import board
from . import realm
from .colony import Colony

colony = Colony(os.environ.get("COLONY_ROOT") or os.getcwd())          # M-3
server = MCPServer("apiary-colony", instructions=(
    "Every change to PHEROMONE_LEDGER.md, TRACES.md and tasks/ goes through these tools. "
    "Keep the token claim_task returns: renew_claim and close_task need it. "
    "Call resume when a session starts."))


def _safe(fn, *args) -> str:
    """M-2: no tool ends in an unhandled error."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)                              # M-4: logs to stderr
        return f"REFUSED: internal error ({type(e).__name__}: {e}); nothing is known to have changed"


@server.tool()
def claim_task(task_file: str, caste: str = "Forager", lease_minutes: int = 60) -> str:
    """Claim a pending task. Exactly one caller wins. Returns 'CLAIMED <task> token=<t> lease_until=<ts>'."""
    return _safe(colony.claim, task_file, caste, lease_minutes)


@server.tool()
def renew_claim(task_file: str, token: str, caste: str = "Forager", lease_minutes: int = 60) -> str:
    """Extend your lease on an active task. Renew before lease_until, or resume may return the task."""
    return _safe(colony.renew, task_file, token, caste, lease_minutes)


@server.tool()
def close_task(task_file: str, token: str, caste: str = "Forager") -> str:
    """Run the task's acceptance command; move it to done only if it exits 0 and you hold the claim."""
    return _safe(colony.close, task_file, token, caste)


@server.tool()
def resume(caste: str = "Nurse") -> str:
    """Return orphaned and lease-expired active tasks to pending. Never touches a live claim."""
    return _safe(colony.resume, caste)


@server.tool()
def append_ledger(caste: str, signal: str, path: str, note: str) -> str:
    """Append one validated line to PHEROMONE_LEDGER.md. CLAIM and DONE are written by claim/close only."""
    return _safe(colony.append_ledger, caste, signal, path, note)


@server.tool()
def write_trace(caste: str, key: str, value: str, supersedes: str = "") -> str:
    """Record a decision in TRACES.md. To change a decision, write a new key with supersedes=<old key>."""
    return _safe(colony.write_trace, caste, key, value, supersedes)


@server.tool()
def create_task(caste: str, slug: str, objective: str, acceptance: str = "", writes: str = "", why: str = "",
                reads: str = "", depends_on: str = "", out_of_scope: str = "", gate_code: str = "",
                gate_args: str = "", lane: str = "", by: str = "") -> str:
    """Create a new task in tasks/pending/. Refuses anything a claim or close would refuse, and never overwrites.

    acceptance: one command, run without a shell, that exits 0 when the task is done (python -m pytest -q tests/x.py).
    If no existing command can check the work, leave acceptance empty and pass gate_code: a Python script that
    checks it (exit 0 = done). It is saved as a new gates/check_NNN.py, run with gate_args. Show the human the
    draft first: tasks are the human's (or the Queen's) decisions, not a Forager's.
    lane: the stream of work this task belongs to (see /colony-plan). writes must not overlap a pending or active
    task's writes unless this task depends on it: two tasks that can run at once never write the same file.
    by: who does it (Queen, Forager, Nurse, Guardian, or Human: a checkpoint that closes on the human's approve <id>).
    """
    return _safe(colony.create_task, caste, slug, objective, acceptance, writes, why, reads, depends_on,
                 out_of_scope, gate_code, gate_args, lane, by)


@server.tool()
def create_plan(caste: str, tasks: Any, decisions: Any = None) -> str:
    """Create a whole plan in one call, all or nothing: its decisions (as TRACEs) and every task.

    tasks: a list of objects with create_task's fields (slug, objective, acceptance or gate_code, writes, why, reads,
    out_of_scope, gate_args, lane, by) and depends_on: a list of slugs from this plan or ids of existing tasks. List them
    in any order; ids follow the dependencies. decisions: a list of {key, value} recorded before any task.
    The same checks as create_task, plus: tasks in the plan that can run at the same time never write the same file.
    If anything is refused, nothing is written. Show the human the plan first.
    """
    return _safe(colony.create_plan, caste, tasks, decisions)


@server.tool()
def plan_board(tasks: Any, decisions: Any = None, limit: Any = 3, name: str = "") -> str:
    """Read only on the colony: the plan as a board, before create_plan. Show its findings and Mermaid to the human.

    tasks, decisions: exactly what you will pass to create_plan. Returns BOARD tasks=... longest_run=..., then every
    refusal create_plan would give (nothing is written), then RUN <n> > <limit> (that many agent tasks in a chain with
    no by: Human checkpoint), NO-HUMAN, VERIFY-BY <slug> (a verify task not by a different Guardian), then the Mermaid
    flowchart. limit: the most agent tasks in a row before a human one. name: also write boards/<name>.board.json,
    .mmd and .html (the HTML board the human can open) and count the revision.
    """
    return _safe(board.plan_board, colony, tasks, decisions, limit, name)


@server.tool()
def plan_status() -> str:
    """What can start now: every pending and active task with its lane, and whether it is ready (all dependencies
    done), blocked (and by which tasks) or active. The Queen dispatches one subagent per ready task, in parallel."""
    return _safe(colony.plan_status)


@server.tool()
def run_connector(caste: str, connector: str, args: str, outputs: str = "", task_file: str = "") -> str:
    """Run an outside program this colony has a connector for (see the colony-connectors skill), and record it.

    args: the program's arguments, split like an acceptance line (no shell; double quotes for spaces).
    outputs: comma-separated colony-relative paths the run should write; their hashes go into the run record.
    task_file: the task this run is for. Returns 'RAN runs/<record>.json exit=<code>'. Every run is recorded,
    including failures, so later agents and the human can see what produced each output.
    """
    return _safe(colony.run_connector, caste, connector, args, outputs, task_file)


@server.tool()
def unlock_test(caste: str, path: str, reason: str, evidence: str) -> str:
    """Queen only. Unlock one locked test file so it can be edited, then relocked with relock_test.

    reason: impassable (no code that follows the story can pass it), conflict (it contradicts a newer story or another
    locked test), requirement_change (a later slice changed what it pins), or nondeterministic (the expected value
    depends on a random roll). evidence: the Guardian review line, the WARN, or the story criterion. Refused unless a
    WARN or ESCALATE for the file is in the ledger since it was locked. The locked text is kept in .apiary/tdd/history/.
    Your next message to the human must carry the lock_report() block.
    """
    return _safe(colony.unlock_test, caste, path, reason, evidence)


@server.tool()
def relock_test(caste: str, paths: str, story: str, approve_weakening: bool = False) -> str:
    """Queen only. Lock edited test files again (comma-separated paths; a test moved between them is not deleted).

    Runs them: new or changed tests may fail (they wait for their code) or pass; an unchanged test that was green must
    still pass. Refuses an edit that weakens a test (a deleted test or check, a looser tolerance, eq to near, a value to
    a range, the file dropped from the story) unless the human wrote "approve weakening <file name>" in chat; then pass
    approve_weakening=true. Writes the hash itself. Your next message to the human must carry the lock_report() block.
    """
    return _safe(colony.relock_test, caste, paths, story, approve_weakening)


@server.tool()
def lock_report(caste: str = "Queen") -> str:
    """Queen only. The block to put at the top of your next message to the human: one line per unlock or relock not
    yet reported, and the files still unlocked. The Stop hook holds your turn until your message carries it."""
    return _safe(colony.lock_report, caste)


@server.tool()
def realm_decrees() -> str:
    """Read only. The decrees this colony's realm has sealed for it (its vassal id or '*'), each OPEN, ACKNOWLEDGED or
    FULFILLED by this colony's ledger, with the append_ledger call that acknowledges an open one and the slug of the
    task that finishes it. 'DECREES none' if the colony has no realm. The Queen calls it on waking."""
    return _safe(realm.report, colony.root)


@server.resource("colony://ledger/tail")
def ledger_tail() -> str:
    """The last 30 ledger lines."""
    if not colony.ledger.exists():
        return ""
    return "\n".join(colony.ledger.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])


def main() -> None:
    colony.ensure_layout()
    print(f"apiary-colony serving {colony.root}", file=sys.stderr, flush=True)
    server.run("stdio")


if __name__ == "__main__":
    main()
