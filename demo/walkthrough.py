"""A recorded walkthrough of one task, from creation to close, with no model involved.

  python demo/walkthrough.py            # prints the run; exit 1 if any step does not give the expected result
  python demo/walkthrough.py --keep     # also keeps the colony folder it made, so you can read its files

It plays the parts an agent would play, with the same tools an agent gets:
  1. make a colony in a temporary folder (`apiary init`)
  2. create a task whose acceptance check is a test that fails today
  3. claim it (the claim pins the task file by its SHA-256)
  4. try to close it: the check fails, so the close is refused and the ledger records why
  5. edit the task's own check into one that passes, and try again: refused, the task file changed since the claim
  6. try to write the ledger and the task file directly, as Claude Code would: the guard hook refuses both
  7. fix the code, close: the check passes and the task moves to done/
  8. `apiary validate`: the colony's files still follow the spec

Each step prints the command's first result line and checks its first word. Tokens and timestamps differ per run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PY = sys.executable
BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
CHECK = "import sys\nfrom calc import add\nsys.exit(0 if add(2, 3) == 5 else 1)\n"
failures: list[str] = []


def show(title: str) -> None:
    print(f"\n## {title}")


def apiary(root: Path, *args: str) -> str:
    out = subprocess.run([PY, "-m", "apiary", "--root", str(root), *args], capture_output=True, text=True,
                         encoding="utf-8", cwd=root)
    return (out.stdout + out.stderr).strip()


def expect(text: str, first_word: str, root: Path) -> str:
    shown = text.replace(str(root), "<colony>").replace(str(root).replace("\\", "/"), "<colony>")
    lines = shown.splitlines() or [""]
    print("  " + lines[0])
    ok = lines[0].split(" ", 1)[0].rstrip(":") == first_word
    print(f"  expected {first_word}: {'yes' if ok else 'NO'}")
    if not ok:
        failures.append(f"{first_word}: {lines[0]}")
    return text


def guard(root: Path, tool: str, tool_input: dict) -> tuple[int, str]:
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(root)}
    out = subprocess.run([PY, "-m", "apiary.hook", "--root", str(root)], input=json.dumps(event),
                         capture_output=True, text=True, encoding="utf-8")
    return out.returncode, out.stderr.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    root = Path(tempfile.mkdtemp(prefix="apiary-walkthrough-")).resolve()
    try:
        show("1. Make a colony")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        out = apiary(root, "init")
        print("  " + out.splitlines()[-1].replace(str(root), "<colony>"))
        (root / "calc.py").write_text(BUGGY, encoding="utf-8")
        (root / "check_calc.py").write_text(CHECK, encoding="utf-8")

        show("2. Create a task whose check fails today")
        out = expect(apiary(root, "task", "new", "fix-add", "--caste", "Queen",
                            "--objective", "add(2, 3) returns 5", "--acceptance", "python check_calc.py",
                            "--writes", "calc.py"), "CREATED", root)
        task = re.search(r"\b(\d{3}-fix-add\.task)\b", out)
        task = task.group(1) if task else "001-fix-add.task"

        show("3. Claim it")
        out = expect(apiary(root, "claim", task), "CLAIMED", root)
        token = re.search(r"token=([0-9a-f]{16})", out)
        token = token.group(1) if token else "0" * 16

        show("4. Close it before the work is done")
        expect(apiary(root, "close", task, token), "REFUSED", root)

        show("5. Rewrite the task's own check so it passes, then close")
        active = root / "tasks" / "active" / task
        original = active.read_bytes()
        active.write_text(active.read_text(encoding="utf-8").replace("python check_calc.py", "python --version"),
                          encoding="utf-8")
        expect(apiary(root, "close", task, token), "REFUSED", root)
        active.write_bytes(original)

        show("6. Write the ledger and the task file directly, as Claude Code would")
        for tool, inp in (("Write", {"file_path": str(root / "PHEROMONE_LEDGER.md"), "content": "DONE"}),
                          ("Edit", {"file_path": str(active), "old_string": "check_calc", "new_string": "x"}),
                          ("Bash", {"command": "echo DONE >> PHEROMONE_LEDGER.md"})):
            code, why = guard(root, tool, inp)
            word = "REFUSED" if code == 2 else "ALLOWED"
            expect(f"{word} {tool}: {why.replace(str(root), '<colony>')[:110]}", "REFUSED", root)
        code, _ = guard(root, "Edit", {"file_path": str(root / "calc.py"), "old_string": "-", "new_string": "+"})
        expect(f"{'ALLOWED' if code == 0 else 'REFUSED'} Edit calc.py (the file the task writes)", "ALLOWED", root)

        show("7. Do the work, then close")
        (root / "calc.py").write_text(FIXED, encoding="utf-8")
        # The fix is the same size as the bug and lands in the same second, so Python would trust the stale .pyc.
        shutil.rmtree(root / "__pycache__", ignore_errors=True)
        expect(apiary(root, "close", task, token), "DONE", root)

        show("8. Check the colony against the spec")
        expect(apiary(root, "validate"), "valid", root)

        show("The ledger this run wrote")
        for line in (root / "PHEROMONE_LEDGER.md").read_text(encoding="utf-8").splitlines():
            if " | " in line:
                print("  " + line)
    finally:
        if args.keep:
            print(f"\nkept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'all steps gave the expected result' if not failures else 'FAILED: ' + '; '.join(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    os.environ.pop("APIARY_CLOCK", None)
    sys.exit(main())
