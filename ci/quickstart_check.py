"""Run QUICKSTART.md's step 2 and step 4 exactly as written, in a temporary folder, with this checkout installed.

  python ci/quickstart_check.py

Step 1 (pip install from GitHub) is replaced by the checkout CI already installed, so CI tests the commit being pushed.
Step 3 is Claude Code's part. Here the CLI claims and closes the example task instead, with the same operations the
colony's MCP tools call. Exit 1 on the first step that fails.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def blocks(text: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", text, re.S)


def run(line: str, cwd: Path) -> str:
    line = re.sub(r"^python\b", lambda _: f'"{sys.executable}"', line)
    out = subprocess.run(line, shell=True, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    print(f"$ {line}\n{out.stdout}{out.stderr}".rstrip())
    if out.returncode != 0:
        raise SystemExit(f"FAILED: {line} exited {out.returncode}")
    return out.stdout


def main() -> int:
    text = (REPO / "QUICKSTART.md").read_text(encoding="utf-8")
    steps = blocks(text)
    make, check = steps[1], steps[2]
    assert "apiary init --example" in make and "apiary validate" in check, "QUICKSTART.md changed shape"
    work = Path(tempfile.mkdtemp(prefix="apiary-quickstart-"))
    try:
        cwd = work
        for line in make.strip().splitlines():
            if line.startswith("cd "):
                cwd = cwd / line[3:].strip()
                continue
            run(line, cwd)
        claimed = run(f"python -m apiary claim 001-hello-colony.task", cwd)
        token = re.search(r"token=([0-9a-f]{16})", claimed).group(1)
        run(f"python -m apiary close 001-hello-colony.task {token}", cwd)
        out = "".join(run(line, cwd) for line in check.strip().splitlines())
        ledger = out.splitlines()
        assert "valid" in ledger[0], "validate did not print valid"
        assert sum(" | CLAIM | " in x for x in ledger) == 1 and sum(" | DONE | " in x and token in x
                                                                  for x in ledger) == 1, "ledger lacks CLAIM and DONE"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("QUICKSTART.md steps 2 and 4: passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
