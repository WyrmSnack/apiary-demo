"""Plant one bug at a time in a copy of the tally reference and run the hidden tests against it.

  py bench/tally/plant_bugs.py bench/tally
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BENCH = Path(sys.argv[1])
REF = BENCH / "hidden" / "reference"
TESTS = BENCH / "hidden" / "tests"

BUGS = {
    "^ is right-associative": ("parser.py", "            self.take()\n            left = Bin(\"^\", left, self.unary())",
                               "            self.take()\n            return Bin(\"^\", left, self.power())"),
    "text comparison is case-sensitive": ("evaluator.py", "        a, b = a.casefold(), b.casefold()", "        pass"),
    "SUM reads numeric text in ranges": ("functions.py", "                if kind(v) == \"number\":\n                    out.append(v)",
                                         "                if kind(v) == \"number\":\n                    out.append(v)\n                elif kind(v) == \"text\" and parse_number(v) is not None:\n                    out.append(parse_number(v))"),
    "insert inside a range moves it instead of growing it": ("ops.py", "            ns, ne = point(s), point(e)",
                                                            "            ns, ne = (s + n, e + n) if e >= a else (s, e)"),
    "partial delete of a range gives #REF!": ("ops.py", "            if a <= lo and hi < a + n:", "            if hi >= a and lo < a + n:"),
    "fill shifts absolute parts": ("fill.py", "    col = ref.col if ref.col_abs else ref.col + dc", "    col = ref.col + dc"),
    "recalc ties by column first": ("workbook.py", "        return (self._sheets.index(sheet), row, col)",
                                    "        return (self._sheets.index(sheet), col, row)"),
    "a self-reference is not a cycle": ("graph.py", "        cyclic = len(members) > 1 or members[0] in preds.get(members[0], ())",
                                        "        cyclic = len(members) > 1"),
    "numbers left-aligned in the grid": ("render.py", "t.rjust(w) if kind(v) == \"number\" else t.ljust(w)", "t.ljust(w)"),
    "CSV rows stop at their last value": ("csvio.py", "        w.writerow([display(wb.cached(sheet, c, r)) for c in range(max_col + 1)])",
                                          "        row = [display(wb.cached(sheet, c, r)) for c in range(max_col + 1)]\n        while row and row[-1] == \"\":\n            row.pop()\n        w.writerow(row)"),
    "CLI error lines count only commands": ("cli.py", "    for n, line in enumerate(lines, 1):\n        line = line.rstrip(\"\\r\")\n        if not line.strip() or line.startswith(\"#\"):\n            continue",
                                           "    lines = [ln for ln in lines if ln.strip() and not ln.startswith(\"#\")]\n    for n, line in enumerate(lines, 1):\n        line = line.rstrip(\"\\r\")\n        if not line.strip() or line.startswith(\"#\"):\n            continue"),
    "ROUND rounds half to even": ("functions.py", "rounding=ROUND_HALF_UP", "rounding=\"ROUND_HALF_EVEN\""),
    "<> criteria skip blanks": ("functions.py", "            return lambda v: not (kind(v) == \"number\" and v == n)",
                                "            return lambda v: v is not BLANK and not (kind(v) == \"number\" and v == n)"),
    "a blank result stays blank": ("evaluator.py", "    return 0.0 if v is BLANK else v", "    return v"),
}


def run(impl: Path) -> tuple[int, int]:
    env = {**os.environ, "TALLY_IMPL": str(impl)}
    with tempfile.TemporaryDirectory() as tmp:
        tests = Path(tmp) / "tests"
        shutil.copytree(TESTS, tests)
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tests)], cwd=tmp,
                           env=env, capture_output=True, text=True)
    last = r.stdout.strip().splitlines()[-1]
    failed = int(last.split(" failed")[0].split()[-1]) if " failed" in last else 0
    passed = int(last.split(" passed")[0].split()[-1]) if " passed" in last else 0
    return failed, passed


print(f"reference, unchanged: {run(REF)[0]} failed")
caught = 0
for name, (file, old, new) in BUGS.items():
    with tempfile.TemporaryDirectory() as tmp:
        impl = Path(tmp) / "impl"
        shutil.copytree(REF, impl)
        path = impl / "tally" / file
        text = path.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"{name}: the text to change is not found exactly once"
        path.write_text(text.replace(old, new), encoding="utf-8")
        failed, passed = run(impl)
    caught += failed > 0
    print(f"{'caught' if failed else 'MISSED'}: {name}: {failed} failed, {passed} passed")
print(f"{caught} of {len(BUGS)} planted bugs caught")
