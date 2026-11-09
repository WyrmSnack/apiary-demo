"""`apiary validate` and the CLI, in-process (the conformance suite covers the protocol over MCP)."""
import re

from apiary.cli import main
from apiary.colony import Colony
from apiary.validate import validate


def _task(root, name, status="pending", acceptance='python -c "exit(0)"'):
    p = root / "tasks" / status / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"objective: x\nacceptance: {acceptance}\n", encoding="utf-8", newline="\n")
    return p


def test_a_colony_built_by_the_tools_validates(tmp_path):
    col = Colony(tmp_path)
    _task(tmp_path, "014-a.task")
    _task(tmp_path, "015-b.task")
    tok = re.search(r"token=(\w+)", col.claim("014-a.task")).group(1)
    assert col.close("014-a.task", tok).startswith("DONE")
    assert col.claim("015-b.task").startswith("CLAIMED")
    assert col.write_trace("Queen", "save-format", "JSON").startswith("TRACED")
    assert col.append_ledger("Guardian", "WARN", "engine/x.py", "risk").startswith("APPENDED")
    assert validate(tmp_path) == []


def test_validate_reports_each_kind_of_problem(tmp_path):
    for d in ("pending", "active", "done"):
        (tmp_path / "tasks" / d).mkdir(parents=True)
    _task(tmp_path, "014-a.task", "active")                    # orphan: no CLAIM
    _task(tmp_path, "015-b.task", "done")                      # moved by hand: no DONE
    _task(tmp_path, "014-dup.task")                            # id 14 twice
    (tmp_path / "tasks" / "pending" / "16-bad.task").write_text("objective: x\nacceptance: y\n")
    (tmp_path / "PHEROMONE_LEDGER.md").write_bytes(
        b"2026-10-14T12:00 | Forager | DEPOSIT | a.py | no Z\n2026-10-14T12:00Z | Forager | DEP")
    (tmp_path / "TRACES.md").write_bytes("# T\n".encode("utf-16"))
    rules = sorted({f.rule for f in validate(tmp_path)})
    assert rules == ["E-3", "L-1", "L-9", "P-13", "P-14", "T-1", "T-2"], rules


def test_cli_round_trip_and_exit_codes(tmp_path, capsys):
    _task(tmp_path, "014-a.task")
    root = ["--root", str(tmp_path)]
    assert main([*root, "claim", "014-a.task"]) == 0
    tok = re.search(r"token=(\w+)", capsys.readouterr().out).group(1)
    assert main([*root, "close", "014-a.task", "0" * 16]) == 1
    assert "CONFLICT" in capsys.readouterr().out
    assert main([*root, "close", "014-a.task", tok]) == 0
    assert main([*root, "log", "Forager", "CLAIM", "tasks/active/x.task", "forged"]) == 1
    assert main([*root, "validate"]) == 0
    assert capsys.readouterr().out.strip().endswith("valid")


def test_lock_timeout_is_a_conflict_not_a_crash(tmp_path, monkeypatch):
    from filelock import FileLock
    import apiary.colony as c
    monkeypatch.setattr(c, "LOCK_TIMEOUT_S", 0.2)
    col = Colony(tmp_path)
    _task(tmp_path, "014-a.task")
    with FileLock(str(tmp_path / ".colony.lock")):
        r = col.claim("014-a.task")
    assert r.startswith("CONFLICT: colony is busy"), r


def test_validate_outside_a_colony_says_so(tmp_path, capsys):
    """Kevin ran `apiary validate` one folder up from his colony and got three 'D-2 missing' lines."""
    assert main(["--root", str(tmp_path), "validate"]) == 1
    out = capsys.readouterr().out
    assert "not a colony" in out and "apiary init" in out and "--root" in out
    assert "D-2" not in out
