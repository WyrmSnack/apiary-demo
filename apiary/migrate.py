"""`apiary migrate --check`: what stops an existing colony working under the spec, and the fix for each.

It reads and never writes. An append-only ledger cannot be repaired in place, so the fixes are steps for a human.
The kinds below come from a read-only survey of Kevin's real colonies (2026-10-15) and the Phase 0 kit.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import grammar as g
from .init import CLAUDE_CODE_CONFIG, CLAUDE_SETTINGS, PRE_COMMIT_MARK, PROTOCOL_MARK

ARCHIVE = ("The ledger is append-only, so old lines cannot be corrected in place. A human archives it: "
           "`git mv PHEROMONE_LEDGER.md PHEROMONE_LEDGER.pre-spec.md`, commit, then run `py -m apiary init`, which "
           "starts a new ledger. Do this before init installs the pre-commit check, which would refuse the rename.")
FIXES = {
    "encoding": "Re-save the file as UTF-8 without a byte-order mark (spec E-1). PowerShell 5's Out-File writes UTF-16.",
    "ledger-timestamps": ARCHIVE,
    "ledger-castes": ARCHIVE,
    "ledger-signals": ARCHIVE,
    "ledger-padding": ARCHIVE,
    "ledger-other": ARCHIVE,
    "task-yaml": "Rewrite each as `key: value` lines (spec 5.2): `objective:` and `acceptance:` are required, "
                 "`depends-on:` is a comma-separated list of ids. The spec does not read YAML front matter.",
    "task-names": "Rename to NNN-words.task (3 to 6 digits, lowercase words joined by '-'), spec T-1.",
    "task-malformed": "Each line must be blank, a # comment, or `key: value` with a lowercase key (spec T-3).",
    "task-folders": "The spec has only tasks/pending/, active/ and done/. Move live tasks to pending/ (say why in "
                    "a `why:` line); archive the rest outside tasks/.",
    "acceptance-missing": "Add an `acceptance:` line: one command that exits 0 when the task is done. "
                          "Close cannot run without it.",
    "acceptance-not-a-command": "This reads as a description, not a command. Write a command that exits 0 when it "
                                "is true, usually a test: `python -m pytest -q tests/test_x.py`.",
    "acceptance-shell": "Acceptance runs without a shell (spec section 9), so `&&`, `|`, `;`, quotes and redirects "
                        "do not work. Use one command (`npm --prefix apiary/desktop test` instead of "
                        "`cd apiary/desktop && npm test`), or put the steps in a script and run that.",
    "claims-without-lease": "Claimed by an older tool, with no lease or task hash. Under the spec, `resume` "
                            "returns these to pending (no claim it can trust), and they can be claimed again.",
    "not-installed": "Run `py -m apiary init` in the colony root (archive an old ledger first; see the ledger fix).",
    "other-tools": "Another tool writes this colony too. Two writers with different rules is the failure the spec "
                   "exists to prevent: retire the other tool's write path once this colony uses apiary.",
}
SHELL_BUILTINS = {"cd", "echo", "test", "[", "set", "export", "source", ".", "if", "for", "exit", "true", "false",
                  "type", "dir", "copy", "del", "mkdir", "rm", "ls", "cat", "grep", "wc", "npx", "npm", "node"}
KNOWN_STATUS = {"pending", "active", "done"}


@dataclass
class Item:
    kind: str
    count: int = 0
    examples: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def fix(self) -> str:
        return FIXES[self.kind]

    def add(self, example: str, limit: int = 3) -> None:
        self.count += 1
        if len(self.examples) < limit:
            self.examples.append(example)


def check(root: str | Path) -> list[Item]:
    root = Path(root).resolve()
    items: dict[str, Item] = {}

    def item(kind: str) -> Item:
        return items.setdefault(kind, Item(kind))

    ledger = root / "PHEROMONE_LEDGER.md"
    claims: dict[str, dict[str, str]] = {}
    if ledger.exists():
        try:
            text = g.read_strict(ledger)
        except g.GrammarError as e:
            item("encoding").add(f"{ledger.name}: {e.why}")
            text = ""
        castes: set[str] = set()
        for n, raw in enumerate(text.split("\n"), 1):
            if g.is_comment(raw):
                continue
            where = f"{ledger.name}:{n}"
            fields = [f.strip() for f in raw.split("|")]
            if len(fields) != 5:
                item("ledger-other").add(f"{where}: {len(fields)} fields")
                continue
            ts, caste, signal, path, note = fields
            if re.search(r"\s{2,}\||\|\s{2,}", raw):
                item("ledger-padding").add(where)
            try:
                g.parse_timestamp(ts)
            except g.GrammarError:
                item("ledger-timestamps").add(f"{where}: {ts}")
            if caste not in g.CASTES:
                castes.add(caste)
            if signal not in g.SIGNALS:
                item("ledger-signals").add(f"{where}: {signal}")
            if signal == "CLAIM":
                claims[path] = g.attributes(note)
            try:
                g.check_path(path)
                g.check_note(note)
            except g.GrammarError as e:
                item("ledger-other").add(f"{where}: {e.why}")
        if castes:
            c = item("ledger-castes")
            c.count, c.examples = len(castes), sorted(castes)[:3]
            c.detail = "castes not in the spec: " + ", ".join(sorted(castes))

    tasks = root / "tasks"
    if tasks.is_dir():
        for d in sorted(p for p in tasks.iterdir() if p.is_dir() and p.name not in KNOWN_STATUS):
            item("task-folders").add(f"tasks/{d.name}/", limit=50)
        for p in sorted(tasks.rglob("*.task")):
            rel = p.relative_to(root).as_posix()
            try:
                g.task_id(p.name)
            except g.GrammarError:
                item("task-names").add(rel)
            try:
                text = g.read_strict(p)
            except g.GrammarError as e:
                item("encoding").add(f"{rel}: {e.why}")
                continue
            first = next((ln for ln in text.split("\n") if ln.strip()), "")
            if first.strip() == "---":
                item("task-yaml").add(rel)
                continue
            m = re.search(r"^acceptance:\s*(.*)$", text, re.M)
            if not m or not m.group(1).strip():
                item("acceptance-missing").add(rel)
            else:
                line = m.group(1).strip()
                program = line.split()[0]
                if program != "python" and program not in SHELL_BUILTINS and not shutil.which(program):
                    item("acceptance-not-a-command").add(f"{rel}: {line[:60]}")
                else:
                    try:
                        g.tokenize_acceptance(line)
                    except g.GrammarError:
                        item("acceptance-shell").add(f"{rel}: {line[:60]}")
            try:
                g.parse_task(text)
            except g.GrammarError as e:
                if e.rule == "T-3":
                    item("task-malformed").add(f"{rel}: {e.why}")
            if p.parent.name == "active":
                a = claims.get(f"tasks/active/{p.name}", {})
                if "lease_until" not in a or "task_sha256" not in a:
                    item("claims-without-lease").add(rel, limit=50)

    missing = []
    mcp = root / CLAUDE_CODE_CONFIG
    if not (mcp.exists() and '"colony"' in mcp.read_text(encoding="utf-8", errors="replace")):
        missing.append(CLAUDE_CODE_CONFIG)
    settings = root / CLAUDE_SETTINGS
    if not (settings.exists() and "apiary.hook" in settings.read_text(encoding="utf-8", errors="replace")):
        missing.append(f"{CLAUDE_SETTINGS} (guard)")
    claude_md = root / "CLAUDE.md"
    if not (claude_md.exists() and PROTOCOL_MARK in claude_md.read_text(encoding="utf-8", errors="replace")):
        missing.append("CLAUDE.md (protocol)")
    hook = root / ".git" / "hooks" / "pre-commit"
    if (root / ".git").is_dir() and not (hook.exists() and PRE_COMMIT_MARK in hook.read_text(errors="replace")):
        missing.append(".git/hooks/pre-commit")
    for m in missing:
        item("not-installed").add(m, limit=10)

    for other in (".cursor", "colony/bin", "tools/claim.py", "mcp/substrate_server.py"):
        if (root / other).exists():
            item("other-tools").add(other)
    return list(items.values())


def report(root: str | Path) -> tuple[int, str]:
    items = check(root)
    lines = [f"apiary migrate --check {Path(root).resolve()}", "Read only: nothing was changed.", ""]
    if not items:
        return 0, "\n".join(lines + ["No blockers: this colony works under the spec."])
    for it in items:
        lines.append(f"[{it.kind}] {it.count}: {it.detail or ', '.join(it.examples)}"
                     + (" ..." if it.count > len(it.examples) and not it.detail else ""))
        lines.append(f"    fix: {it.fix}")
    lines += ["", f"{len(items)} kind(s) of blocker. Fix them in the order shown, the ledger first."]
    return 1, "\n".join(lines)
