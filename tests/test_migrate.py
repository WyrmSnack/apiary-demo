"""`apiary migrate --check` (Phase 3 gate c). The sample colony copies patterns found in Kevin's real colonies
(2026-10-15, read-only survey of eight on the author's machine) and in the Phase 0 kit's output."""
import hashlib

import pytest

from apiary.cli import main
from apiary.migrate import check

LEDGER = """# PHEROMONE_LEDGER
2026-05-15T12:00:00Z | Queen | DEPOSIT | tasks/pending/ | seeded 50 tasks
2026-07-28T19:50:00-07:00 | Queen | DEPOSIT | tasks/pending/ | seeded with an offset
2026-05-16T24:00:00Z | Queen | DEPOSIT | skills/ | hour 24
2026-10-14T05:38Z | Queen    | DEPOSIT   | research/README.md        | padded columns
2026-05-17T15:10 | stigmerge | DEPOSIT | x | caste not in the spec
2026-10-14T12:00Z | Signal Sprite | DEPOSIT | reports/x.md | kit spelling
2026-10-14T12:01Z | Forager | CLAIM | tasks/active/014-a.task | claimed via substrate server token=0123456789abcdef
"""
YAML_TASK = """---
id: 0004
title: Day-tick timing percentiles
caste: forager
depends-on: []
writes: [tests/helpers/perf.mjs]
---
"""


@pytest.fixture
def old(tmp_path):
    (tmp_path / "PHEROMONE_LEDGER.md").write_text(LEDGER, encoding="utf-8", newline="\n")
    for d in ("pending", "active", "done", "blocked", "deferred"):
        (tmp_path / "tasks" / d).mkdir(parents=True)
    (tmp_path / "tasks/pending/0004-day-tick-timing.task").write_text(YAML_TASK, encoding="utf-8")
    (tmp_path / "tasks/pending/015-shell.task").write_text(
        "objective: x\nacceptance: cd apiary/desktop && npm test\n", encoding="utf-8")
    (tmp_path / "tasks/pending/016-prose.task").write_text(
        "objective: x\nacceptance: primary cards grep-hit in Core ideas; wc >= 85% target\n", encoding="utf-8")
    (tmp_path / "tasks/pending/017-none.task").write_text("objective: x\n", encoding="utf-8")
    (tmp_path / "tasks/active/014-a.task").write_text("objective: x\nacceptance: pytest\n", encoding="utf-8")
    (tmp_path / "tasks/blocked/018-b.task").write_text("objective: x\nacceptance: pytest\n", encoding="utf-8")
    return tmp_path


def snapshot(root):
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def test_every_kind_of_blocker_is_reported(old):
    report = {f.kind: f for f in check(old)}
    for kind in ("ledger-timestamps", "ledger-castes", "ledger-padding", "task-yaml", "task-folders",
                 "acceptance-shell", "acceptance-not-a-command", "acceptance-missing", "claims-without-lease",
                 "not-installed"):
        assert kind in report, (kind, sorted(report))
    assert report["ledger-castes"].count == 2                     # stigmerge, Signal Sprite
    assert "stigmerge" in report["ledger-castes"].detail
    assert report["task-folders"].examples == ["tasks/blocked/", "tasks/deferred/"]
    assert report["claims-without-lease"].examples == ["tasks/active/014-a.task"]
    assert all(f.fix for f in report.values())


def test_check_changes_nothing(old):
    before = snapshot(old)
    check(old)
    assert snapshot(old) == before


def test_a_colony_made_by_init_has_no_blockers(tmp_path):
    main(["--root", str(tmp_path), "init", "--example"])
    assert check(tmp_path) == []


def test_cli_exit_codes(old, tmp_path_factory, capsys):
    assert main(["--root", str(old), "migrate", "--check"]) == 1
    out = capsys.readouterr().out
    assert "YAML" in out and "read only" in out.lower()
    fresh = tmp_path_factory.mktemp("fresh")
    main(["--root", str(fresh), "init"])
    capsys.readouterr()
    assert main(["--root", str(fresh), "migrate", "--check"]) == 0
