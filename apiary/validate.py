"""Check a colony directory against the spec. Reads only; never repairs."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import grammar as g


@dataclass(frozen=True)
class Finding:
    rule: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.rule:5} {self.where}: {self.message}"


def validate(root: str | Path) -> list[Finding]:
    root = Path(root)
    out: list[Finding] = []
    lines: list[g.LedgerLine] = []

    ledger = root / "PHEROMONE_LEDGER.md"
    if ledger.exists():
        data = ledger.read_bytes()
        try:
            text = g.decode_strict(data, ledger.name)
        except g.GrammarError as e:
            out.append(Finding(e.rule, ledger.name, e.why))
            text = ""
        if data and not data.endswith(b"\n"):
            out.append(Finding("L-9", ledger.name, "last line has no LF: a partial append (the next write quarantines it)"))
        for n, raw in enumerate(text.split("\n"), 1):
            if g.is_comment(raw):
                continue
            try:
                lines.append(g.parse_ledger_line(raw))
            except g.GrammarError as e:
                out.append(Finding(e.rule, f"{ledger.name}:{n}", e.why))

    traces = root / "TRACES.md"
    if traces.exists():
        try:
            g.parse_traces(g.read_strict(traces))
        except g.GrammarError as e:
            out.append(Finding(e.rule, traces.name, e.why))

    from . import connectors
    cdir = root / "connectors"
    if cdir.is_dir():
        for p in sorted(cdir.glob("*.toml")):
            try:
                if not connectors.NAME.match(p.stem) or connectors.load(root, p.stem) is None:
                    out.append(Finding("C-1", f"connectors/{p.name}", "name must match [a-z][a-z0-9-]{1,30}"))
            except ValueError as e:
                out.append(Finding("C-1", f"connectors/{p.name}", str(e)))

    ids: dict[int, str] = {}
    for status in ("pending", "active", "done"):
        folder = root / "tasks" / status
        if not folder.is_dir():
            out.append(Finding("D-2", f"tasks/{status}/", "missing (any operation creates it)"))
            continue
        for p in sorted(folder.glob("*.task")):
            where = f"tasks/{status}/{p.name}"
            try:
                tid = g.task_id(p.name)
            except g.GrammarError as e:
                out.append(Finding(e.rule, where, e.why))
                continue
            if tid in ids:
                out.append(Finding("T-2", where, f"task id {tid} is also used by {ids[tid]}"))
            ids[tid] = where
            try:
                g.parse_task(g.read_strict(p))
            except g.GrammarError as e:
                out.append(Finding(e.rule, where, e.why))
            if status == "active" and not any(
                    ln.signal == "CLAIM" and ln.path == where and "token" in ln.attrs for ln in lines):
                out.append(Finding("P-14", where, "active with no CLAIM line: an orphan (resume returns it)"))
            if status == "done" and not any(ln.signal == "DONE" and ln.path == where for ln in lines):
                out.append(Finding("P-13", where, "in done/ with no DONE line: moved by hand, not closed"))
    return out


# --- append-only check against git (spec L-7, R-6, T-6) -----------------------

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True)


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def history(root: str | Path, rev: str) -> list[Finding]:
    """Findings for anything an append-only or closed file lost or changed since commit `rev`."""
    root = Path(root).resolve()
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        return [Finding("L-7", str(root), "--since needs a git repository")]
    if _git(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").returncode != 0:
        if rev == "HEAD" and _git(root, "rev-parse", "--verify", "--quiet", "HEAD").returncode != 0:
            return []                                  # no commits yet: nothing to compare against
        return [Finding("L-7", rev, "revision not found, so the append-only check could not run")]
    out: list[Finding] = []
    for name, rule in (("PHEROMONE_LEDGER.md", "L-7"), ("TRACES.md", "R-6")):
        old = _git(root, "show", f"{rev}:./{name}")
        if old.returncode != 0:
            continue                                   # not in that commit
        before = _lf(old.stdout)
        complete = before[:before.rfind(b"\n") + 1]    # a partial last line may be quarantined (L-9)
        path = root / name
        now = _lf(path.read_bytes()) if path.exists() else b""
        if not now.startswith(complete):
            old_lines, new_lines = complete.split(b"\n"), now.split(b"\n")
            n = next((i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b),
                     min(len(old_lines), len(new_lines)))
            out.append(Finding(rule, f"{name}:{n + 1}", f"line changed or removed since {rev}; "
                                                       "this file is append-only"))
    runs = _git(root, "ls-tree", "-r", "--name-only", rev, "--", "runs/")
    for rel in runs.stdout.decode("utf-8", "replace").splitlines():
        if not rel.endswith(".json"):
            continue
        path = root / rel
        if not path.exists():
            out.append(Finding("C-4", rel, f"run record existed at {rev}, now removed"))
        elif _lf(path.read_bytes()) != _lf(_git(root, "show", f"{rev}:./{rel}").stdout):
            out.append(Finding("C-4", rel, f"run record changed since {rev}; run records are never edited"))
    listed = _git(root, "ls-tree", "-r", "--name-only", rev, "--", "tasks/done/")
    for rel in listed.stdout.decode("utf-8", "replace").splitlines():
        if not rel.endswith(".task"):
            continue
        old = _lf(_git(root, "show", f"{rev}:./{rel}").stdout)
        path = root / rel
        if not path.exists():
            out.append(Finding("T-6", rel, f"closed at {rev}, now moved or deleted"))
        elif _lf(path.read_bytes()) != old:
            out.append(Finding("T-6", rel, f"closed at {rev}, now edited"))
    return out
