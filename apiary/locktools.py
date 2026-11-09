"""The Queen's lock tools: unlock a locked test, edit it, relock it, and report every change to the human.

Measured in the Beyond the Ice Wall colony (S1 to S4b, 2026-10-17): 18 of about 32 human turns went to locks, and the
human hand-edited 12 entries of .apiary/tdd/locks.json. This module replaces those hand edits:

- unlock: the Queen names a reason and evidence; a WARN or ESCALATE for the file must already be in the ledger since
  it was locked. The entry stays, marked "unlocked"; the locked text is kept under .apiary/tdd/history/ for audit.
- relock: runs the edited file, refuses a regression of an unchanged green test, refuses an edit that weakens a test
  unless the human approved it in chat (the guard checks their words), and writes the hash itself.
- report: every change waits in .apiary/tdd/unreported.jsonl until the Queen's message to the human carries the
  lock_report() block; the Stop hook (apiary.hook) enforces that.

Locks gain two optional keys, so entries written before this version keep working: "tests" (per test: the hash of
its body and when it went green) and "unlocked" (while the Queen edits it).
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .gates import tdd

REASONS = {
    "impassable": "no code that follows the story can pass it",
    "conflict": "it contradicts a newer story or another locked test",
    "requirement_change": "a later slice legitimately changed what it pins",
    "nondeterministic": "the expected value depends on a random roll",
}
TDD = Path(".apiary/tdd")
UNREPORTED = TDD / "unreported.jsonl"
REPORTED = TDD / "reported.jsonl"
HISTORY = TDD / "history"
APPROVAL = "approve weakening"


class Refused(Exception):
    pass


# --- reading GDScript tests ----------------------------------------------------------------

_FUNC = re.compile(r"^func\s+(test_\w+)\s*\(")
_CHECK = re.compile(r"\b(check_eq|check_near|check|assert_\w+|assert)\s*\(")
_RANGE = re.compile(r"(<=|>=|(?<![<>=!])<(?!=)|(?<![<>=-])>(?!=)|!=)")


def _clean(line: str) -> str:
    """A line without its trailing comment or spaces; '' for blank and comment-only lines."""
    out, quote = [], ""
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def split_tests(text: str) -> tuple[dict[str, str], str]:
    """({test name: body}, everything else), comments and blank lines dropped."""
    tests: dict[str, list[str]] = {}
    other: list[str] = []
    current: list[str] | None = None
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = _clean(raw)
        if not line:
            continue
        m = _FUNC.match(line)
        if m:
            current = tests.setdefault(m.group(1), [])
            current.append(line)
        elif line[0] in " \t" and current is not None:
            current.append(line)
        else:
            current = other if line.startswith("func ") or line[0] not in " \t" else current
            if current is other or current is None:
                other.append(line)
                current = other
            else:
                current.append(line)
    return {k: "\n".join(v) for k, v in tests.items()}, "\n".join(other)


def body_sha(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _args(text: str, start: int) -> tuple[list[str], int]:
    """Top-level arguments of the call whose '(' is at text[start]; and the index after its ')'."""
    depth, quote, cur, args, i = 0, "", [], [], start + 1
    while i < len(text):
        ch = text[i]
        if quote:
            cur.append(ch)
            if ch == "\\":
                cur.append(text[i + 1] if i + 1 < len(text) else "")
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            if depth == 0:
                args.append("".join(cur).strip())
                return [a for a in args if a], i + 1
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    return [a for a in args if a], i


@dataclass
class Check:
    kind: str
    args: list[str]

    def _n(self, i: int) -> str:
        return re.sub(r"\s+", "", self.args[i]) if i < len(self.args) else ""

    @property
    def actual(self) -> str:
        return self._n(0)

    @property
    def expected(self) -> str:
        return self._n(1) if self.kind in ("check_eq", "check_near") else ""

    @property
    def tolerance(self) -> float:
        try:
            return float(self.args[2]) if self.kind == "check_near" and len(self.args) > 2 else 0.001
        except ValueError:
            return float("inf")

    @property
    def core(self) -> tuple:
        """What it tests: the call without its message."""
        keep = {"check": 1, "check_eq": 2, "check_near": 3}.get(self.kind, len(self.args))
        return (self.kind, tuple(self._n(i) for i in range(min(keep, len(self.args)))))

    def __str__(self) -> str:
        return f"{self.kind}({', '.join(self.args[:2])})"[:80]


def checks_and_setup(body: str) -> tuple[list[Check], str]:
    found, setup, pos = [], [], 0
    for m in _CHECK.finditer(body):
        if m.start() < pos:
            continue
        args, end = _args(body, m.end() - 1)
        found.append(Check(m.group(1), args))
        setup.append(body[pos:m.start()])
        pos = end
    setup.append(body[pos:])
    lines = [ln.strip() for ln in "".join(setup).split("\n")]
    lines = [ln for ln in lines if ln and not ln.startswith("func ")]
    return found, "\n".join(lines)


def _short(s: str, n: int = 40) -> str:
    s = re.sub(r"\s+", " ", s)
    return s if len(s) <= n else s[:n - 1] + "…"


_ITEM = re.compile(r'"([^"]+)"\s*:\s*((?:"[^"]*"|\[[^\]]*\]|\{[^}]*\}|[^,}\]])+)')


def _delta(old: str, new: str) -> str:
    """An expected value's change in a few words: a dictionary by its keys and changed values."""
    if old.strip()[:1] == "{" and new.strip()[:1] == "{":
        a = {k: v.strip() for k, v in _ITEM.findall(old)}
        b = {k: v.strip() for k, v in _ITEM.findall(new)}
        parts = [f"+{k}" for k in b if k not in a] + [f"-{k}" for k in a if k not in b]
        parts += [f"{k} {_short(a[k], 16)} → {_short(b[k], 16)}" for k in a if k in b and a[k] != b[k]]
        if parts:
            return "dict " + ", ".join(parts)
    return f"{_short(old, 24)} → {_short(new, 24)}"


@dataclass
class Diff:
    changes: list[str] = field(default_factory=list)       # what changed, in a few words each
    weakenings: list[str] = field(default_factory=list)    # what the human must approve
    changed: set = field(default_factory=set)              # tests whose body changed (or all, if helpers changed)
    added: set = field(default_factory=set)
    helpers_changed: bool = False


def _compare_test(name: str, old: str, new: str, d: Diff) -> bool:
    """Adds what changed to d; False when only messages changed."""
    before = (len(d.changes), len(d.weakenings))
    oc, osetup = checks_and_setup(old)
    nc, nsetup = checks_and_setup(new)
    if osetup != nsetup:
        d.changes.append(f"{name}: setup changed")
    rest_new = list(nc)
    rest_old = []
    for c in oc:                                            # 1. unchanged checks
        twin = next((x for x in rest_new if x.core == c.core), None)
        if twin:
            rest_new.remove(twin)
        else:
            rest_old.append(c)
    still = []
    for c in rest_old:                                      # 2. the same value checked another way
        twin = next((x for x in rest_new if x.actual == c.actual and x.kind in ("check_eq", "check_near")
                     and c.kind in ("check_eq", "check_near")), None)
        if not twin:
            still.append(c)
            continue
        rest_new.remove(twin)
        if c.kind == "check_eq" and twin.kind == "check_near":
            d.weakenings.append(f"{name}: check_eq → check_near on {_short(c.args[0])}")
        elif c.kind == twin.kind == "check_near" and twin.tolerance > c.tolerance:
            d.weakenings.append(f"{name}: tolerance {c.tolerance:g} → {twin.tolerance:g} on {_short(c.args[0])}")
        elif c.expected != twin.expected:
            d.changes.append(f"{name}: expected {_delta(c.args[1], twin.args[1])}")
        else:
            d.changes.append(f"{name}: {c.kind} → {twin.kind} on {_short(c.args[0])}")
    rest_old = []
    for c in still:                                         # 3. a condition or value rewritten as a condition
        cands = [x for x in rest_new if x.kind == "check"]
        target = c.actual if c.kind == "check" else c.actual
        best = max(cands, key=lambda x: difflib.SequenceMatcher(None, target, x.actual).ratio(), default=None)
        if best is None or (c.kind == "check" and difflib.SequenceMatcher(None, target, best.actual).ratio() < 0.5) \
                or (c.kind != "check" and c.actual not in best.actual):
            rest_old.append(c)
            continue
        rest_new.remove(best)
        old_text, new_text = (c.args[0] if c.args else ""), (best.args[0] if best.args else "")
        exact_before = c.kind == "check_eq" or ("==" in old_text)
        if exact_before and _RANGE.search(new_text) and "==" not in new_text:
            d.weakenings.append(f"{name}: value → range: {_short(str(c), 50)} → {_short(new_text, 50)}")
        elif new_text.count(" or ") > old_text.count(" or "):
            d.weakenings.append(f"{name}: looser condition: {_short(old_text)} → {_short(new_text)}")
        else:
            d.changes.append(f"{name}: condition {_short(old_text, 30)} → {_short(new_text, 30)}")
    for c in rest_old:
        d.weakenings.append(f"{name}: removed check {c}")
    for c in rest_new:
        d.changes.append(f"{name}: added check {c}")
    return (len(d.changes), len(d.weakenings)) != before


def diff(old_text: str, new_text: str, moved: set | None = None) -> Diff:
    """What an edit of a locked test file changed, and which of those changes weaken it."""
    moved = moved or set()
    old, old_rest = split_tests(old_text)
    new, new_rest = split_tests(new_text)
    d = Diff()
    if not old_text.strip():                                # a new file in the relock: every test is added
        d.added = set(new)
        d.changes.append(f"new file, {len(new)} tests: {', '.join(new)}")
        return d
    if old_rest != new_rest:
        d.helpers_changed = True
        d.changes.append("helper code changed: every test counts as changed")
    for name in old:
        if name not in new:
            if name in moved:
                d.changes.append(f"{name}: moved to another file")
            else:
                d.weakenings.append(f"{name}: test deleted")
        elif old[name] != new[name] and _compare_test(name, old[name], new[name], d):
            d.changed.add(name)
    for name in new:
        if name not in old:
            d.added.add(name)
            d.changes.append(f"{name}: added test")
    if d.helpers_changed:
        d.changed |= set(new) & set(old)
    return d


# --- the locks file ------------------------------------------------------------------------

def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())


def load(root: Path) -> dict:
    p = root / tdd.LOCKS
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def save(root: Path, locks: dict) -> None:
    p = root / tdd.LOCKS
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(locks, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def per_test(text: str, green: str | None) -> dict:
    tests, _ = split_tests(text)
    return {n: {"sha256": body_sha(b), "green": green} for n, b in tests.items()}


def was_green(entry: dict, name: str) -> str | None:
    """When a test last went green, for entries with per-test data or (older ones) the whole file's."""
    if "tests" in entry:
        return (entry["tests"].get(name) or {}).get("green")
    return entry.get("green")


def _project(path: str, root: Path) -> str:
    p = (root / path).parent
    while p != root and p != p.parent:
        if (p / "project.godot").is_file():
            return p.relative_to(root).as_posix()
        p = p.parent
    raise Refused(f"{path} is not inside a Godot project (no project.godot above it)")


def _norm(path: str) -> str:
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


# --- the report queue ----------------------------------------------------------------------

def _jsonl(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def unreported(root: str | Path) -> list[dict]:
    return _jsonl(Path(root) / UNREPORTED)


def record(root: str | Path, change: dict) -> dict:
    root = Path(root)
    n = len(_jsonl(root / REPORTED)) + len(unreported(root)) + 1
    change = {"id": f"L{n}", "at": _stamp(), **change}
    (root / UNREPORTED).parent.mkdir(parents=True, exist_ok=True)
    with open(root / UNREPORTED, "a", encoding="utf-8") as f:
        f.write(json.dumps(change, ensure_ascii=False) + "\n")
    return change


def mark_reported(root: str | Path) -> None:
    root = Path(root)
    pending = unreported(root)
    if pending:
        with open(root / REPORTED, "a", encoding="utf-8") as f:
            for p in pending:
                f.write(json.dumps({**p, "reported": _stamp()}, ensure_ascii=False) + "\n")
    (root / UNREPORTED).unlink(missing_ok=True)


def line(c: dict) -> str:
    tags = []
    if c["action"] == "relocked":
        tags.append("WEAKENED (human approved)" if c.get("weakened") else "not weakened")
    if c.get("self_evidenced"):
        tags.append("self-evidenced" + ("; changed tests pass existing code" if c.get("passes_existing") else ""))
    what = _short(c.get("what") or "", 150)
    return f"- [{c['id']}] {c['path']}: {c['action']} ({c['reason']}). {what}" + (f" [{'; '.join(tags)}]" if tags
                                                                                    else "")


def report(root: str | Path) -> str:
    root = Path(root)
    pending = unreported(root)
    still = sorted(p for p, e in load(root).items() if "unlocked" in e)
    head = (f"LOCK REPORT ({len(pending)} change{'s' if len(pending) != 1 else ''} since the last report)"
            if pending else "LOCK REPORT (no changes since the last report)")
    out = [head, *(line(c) for c in pending), f"Still unlocked: {', '.join(still) if still else 'none'}"]
    return "\n".join(out)


def reported_in(text: str, pending: list[dict]) -> bool:
    return "LOCK REPORT" in text and all(f"[{p['id']}]" in text for p in pending)


# --- unlock and relock ---------------------------------------------------------------------

def unlock(root: Path, path: str, reason: str, evidence: str, warns: list, by: str = "Queen") -> dict:
    """warns: the ledger's WARN and ESCALATE lines (grammar.LedgerLine). Returns the change to report."""
    path = _norm(path)
    if reason not in REASONS:
        raise Refused(f"reason must be one of: {', '.join(f'{k} ({v})' for k, v in REASONS.items())}")
    if not evidence.strip():
        raise Refused("evidence must name the Guardian review finding, the WARN, or the story criterion")
    locks = load(root)
    entry = locks.get(path)
    if entry is None:
        raise Refused(f"{path} is not locked; there is nothing to unlock")
    if "unlocked" in entry:
        raise Refused(f"{path} is already unlocked (since {entry['unlocked']['at']}); edit it, then relock_test")
    f = root / path
    if not f.is_file():
        raise Refused(f"{path} does not exist. Restore the locked text first (git), then unlock it")
    if tdd._sha(str(f)) != entry["sha256"]:
        raise Refused(f"{path} changed since it was locked ({entry['locked']}). Restore the locked text first, "
                      "so the edit can be audited from unlock to relock; if you cannot, ESCALATE to the human")
    found = [w for w in warns if w.path == path and w.timestamp >= entry["locked"]]
    if not found:
        raise Refused(f"no WARN or ESCALATE for {path} in the ledger since it was locked ({entry['locked']}). "
                      "File the WARN first (append_ledger), naming the review finding or story criterion")
    sha = entry["sha256"]
    hist = HISTORY / f"{path}@{sha}"
    (root / hist).parent.mkdir(parents=True, exist_ok=True)
    (root / hist).write_bytes(f.read_bytes())
    self_evidenced = all(w.caste == "Queen" for w in found)
    entry["unlocked"] = {"at": _stamp(), "by": by, "reason": reason, "evidence": evidence.strip(),
                         "history": hist.as_posix(), "self_evidenced": self_evidenced,
                         "stories": sorted(s for s, files in _stories(root).items() if path in files)}
    save(root, locks)
    return record(root, {"path": path, "action": "unlocked", "reason": reason,
                         "what": f"evidence: {evidence.strip()}", "weakened": False,
                         "self_evidenced": self_evidenced})


def _stories(root: Path) -> dict[str, list[str]]:
    """{story id: the test files in its feature_tests and unit_tests}."""
    from .gates.stories import _list, front
    folder = root / "docs" / "stories"
    out = {}
    for p in sorted(folder.rglob("*.md")) if folder.is_dir() else []:
        fm, _ = front(p.read_text(encoding="utf-8", errors="replace"))
        if fm and fm.get("id"):
            out[fm["id"]] = [_norm(x) for x in _list(fm.get("feature_tests", "")) + _list(fm.get("unit_tests", ""))]
    return out


def relock(root: Path, paths: list[str], story: str, approve_weakening: bool = False,
           godot: str | None = None) -> list[dict]:
    """Lock edited files again. All or nothing: if any file is refused, nothing is written."""
    paths = [_norm(p) for p in paths if p.strip()]
    if not paths:
        raise Refused("name the test files to relock")
    locks = load(root)
    unlocked = [p for p in paths if "unlocked" in locks.get(p, {})]
    if not unlocked:
        raise Refused(f"none of {', '.join(paths)} is unlocked; unlock_test first (or lock a new file with tdd red)")
    for p in paths:
        if p in locks and p not in unlocked:
            raise Refused(f"{p} is locked and was not unlocked; it cannot be relocked")
        if not (root / p).is_file():
            raise Refused(f"{p} does not exist")
    stories = _stories(root)
    if story not in stories:
        raise Refused(f"story {story} not found under docs/stories")
    old = {p: (root / locks[p]["unlocked"]["history"]).read_text(encoding="utf-8") if p in locks else ""
           for p in paths}
    new = {p: (root / p).read_text(encoding="utf-8") for p in paths}
    names_new = {p: set(split_tests(t)[0]) for p, t in new.items()}
    diffs, weak, weak_by = {}, [], {}
    for p in paths:
        moved = set().union(*(names_new[q] for q in paths if q != p)) if len(paths) > 1 else set()
        diffs[p] = diff(old[p], new[p], moved)
        dropped = [s for s in locks.get(p, {}).get("unlocked", {}).get("stories", []) if p not in stories.get(s, [])]
        weak_by[p] = diffs[p].weakenings + [f"dropped from {s}'s feature_tests and unit_tests" for s in dropped]
        weak += [f"{p}: {w}" for w in weak_by[p]]
    if weak and not approve_weakening:
        phrases = " and ".join(f'"{APPROVAL} {n}"' for n in sorted({Path(p).name for p in paths}))
        raise Refused("this edit weakens a locked test, which needs the human's approval:\n  - " + "\n  - ".join(weak)
                      + f"\nShow the human these lines and ask them to reply {phrases} if they agree. Then call "
                        "relock_test again with approve_weakening=true; otherwise restore the checks and relock")
    project = _project(paths[0], root)
    res = {p: tdd._res(project, str(root / p)) for p in paths}
    found, out = tdd.run(project, list(res.values()), godot)
    problems = []
    for p in paths:
        result = found.get(res[p], {})
        if result is None:
            problems.append(f"{p} does not load (parse error?)")
        elif not result:
            problems.append(f"{p}: no tests ran")
        else:
            entry = locks.get(p, {})
            for name, ok in result.items():
                if not ok and name not in diffs[p].changed and name not in diffs[p].added and was_green(entry, name):
                    problems.append(f"{p}: {name} was green and is unchanged, and now fails (a regression)")
    if problems:
        raise Refused("; ".join(problems) + ("" if found else f"\nrunner output:\n{out[-1000:]}"))
    stamp, changes = _stamp(), []
    for p in paths:
        prior = locks.get(p, {})
        result = found[res[p]]
        tests = {}
        for name, body in split_tests(new[p])[0].items():
            kept = None if (name in diffs[p].changed or name in diffs[p].added) else was_green(prior, name)
            tests[name] = {"sha256": body_sha(body), "green": (kept or stamp) if result.get(name) else None}
        unl = prior.get("unlocked", {})
        relocks = prior.get("relocks", []) + ([{"at": stamp, "reason": unl.get("reason"), "story": story,
                                                "history": unl.get("history"),
                                                "weakened": weak_by[p]}] if unl else [])
        locks[p] = {"sha256": tdd._sha(str(root / p)), "locked": stamp,
                    "green": stamp if all(result.values()) else None, "tests": tests,
                    **({"relocks": relocks} if relocks else {})}
        touched = diffs[p].changed | diffs[p].added
        passes = bool(touched) and all(result.get(n) for n in touched)
        what = "; ".join(weak_by[p] + diffs[p].changes) or "no change to what it tests"
        pend = [n for n, ok in result.items() if not ok]
        what += f". Pending (fail until coded): {', '.join(pend)}" if pend else ". All pass"
        changes.append({"path": p, "action": "relocked", "reason": unl.get("reason", "new file"), "story": story,
                        "what": what, "weakened": bool(weak_by[p]),
                        "self_evidenced": bool(unl.get("self_evidenced")), "passes_existing": passes})
    save(root, locks)
    return [record(root, c) for c in changes]
