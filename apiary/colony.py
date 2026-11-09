"""Colony operations: claim, renew, close, resume, append_ledger, write_trace (spec sections 4 to 9).

Every public method returns the result text of spec M-1. None raises for bad input or a busy colony.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

from filelock import FileLock, Timeout

from . import connectors
from . import grammar as g
from . import locktools

ACCEPTANCE_TIMEOUT_S = 600     # A-5
PLAN_FIELDS = {"slug", "objective", "acceptance", "writes", "why", "reads", "out_of_scope", "gate_code", "gate_args",
               "lane", "depends_on", "by"}                                    # O-5, and K-1's by
LOCK_TIMEOUT_S = 30


class _Stop(Exception):
    """Ends an operation with a result text."""


def _conflict(msg: str) -> _Stop:
    return _Stop(f"CONFLICT: {msg}")


def _refused(msg: str) -> _Stop:
    return _Stop(f"REFUSED: {msg}")


def _write_targets(writes: str) -> list[str]:
    """The paths in a writes: line, normalised: forward slashes, no ./ prefix, no trailing slash."""
    out = []
    for w in (writes or "").split(","):
        w = w.strip().replace("\\", "/")
        while w.startswith("./"):
            w = w[2:]
        w = w.rstrip("/")
        if w:
            out.append(w.lower() if os.name == "nt" else w)
    return out


def _overlaps(a: str, b: str) -> bool:
    """Same path, or one is a folder containing the other. 'art/logo' and 'art/logo-notes.md' do not overlap."""
    return a == b or b.startswith(a + "/") or a.startswith(b + "/")


class Colony:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).resolve()
        self.ledger = self.root / "PHEROMONE_LEDGER.md"
        self.traces = self.root / "TRACES.md"
        self.tasks = self.root / "tasks"
        self.quarantine = self.root / ".apiary" / "quarantine.log"
        self._lock = FileLock(str(self.root / ".colony.lock"), timeout=LOCK_TIMEOUT_S)

    # --- plumbing ------------------------------------------------------------

    def ensure_layout(self) -> None:
        for d in ("pending", "active", "done"):                       # D-2
            (self.tasks / d).mkdir(parents=True, exist_ok=True)

    def now(self) -> dt.datetime:
        clock = os.environ.get("APIARY_CLOCK")                          # H-1
        if clock:
            return g.parse_timestamp(clock)
        return dt.datetime.now(dt.timezone.utc).replace(second=0, microsecond=0)

    def _ts(self) -> str:
        return g.format_timestamp(self.now())

    def _run(self, op) -> str:
        try:
            self.ensure_layout()
            return op()
        except _Stop as stop:
            return str(stop)
        except Timeout:
            return "CONFLICT: colony is busy (lock not acquired in time); retry"
        except g.GrammarError as e:
            return f"REFUSED: {e}"

    def _check_encoding(self) -> None:
        for path in (self.ledger, self.traces):
            if path.exists():
                try:
                    g.read_strict(path)
                except g.GrammarError as e:
                    raise _refused(f"{e}. Fix {path.name} before anything else is written to it.") from None

    def _repair_tail(self, path: Path) -> None:
        """L-9: move a partial last line to the quarantine log before appending."""
        if not path.exists() or path.stat().st_size == 0:
            return
        data = path.read_bytes()
        if data.endswith(b"\n"):
            return
        cut = data.rfind(b"\n") + 1
        self.quarantine.parent.mkdir(exist_ok=True)
        with open(self.quarantine, "ab") as q:
            q.write(f"{self._ts()} {path.name}: ".encode() + data[cut:] + b"\n")
        with open(path, "r+b") as f:
            f.truncate(cut)
        self._raw_append(self.ledger, str(g.make_ledger_line(
            self._ts(), "Nurse", "WARN", path.name, "partial last line moved to .apiary/quarantine.log")) + "\n")

    def _raw_append(self, path: Path, text: str) -> None:
        if path == self.ledger:
            self._repair_tail(path)
        with open(path, "ab") as f:
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())

    def _append(self, path: Path, text: str) -> None:
        self._repair_tail(path)
        self._raw_append(path, text)

    def _log(self, caste: str, signal: str, path: str, note: str) -> str:
        line = str(g.make_ledger_line(self._ts(), caste, signal, path, note))
        self._append(self.ledger, line + "\n")
        return line

    def _ledger_lines(self) -> list[g.LedgerLine]:
        if not self.ledger.exists():
            return []
        out = []
        for raw in g.read_strict(self.ledger).split("\n"):
            if g.is_comment(raw):
                continue
            try:
                out.append(g.parse_ledger_line(raw))
            except g.GrammarError:
                continue          # malformed lines carry no signal; `apiary validate` reports them
        return out

    def claim_state(self, task_file: str) -> tuple[str, dt.datetime, str] | None:
        """(current token, lease end, task digest) for a task in active/, per 7.2. Call under the lock.
        The digest is "" when the CLAIM line records none."""
        path = f"tasks/active/{task_file}"
        token, lease, digest = None, None, ""
        for line in self._ledger_lines():
            if line.path != path:
                continue
            a = line.attrs
            if line.signal == "CLAIM" and "token" in a:
                token, lease, digest = a["token"], self._lease(a), a.get("task_sha256", "")
            elif line.signal == "REINFORCE" and token and a.get("token") == token:
                renewed = self._lease(a)
                if renewed and (lease is None or renewed > lease):
                    lease = renewed
        if token is None:
            return None
        return token, lease or dt.datetime.min.replace(tzinfo=dt.timezone.utc), digest

    @staticmethod
    def _lease(attrs: dict[str, str]) -> dt.datetime | None:
        try:
            return g.parse_timestamp(attrs["lease_until"])
        except (KeyError, g.GrammarError):
            return None

    @staticmethod
    def _check_args(task_file: str, caste: str, lease_minutes: int | None = None) -> None:
        try:
            g.task_id(task_file)
            g.check_caste(caste)
        except g.GrammarError as e:
            raise _refused(str(e)) from None
        if lease_minutes is not None and not (isinstance(lease_minutes, int) and 1 <= lease_minutes <= 1440):
            raise _refused("lease_minutes must be a whole number from 1 to 1440")

    def _move(self, src: Path, dst: Path, what: str) -> None:
        if dst.exists():
            raise _conflict(f"{dst.relative_to(self.root).as_posix()} already exists (T-2); nothing moved")
        try:
            os.rename(src, dst)          # one atomic rename (P-5); never copy-then-delete
        except PermissionError:
            raise _conflict(f"{what} is open in another program; close it and retry. Nothing changed.") from None

    # --- 7.3 claim -----------------------------------------------------------

    def claim(self, task_file: str, caste: str = "Forager", lease_minutes: int = 60) -> str:
        def op() -> str:
            self._check_args(task_file, caste, lease_minutes)
            with self._lock:
                self._check_encoding()
                src, dst = self.tasks / "pending" / task_file, self.tasks / "active" / task_file
                if not src.is_file():
                    where = next((d for d in ("active", "done") if (self.tasks / d / task_file).exists()), None)
                    raise _conflict(f"{task_file} is not pending" + (f" (it is in {where}/)" if where else ""))
                try:
                    text = g.read_strict(src)
                    task = g.parse_task(text)
                except g.GrammarError as e:
                    raise _refused(f"{task_file} is malformed: {e}") from None
                done = {g.task_id(p.name) for p in (self.tasks / "done").glob("*.task") if g.TASK_NAME.match(p.name)}
                missing = [d for d in task.depends_on if d not in done]
                if missing:
                    raise _refused(f"{task_file} depends on unfinished task(s) {', '.join(f'{d:03d}' for d in missing)}")
                self._move(src, dst, task_file)
                token = secrets.token_hex(8)
                lease = g.format_timestamp(self.now() + dt.timedelta(minutes=lease_minutes))
                self._log(caste, "CLAIM", f"tasks/active/{task_file}",
                          f"token={token} lease_until={lease} task_sha256={g.task_digest(text)}")
            # P-19: the task as claimed, so the claimant does not read the file in a call of its own.
            return f"CLAIMED {task_file} token={token} lease_until={lease}\n" + text.replace("\r\n", "\n")
        return self._run(op)

    # --- 7.4 renew -----------------------------------------------------------

    def renew(self, task_file: str, token: str, caste: str = "Forager", lease_minutes: int = 60) -> str:
        def op() -> str:
            self._check_args(task_file, caste, lease_minutes)
            with self._lock:
                self._check_encoding()
                self._require_claim(task_file, token)
                lease = g.format_timestamp(self.now() + dt.timedelta(minutes=lease_minutes))
                self._log(caste, "REINFORCE", f"tasks/active/{task_file}", f"renew token={token} lease_until={lease}")
            return f"RENEWED {task_file} lease_until={lease}"
        return self._run(op)

    def _require_claim(self, task_file: str, token: str) -> None:
        if not (self.tasks / "active" / task_file).is_file():
            raise _conflict(f"{task_file} is not active")
        state = self.claim_state(task_file)
        if not token or state is None or state[0] != token:
            raise _conflict(f"{task_file} is not claimed with this token; it may have been resumed and "
                            "re-claimed. Claim it again or escalate.")

    def _require_unchanged(self, task_file: str, caste: str) -> None:
        """P-18: the task file must be the one that was claimed. Call under the lock."""
        recorded = self.claim_state(task_file)[2]
        if not recorded:
            raise _refused(f"{task_file}'s claim records no task_sha256 (an older tool claimed it). "
                           "Resume returns it once its lease ends; then claim it again.")
        try:
            now = g.task_digest(g.read_strict(self.tasks / "active" / task_file))
        except g.GrammarError as e:
            now = f"unreadable ({e.rule})"
        if now != recorded:
            self._log(caste, "WARN", f"tasks/active/{task_file}", "close refused: task file changed since claim")
            raise _refused(f"{task_file} changed since it was claimed, so its acceptance line is not the one "
                           "that was agreed. Nothing closed. Restore it, or escalate to the Queen.")

    # --- 7.5 close -----------------------------------------------------------

    def close(self, task_file: str, token: str, caste: str = "Forager") -> str:
        def op() -> str:
            self._check_args(task_file, caste)
            active = self.tasks / "active" / task_file
            with self._lock:
                self._check_encoding()
                self._require_claim(task_file, token)
                self._require_unchanged(task_file, caste)
                try:
                    task = g.parse_task(g.read_strict(active))
                    line = task.acceptance
                    argv = g.tokenize_acceptance(line)
                except g.GrammarError as e:
                    raise _refused(f"acceptance not run: {e}") from None
            exe, conn = self._resolve_connector(argv[0])
            limit = (conn.timeout_s if conn else None) or ACCEPTANCE_TIMEOUT_S      # C-6
            errors: list[str] = []
            try:
                run = subprocess.run([exe, *argv[1:]], cwd=self.root, stdin=subprocess.DEVNULL,
                                     capture_output=True, timeout=limit)
                code, out = run.returncode, (run.stdout + run.stderr).decode("utf-8", "replace")
                errors = conn.errors(out) if conn else []
            except subprocess.TimeoutExpired:
                code, out = None, f"timed out after {limit}s"
            with self._lock:
                self._check_encoding()
                try:
                    self._require_claim(task_file, token)       # P-11: re-check after the unlocked run
                except _Stop:
                    raise _conflict(f"{task_file} changed hands while acceptance ran; nothing closed") from None
                self._require_unchanged(task_file, caste)
                if code != 0 or errors:
                    why = ("timed out" if code is None else f"exit {code}") + (", error pattern matched" if errors else "")
                    self._log(caste, "WARN", f"tasks/active/{task_file}", f"close refused: acceptance {why}")
                    shown = "".join(f"\n{e}" for e in errors)
                    raise _refused(f"acceptance {why}; task stays active{shown}\n{out[-1500:]}")
                self._move(active, self.tasks / "done" / task_file, task_file)
                approved = ", human approved" if task.fields.get("by") == "Human" else ""      # K-2
                self._log(caste, "DONE", f"tasks/done/{task_file}", f"acceptance passed{approved} token={token}")
            return f"DONE {task_file}"
        return self._run(op)

    def _resolve(self, program: str) -> str:
        return self._resolve_connector(program)[0]

    def _resolve_connector(self, program: str) -> tuple[str, connectors.Connector | None]:
        """The program to run, and the connector it resolved through (C-2), if any."""
        if program == "python":                                          # A-3
            return sys.executable, None
        if connectors.NAME.match(program):                               # C-2: a connector name, before PATH
            try:
                c = connectors.load(self.root, program)
            except ValueError as e:
                raise _refused(f"acceptance not run: {e}") from None
            if c:
                exe = c.resolve()
                if not exe:
                    raise _refused(f"acceptance not run: connector {program!r} points at {c.program!r}, "
                                   "which is not on this machine")
                return exe, c
        if "/" in program or "\\" in program:
            found = shutil.which(str(self.root / program))
        else:
            found = shutil.which(program)
        if not found:
            raise _refused(f"acceptance not run: program {program!r} not found on PATH")
        return found, None

    # --- 7.6 resume ----------------------------------------------------------

    def resume(self, caste: str = "Nurse") -> str:
        def op() -> str:
            try:
                g.check_caste(caste)
            except g.GrammarError as e:
                raise _refused(str(e)) from None
            returned, kept, notes = 0, 0, []
            with self._lock:
                self._check_encoding()
                now = self.now()
                for task in sorted((self.tasks / "active").glob("*.task")):
                    state = self.claim_state(task.name)
                    if state is None:
                        why = "no claim"
                    elif now > state[1]:
                        why = "lease expired"
                    else:
                        kept += 1
                        continue
                    try:
                        self._move(task, self.tasks / "pending" / task.name, task.name)
                    except _Stop as stop:
                        kept += 1
                        notes.append(f"kept {task.name}: {stop}")
                        continue
                    self._log(caste, "EVAPORATE", f"tasks/pending/{task.name}", f"returned on resume: {why}")
                    returned += 1
                    notes.append(f"returned {task.name}: {why}")
            return "\n".join([f"RESUMED returned={returned} kept={kept}", *notes])
        return self._run(op)

    # --- 8 other operations --------------------------------------------------

    def _check_task_fields(self, caste: str, slug, objective, acceptance="", writes="", why="", reads="",
                           out_of_scope="", gate_code="", gate_args="", lane="", by="") -> dict:
        """O-3's checks that need no colony state. Returns the task's collapsed fields."""
        try:
            g.check_caste(caste)
        except g.GrammarError as e:
            raise _refused(str(e)) from None
        texts = (objective, acceptance, writes, why, reads, out_of_scope, gate_code, gate_args, lane, by)
        if not all(isinstance(v, str) for v in texts):
            raise _refused("every task field is text")
        if by and by not in g.TASK_BY:                                   # K-1
            raise _refused(f"by must be one of {', '.join(g.TASK_BY)}: who does the task (Human is a checkpoint "
                           "that closes only on the human's approval)")
        if lane and not (g.TASK_SLUG.fullmatch(lane) and len(lane) <= 40):
            raise _refused("lane must be lowercase words joined by '-' (geometry, look, docs)")
        if not isinstance(slug, str) or not g.TASK_SLUG.fullmatch(slug) or len(slug) > 50:
            raise _refused("slug must be lowercase words joined by '-', at most 50 characters (save-slots)")
        fields = {k: g.collapse(v or "") for k, v in (("objective", objective), ("why", why), ("writes", writes),
                                                      ("reads", reads), ("out-of-scope", out_of_scope))}
        if not fields["objective"]:
            raise _refused(f"{slug}: objective is required: one sentence saying what is true when the task is done")
        acceptance_in = g.collapse(acceptance or "")
        if gate_code and acceptance_in:
            raise _refused(f"{slug}: give either acceptance or gate_code, not both: a gate becomes the acceptance "
                           "command")
        if not gate_code and not acceptance_in:
            raise _refused(f"{slug}: acceptance is required: one command that exits 0 when the task is done. If no "
                           "existing command can check it, pass gate_code (a Python check script)")
        if gate_code:
            try:
                compile(gate_code, "gate", "exec")
            except SyntaxError as e:
                raise _refused(f"{slug}: gate_code does not compile: {e.msg} (line {e.lineno})") from None
        return {"slug": slug, "fields": fields, "acceptance": acceptance_in, "gate_code": gate_code or "",
                "gate_args": g.collapse(gate_args or ""), "lane": lane or "", "by": by or ""}

    def _render_task(self, caste: str, nid: int, d: dict, deps: list[int]) -> tuple[str, str, str]:
        """O-3's checks for task `nid`, under the lock. Returns (file name, task text, gate path or "")."""
        if nid > 999_999:
            raise _refused("no task ids left (T-1 allows six digits)")
        name = f"{nid:03d}-{d['slug']}.task"
        gate_rel = f"gates/check_{nid:03d}.py" if d["gate_code"] else ""
        if gate_rel and (self.root / gate_rel).exists():
            raise _conflict(f"{gate_rel} already exists; create_task never replaces a gate")
        line = f"python {gate_rel} {d['gate_args']}".strip() if gate_rel else d["acceptance"]
        try:
            argv = g.tokenize_acceptance(line)
        except g.GrammarError as e:
            raise _refused(f"{d['slug']}: acceptance: {e.why}") from None
        if not gate_rel:
            try:
                self._resolve(argv[0])
            except _Stop:
                raise _refused(f"{d['slug']}: acceptance does not start with a command: {argv[0]!r} is not a "
                               "program on PATH. Write a command that exits 0 when the task is done, or pass "
                               "gate_code") from None
        fields = d["fields"]
        text = f"# Created by {caste} with create_task at {self._ts()}.\n"
        text += f"objective: {fields['objective']}\nacceptance: {line}\n"
        for key in ("why", "writes", "reads", "out-of-scope"):
            if fields[key]:
                text += f"{key}: {fields[key]}\n"
        if d["lane"]:
            text += f"lane: {d['lane']}\n"
        if d["by"]:
            text += f"by: {d['by']}\n"
        if deps:
            text += f"depends-on: {', '.join(f'{x:03d}' for x in sorted(deps))}\n"
        g.parse_task(text)                                   # never write what claim would refuse
        if (self.tasks / "pending" / name).exists():
            raise _conflict(f"{name} already exists")
        return name, text, gate_rel

    @staticmethod
    def _overlap(label: str, writes: str, others) -> None:
        """The no-overlap rule (O-3): refuse if `writes` overlaps any (name, status, writes, depends_on hint)."""
        mine = _write_targets(writes)
        for rel, status, their_writes, tid in others:
            clash = [f"{a} and {b}" for a in mine for b in _write_targets(their_writes) if _overlaps(a, b)]
            if clash:
                raise _refused(f"{label}writes overlap {rel} ({clash[0]}), which is {status} and could run at the "
                               f"same time. Two tasks that can run at once never write the same file: make this "
                               f"task wait for it (depends_on {tid}), or narrow writes so they do not overlap")

    def _write_task(self, caste: str, name: str, text: str, gate_rel: str, gate_code: str, how: str) -> None:
        nid = g.task_id(name)
        if gate_rel:
            self._write_new(self.root / gate_rel, gate_code)
            self._log(caste, "DEPOSIT", gate_rel, f"acceptance check for task {nid:03d}, written by {how}")
        self._write_new(self.tasks / "pending" / name, text)
        self._log(caste, "DEPOSIT", f"tasks/pending/{name}", f"task created with {how}")

    def create_task(self, caste: str, slug: str, objective: str, acceptance: str = "", writes: str = "",
                    why: str = "", reads: str = "", depends_on: str = "", out_of_scope: str = "",
                    gate_code: str = "", gate_args: str = "", lane: str = "", by: str = "") -> str:
        """O-3: write a new, valid task to tasks/pending/ (and, optionally, a new gate). Never overwrites."""
        def op() -> str:
            d = self._check_task_fields(caste, slug, objective, acceptance, writes, why, reads, out_of_scope,
                                        gate_code, gate_args, lane, by)
            deps: list[int] = []
            for item in filter(None, (s.strip() for s in (depends_on or "").split(","))):
                if not item.isdigit():
                    raise _refused(f"depends_on item {item!r} is not a task id")
                deps.append(int(item))
            with self._lock:
                self._check_encoding()
                index = self._task_index()
                missing = [x for x in deps if x not in index]
                if missing:
                    raise _refused(f"depends_on names task(s) that do not exist: {', '.join(map(str, missing))}")
                waits_for = self._ancestors(deps, index)
                self._overlap("", d["fields"]["writes"], [
                    (rel, status, task.fields.get("writes", ""), tid) for tid, (rel, status, task)
                    in sorted(index.items()) if status in ("pending", "active") and tid not in waits_for and task])
                name, text, gate_rel = self._render_task(caste, max(index, default=0) + 1, d, deps)
                self._write_task(caste, name, text, gate_rel, d["gate_code"], "create_task")
            return f"CREATED {name}" + (f" gate={gate_rel}" if gate_rel else "")
        return self._run(op)

    def create_plan(self, caste: str, tasks, decisions=None) -> str:
        """O-5: record a plan's decisions and create all its tasks in one operation, all or nothing."""
        def op() -> str:
            with self._lock:
                entries, rendered, local = self._check_plan(caste, tasks, decisions)
                # Everything is checked: write the decisions, then the tasks in dependency order.
                if entries and not (self.traces.exists() and g.read_strict(self.traces)):
                    self._append(self.traces, "# TRACES\n")
                for key, _, entry in entries:
                    self._append(self.traces, entry)
                    self._log(caste, "TRACE", "TRACES.md", f"KEY {key}")
                for slug, name, text, gate_rel in rendered:
                    self._write_task(caste, name, text, gate_rel, local[slug]["gate_code"], "create_plan")
            return "\n".join([f"CREATED {len(rendered)} tasks {len(entries)} decisions"] +
                             [f"{slug} {name}" + (f" gate={gate_rel}" if gate_rel else "")
                              for slug, name, _, gate_rel in rendered])
        return self._run(op)

    def check_plan(self, caste: str, tasks, decisions=None) -> str:
        """B-1: the refusal create_plan would give these arguments now, or "" if it would create them. Reads only:
        no lock, no folders, no file written."""
        try:
            self._check_plan(caste, tasks, decisions)
        except _Stop as stop:
            return str(stop)
        except g.GrammarError as e:
            return f"REFUSED: {e}"
        return ""

    def task_refusals(self, caste: str, tasks) -> list[str]:
        """B-1: every task's own refusal, from the checks that need no other task and no colony state."""
        out = []
        for i, t in enumerate(tasks if isinstance(tasks, list) else []):
            try:
                self._check_plan_task(caste, i, t)
            except _Stop as stop:
                out.append(str(stop))
        return out

    def _check_plan_task(self, caste: str, i: int, t) -> dict:
        if not isinstance(t, dict):
            raise _refused(f"task {i + 1} is not an object")
        unknown = sorted(set(t) - PLAN_FIELDS)
        if unknown:
            raise _refused(f"task {i + 1}: unknown field(s) {', '.join(unknown)}")
        return self._check_task_fields(caste, t.get("slug"), t.get("objective", ""), t.get("acceptance", ""),
                                       t.get("writes", ""), t.get("why", ""), t.get("reads", ""),
                                       t.get("out_of_scope", ""), t.get("gate_code", ""),
                                       t.get("gate_args", ""), t.get("lane", ""), t.get("by", ""))

    def _check_plan(self, caste: str, tasks, decisions) -> tuple[list, list, dict]:
        """O-5's checks, all of them, writing nothing. Returns (decision entries, rendered tasks, drafts by slug)."""
        try:                                         # a client may send the lists as JSON text
            tasks = json.loads(tasks) if isinstance(tasks, str) else tasks
            decisions = json.loads(decisions) if isinstance(decisions, str) and decisions else decisions
        except json.JSONDecodeError:
            raise _refused("tasks and decisions are lists (or JSON text holding lists)") from None
        if not isinstance(tasks, list) or not tasks:
            raise _refused("tasks must be a non-empty list of task objects (slug, objective, acceptance, "
                           "writes, depends_on, lane, ...)")
        if decisions is not None and not isinstance(decisions, list):
            raise _refused("decisions must be a list of {key, value} objects")
        drafts, local = [], {}
        for i, t in enumerate(tasks):
            d = self._check_plan_task(caste, i, t)
            if d["slug"] in local:
                raise _refused(f"slug {d['slug']!r} appears twice in the plan")
            dep_in = t.get("depends_on", [])
            if isinstance(dep_in, str):
                dep_in = [s for s in (x.strip() for x in dep_in.split(",")) if s]
            if not isinstance(dep_in, list) or not all(isinstance(x, (str, int)) for x in dep_in):
                raise _refused(f"{d['slug']}: depends_on is a list of slugs in this plan or existing task ids")
            d["dep_in"] = [str(x).strip() for x in dep_in]
            local[d["slug"]] = d
            drafts.append(d)
        entries = []
        for i, dec in enumerate(decisions or []):
            if not isinstance(dec, dict) or set(dec) - {"key", "value", "supersedes"}:
                raise _refused(f"decision {i + 1} must be an object with key and value")
            try:
                entries.append((dec.get("key"), dec.get("supersedes", ""),
                                g.make_trace_entry(self._ts(), caste, dec.get("key"), dec.get("value"),
                                                   dec.get("supersedes", ""))))
            except (g.GrammarError, TypeError, AttributeError) as e:
                raise _refused(f"decision {i + 1}: {getattr(e, 'why', e)}") from None
        if len({k for k, _, _ in entries}) != len(entries):
            raise _refused("a decision key appears twice in the plan")
        self._check_encoding()
        index = self._task_index()
        for d in drafts:
            d["plan_deps"], d["old_deps"] = [], []
            for x in d["dep_in"]:
                if x in local:
                    d["plan_deps"].append(x)
                elif x.isdigit() and int(x) in index:
                    d["old_deps"].append(int(x))
                else:
                    raise _refused(f"{d['slug']}: depends_on {x!r} is neither a slug in this plan nor an "
                                   "existing task id")
        order, state = [], {}

        def visit(slug: str) -> None:            # dependency order; a cycle is refused
            if state.get(slug) == "done":
                return
            if state.get(slug) == "open":
                raise _refused(f"depends_on forms a cycle through {slug!r}")
            state[slug] = "open"
            for dep in local[slug]["plan_deps"]:
                visit(dep)
            state[slug] = "done"
            order.append(slug)
        for d in drafts:
            visit(d["slug"])
        nid = max(index, default=0)
        for slug in order:
            nid += 1
            local[slug]["id"] = nid
        for slug in order:                       # ancestors: existing ids plus earlier plan tasks
            d = local[slug]
            d["deps"] = d["old_deps"] + [local[x]["id"] for x in d["plan_deps"]]
            d["up_plan"] = set(d["plan_deps"]).union(*(local[x]["up_plan"] for x in d["plan_deps"]))
            d["up_old"] = self._ancestors(d["old_deps"], index).union(
                *(local[x]["up_old"] for x in d["plan_deps"]))
        for slug in order:
            d = local[slug]
            self._overlap(f"{slug}: ", d["fields"]["writes"], [
                (rel, status, task.fields.get("writes", ""), tid) for tid, (rel, status, task)
                in sorted(index.items()) if status in ("pending", "active") and tid not in d["up_old"]
                and task] + [
                (f"plan task {o}", "in this plan", local[o]["fields"]["writes"], o) for o in order
                if o != slug and o not in d["up_plan"] and slug not in local[o]["up_plan"]])
        rendered = [(slug, *self._render_task(caste, local[slug]["id"], local[slug], local[slug]["deps"]))
                    for slug in order]
        existing = g.read_strict(self.traces) if self.traces.exists() else ""
        keys = {ln[len("## KEY: "):] for ln in existing.split("\n") if ln.startswith("## KEY: ")}
        for key, supersedes, _ in entries:
            if key in keys:
                raise _conflict(f"decision key {key!r} already has an entry (R-3); use a new key with "
                                f"supersedes={key!r}")
            if supersedes and supersedes not in keys:
                raise _refused(f"R-4: supersedes names unknown key {supersedes!r}")
        return entries, rendered, local

    # --- 13 connectors ------------------------------------------------------

    def run_connector(self, caste: str, connector: str, args: str, outputs: str = "", task_file: str = "") -> str:
        """C-3: run an outside program without a shell and leave a run record in runs/."""
        def op() -> str:
            try:
                g.check_caste(caste)
            except g.GrammarError as e:
                raise _refused(str(e)) from None
            if not isinstance(connector, str) or not connectors.NAME.match(connector):
                raise _refused(f"connector name {connector!r} must match [a-z][a-z0-9-]{{1,30}}")
            try:
                c = connectors.load(self.root, connector)
            except ValueError as e:
                raise _refused(str(e)) from None
            if c is None:
                known = ", ".join(connectors.names(self.root)) or "none yet"
                raise _refused(f"no connector {connector!r} (this colony has: {known}). A human adds one with "
                               f"`apiary connect add {connector}`")
            try:
                argv = g.tokenize_acceptance(args) if (args or "").strip() else []
            except g.GrammarError as e:
                raise _refused(f"args: {e.why}") from None
            outs = [o.strip() for o in (outputs or "").split(",") if o.strip()]
            for o in outs:
                try:
                    g.check_path(o)
                except g.GrammarError as e:
                    raise _refused(f"output {o!r}: {e.why}") from None
            if task_file:
                try:
                    g.task_id(task_file)
                except g.GrammarError as e:
                    raise _refused(str(e)) from None
            exe = c.resolve()
            if not exe:
                raise _refused(f"connector {connector!r} points at {c.program!r}, which is not on this machine")
            version = c.probe()
            limit = c.timeout_s or ACCEPTANCE_TIMEOUT_S                  # C-6
            started = self.now()
            t0 = time.monotonic()
            try:
                run = subprocess.run([exe, *argv], cwd=self.root, stdin=subprocess.DEVNULL, capture_output=True,
                                     timeout=limit)
                code, out, err, timed_out = run.returncode, run.stdout, run.stderr, False
            except subprocess.TimeoutExpired as e:
                code, out, err, timed_out = -1, e.stdout or b"", e.stderr or b"", True
            seconds = round(time.monotonic() - t0, 3)
            hashes = []
            for o in outs:
                p = self.root / o
                hashes.append({"path": o, "sha256": hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None})
            stdout, stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
            errors = c.errors(stdout + "\n" + stderr)
            missing = [h["path"] for h in hashes if not h["sha256"]]
            why = ([f"timed out after {limit}s"] if timed_out else [f"exit {code}"] if code != 0 else []) + \
                  ([f"error pattern matched: {errors[0][:200]}"] if errors else []) + \
                  ([f"missing outputs: {', '.join(missing)}"] if missing else [])
            record = {"connector": connector, "program": Path(exe).as_posix(), "version": version,
                      "version_changed": bool(c.version) and c.version != version,
                      "argv": [Path(exe).as_posix(), *argv], "exit_code": code, "timed_out": timed_out,
                      "seconds": seconds, "task_file": task_file, "caste": caste,
                      "timestamp": g.format_timestamp(started),
                      "stdout": stdout[-4000:], "stderr": stderr[-4000:],
                      "outputs": hashes, "ok": not why, "errors": errors, "missing_outputs": missing}
            stamp = started.strftime("%Y%m%dT%H%MZ")
            name = f"runs/{stamp}-{connector}-{secrets.token_hex(2)}.json"
            produced = sum(1 for h in hashes if h["sha256"])
            with self._lock:
                self._check_encoding()
                self._write_new(self.root / name, json.dumps(record, indent=2) + "\n")
                v = g.collapse(version)[:30].replace("|", "/")
                self._log(caste, "DEPOSIT", name, f"{connector} {v} exit {code}, {produced} of {len(hashes)} outputs"
                          + ("" if not why else ", NOT OK"))
            return f"RAN {name} exit={code}" + ("" if not why else f" NOT OK: {'; '.join(why)}")
        return self._run(op)

    # --- plans and lanes (O-3 no-overlap, O-4) ------------------------------

    def _task_index(self) -> dict[int, tuple[str, str, g.Task | None]]:
        """id -> (path relative to the root, status folder, parsed task or None if malformed)."""
        out: dict[int, tuple[str, str, g.Task | None]] = {}
        for p in sorted(self.tasks.rglob("*.task")):
            if not g.TASK_NAME.match(p.name):
                continue
            try:
                task = g.parse_task(g.read_strict(p))
            except g.GrammarError:
                task = None
            out[g.task_id(p.name)] = (p.relative_to(self.root).as_posix(), p.parent.name, task)
        return out

    @staticmethod
    def _ancestors(deps: list[int], index: dict) -> set[int]:
        seen: set[int] = set()
        stack = list(deps)
        while stack:
            d = stack.pop()
            if d in seen:
                continue
            seen.add(d)
            task = index.get(d, (None, None, None))[2]
            stack.extend(task.depends_on if task else [])
        return seen

    def plan_status(self) -> str:
        """O-4: what can start now. Read-only."""
        def op() -> str:
            index = self._task_index()
            done = {tid for tid, (_, status, _t) in index.items() if status == "done"}
            rows, counts = [], {"ready": 0, "blocked": 0, "active": 0}
            for tid, (rel, status, task) in sorted(index.items()):
                if status not in ("pending", "active"):
                    continue
                name = rel.rsplit("/", 1)[-1]
                lane = (task.fields.get("lane") if task else "") or "-"
                if task is None:
                    rows.append((lane, f"malformed {name} (claim will refuse it)"))
                    continue
                if status == "active":
                    counts["active"] += 1
                    rows.append((lane, f"active  {name} lane={lane}"))
                    continue
                waiting = [d for d in task.depends_on if d not in done]
                if waiting:
                    counts["blocked"] += 1
                    rows.append((lane, f"blocked {name} lane={lane} waits for {', '.join(f'{d:03d}' for d in waiting)}"))
                else:
                    counts["ready"] += 1
                    rows.append((lane, f"ready   {name} lane={lane}"))
            head = (f"PLAN ready={counts['ready']} blocked={counts['blocked']} active={counts['active']} "
                    f"done={len(done)}")
            return "\n".join([head] + [r for _, r in sorted(rows, key=lambda x: x[0])])
        return self._run(op)

    def _write_new(self, path: Path, text: str) -> None:
        """Write a new file atomically (temp file, then rename). Fails if the file exists."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        try:
            if path.exists():
                raise _conflict(f"{path.relative_to(self.root).as_posix()} already exists")
            os.rename(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def append_ledger(self, caste: str, signal: str, path: str, note: str) -> str:
        def op() -> str:
            line = g.make_ledger_line(self._ts(), caste, signal, path, note)     # O-1: refuse, never clean
            if signal in g.PROTOCOL_SIGNALS:
                raise _refused(f"L-10: {signal} lines are written only by claim_task and close_task")
            if signal in g.LOCK_SIGNALS:
                raise _refused(f"L-11: {signal} lines are written only by unlock_test and relock_test")
            reserved = [a for a in g.RESERVED_ATTRS if a in line.attrs]
            if reserved:
                raise _refused(f"L-10: the note attribute(s) {', '.join(reserved)} are reserved for the protocol")
            with self._lock:
                self._check_encoding()
                written = self._log(caste, signal, path, note)
            return f"APPENDED {written}"
        return self._run(op)

    def write_trace(self, caste: str, key: str, value: str, supersedes: str = "") -> str:
        def op() -> str:
            entry = g.make_trace_entry(self._ts(), caste, key, value, supersedes)
            with self._lock:
                self._check_encoding()
                existing = g.read_strict(self.traces) if self.traces.exists() else ""
                keys = {ln[len("## KEY: "):] for ln in existing.split("\n") if ln.startswith("## KEY: ")}
                if key in keys:
                    raise _conflict(f"key {key!r} already has an entry (R-3); write a new key with "
                                    f"supersedes={key!r}")
                if supersedes and supersedes not in keys:
                    raise _refused(f"R-4: supersedes names unknown key {supersedes!r}")
                if not existing:
                    self._append(self.traces, "# TRACES\n")
                self._append(self.traces, entry)
                self._log(caste, "TRACE", "TRACES.md", f"KEY {key}")
            return f"TRACED {key}"
        return self._run(op)

    # --- the Queen's lock tools (apiary.locktools) --------------------------------------------

    @staticmethod
    def _note(text: str) -> str:
        text = " ".join(text.replace("|", "/").split())
        return text if len(text) <= g.NOTE_MAX else text[:g.NOTE_MAX - 1] + "…"

    @staticmethod
    def _queen_only(caste: str, what: str) -> None:
        if caste != "Queen":
            raise _refused(f"only the Queen {what}. A {caste} files a WARN for the test (append_ledger) and stops")

    def unlock_test(self, caste: str, path: str, reason: str, evidence: str) -> str:
        def op() -> str:
            self._queen_only(caste, "unlocks a locked test")
            with self._lock:
                self._check_encoding()
                warns = [ln for ln in self._ledger_lines() if ln.signal in ("WARN", "ESCALATE")]
                try:
                    change = locktools.unlock(self.root, path, reason, evidence, warns, by=caste)
                except locktools.Refused as e:
                    raise _refused(str(e)) from None
                self._log(caste, "UNLOCK", change["path"], self._note(f"reason={reason} evidence: {evidence}"))
            return (f"UNLOCKED {change['path']} [{change['id']}]. Edit only what the evidence needs, then "
                    "relock_test. Your next message to the human must carry the lock_report() block.")
        return self._run(op)

    def relock_test(self, caste: str, paths: str, story: str, approve_weakening: bool = False) -> str:
        def op() -> str:
            self._queen_only(caste, "relocks a test")
            names = [p for p in str(paths).split(",") if p.strip()]
            with self._lock:
                self._check_encoding()
                here = os.getcwd()
                try:
                    os.chdir(self.root)                 # the godot connector and the runner are colony-relative
                    changes = locktools.relock(self.root, names, story, bool(approve_weakening))
                except locktools.Refused as e:
                    raise _refused(str(e)) from None
                finally:
                    os.chdir(here)
                for c in changes:
                    self._log(caste, "RELOCK", c["path"], self._note(
                        f"story={story} weakened={'yes' if c['weakened'] else 'no'} {c['what']}"))
            body = "\n".join(f"RELOCKED {c['path']} [{c['id']}]: {c['what']}" for c in changes)
            return body + "\nYour next message to the human must carry the lock_report() block."
        return self._run(op)

    def lock_report(self, caste: str = "Queen") -> str:
        return (locktools.report(self.root) + "\n\n(Put this block, unchanged, at the top of your next message to "
                "the human. The Stop hook checks for every [L<n>] in it.)")
