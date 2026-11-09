import os
import shlex
import sys
from pathlib import Path

import pytest

from harness import Colony, Impl

REPO = Path(__file__).resolve().parents[1]
KNOWN = {
    "reference": Impl("reference", [sys.executable, "-m", "apiary.server"],
                      {"PYTHONPATH": os.pathsep.join([str(REPO), os.environ.get("PYTHONPATH", "")])}),
    "naive": Impl("naive", [sys.executable, str(REPO / "conformance" / "naive_server.py")]),
    "kit": Impl("kit", [sys.executable, str(REPO / "authoring-kit" / "mcp" / "substrate_server.py")]),
}


def pytest_addoption(parser):
    parser.addoption("--impl", default="reference",
                     help="reference | naive | kit | a command that starts an MCP stdio server")


@pytest.fixture(scope="session")
def impl(request) -> Impl:
    spec = request.config.getoption("--impl")
    return KNOWN.get(spec) or Impl("custom", shlex.split(spec))


@pytest.fixture
def colony(tmp_path, impl) -> Colony:
    return Colony(tmp_path, impl)
