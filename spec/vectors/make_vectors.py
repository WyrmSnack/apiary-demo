"""Writes the JSON vectors in this folder. The JSON files are the normative artifact; this script
only keeps them readable to edit. Run: python spec/vectors/make_vectors.py"""
import json
from pathlib import Path

V = Path(__file__).resolve().parent
TS = "2026-10-14T12:00Z"


def L(caste="Forager", sig="DEPOSIT", path="engine/save.py", note="added save slots", ts=TS):
    return f"{ts} | {caste} | {sig} | {path} | {note}"


ledger = {
    "about": "Ledger lines (spec section 4), each given without its LF.",
    "valid": [
        L(sig="CLAIM", path="tasks/active/014-save-slots.task",
          note="token=0123456789abcdef lease_until=2026-10-14T13:00Z"),
        L("Guardian", "WARN", "engine/physics.py", "4 open WARNs; see ledger"),
        L("SignalSprite", "DEPOSIT", "reports/run-1.md", "Grassé would approve"),
        L("Scribe", "ESCALATE", "parts/ch07.md", "no card supports the 68% figure"),
        L(note="x" * 160),
        L(path="p" * 200),
        L(ts="2024-02-29T23:59Z"),
    ],
    "invalid": [
        {"line": L(ts="2026-10-14T12:00"), "rule": "L-1", "why": "timestamp without Z"},
        {"line": L(ts="2026-10-14T12:00:00Z"), "rule": "L-1", "why": "seconds"},
        {"line": L(ts="2026-13-01T00:00Z"), "rule": "L-2", "why": "month 13"},
        {"line": L(ts="2025-02-29T00:00Z"), "rule": "L-2", "why": "not a leap year"},
        {"line": L(caste="Signal Sprite"), "rule": "L-1", "why": "kit spelling of the caste"},
        {"line": L(caste="Overlord"), "rule": "L-1", "why": "unknown caste"},
        {"line": L(sig="ISSUE"), "rule": "L-1", "why": "unknown signal"},
        {"line": L(note="x" * 161), "rule": "L-1", "why": "note longer than 160"},
        {"line": L(path="p" * 201), "rule": "L-1", "why": "path longer than 200"},
        {"line": L(path="engine/my file.py"), "rule": "L-1", "why": "space in path"},
        {"line": L(path="/etc/passwd"), "rule": "L-3", "why": "absolute path"},
        {"line": L(path="C:/colony/x.py"), "rule": "L-3", "why": "drive letter"},
        {"line": L(path="engine\\save.py"), "rule": "L-3", "why": "backslash"},
        {"line": L(path="tasks/../secrets"), "rule": "L-3", "why": "dot-dot segment"},
        {"line": L(note=" leading space"), "rule": "L-4", "why": "note starts with a space"},
        {"line": L(note="trailing space "), "rule": "L-4", "why": "note ends with a space"},
        {"line": L(note="tab\there"), "rule": "L-1", "why": "control character in note"},
        {"line": L(note=""), "rule": "L-1", "why": "empty note"},
        {"line": f"{TS} | Forager | DEPOSIT | engine/save.py", "rule": "L-1", "why": "four fields"},
        {"line": f"{TS} | Forager | DEPOSIT | engine/save.py | a | b", "rule": "L-1", "why": "extra field"},
        {"line": f"{TS}|Forager|DEPOSIT|engine/save.py|note", "rule": "L-1", "why": "separators without spaces"},
    ],
    "comments": ["", "# PHEROMONE_LEDGER for the save-slots colony"],
}

acceptance = {
    "about": "Acceptance lines (spec section 9). 'argv' is the exact argument vector, program first.",
    "valid": [
        {"line": "pytest tests/test_x.py", "argv": ["pytest", "tests/test_x.py"]},
        {"line": 'python -c "exit(1)"', "argv": ["python", "-c", "exit(1)"]},
        {"line": "python -c \"print('hi')\"", "argv": ["python", "-c", "print('hi')"]},
        {"line": "a   b\tc", "argv": ["a", "b", "c"]},
        {"line": "  a b  ", "argv": ["a", "b"]},
        {"line": "tests\\test_x.py", "argv": ["tests\\test_x.py"]},
        {"line": '"a \\"b\\" c"', "argv": ['a "b" c']},
        {"line": 'a"b c"d', "argv": ["ab cd"]},
        {"line": 'x ""', "argv": ["x", ""]},
        {"line": '"C:\\\\Program Files\\\\x"', "argv": ["C:\\Program Files\\x"]},
        {"line": '"C:\\Program Files"', "argv": ["C:\\Program Files"]},
        {"line": 'python -m pytest -q -k "not slow"', "argv": ["python", "-m", "pytest", "-q", "-k", "not slow"]},
        {"line": 'x --flag="#not-a-comment; |&<>$%*?()`\'"', "argv": ["x", "--flag=#not-a-comment; |&<>$%*?()`'"]},
        {"line": 'x "trailing backslash\\\\"', "argv": ["x", "trailing backslash\\"]},
        {"line": "x Grassé", "argv": ["x", "Grassé"]},
    ],
    "invalid": [
        {"line": "", "why": "empty"},
        {"line": "   ", "why": "blank"},
        {"line": "python -c 'exit(1)'", "why": "single quotes: exits 0 under cmd.exe (ADR 0002)"},
        {"line": "pytest tests/x.py   # comment", "why": "hash: a comment in sh, an argument in cmd.exe"},
        {"line": "a | b", "why": "pipe"},
        {"line": "a && b", "why": "ampersand"},
        {"line": "a; b", "why": "semicolon"},
        {"line": "a > out.txt", "why": "redirect"},
        {"line": "a < in.txt", "why": "redirect"},
        {"line": "echo $HOME", "why": "sh variable"},
        {"line": "echo %PATH%", "why": "cmd variable"},
        {"line": "ls *.py", "why": "glob"},
        {"line": "ls ?.py", "why": "glob"},
        {"line": "(a)", "why": "subshell"},
        {"line": "echo `id`", "why": "command substitution"},
        {"line": 'x "unterminated', "why": "unterminated quote"},
        {"line": 'x "ends in escaped quote\\"', "why": "unterminated quote"},
    ],
}

tasks = {
    "about": "Task file names (5.1) and contents (5.2).",
    "valid_names": ["014-save-slots.task", "123456-x.task", "001-a1-b2.task", "000-x.task"],
    "invalid_names": ["14-x.task", "1234567-x.task", "014_save.task", "014-Save.task", "014-.task",
                      "014-x.txt", "014-x--y.task", "014-x-.task", "../014-x.task", "014-x.task.bak"],
    "valid_contents": [
        {"text": "objective: Player can save.\nacceptance: pytest tests/test_save.py\n",
         "fields": {"objective": "Player can save.", "acceptance": "pytest tests/test_save.py"},
         "depends_on": []},
        {"text": ("# tasks/pending/014-save-slots.task\nobjective:    Save to three slots.\n\n"
                  "acceptance:   python -m pytest -q tests/test_save_slots.py\n"
                  "writes:       engine/save.py, tests/test_save_slots.py\n"
                  "depends-on:   011, 12\nestimate: 2h\n"),
         "fields": {"objective": "Save to three slots.",
                    "acceptance": "python -m pytest -q tests/test_save_slots.py",
                    "writes": "engine/save.py, tests/test_save_slots.py",
                    "depends-on": "011, 12", "estimate": "2h"},
         "depends_on": [11, 12]},
        {"text": "objective: x\r\nacceptance: y\r\n", "fields": {"objective": "x", "acceptance": "y"},
         "depends_on": []},
        {"text": "objective: a: b: c\nacceptance: y\n", "fields": {"objective": "a: b: c", "acceptance": "y"},
         "depends_on": []},
    ],
    "invalid_contents": [
        {"text": "objective: x\n", "rule": "T-4", "why": "no acceptance"},
        {"text": "acceptance: y\n", "rule": "T-4", "why": "no objective"},
        {"text": "objective:\nacceptance: y\n", "rule": "T-4", "why": "empty objective"},
        {"text": "objective: x\nacceptance: y\nobjective: z\n", "rule": "T-4", "why": "duplicate key"},
        {"text": "objective: x\nacceptance: y\nthis line has no key\n", "rule": "T-3", "why": "not a field"},
        {"text": "Objective: x\nacceptance: y\n", "rule": "T-3", "why": "uppercase key"},
        {"text": "objective: x\nacceptance: y\ndepends-on: eleven\n", "rule": "T-5", "why": "depends-on is not ids"},
    ],
}

E1 = "## KEY: a1\n- by: Queen at 2026-10-14T12:00Z\n"
traces = {
    "about": "TRACES.md (section 6).",
    "valid_keys": ["save-format", "save-format-v2", "a1", "0-start", "k" * 61],
    "invalid_keys": ["a", "Save-format", "save_format", "-save", "save format", "k" * 62, ""],
    "valid_documents": [
        "# TRACES\n",
        ("# TRACES\n\n## KEY: save-format\n- by: Queen at 2026-10-14T12:00Z\n- VALUE: JSON, versioned.\n\n"
         "## KEY: save-format-v2\n- by: Guardian at 2026-10-14T13:00Z\n- SUPERSEDES: save-format\n"
         "- VALUE: JSON, versioned, atomic writes.\n"),
    ],
    "invalid_documents": [
        {"text": "\n" + E1 + "- VALUE: x\n\n## KEY: a1\n- by: Queen at 2026-10-14T12:01Z\n- VALUE: y\n",
         "rule": "R-3", "why": "duplicate key"},
        {"text": "\n## KEY: a2\n- by: Queen at 2026-10-14T12:00Z\n- SUPERSEDES: nope\n- VALUE: x\n",
         "rule": "R-4", "why": "supersedes an unknown key"},
        {"text": "\n" + E1, "rule": "R-1", "why": "no VALUE"},
        {"text": "\n## KEY: a1\n- by: Overlord at 2026-10-14T12:00Z\n- VALUE: x\n", "rule": "R-1", "why": "unknown caste"},
        {"text": "\n" + E1 + "- VALUE: x\n- EXTRA: y\n", "rule": "R-1", "why": "unknown entry line"},
    ],
}

if __name__ == "__main__":
    for name, obj in [("ledger_lines", ledger), ("acceptance", acceptance),
                      ("task_files", tasks), ("traces", traces)]:
        (V / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8", newline="\n")
