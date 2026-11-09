"""`apiary validate --since <rev>`: the append-only check (spec L-7, R-6) against git (Phase 2 gate b)."""
import re
import subprocess

import pytest

from apiary.cli import main
from apiary.colony import Colony
from apiary.init import init
from apiary.validate import history


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "core.autocrlf", "false")
    init(tmp_path, example=True)
    col = Colony(tmp_path)
    tok = re.search(r"token=(\w+)", col.claim("001-hello-colony.task")).group(1)
    assert col.close("001-hello-colony.task", tok).startswith("DONE")
    assert col.write_trace("Queen", "save-format", "JSON").startswith("TRACED")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "colony")
    return tmp_path


def rules(repo, rev="HEAD"):
    return sorted({f.rule for f in history(repo, rev)})


def test_ordinary_appends_pass(repo):
    col = Colony(repo)
    assert col.append_ledger("Guardian", "WARN", "engine/x.py", "risk").startswith("APPENDED")
    assert col.write_trace("Queen", "units", "metres").startswith("TRACED")
    assert history(repo, "HEAD") == []


def test_a_rewritten_ledger_line_is_caught(repo):
    p = repo / "PHEROMONE_LEDGER.md"
    p.write_text(re.sub(r"token=\w+", "token=" + "f" * 16, p.read_text(encoding="utf-8"), count=1),
                 encoding="utf-8", newline="\n")
    found = history(repo, "HEAD")
    assert [f.rule for f in found] == ["L-7"] and ":2" in found[0].where, found


def test_a_deleted_ledger_line_is_caught(repo):
    p = repo / "PHEROMONE_LEDGER.md"
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    p.write_text("".join(lines[:1] + lines[2:]), encoding="utf-8", newline="\n")
    assert rules(repo) == ["L-7"]


def test_an_edited_traces_entry_is_caught(repo):
    p = repo / "TRACES.md"
    p.write_text(p.read_text(encoding="utf-8").replace("VALUE: JSON", "VALUE: XML"), encoding="utf-8", newline="\n")
    assert rules(repo) == ["R-6"]


def test_an_edited_closed_task_is_caught(repo):
    p = repo / "tasks" / "done" / "001-hello-colony.task"
    p.write_text(p.read_text(encoding="utf-8") + "estimate: 1h\n", encoding="utf-8", newline="\n")
    assert rules(repo) == ["T-6"]


def test_a_closed_task_moved_out_of_done_is_caught(repo):
    (repo / "tasks" / "done" / "001-hello-colony.task").rename(repo / "tasks" / "pending" / "001-hello-colony.task")
    assert "T-6" in rules(repo)


def test_tail_repair_is_not_a_rewrite(repo):
    p = repo / "PHEROMONE_LEDGER.md"
    with open(p, "ab") as f:
        f.write(b"2026-10-15T12:00Z | Forager | DEP")          # a crash mid-append, then committed
    # The installed pre-commit refuses a partial line (L-9), so this history needs --no-verify to exist.
    git(repo, "commit", "-q", "--no-verify", "-am", "partial line")
    assert Colony(repo).append_ledger("Forager", "DEPOSIT", "a.py", "next").startswith("APPENDED")
    assert history(repo, "HEAD") == []


def test_crlf_checkout_is_not_a_rewrite(repo):
    p = repo / "PHEROMONE_LEDGER.md"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert history(repo, "HEAD") == []


def test_a_repo_with_no_commits_has_nothing_to_compare(tmp_path):
    git(tmp_path, "init", "-q")
    init(tmp_path)
    assert history(tmp_path, "HEAD") == []


def test_an_unknown_revision_is_reported(repo):
    assert rules(repo, "no-such-rev") == ["L-7"]


def test_cli_since_flag(repo, capsys):
    assert main(["--root", str(repo), "validate", "--since", "HEAD"]) == 0
    (repo / "PHEROMONE_LEDGER.md").write_text("# rewritten\n", encoding="utf-8")
    assert main(["--root", str(repo), "validate", "--since", "HEAD"]) == 1
    assert "L-7" in capsys.readouterr().out
