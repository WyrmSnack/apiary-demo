"""`apiary init`: an empty repo becomes a working colony, and running it again changes nothing."""
import json
import pytest
import re
import sys

from apiary.cli import main
from apiary.colony import Colony
from apiary.validate import validate


def test_init_makes_an_empty_directory_a_valid_working_colony(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "init", "--example"]) == 0
    for d in ("pending", "active", "done"):
        assert (tmp_path / "tasks" / d / ".gitkeep").exists()      # git does not track empty folders
    assert validate(tmp_path) == []
    col = Colony(tmp_path)
    r = col.claim("001-hello-colony.task")
    assert r.startswith("CLAIMED"), r
    assert col.close("001-hello-colony.task", re.search(r"token=(\w+)", r).group(1)).startswith("DONE")
    assert validate(tmp_path) == []


def _server(path):
    return json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["colony"]


def test_init_writes_claude_code_config_with_this_interpreter(tmp_path):
    main(["--root", str(tmp_path), "init"])
    server = _server(tmp_path / ".mcp.json")            # Claude Code reads project servers from .mcp.json
    assert server["command"] == sys.executable          # never bare "python": it may be the Store stub
    assert server["args"] == ["-m", "apiary.server"] and server["env"] == {"COLONY_ROOT": str(tmp_path.resolve())}
    ignored = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".colony.lock" in ignored and ".apiary/" in ignored


def test_init_has_no_cursor_option_and_never_writes_cursor_files(tmp_path):
    with pytest.raises(SystemExit) as e:             # Claude Code is the only supported agent (Kevin, 2026-10-15)
        main(["--root", str(tmp_path), "init", "--cursor"])
    assert e.value.code == 2
    main(["--root", str(tmp_path), "init"])
    assert not (tmp_path / ".cursor").exists()


def test_init_twice_changes_nothing_and_keeps_other_servers(tmp_path):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    (tmp_path / ".gitignore").write_text("node_modules/\n.colony.lock\n")
    main(["--root", str(tmp_path), "init"])
    snapshot = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    main(["--root", str(tmp_path), "init"])
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == snapshot
    cfg = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert set(cfg["mcpServers"]) == {"other", "colony"}
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines.count(".colony.lock") == 1 and "node_modules/" in lines


def test_init_does_not_touch_an_unreadable_mcp_json(tmp_path, capsys):
    bad = tmp_path / ".mcp.json"
    bad.write_text("{ not json")
    assert main(["--root", str(tmp_path), "init"]) == 1
    assert bad.read_text() == "{ not json"
    assert ".mcp.json" in capsys.readouterr().out
    assert not (tmp_path / "PHEROMONE_LEDGER.md").exists()     # refused before changing anything


# --- Phase 2: init installs enforcement (gate c) -------------------------------

import os
import shutil
import subprocess
from pathlib import Path


def _bash():
    if os.name != "nt":
        return shutil.which("bash")
    git = Path(shutil.which("git")).resolve()            # Git Bash, not WSL's System32\bash.exe
    for base in (git.parents[1], git.parents[2]):
        if (base / "bin" / "bash.exe").exists():
            return str(base / "bin" / "bash.exe")
    raise AssertionError("Git Bash not found")


def _git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def _hook_entries(root):
    cfg = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return [h for e in cfg["hooks"]["PreToolUse"] for h in e["hooks"] if "apiary.hook" in h["command"]], cfg


def test_init_installs_the_claude_code_guard_and_it_runs_from_bash(tmp_path):
    main(["--root", str(tmp_path), "init"])
    hooks, cfg = _hook_entries(tmp_path)
    assert len(hooks) == 1
    matcher = next(e["matcher"] for e in cfg["hooks"]["PreToolUse"] if hooks[0] in e["hooks"])
    for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"):
        assert tool in matcher.split("|")
    event = {"tool_name": "Edit", "cwd": str(tmp_path), "tool_input": {"file_path": str(tmp_path / "TRACES.md")}}
    r = subprocess.run([_bash(), "-c", hooks[0]["command"]], input=json.dumps(event), capture_output=True, text=True)
    assert r.returncode == 2 and "colony guard" in r.stderr, (hooks[0]["command"], r.stderr)
    event["tool_input"]["file_path"] = str(tmp_path / "engine" / "x.py")
    r = subprocess.run([_bash(), "-c", hooks[0]["command"]], input=json.dumps(event), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_init_keeps_existing_claude_settings(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(
        {"permissions": {"allow": ["Bash(ls:*)"]},
         "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine"}]}]}}))
    main(["--root", str(tmp_path), "init"])
    hooks, cfg = _hook_entries(tmp_path)
    assert len(hooks) == 1 and cfg["permissions"] == {"allow": ["Bash(ls:*)"]}
    assert any(h["command"] == "echo mine" for e in cfg["hooks"]["PreToolUse"] for h in e["hooks"])


def test_init_writes_the_forager_protocol_and_imports_it_from_claude_md(tmp_path):
    main(["--root", str(tmp_path), "init"])
    protocol = (tmp_path / "castes" / "forager.md").read_text(encoding="utf-8")
    for word in ("resume", "claim_task", "renew_claim", "close_task", "ESCALATE", "write_trace"):
        assert word in protocol, word
    assert "@castes/forager.md" in (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")


def test_init_appends_to_an_existing_claude_md_once(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# My project\n\nHouse rules.\n", encoding="utf-8")
    main(["--root", str(tmp_path), "init"])
    main(["--root", str(tmp_path), "init"])
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith("# My project\n\nHouse rules.\n") and text.count("@castes/forager.md") == 1


def test_init_pre_commit_refuses_a_rewritten_ledger(tmp_path):
    _git(tmp_path, "init", "-q")
    for k, v in (("user.email", "t@example.com"), ("user.name", "t"), ("core.autocrlf", "false")):
        _git(tmp_path, "config", k, v)
    main(["--root", str(tmp_path), "init", "--example"])
    _git(tmp_path, "add", "-A")
    assert _git(tmp_path, "commit", "-q", "-m", "colony", check=False).returncode == 0
    col = Colony(tmp_path)
    assert col.append_ledger("Guardian", "WARN", "engine/x.py", "risk").startswith("APPENDED")
    _git(tmp_path, "add", "-A")
    assert _git(tmp_path, "commit", "-q", "-m", "append", check=False).returncode == 0
    (tmp_path / "PHEROMONE_LEDGER.md").write_text("# rewritten\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    r = _git(tmp_path, "commit", "-q", "-m", "rewrite", check=False)
    assert r.returncode != 0 and "L-7" in r.stdout + r.stderr, r.stdout + r.stderr


def test_init_leaves_a_foreign_pre_commit_alone(tmp_path, capsys):
    _git(tmp_path, "init", "-q")
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho theirs\n")
    main(["--root", str(tmp_path), "init"])
    assert hook.read_text() == "#!/bin/sh\necho theirs\n"
    assert "pre-commit" in capsys.readouterr().out


def test_init_keeps_colony_files_lf_under_autocrlf(tmp_path):
    """Kevin's git has core.autocrlf=true: without this, every colony file is checked out CRLF."""
    (tmp_path / ".gitattributes").write_text("*.png binary\n")
    main(["--root", str(tmp_path), "init"])
    main(["--root", str(tmp_path), "init"])
    lines = (tmp_path / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "*.png binary"
    for pattern in ("PHEROMONE_LEDGER.md", "TRACES.md", "tasks/**", "castes/**"):
        assert lines.count(f"{pattern} text eol=lf") == 1, lines


def test_init_refuses_unreadable_claude_settings(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{ nope")
    assert main(["--root", str(tmp_path), "init"]) == 1
    assert not (tmp_path / "PHEROMONE_LEDGER.md").exists()
