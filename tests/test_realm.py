"""A colony in a realm reads the decrees its Supreme Queen seals, and answers in its own ledger (ADR 0005)."""
import json
import re

import pytest

from apiary import grammar as g
from apiary import realm
from apiary.cli import main
from apiary.colony import Colony
from apiary.init import QUEEN, update_protocols


@pytest.fixture(autouse=True)
def _no_realm_in_the_environment(monkeypatch):
    monkeypatch.delenv(realm.ENV, raising=False)


def _realm(tmp_path):
    root = tmp_path / "forge"
    (root / "realm" / "decrees").mkdir(parents=True)
    return root


def _seal(realm_root, did, to, objective="Add a health check", why="the realm needs it", priority="normal"):
    """The exact text the Forge writes (hive-ui/src/server/server.ts and tools/realm.py)."""
    issued = "2026-10-17T12:00Z"
    (realm_root / "realm" / "decrees" / f"{did}.decree").write_text("\n".join([
        f"# Issued by the Supreme Queen at {issued}. Vassal Queens answer by naming {did} in their own ledger.",
        f"to: {to}", f"objective: {objective}", f"why: {why}", f"priority: {priority}", f"issued: {issued}", ""]),
        encoding="utf-8", newline="\n")


def _vassal(realm_root, *parts):
    col = realm_root.joinpath("projects", *parts)
    col.mkdir(parents=True)
    assert main(["--root", str(col), "init", "--realm", str(realm_root)]) == 0
    return col


def _states(col):
    return {d.id: d.state for d in realm.decrees_for(col).decrees}


def test_init_realm_stores_the_realm_and_the_vassal_id_from_its_projects_folder(tmp_path, capsys):
    forge = _realm(tmp_path)
    col = forge / "projects" / "12-Apiary-SDK" / "apiary-sdk"           # a hive nested inside its vassal folder
    col.mkdir(parents=True)
    assert main(["--root", str(col), "init", "--realm", str(forge)]) == 0
    stored = json.loads((col / ".apiary" / "realm.json").read_text(encoding="utf-8"))
    assert stored == {"root": forge.resolve().as_posix(), "id": "12-apiary-sdk"}   # the vassal id: folder name, lower
    assert "12-apiary-sdk" in capsys.readouterr().out
    assert (col / "PHEROMONE_LEDGER.md").exists()                         # init itself still ran


def test_init_realm_outside_projects_uses_the_colony_folder_name_or_realm_id(tmp_path):
    forge = _realm(tmp_path)
    col = tmp_path / "Elsewhere"
    col.mkdir()
    assert main(["--root", str(col), "init", "--realm", str(forge)]) == 0
    assert realm.realm_of(col).vassal_id == "elsewhere"
    assert main(["--root", str(col), "init", "--realm", str(forge), "--realm-id", "Kitchen"]) == 0
    assert realm.realm_of(col).vassal_id == "kitchen"


def test_init_realm_refuses_a_folder_that_is_not_a_realm_and_changes_nothing(tmp_path, capsys):
    col = tmp_path / "col"
    col.mkdir()
    (tmp_path / "forge" / "realm").mkdir(parents=True)
    assert main(["--root", str(col), "init", "--realm", str(tmp_path / "nowhere")]) == 1
    assert main(["--root", str(col), "init", "--realm", str(tmp_path / "forge" / "realm")]) == 1
    out = capsys.readouterr().out
    assert "not a realm" in out and str((tmp_path / "forge").resolve()) in out    # points at the folder meant
    assert list(col.iterdir()) == []


def test_init_realm_refuses_a_bad_realm_id(tmp_path):
    forge = _realm(tmp_path)
    col = tmp_path / "col"
    col.mkdir()
    for bad in ("*", "a b", "x|y"):
        assert main(["--root", str(col), "init", "--realm", str(forge), "--realm-id", bad]) == 1
    assert not (col / ".apiary" / "realm.json").exists()


def test_init_realm_twice_changes_nothing(tmp_path, capsys):
    forge = _realm(tmp_path)
    col = forge / "projects" / "kitchen"
    col.mkdir(parents=True)
    main(["--root", str(col), "init", "--realm", str(forge)])
    snapshot = {p: p.read_bytes() for p in col.rglob("*") if p.is_file()}
    capsys.readouterr()
    assert main(["--root", str(col), "init", "--realm", str(forge)]) == 0
    assert {p: p.read_bytes() for p in col.rglob("*") if p.is_file()} == snapshot
    assert "vassal kitchen" not in capsys.readouterr().out      # no change, so nothing said about the realm


def test_update_protocols_keeps_the_realm_and_can_set_it(tmp_path):
    forge = _realm(tmp_path)
    col = _vassal(forge, "kitchen")
    assert main(["--root", str(col), "init", "--update-protocols", "--realm", str(forge)]) == 0
    assert realm.realm_of(col).vassal_id == "kitchen"
    update_protocols(col)
    assert realm.realm_of(col).root == forge.resolve()


def test_a_colony_without_a_realm_has_no_decrees(tmp_path):
    col = tmp_path / "col"
    col.mkdir()
    main(["--root", str(col), "init"])
    assert realm.decrees_for(col).decrees == []
    text = realm.report(col)
    assert text.startswith("DECREES none") and "apiary init --realm" in text
    assert main(["--root", str(col), "decrees"]) == 0


def test_lists_only_decrees_addressed_to_this_vassal_or_everyone(tmp_path):
    forge = _realm(tmp_path)
    col = _vassal(forge, "kitchen")
    _seal(forge, "001-add-a-health-check", "kitchen")
    _seal(forge, "002-adopt-lf", "*")
    _seal(forge, "003-not-ours", "other")
    assert _states(col) == {"001-add-a-health-check": "open", "002-adopt-lf": "open"}
    d = realm.decrees_for(col).decrees[0]
    assert (d.objective, d.why, d.priority, d.issued) == (
        "Add a health check", "the realm needs it", "normal", "2026-10-17T12:00Z")


def test_acknowledge_then_close_the_decree_task_fulfils_it(tmp_path):
    forge = _realm(tmp_path)
    col = _vassal(forge, "kitchen")
    did = "001-add-a-health-check"
    _seal(forge, did, "kitchen")
    path = realm.ack_path(did)
    g.check_path(path)                                         # the acknowledgement passes the ledger grammar
    c = Colony(col)
    assert c.append_ledger("Queen", "DEPOSIT", path, "acknowledged").startswith("APPENDED")
    assert _states(col) == {did: "acknowledged"}
    slug = realm.task_slug(did)
    assert slug == "decree-001-add-a-health-check"
    assert c.create_task("Queen", slug, "The health check exists.", 'python -c "pass"').startswith("CREATED")
    task = next(p.name for p in (col / "tasks" / "pending").glob("*.task"))
    token = re.search(r"token=(\w+)", c.claim(task, "Queen")).group(1)
    assert _states(col) == {did: "acknowledged"}               # a CLAIM names it too, but is not a DONE
    assert c.close(task, token, "Queen").startswith("DONE")
    assert _states(col) == {did: "fulfilled"}
    done = [ln for ln in (col / "PHEROMONE_LEDGER.md").read_text(encoding="utf-8").splitlines() if "| DONE |" in ln]
    assert did in done[-1]                                     # what the Throne Room and the survey match on


def test_a_decree_id_ending_in_a_hyphen_still_gets_a_valid_task_slug(tmp_path):
    forge = _realm(tmp_path)
    col = _vassal(forge, "kitchen")
    did = "004-make-the-kitchen-ticket-printer-print-"    # the Forge cuts slugs at 40 characters
    _seal(forge, did, "kitchen")
    slug = realm.task_slug(did)
    assert g.TASK_SLUG.fullmatch(slug)
    c = Colony(col)
    c.create_task("Queen", slug, "It prints.", 'python -c "pass"')
    task = next(p.name for p in (col / "tasks" / "pending").glob("*.task"))
    c.close(task, re.search(r"token=(\w+)", c.claim(task, "Queen")).group(1), "Queen")
    assert _states(col) == {did: "fulfilled"}


def test_a_line_naming_a_longer_decree_id_does_not_answer_a_shorter_one():
    assert realm.names("x | Queen | DEPOSIT | realm/decrees/001-fix.decree | acknowledged", "001-fix")
    assert realm.names("x | Queen | DONE | tasks/done/007-decree-001-fix.task | ok", "001-fix")
    assert not realm.names("x | Queen | DEPOSIT | realm/decrees/001-fix-all.decree | acknowledged", "001-fix")
    assert not realm.names("x | Queen | DEPOSIT | realm/decrees/1001-fix.decree | acknowledged", "001-fix")


def test_the_environment_variable_overrides_the_stored_realm(tmp_path, monkeypatch):
    forge, other = _realm(tmp_path), tmp_path / "other"
    (other / "realm" / "decrees").mkdir(parents=True)
    col = _vassal(forge, "kitchen")
    _seal(other, "001-from-the-other-realm", "kitchen")
    monkeypatch.setenv(realm.ENV, str(other))
    assert _states(col) == {"001-from-the-other-realm": "open"}


def test_report_tells_the_queen_exactly_how_to_answer(tmp_path, capsys):
    forge = _realm(tmp_path)
    col = _vassal(forge, "kitchen")
    _seal(forge, "001-add-a-health-check", "kitchen", priority="high")
    text = realm.report(col)
    assert text.splitlines()[0].startswith("DECREES vassal kitchen") and "1 open" in text
    assert 'path="realm/decrees/001-add-a-health-check.decree"' in text and "decree-001-add-a-health-check" in text
    assert main(["--root", str(col), "decrees"]) == 0
    assert "OPEN 001-add-a-health-check" in capsys.readouterr().out


def test_reading_decrees_never_writes_to_the_realm_or_the_colony(tmp_path):
    forge = _realm(tmp_path)
    col = _vassal(forge, "kitchen")
    _seal(forge, "001-add-a-health-check", "*")
    snapshot = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    realm.report(col)
    main(["--root", str(col), "decrees"])
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == snapshot


def test_an_unreadable_realm_file_or_decree_is_reported_not_a_crash(tmp_path):
    forge = _realm(tmp_path)
    col = _vassal(forge, "kitchen")
    (col / ".apiary").mkdir(exist_ok=True)
    (col / ".apiary" / "realm.json").write_text("{not json", encoding="utf-8")
    assert "WARN" in realm.report(col)
    main(["--root", str(col), "init", "--realm", str(forge)])
    (forge / "realm" / "decrees" / "001-bad.decree").write_bytes(b"\xff\xfeto: kitchen")
    _seal(forge, "002-good", "kitchen")
    view = realm.decrees_for(col)
    assert [d.id for d in view.decrees] == ["002-good"] and any("001-bad" in p for p in view.problems)


def test_the_mcp_server_exposes_realm_decrees(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from apiary import server
    forge = _realm(tmp_path)
    col = _vassal(forge, "kitchen")
    _seal(forge, "001-add-a-health-check", "kitchen")
    monkeypatch.setattr(server, "colony", Colony(col))
    assert server.realm_decrees().startswith("DECREES vassal kitchen")


def test_the_queen_protocol_reads_decrees_on_waking():
    assert "realm_decrees" in QUEEN and "realm/decrees/<id>.decree" in QUEEN
    assert "decree-<id>" in QUEEN and "acknowledged" in QUEEN
