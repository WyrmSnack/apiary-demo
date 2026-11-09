"""Grammar of the colony substrate files (spec/SUBSTRATE_SPEC.md v0.9.0). Standard library only.

Every check raises GrammarError carrying the spec requirement it enforces.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

CASTES = ("Queen", "Forager", "Nurse", "Guardian", "SignalSprite", "Cartographer", "Scribe")
SIGNALS = ("DEPOSIT", "REINFORCE", "EVAPORATE", "WARN", "CLAIM", "DONE", "SKILL", "TRACE", "ESCALATE",
           "UNLOCK", "RELOCK")
PROTOCOL_SIGNALS = ("CLAIM", "DONE")          # L-10: only claim and close write these
LOCK_SIGNALS = ("UNLOCK", "RELOCK")           # L-11: only unlock_test and relock_test write these
RESERVED_ATTRS = ("token", "lease_until", "task_sha256")     # L-6
NOTE_MAX, PATH_MAX, VALUE_MAX = 160, 200, 2000
TS_FORMAT = "%Y-%m-%dT%H:%MZ"


class GrammarError(ValueError):
    def __init__(self, rule: str, why: str):
        super().__init__(f"{rule}: {why}")
        self.rule, self.why = rule, why


# --- encoding (E-1 to E-3) ---------------------------------------------------

def decode_strict(data: bytes, name: str = "file") -> str:
    """UTF-8 without BOM, CRLF read as LF. Anything else is reported, never guessed (E-3)."""
    if data.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")):
        raise GrammarError("E-3", f"{name} starts with a byte-order mark; write UTF-8 without BOM")
    if b"\x00" in data:
        raise GrammarError("E-3", f"{name} contains NUL bytes; it looks like UTF-16, not UTF-8")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise GrammarError("E-3", f"{name} is not valid UTF-8 (byte {e.start})") from None
    return text.replace("\r\n", "\n")


def read_strict(path: Path) -> str:
    return decode_strict(path.read_bytes(), path.name)


# --- timestamps --------------------------------------------------------------

_TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\dZ")


def parse_timestamp(s: str) -> dt.datetime:
    if not _TS.fullmatch(s):
        raise GrammarError("L-1", f"timestamp {s!r} is not YYYY-MM-DDTHH:MMZ")
    try:
        return dt.datetime.strptime(s, TS_FORMAT).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        raise GrammarError("L-2", f"timestamp {s!r} is not a real date and time") from None


def format_timestamp(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime(TS_FORMAT)


# --- ledger (section 4) ------------------------------------------------------

def _bad_char(s: str) -> str | None:
    for c in s:
        if c == "|" or ord(c) < 0x20 or ord(c) == 0x7F:
            return c
    return None


def check_caste(caste: str) -> None:
    if caste not in CASTES:
        raise GrammarError("L-1", f"unknown caste {caste!r}; use one of {', '.join(CASTES)}")


def check_signal(signal: str) -> None:
    if signal not in SIGNALS:
        raise GrammarError("L-1", f"unknown signal {signal!r}; use one of {', '.join(SIGNALS)}")


def check_path(path: str) -> None:
    if not 1 <= len(path) <= PATH_MAX:
        raise GrammarError("L-1", f"path must be 1 to {PATH_MAX} characters")
    if " " in path or _bad_char(path):
        raise GrammarError("L-1", "path must not contain spaces, '|' or control characters")
    if path.startswith("/") or re.match(r"[A-Za-z]:", path):
        raise GrammarError("L-3", f"path {path!r} must be relative to the colony root")
    if "\\" in path:
        raise GrammarError("L-3", f"path {path!r} must use '/', not '\\'")
    if ".." in path.split("/"):
        raise GrammarError("L-3", f"path {path!r} must not contain a '..' segment")


def check_note(note: str) -> None:
    if not 1 <= len(note) <= NOTE_MAX:
        raise GrammarError("L-1", f"note must be 1 to {NOTE_MAX} characters (got {len(note)})")
    if _bad_char(note):
        raise GrammarError("L-1", "note must not contain '|' or control characters such as newlines")
    if note != note.strip(" "):
        raise GrammarError("L-4", "note must not begin or end with a space")


_ATTR = re.compile(r"(?:^| )([a-z_][a-z0-9_]*)=(\S+)")


def attributes(note: str) -> dict[str, str]:
    """name=value pairs in a note (4.2). The first occurrence of a name wins."""
    out: dict[str, str] = {}
    for name, value in _ATTR.findall(note):
        out.setdefault(name, value)
    return out


@dataclass(frozen=True)
class LedgerLine:
    timestamp: str
    caste: str
    signal: str
    path: str
    note: str

    @property
    def attrs(self) -> dict[str, str]:
        return attributes(self.note)

    def __str__(self) -> str:
        return " | ".join((self.timestamp, self.caste, self.signal, self.path, self.note))


def is_comment(line: str) -> bool:
    return not line.strip() or line.startswith("#")


def parse_ledger_line(line: str) -> LedgerLine:
    parts = line.split(" | ")
    if len(parts) != 5:
        raise GrammarError("L-1", "a ledger line has five fields separated by ' | '")
    ts, caste, signal, path, note = parts
    parse_timestamp(ts)
    check_caste(caste)
    check_signal(signal)
    check_path(path)
    check_note(note)
    return LedgerLine(ts, caste, signal, path, note)


def make_ledger_line(ts: str, caste: str, signal: str, path: str, note: str) -> LedgerLine:
    return parse_ledger_line(" | ".join((ts, caste, signal, path, note)))


# --- task files (section 5) --------------------------------------------------

TASK_NAME = re.compile(r"^([0-9]{3,6})-[a-z0-9]+(?:-[a-z0-9]+)*\.task$")
TASK_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
TASK_FIELDS = ("objective", "acceptance", "why", "writes", "reads", "depends-on", "out-of-scope")
TASK_BY = ("Queen", "Forager", "Nurse", "Guardian", "Human")     # K-1: who does a task; Human is a checkpoint
_KEY = re.compile(r"[a-z][a-z0-9-]*")


def task_digest(text: str) -> str:
    """P-18: SHA-256 of the task file's text after CRLF is read as LF, encoded as UTF-8."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def task_id(name: str) -> int:
    m = TASK_NAME.match(name)
    if not m:
        raise GrammarError("T-1", f"task file name {name!r} must look like 014-save-slots.task")
    return int(m.group(1))


@dataclass
class Task:
    fields: dict[str, str]
    depends_on: list[int] = field(default_factory=list)

    @property
    def acceptance(self) -> str:
        return self.fields["acceptance"]


def parse_task(text: str) -> Task:
    fields: dict[str, str] = {}
    for n, line in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if is_comment(line):
            continue
        key, sep, value = line.partition(":")
        if not sep or not _KEY.fullmatch(key):
            raise GrammarError("T-3", f"line {n} is not 'key: value' with a lowercase key")
        if key in fields:
            raise GrammarError("T-4", f"line {n}: key {key!r} appears twice")
        fields[key] = value.strip()
    for key in ("objective", "acceptance"):
        if not fields.get(key):
            raise GrammarError("T-4", f"required field {key!r} is missing or empty")
    deps: list[int] = []
    if fields.get("depends-on"):
        for item in fields["depends-on"].split(","):
            item = item.strip()
            if not re.fullmatch(r"[0-9]{1,6}", item):
                raise GrammarError("T-5", f"depends-on item {item!r} is not a task id")
            deps.append(int(item))
    return Task(fields, deps)


# --- acceptance commands (section 9) -----------------------------------------

FORBIDDEN = "'#|&;<>()$`%*?"


def tokenize_acceptance(line: str) -> list[str]:
    """Split an acceptance line into argv (A-1). Raises GrammarError("A-2") if it is invalid."""
    tokens: list[str] = []
    cur: list[str] = []
    in_token = False
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t":
            if in_token:
                tokens.append("".join(cur))
                cur, in_token = [], False
            i += 1
        elif c == '"':
            in_token = True
            i += 1
            while True:
                if i >= n:
                    raise GrammarError("A-2", "unterminated double quote")
                c = line[i]
                if c == "\\" and i + 1 < n and line[i + 1] in '"\\':
                    cur.append(line[i + 1])
                    i += 2
                elif c == '"':
                    i += 1
                    break
                else:
                    cur.append(c)
                    i += 1
        elif c in FORBIDDEN:
            raise GrammarError("A-2", f"{c!r} outside double quotes is shell syntax; acceptance runs without a "
                                      "shell (use double quotes, one command, no comments)")
        elif ord(c) < 0x20:
            raise GrammarError("A-2", "control character in acceptance line")
        else:
            cur.append(c)
            in_token = True
            i += 1
    if in_token:
        tokens.append("".join(cur))
    if not tokens:
        raise GrammarError("A-2", "acceptance line is empty")
    return tokens


# --- TRACES (section 6) ------------------------------------------------------

TRACE_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")


def check_trace_key(key: str) -> None:
    if not TRACE_KEY.match(key):
        raise GrammarError("R-2", f"key {key!r} must be 2 to 61 characters of a-z, 0-9 and '-', "
                                  "not starting with '-'")


def collapse(value: str) -> str:
    return " ".join(value.split())


@dataclass(frozen=True)
class TraceEntry:
    key: str
    caste: str
    timestamp: str
    value: str
    supersedes: str = ""


_BY = re.compile(r"^- by: (\S+) at (\S+)$")


def parse_traces(text: str) -> list[TraceEntry]:
    lines = text.replace("\r\n", "\n").split("\n")
    entries: list[TraceEntry] = []
    keys: set[str] = set()
    i = 0
    while i < len(lines) and not lines[i].startswith("## KEY:"):
        i += 1                                             # free header (R-1)
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if not line.startswith("## KEY: "):
            raise GrammarError("R-1", f"line {i + 1}: expected '## KEY: <key>'")
        key = line[len("## KEY: "):]
        check_trace_key(key)
        if key in keys:
            raise GrammarError("R-3", f"line {i + 1}: key {key!r} already has an entry")
        m = _BY.match(lines[i + 1]) if i + 1 < len(lines) else None
        if not m:
            raise GrammarError("R-1", f"line {i + 2}: expected '- by: <caste> at <timestamp>'")
        caste, ts = m.groups()
        try:
            check_caste(caste)
            parse_timestamp(ts)
        except GrammarError as e:
            raise GrammarError("R-1", f"line {i + 2}: {e.why}") from None
        j, supersedes = i + 2, ""
        if j < len(lines) and lines[j].startswith("- SUPERSEDES: "):
            supersedes = lines[j][len("- SUPERSEDES: "):]
            if supersedes not in keys:
                raise GrammarError("R-4", f"line {j + 1}: SUPERSEDES names unknown key {supersedes!r}")
            j += 1
        if j >= len(lines) or not lines[j].startswith("- VALUE: "):
            raise GrammarError("R-1", f"line {j + 1}: expected '- VALUE: <value>'")
        value = lines[j][len("- VALUE: "):]
        if not 1 <= len(value) <= VALUE_MAX or value != collapse(value):
            raise GrammarError("R-5", f"line {j + 1}: VALUE must be one line of 1 to {VALUE_MAX} characters")
        j += 1
        if j < len(lines) and lines[j].strip():
            raise GrammarError("R-1", f"line {j + 1}: unexpected line inside an entry")
        entries.append(TraceEntry(key, caste, ts, value, supersedes))
        keys.add(key)
        i = j
    return entries


def make_trace_entry(ts: str, caste: str, key: str, value: str, supersedes: str = "") -> str:
    """The text appended to TRACES.md for one entry, starting with its blank separator line."""
    check_caste(caste)
    check_trace_key(key)
    if supersedes:
        check_trace_key(supersedes)
    value = collapse(value)
    if not 1 <= len(value) <= VALUE_MAX:
        raise GrammarError("R-5", f"VALUE must be 1 to {VALUE_MAX} characters after collapsing whitespace")
    out = f"\n## KEY: {key}\n- by: {caste} at {ts}\n"
    if supersedes:
        out += f"- SUPERSEDES: {supersedes}\n"
    return out + f"- VALUE: {value}\n"
