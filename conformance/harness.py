"""Drives an implementation under test over MCP stdio. Independent of the reference implementation:
the suite imports nothing from `apiary`, so it tests the spec, not our code's opinion of itself."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

HERE = Path(__file__).resolve().parent
VECTORS = HERE.parent / "spec" / "vectors"
RESULT_WORDS = {"CLAIMED", "RENEWED", "DONE", "RESUMED", "APPENDED", "TRACED", "CREATED", "RAN", "PLAN", "BOARD", "CONFLICT",
                "REFUSED"}

# Spec 4.1, written independently of apiary/grammar.py.
CASTES = "Queen|Forager|Nurse|Guardian|SignalSprite|Cartographer|Scribe"
SIGNALS = "DEPOSIT|REINFORCE|EVAPORATE|WARN|CLAIM|DONE|SKILL|TRACE|ESCALATE|UNLOCK|RELOCK"
LEDGER_LINE = re.compile(
    rf"^\d{{4}}-\d\d-\d\dT\d\d:\d\dZ \| (?:{CASTES}) \| (?:{SIGNALS}) \| [^\s|]{{1,200}} \| "
    r"(?=[^ ])[^|\x00-\x1f\x7f]{1,160}(?<! )$")


def vectors(name: str) -> dict:
    return json.loads((VECTORS / f"{name}.json").read_text(encoding="utf-8"))


def first_word(result: str) -> str:
    return re.split(r"[\s:]", result, maxsplit=1)[0]


@dataclass
class Impl:
    """How to start the implementation: a command and extra environment."""
    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)

    @contextlib.asynccontextmanager
    async def session(self, root: Path, clock: str | None = None):
        env = {**os.environ, **self.env, "COLONY_ROOT": str(root)}
        env.pop("APIARY_CLOCK", None)
        if clock:
            env["APIARY_CLOCK"] = clock
        params = StdioServerParameters(command=self.command[0], args=self.command[1:], env=env, cwd=str(root))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                yield Session(s)


class Session:
    def __init__(self, s: ClientSession):
        self._s = s

    async def call(self, tool: str, **args) -> str:
        result = await self._s.call_tool(tool, args)
        text = "".join(getattr(c, "text", "") for c in result.content)
        if result.is_error:
            return f"ERROR {text}"      # an unhandled error or a missing tool: never a valid result (M-1, M-2)
        return text


class Colony:
    """A temporary colony on disk plus helpers to call the implementation against it."""

    def __init__(self, root: Path, impl: Impl):
        self.root, self.impl = root, impl
        for d in ("pending", "active", "done"):
            (root / "tasks" / d).mkdir(parents=True, exist_ok=True)
        (root / "probe.py").write_text(PROBE, encoding="utf-8")

    def task(self, name: str, acceptance: str = 'python -c "exit(0)"', status: str = "pending",
             extra: str = "") -> Path:
        p = self.root / "tasks" / status / name
        p.write_text(f"objective: conformance task {name}\nacceptance: {acceptance}\n{extra}",
                     encoding="utf-8", newline="\n")
        return p

    def connector(self, name: str = "fake", version: str = "1.2.3", recorded: str | None = None,
                  extra: list[str] | None = None) -> None:
        """A stand-in connector (spec C-1): this Python, reporting `Fake <version>` as its version.
        `extra` adds TOML lines, such as C-6's `timeout_s` and `error_patterns`."""
        import sys as _sys
        d = self.root / "connectors"
        d.mkdir(exist_ok=True)
        lines = [f"program = '{Path(_sys.executable).as_posix()}'",
                 f"version_args = ['-c', \"print('Fake {version}')\"]",
                 "version_pattern = 'Fake (\\S+)'"]
        if recorded:
            lines.append(f"version = '{recorded}'")
        lines += extra or []
        (d / f"{name}.toml").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        (self.root / "make_output.py").write_text(MAKE_OUTPUT, encoding="utf-8")
        (self.root / "say.py").write_text(SAY, encoding="utf-8")
        (self.root / "sleepy.py").write_text(SLEEPY, encoding="utf-8")

    def runs(self) -> list[Path]:
        d = self.root / "runs"
        return sorted(d.glob("*.json")) if d.is_dir() else []

    def call(self, tool: str, clock: str | None = None, **args) -> str:
        return self.calls([(tool, args)], clock)[0]

    def calls(self, steps: list[tuple[str, dict]], clock: str | None = None) -> list[str]:
        async def go():
            out = []
            async with self.impl.session(self.root, clock) as s:
                for tool, args in steps:
                    out.append(await s.call(tool, **args))
            return out
        return asyncio.run(go())

    @property
    def ledger_path(self) -> Path:
        return self.root / "PHEROMONE_LEDGER.md"

    def ledger(self) -> list[str]:
        if not self.ledger_path.exists():
            return []
        return [ln for ln in self.ledger_path.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
                if ln.strip() and not ln.startswith("#")]

    def signals(self, signal: str) -> list[str]:
        return [ln for ln in self.ledger() if f" | {signal} | " in ln]

    def where(self, name: str) -> str | None:
        return next((d for d in ("pending", "active", "done") if (self.root / "tasks" / d / name).exists()), None)

    def probe(self) -> dict | None:
        p = self.root / "argv.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def token_of(result: str) -> str:
    """The token from a claim result, or "" if there is none. A missing token is P-5's failure
    (test_P5_...). Other tests carry on with "" so each one reports on its own requirement."""
    m = re.search(r"\btoken=([0-9a-f]{16})\b", result)
    return m.group(1) if m else ""


MAKE_OUTPUT = '''import pathlib, sys
p = pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(sys.argv[2] if len(sys.argv) > 2 else "hello", encoding="utf-8")
sys.exit(int(sys.argv[3]) if len(sys.argv) > 3 else 0)
'''

SAY = '''import sys
print(" ".join(sys.argv[1:]))
'''

SLEEPY = '''import sys, time
time.sleep(float(sys.argv[1]))
'''

PROBE = '''import json, os, sys
json.dump({"argv": sys.argv[1:], "cwd": os.getcwd()}, open("argv.json", "w", encoding="utf-8"))
'''
