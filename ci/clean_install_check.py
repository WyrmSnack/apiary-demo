"""Phase 3 gate (a): install apiary the way a user does, with nothing from the checkout on the path, then
use it the way Claude Code does. Standard library only, so it runs before anything is installed.

  python ci/clean_install_check.py              # builds a wheel from this checkout
  python ci/clean_install_check.py --from SPEC   # or installs SPEC (a wheel, a path, or git+https://...)

Prints each step with its elapsed time and exits 1 on the first failure.
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
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
T0 = time.monotonic()


def step(msg: str) -> None:
    print(f"[{time.monotonic() - T0:6.1f}s] {msg}", flush=True)


def run(cmd: list[str], cwd: Path, ok: bool = True, **kw) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if ok and r.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
        sys.exit(1)
    return r


def bash() -> str:
    if os.name != "nt":
        return shutil.which("bash")
    git = Path(shutil.which("git")).resolve()          # Git Bash, which Claude Code uses for hooks on Windows
    for base in (git.parents[1], git.parents[2]):
        if (base / "bin" / "bash.exe").exists():
            return str(base / "bin" / "bash.exe")
    sys.exit("Git Bash not found")


MCP_CLIENT = r'''
import asyncio, json, os, re, sys
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
srv = json.load(open(".mcp.json", encoding="utf-8"))["mcpServers"]["colony"]
async def main():
    p = StdioServerParameters(command=srv["command"], args=srv["args"], env={**os.environ, **srv["env"]},
                              cwd=os.path.expanduser("~"))
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            t = lambda res: "".join(c.text for c in res.content)
            out = [t(await s.call_tool("resume", {}))]
            out.append(t(await s.call_tool("claim_task", {"task_file": "001-hello-colony.task"})))
            tok = re.search(r"token=(\w+)", out[-1]).group(1)
            out.append(t(await s.call_tool("renew_claim", {"task_file": "001-hello-colony.task", "token": tok})))
            out.append(t(await s.call_tool("close_task", {"task_file": "001-hello-colony.task", "token": tok})))
            print("\n".join(o.splitlines()[0] for o in out))
asyncio.run(main())
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="source", help="what to pip install (default: a wheel built from this checkout)")
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="apiary-clean-"))
    step(f"working in {work}")

    source = args.source
    if not source:
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-q", "-w", str(work / "dist"), str(REPO)], cwd=work)
        source = str(next((work / "dist").glob("apiary-*.whl")))
        step(f"built {Path(source).name}")

    run([sys.executable, "-m", "venv", str(work / "venv")], cwd=work)
    py = work / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([str(py), "-m", "pip", "install", "-q", source], cwd=work)
    step("installed into a fresh venv")
    probe = run([str(py), "-c", "import apiary, sys; print(apiary.__file__)"], cwd=work).stdout.strip()
    if str(REPO) in probe:
        print(f"FAILED: imported apiary from the checkout ({probe}), not from the install")
        return 1

    colony = work / "colony"
    colony.mkdir()
    run(["git", "init", "-q"], cwd=colony)
    for k, v in (("user.email", "ci@example.com"), ("user.name", "ci"), ("core.autocrlf", "false")):
        run(["git", "config", k, v], cwd=colony)
    out = run([str(py), "-m", "apiary", "init", "--example"], cwd=colony).stdout
    step("python -m apiary init --example: " + out.strip().splitlines()[-1][:60])
    for rel in (".mcp.json", ".claude/settings.json", "CLAUDE.md", "castes/forager.md", ".git/hooks/pre-commit",
                "tasks/pending/001-hello-colony.task"):
        if not (colony / rel).exists():
            print(f"FAILED: init did not create {rel}")
            return 1
    run(["git", "add", "-A"], cwd=colony)
    run(["git", "commit", "-q", "-m", "colony"], cwd=colony)
    step("first commit passed the installed pre-commit")

    hook = [h["command"] for e in json.loads((colony / ".claude/settings.json").read_text(encoding="utf-8"))
            ["hooks"]["PreToolUse"] for h in e["hooks"] if "apiary.hook" in h["command"]][0]
    event = {"tool_name": "Edit", "cwd": str(colony), "tool_input": {"file_path": str(colony / "PHEROMONE_LEDGER.md")}}
    r = run([bash(), "-c", hook], cwd=colony, ok=False, input=json.dumps(event))
    if r.returncode != 2 or "colony guard" not in r.stderr:
        print(f"FAILED: the installed guard did not block a ledger edit (exit {r.returncode}): {r.stderr}")
        return 1
    step("installed guard blocks a ledger edit")

    r = run([str(py), "-m", "apiary.gates.research", "research/none"], cwd=colony, ok=False)
    if r.returncode != 1 or "does not exist" not in r.stdout:
        print(f"FAILED: the installed research gate did not run (exit {r.returncode}): {r.stdout}{r.stderr}")
        return 1
    for rel in ("castes/queen.md", "castes/nurse.md", ".claude/skills/colony-plan/SKILL.md",
                "knowledge/_templates/Tool Card Template.md", "knowledge/Playbooks/.gitkeep"):
        if not (colony / rel).exists():
            print(f"FAILED: init did not create {rel}")
            return 1
    step("installed research gate runs; Queen and Nurse protocols installed")

    (colony / "client.py").write_text(MCP_CLIENT, encoding="utf-8")
    words = [ln.split()[0] for ln in run([str(py), "client.py"], cwd=colony).stdout.splitlines()]
    (colony / "client.py").unlink()
    if words != ["RESUMED", "CLAIMED", "RENEWED", "DONE"]:
        print(f"FAILED: MCP round trip gave {words}")
        return 1
    step("MCP round trip from .mcp.json: resume, claim, renew, close")

    run(["git", "add", "-A"], cwd=colony)
    run(["git", "commit", "-q", "-m", "closed 001"], cwd=colony)
    ledger = colony / "PHEROMONE_LEDGER.md"
    ledger.write_text(re.sub(r"token=\w+", "token=" + "0" * 16, ledger.read_text(encoding="utf-8"), count=1),
                      encoding="utf-8", newline="\n")
    run(["git", "add", "-A"], cwd=colony)
    r = run(["git", "commit", "-q", "-m", "rewrite"], cwd=colony, ok=False)
    if r.returncode == 0 or "L-7" not in r.stdout + r.stderr:
        print(f"FAILED: a rewritten ledger line was committed\n{r.stdout}{r.stderr}")
        return 1
    step("installed pre-commit refused a rewritten ledger line (L-7)")
    shutil.rmtree(work, ignore_errors=True)
    step("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
