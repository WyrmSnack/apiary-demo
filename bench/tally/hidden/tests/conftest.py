"""Hidden tests for bench/tally. TALLY_IMPL is the folder that contains the `tally` package under test."""
import os
import subprocess
import sys

import pytest

IMPL = os.environ.get("TALLY_IMPL")
if not IMPL:
    raise RuntimeError("set TALLY_IMPL to the folder containing the tally package")
sys.path.insert(0, IMPL)


@pytest.fixture
def wb():
    from tally.workbook import Workbook
    return Workbook()


@pytest.fixture
def cli(tmp_path):
    def run(script, files=None):
        for name, text in (files or {}).items():
            (tmp_path / name).write_text(text, encoding="utf-8", newline="")
        (tmp_path / "script.txt").write_text(script, encoding="utf-8", newline="")
        env = {**os.environ, "PYTHONPATH": IMPL}
        r = subprocess.run([sys.executable, "-m", "tally", "run", "script.txt"], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout.replace("\r\n", "\n").rstrip("\n"), r.stderr
    run.dir = tmp_path
    return run
