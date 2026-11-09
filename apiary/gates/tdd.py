"""Test-first gates for Godot projects (Phase 10 gate f). Run from the colony root, as acceptance commands are.

  python -m apiary.gates.tdd red   --project game --tests game/tests/unit/test_grid.gd[,...] --lock
  python -m apiary.gates.tdd green --project game --tests game/tests/unit/test_grid.gd[,...]

`red` is a test-writing task's gate: every test in the named files must load, run and FAIL, because nothing makes
it pass yet. With --lock it then records each file's hash in .apiary/tdd/locks.json, which agents cannot write
(the guard protects .apiary/). A lock is never replaced by different contents here: a locked test changes only by the
Queen's unlock_test, edit, relock_test (apiary.locktools), each reported to the human.

`green` is an implementation task's gate: the named files must be locked (seen failing), unchanged since, and every
test in them must pass. The whole suite runs too: a file already green that now fails is a regression, and a failing
test in a file that was never locked fails the gate. Locked files still waiting for their code may fail, and so may a file
the Queen has unlocked to edit; a gate that names an unlocked file waits until it is relocked.

Tests run with apiary's GDScript runner (`apiary gamedev godot-tests`) through the colony's godot connector.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

LOCKS = Path(".apiary/tdd/locks.json")
LINE = re.compile(r"^(PASS|FAIL) (res://\S+?)(?:::(\w+)| does not load|: does not load)")


def _godot(godot: str | None) -> list[str]:
    if godot:
        return [godot]
    from apiary import connectors
    c = connectors.load(Path.cwd(), "godot")
    exe = c.resolve() if c else None
    if not exe:
        raise SystemExit("no godot connector in this colony (apiary connect add godot), and no --godot given")
    return [exe]


def _timeout() -> int:
    from apiary import connectors
    try:
        c = connectors.load(Path.cwd(), "godot")
    except ValueError:
        c = None
    return (c.timeout_s if c and c.timeout_s else 300)


def run(project: str, files: list[str] | None, godot: str | None) -> tuple[dict[str, dict[str, bool] | None], str]:
    """{res path: {test: passed} or None if the file did not load}, and the raw output."""
    cmd = _godot(godot) + ["--headless", "--path", project, "--script", "res://tests/run_tests.gd"]
    if files:
        cmd += ["--", "--files", ",".join(files)]
    try:
        r = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=_timeout())
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", "replace") + "\n(timed out)"
    found: dict[str, dict[str, bool] | None] = {}
    for line in out.splitlines():
        m = LINE.match(line.strip())
        if not m:
            continue
        kind, path, test = m.groups()
        if test is None:
            found[path] = None
        elif found.get(path, {}) is not None:
            found.setdefault(path, {})[test] = kind == "PASS"
    return found, out


def _res(project: str, test: str) -> str:
    rel = Path(test).resolve().relative_to(Path(project).resolve()).as_posix()
    return "res://" + rel


def _sha(path: str) -> str:
    """Of the text with LF line ends: git's autocrlf may change CRLF and LF on checkout without changing the test."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _locks() -> dict:
    return json.loads(LOCKS.read_text(encoding="utf-8")) if LOCKS.is_file() else {}


def _save(locks: dict) -> None:
    LOCKS.parent.mkdir(parents=True, exist_ok=True)
    LOCKS.write_text(json.dumps(locks, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _named(project: str, tests: list[str]) -> tuple[dict[str, str], list[str]]:
    named, problems = {}, []
    for t in tests:
        p = Path(t)
        if not p.is_file():
            problems.append(f"{t} does not exist")
            continue
        try:
            named[t] = _res(project, t)
        except ValueError:
            problems.append(f"{t} is not inside the project {project}")
    return named, problems


def red(project: str, tests: list[str], lock: bool = False, godot: str | None = None) -> list[str]:
    named, problems = _named(project, tests)
    if problems:
        return problems
    found, out = run(project, list(named.values()), godot)
    for t, res in named.items():
        result = found.get(res, {})
        if result is None:
            problems.append(f"{t} does not load (parse error?): a test that cannot run is not a failing test")
        elif not result:
            problems.append(f"{t}: no tests ran (methods named test_*)")
        else:
            passing = [name for name, ok in result.items() if ok]
            if passing:
                problems.append(f"{t}: {', '.join(passing)} already passes, so it does not test new behaviour")
    if problems:
        return problems + ([] if found else [f"runner output:\n{out[-1500:]}"])
    if lock:
        locks = _locks()
        for t in named:
            held = locks.get(t)
            if held and (held["sha256"] != _sha(t) or "unlocked" in held):
                problems.append(f"{t} is locked (seen failing {held['locked']}) with different contents; changing a "
                                "locked test is the Queen's decision, reported to the human: unlock_test, edit, "
                                "relock_test")
        if problems:
            return problems
        stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
        from apiary.locktools import per_test
        for t in named:
            locks.setdefault(t, {"sha256": _sha(t), "locked": stamp, "green": None,
                                 "tests": per_test(Path(t).read_text(encoding="utf-8"), None)})
        _save(locks)
    return []


def green(project: str, tests: list[str], godot: str | None = None) -> list[str]:
    named, problems = _named(project, tests)
    if problems:
        return problems
    locks = _locks()
    for t in named:
        if t not in locks:
            problems.append(f"{t} was never seen failing (no tdd red lock); run its test task first")
        elif "unlocked" in locks[t]:
            problems.append(f"{t} is unlocked ({locks[t]['unlocked']['reason']}, since {locks[t]['unlocked']['at']}); "
                            "the Queen relocks it with relock_test before its code can go green")
        elif locks[t]["sha256"] != _sha(t):
            problems.append(f"{t} changed since it was seen failing ({locks[t]['locked']}); "
                            "fix the code, not the test, or ask a human")
    if problems:
        return problems
    found, out = run(project, None, godot)
    res_to_file = {_res(project, f): f for f in locks if Path(f).is_file()}
    for t, res in named.items():
        result = found.get(res)
        if not result:
            problems.append(f"{t}: did not load or ran no tests")
        else:
            failing = [n for n, ok in result.items() if not ok]
            if failing:
                problems.append(f"{t}: still failing: {', '.join(failing)}")
    for res, result in found.items():
        if res in named.values():
            continue
        failing = ["(does not load)"] if result is None else [n for n, ok in result.items() if not ok]
        if not failing:
            continue
        f = res_to_file.get(res)
        if f is None:
            problems.append(f"{res}: fails ({', '.join(failing)}) but was never locked by tdd red")
        elif "unlocked" in locks[f]:
            continue                               # the Queen is editing it; relock_test checks it
        elif locks[f].get("tests") and result is not None:
            tests = locks[f]["tests"]
            regressed = [n for n in failing if (tests[n]["green"] if n in tests else locks[f]["green"])]
            if regressed:
                problems.append(f"regression: {res} had these green and now they fail: {', '.join(regressed)}")
        elif locks[f]["green"]:
            problems.append(f"regression: {res} was green ({locks[f]['green']}) and now fails: {', '.join(failing)}")
    if not found:
        problems.append(f"no test results; runner output:\n{out[-1500:]}")
    if problems:
        return problems
    stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    for t in named:
        locks[t]["green"] = locks[t]["green"] or stamp
        for name in locks[t].get("tests", {}):
            locks[t]["tests"][name]["green"] = locks[t]["tests"][name]["green"] or stamp
    _save(locks)
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m apiary.gates.tdd", description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", choices=["red", "green"])
    ap.add_argument("--project", required=True, help="the Godot project folder, colony-relative")
    ap.add_argument("--tests", required=True, help="comma-separated test files, colony-relative")
    ap.add_argument("--lock", action="store_true", help="red: lock the tests once they are seen failing")
    ap.add_argument("--godot", help="the Godot program (default: this colony's godot connector)")
    ap.add_argument("--story", help="first check this feature story's rung of the ladder (apiary.gates.stories)")
    ap.add_argument("--stories", default="docs/stories", help="the stories folder for --story")
    a = ap.parse_args(argv)
    tests = [t.strip() for t in a.tests.split(",") if t.strip()]
    problems = []
    if a.story:
        from apiary.gates import stories
        problems = stories.check(a.stories, stage="units", story=a.story)
    if not problems:
        problems = (red(a.project, tests, a.lock, a.godot) if a.mode == "red" else green(a.project, tests, a.godot))
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        print(f"PASS tdd {a.mode} {', '.join(tests)}" + (" (locked)" if a.mode == "red" and a.lock else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
