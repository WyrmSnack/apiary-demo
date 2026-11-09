"""Hidden tests for bench/skirmish. SKIRMISH_IMPL is the folder that contains the `skirmish` package under test."""
import os
import subprocess
import sys

import pytest

IMPL = os.environ.get("SKIRMISH_IMPL")
if not IMPL:
    raise RuntimeError("set SKIRMISH_IMPL to the folder containing the skirmish package")
sys.path.insert(0, IMPL)


@pytest.fixture
def cli(tmp_path):
    def run(*args, files=None):
        for name, text in (files or {}).items():
            (tmp_path / name).write_text(text, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": IMPL}
        r = subprocess.run([sys.executable, "-m", "skirmish", *args], cwd=tmp_path, env=env, capture_output=True,
                           text=True, timeout=60)
        return r.returncode, r.stdout.replace("\r\n", "\n").rstrip("\n"), r.stderr
    return run
