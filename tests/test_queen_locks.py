"""The Queen unlocks and relocks tests through the colony tools, and every change is reported to the human.

Measured in the Beyond the Ice Wall colony (S1 to S4b, 2026-10-17): 18 of about 32 human turns went to locks, and
the human hand-edited 12 entries of .apiary/tdd/locks.json (4 added with hashes the Queen pasted). 5 of those turns
were spent recovering from an edit that went wrong or an instruction the human could not follow.
Kevin, 2026-10-17: "the Queen can review and unlock, but MUST REPORT TO THE HUMAN CONCISELY WHAT HAPPENED."

unlock_test needs a WARN or ESCALATE for the file in the ledger since it was locked. relock_test runs the file. It
refuses an edit that weakens a test unless the human approved it in chat (checked by the guard), and it writes the
hash itself. Every change waits in .apiary/tdd/unreported.jsonl until the Queen's message to the human carries the
lock_report() block. The Stop hook enforces that (see test_lock_hooks.py).
"""
import json
import os
import sys
from pathlib import Path

import pytest

from apiary import locktools
from apiary.colony import Colony
from apiary.gates import tdd

FAKE_GODOT = r'''import json, sys
args = sys.argv[1:]
only = args[args.index("--files") + 1].split(",") if "--files" in args else []
results = json.load(open("results.json", encoding="utf-8"))
for path, tests in results.items():
    if only and path not in only:
        continue
    if tests == "noload":
        print(f"FAIL {path}: does not load (parse error?)"); continue
    for name, ok in tests.items():
        print(f"{'PASS' if ok else 'FAIL'} {path}::{name}")
'''

PRICE = '''extends "res://tests/case.gd"

const DIP := "res://src/rivals/diplomacy.gd"


func _war():
	var d = make(DIP)
	d.declare("rival1")
	return d


func test_paying_for_peace():
	var d = _war()
	d.advance(60)
	check_eq(d.peace_price("rival1"), 2200, "price for strength 11")
	check(d.at_war("rival1"), "still at war before paying")


func test_strength():
	var d = _war()
	check_near(d.strength("rival1"), 10.0, 0.01, "starting strength")
'''


@pytest.fixture
def colony(tmp_path, monkeypatch):
    root = tmp_path / "colony"
    for d in ("game/tests/feature", "game/tests/unit", "docs/stories/feature"):
        (root / d).mkdir(parents=True)
    (root / "game/project.godot").write_text("config_version=5\n", encoding="utf-8")
    script = tmp_path / "fake_godot.py"
    script.write_text(FAKE_GODOT, encoding="utf-8")
    if os.name == "nt":
        exe = tmp_path / "godot.bat"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="ascii")
    else:
        exe = tmp_path / "godot"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="ascii")
        exe.chmod(0o755)
    monkeypatch.chdir(root)
    monkeypatch.setattr(tdd, "_godot", lambda godot=None: [str(exe)])
    story(root, "FS-028", feature="game/tests/feature/test_diplomacy.gd")
    return root


def story(root, sid, feature="", unit=""):
    (root / f"docs/stories/feature/{sid}.md").write_text(
        f"---\nid: {sid}\nkind: feature\nparent: US-001\nfeature_tests: {feature}\nunit_tests: {unit}\n---\n"
        "## Acceptance criteria\n- something\n", encoding="utf-8")


def write(root, rel, text):
    (root / rel).write_text(text, encoding="utf-8")


def results(root, **files):
    """files: res path below res://tests/ (feature__test_x) -> {test: passed} or "noload"."""
    data = {"res://tests/" + k.replace("__", "/") + ".gd": v for k, v in files.items()}
    (root / "results.json").write_text(json.dumps(data), encoding="utf-8")


DIP = "game/tests/feature/test_diplomacy.gd"


def locks(root):
    return json.loads((root / ".apiary/tdd/locks.json").read_text(encoding="utf-8"))


def ledger(root):
    return (root / "PHEROMONE_LEDGER.md").read_text(encoding="utf-8")


def locked(root, green=False):
    """test_diplomacy.gd seen failing and locked by tdd red, then (optionally) made green."""
    write(root, DIP, PRICE)
    results(root, feature__test_diplomacy={"test_paying_for_peace": False, "test_strength": False})
    assert tdd.red("game", [DIP], lock=True) == []
    if green:
        results(root, feature__test_diplomacy={"test_paying_for_peace": True, "test_strength": True})
        assert tdd.green("game", [DIP]) == []
    return Colony(root)


def warned(c, caste="Guardian"):
    assert c.append_ledger(caste, "WARN", DIP, "Impassable test_paying_for_peace: rival grows monthly").startswith(
        "APPENDED")


# --- the weakening detector --------------------------------------------------------------

def diff(old, new, moved=()):
    return locktools.diff(old, new, moved=set(moved))


def test_fixing_an_expected_value_is_not_a_weakening_and_says_what_changed():
    d = diff(PRICE, PRICE.replace("2200, \"price", "2560, \"price"))
    assert d.weakenings == []
    assert d.changed == {"test_paying_for_peace"}
    assert any("2200" in c and "2560" in c for c in d.changes), d.changes


PANEL = '''extends "res://tests/case.gd"


func test_region_panel():
	var g = make("res://src/world/continent.gd")
	check_eq(g.region_info(Vector2i(3, 3)), {"terrain": "tundra", "owner": "player", "outpost": false}, "panel")
	check_eq(g.warning(), {"days": 10, "drones": 10, "missiles": 2}, "raid")
'''


def test_a_changed_dictionary_is_described_by_its_keys_and_values():
    """S4b replay, 2026-10-17: the region panel's dict gained two keys, and the report showed two truncated dicts."""
    new = PANEL.replace('"outpost": false}', '"outpost": false, "river": true, "site": ""}')
    new = new.replace('"drones": 10, "missiles"', '"drones": drones, "missiles"')
    d = diff(PANEL, new)
    assert d.weakenings == []
    assert any("+river" in c and "+site" in c for c in d.changes), d.changes
    assert any("drones 10 → drones" in c for c in d.changes), d.changes


def test_deleting_a_test_function_is_a_weakening():
    new = PRICE[:PRICE.index("func test_strength")]
    d = diff(PRICE, new)
    assert any("test_strength" in w and "deleted" in w for w in d.weakenings), d.weakenings


def test_a_test_moved_to_another_file_in_the_same_relock_is_not_deleted():
    new = PRICE[:PRICE.index("func test_strength")]
    assert diff(PRICE, new, moved={"test_strength"}).weakenings == []


def test_removing_a_check_is_a_weakening():
    d = diff(PRICE, PRICE.replace('\tcheck(d.at_war("rival1"), "still at war before paying")\n', ""))
    assert any("removed" in w and "at_war" in w for w in d.weakenings), d.weakenings


def test_loosening_a_tolerance_is_a_weakening():
    d = diff(PRICE, PRICE.replace("10.0, 0.01", "10.0, 0.5"))
    assert any("tolerance" in w for w in d.weakenings), d.weakenings


def test_a_tighter_tolerance_is_not():
    assert diff(PRICE, PRICE.replace("10.0, 0.01", "10.0, 0.001")).weakenings == []


def test_an_exact_check_turned_near_is_a_weakening():
    d = diff(PRICE, PRICE.replace('check_eq(d.peace_price("rival1"), 2200,',
                                  'check_near(d.peace_price("rival1"), 2200, 50,'))
    assert any("check_eq" in w and "check_near" in w for w in d.weakenings), d.weakenings


@pytest.mark.parametrize("old,new", [
    ('check_eq(d.peace_price("rival1"), 2200, "price for strength 11")',
     'check(d.peace_price("rival1") >= 2200, "price for strength 11")'),
    ('check(d.at_war("rival1"), "still at war before paying")',
     'check(d.at_war("rival1") or d.at_peace("rival1"), "still at war before paying")'),
])
def test_a_value_turned_into_a_range_or_a_looser_condition_is_a_weakening(old, new):
    assert old in PRICE
    assert diff(PRICE, PRICE.replace(old, new)).weakenings


def test_adding_a_check_or_changing_setup_is_reported_but_not_a_weakening():
    new = PRICE.replace('\td.advance(60)\n', '\td.advance(60)\n\tcheck_eq(d.strength("rival1"), 13, "grew")\n')
    new = new.replace('d.declare("rival1")', 'd.declare("rival1", true)')
    d = diff(PRICE, new)
    assert d.weakenings == []
    assert any("added check" in c for c in d.changes) and any("setup" in c or "helper" in c for c in d.changes)


def test_a_comment_or_message_change_is_no_change_to_what_is_tested():
    d = diff(PRICE, PRICE.replace('"starting strength"', '"strength at the start"') + "# a note\n")
    assert d.weakenings == [] and d.changed == set()


# --- unlock_test -------------------------------------------------------------------------

def test_only_the_queen_may_unlock(colony):
    c = locked(colony)
    warned(c)
    for caste in ("Forager", "Guardian", "Nurse"):
        out = c.unlock_test(caste, DIP, "impassable", "Guardian WARN: rival grows monthly")
        assert out.startswith("REFUSED") and "Queen" in out, out
    assert "unlocked" not in locks(colony)[DIP]


def test_unlock_needs_a_warn_for_that_file_in_the_ledger_since_it_was_locked(colony, monkeypatch):
    c = locked(colony)
    out = c.unlock_test("Queen", DIP, "impassable", "my own reading")
    assert out.startswith("REFUSED") and "WARN" in out, out
    monkeypatch.setenv("APIARY_CLOCK", "2000-01-01T00:00Z")         # a WARN from before the lock does not count
    warned(c)
    monkeypatch.delenv("APIARY_CLOCK")
    assert c.unlock_test("Queen", DIP, "impassable", "old WARN").startswith("REFUSED")


@pytest.mark.parametrize("reason,evidence", [("it_annoys_me", "Guardian WARN"), ("impassable", "")])
def test_unlock_needs_a_known_reason_and_evidence(colony, reason, evidence):
    c = locked(colony)
    warned(c)
    assert c.unlock_test("Queen", DIP, reason, evidence).startswith("REFUSED")


def test_unlock_refuses_a_file_already_changed_since_it_was_locked(colony):
    c = locked(colony)
    warned(c)
    write(colony, DIP, PRICE.replace("2200", "2560"))
    out = c.unlock_test("Queen", DIP, "impassable", "Guardian WARN")
    assert out.startswith("REFUSED") and "changed" in out, out


def test_unlock_keeps_the_entry_saves_the_text_logs_and_waits_to_be_reported(colony):
    c = locked(colony)
    warned(c)
    out = c.unlock_test("Queen", DIP, "impassable", "Guardian WARN 2026-10-17T18:12Z: rival grows monthly")
    assert out.startswith("UNLOCKED"), out
    entry = locks(colony)[DIP]
    assert entry["unlocked"]["reason"] == "impassable"
    history = colony / entry["unlocked"]["history"]
    assert history.read_text(encoding="utf-8") == PRICE
    assert entry["unlocked"]["history"].startswith(".apiary/tdd/history/game/tests/feature/test_diplomacy.gd@")
    line = [ln for ln in ledger(colony).splitlines() if " | UNLOCK | " in ln]
    assert len(line) == 1 and "| Queen |" in line[0] and "reason=impassable" in line[0], line
    pending = locktools.unreported(colony)
    assert [(p["path"], p["action"]) for p in pending] == [(DIP, "unlocked")]


def test_an_unlock_is_not_self_evidenced_when_the_guardian_warned(colony):
    c = locked(colony)
    warned(c, "Guardian")
    c.unlock_test("Queen", DIP, "impassable", "Guardian WARN")
    assert not locktools.unreported(colony)[0]["self_evidenced"]
    c2 = locked_other(colony)
    c2.append_ledger("Queen", "WARN", OTHER, "My test expects 20000 after the setup spent 210")
    c2.unlock_test("Queen", OTHER, "impassable", "my WARN")
    assert locktools.unreported(colony)[1]["self_evidenced"]


OTHER = "game/tests/unit/test_edge_roads.gd"
EDGE = '''extends "res://tests/case.gd"


func test_free_link():
	var g = make("res://src/city/city_grid.gd", [96, 96, 20000])
	g.lay("road", Vector2i(38, 48), Vector2i(58, 48))
	make("res://src/world/edge_roads.gd").lay(g, Vector2i(95, 48))
	check_eq(g.money, 20000, "free")
'''


def locked_other(root):
    write(root, OTHER, EDGE)
    story(root, "FS-025", unit=OTHER)
    results(root, unit__test_edge_roads={"test_free_link": False})
    assert tdd.red("game", [OTHER], lock=True) == []
    return Colony(root)


# --- green while a file is unlocked ------------------------------------------------------

def test_an_unlocked_file_does_not_block_unrelated_green_gates_but_its_own_gate_waits(colony):
    """S3, 2026-10-17: an unlocked file with failing tests failed every green gate in the colony (ESCALATE)."""
    c = locked(colony)
    warned(c)
    c.unlock_test("Queen", DIP, "impassable", "Guardian WARN")
    write(colony, "game/tests/unit/test_grid.gd", 'extends "res://tests/case.gd"\n\n\nfunc test_cell():\n\tcheck(true)\n')
    results(colony, unit__test_grid={"test_cell": False}, feature__test_diplomacy={"test_paying_for_peace": False,
                                                                                  "test_strength": False})
    assert tdd.red("game", ["game/tests/unit/test_grid.gd"], lock=True) == []
    results(colony, unit__test_grid={"test_cell": True}, feature__test_diplomacy={"test_paying_for_peace": False,
                                                                                 "test_strength": True})
    assert tdd.green("game", ["game/tests/unit/test_grid.gd"]) == []
    problems = tdd.green("game", [DIP])
    assert problems and "unlocked" in problems[0] and "relock_test" in problems[0], problems


# --- relock_test -------------------------------------------------------------------------

def unlocked(colony, green=False):
    c = locked(colony, green=green)
    warned(c)
    assert c.unlock_test("Queen", DIP, "impassable", "Guardian WARN").startswith("UNLOCKED")
    return c


def test_relock_records_the_hash_itself_and_a_changed_failing_test_is_pending(colony):
    c = unlocked(colony)
    write(colony, DIP, PRICE.replace("2200", "2560"))
    results(colony, feature__test_diplomacy={"test_paying_for_peace": False, "test_strength": False})
    out = c.relock_test("Queen", DIP, "FS-028")
    assert out.startswith("RELOCKED"), out
    entry = locks(colony)[DIP]
    assert "unlocked" not in entry and entry["sha256"] == tdd._sha(DIP) and entry["green"] is None
    assert entry["tests"]["test_paying_for_peace"]["green"] is None
    line = [ln for ln in ledger(colony).splitlines() if " | RELOCK | " in ln]
    assert len(line) == 1 and "story=FS-028" in line[0] and "weakened=no" in line[0], line
    relock = locktools.unreported(colony)[-1]
    assert relock["action"] == "relocked" and not relock["weakened"] and "2560" in relock["what"]
    assert tdd.green("game", [DIP]) != []            # still failing, and locked again: green waits for the code


def test_relock_accepts_a_changed_test_that_passes_because_the_code_exists(colony):
    c = unlocked(colony, green=True)
    write(colony, DIP, PRICE.replace("2200", "2560"))
    results(colony, feature__test_diplomacy={"test_paying_for_peace": True, "test_strength": True})
    assert c.relock_test("Queen", DIP, "FS-028").startswith("RELOCKED")
    assert locks(colony)[DIP]["green"]


def test_relock_refuses_when_an_unchanged_green_test_now_fails(colony):
    c = unlocked(colony, green=True)
    write(colony, DIP, PRICE.replace("2200", "2560"))
    results(colony, feature__test_diplomacy={"test_paying_for_peace": True, "test_strength": False})
    out = c.relock_test("Queen", DIP, "FS-028")
    assert out.startswith("REFUSED") and "test_strength" in out, out
    assert "unlocked" in locks(colony)[DIP]


def test_relock_refuses_a_file_that_does_not_load(colony):
    c = unlocked(colony)
    results(colony, feature__test_diplomacy="noload")
    assert c.relock_test("Queen", DIP, "FS-028").startswith("REFUSED")


def test_relock_refuses_a_weakening_without_the_humans_approval(colony):
    c = unlocked(colony)
    write(colony, DIP, PRICE[:PRICE.index("func test_strength")])
    results(colony, feature__test_diplomacy={"test_paying_for_peace": False})
    out = c.relock_test("Queen", DIP, "FS-028")
    assert out.startswith("REFUSED") and "weaken" in out and "approve weakening test_diplomacy.gd" in out, out
    assert "unlocked" in locks(colony)[DIP] and " | RELOCK | " not in ledger(colony)
    out = c.relock_test("Queen", DIP, "FS-028", approve_weakening=True)     # the guard checked the human's words
    assert out.startswith("RELOCKED"), out
    assert locktools.unreported(colony)[-1]["weakened"]
    assert "weakened=yes" in [ln for ln in ledger(colony).splitlines() if " | RELOCK | " in ln][0]


def test_dropping_the_file_from_its_story_is_a_weakening(colony):
    c = unlocked(colony)
    story(colony, "FS-028", feature="")
    results(colony, feature__test_diplomacy={"test_paying_for_peace": False, "test_strength": False})
    out = c.relock_test("Queen", DIP, "FS-028")
    assert out.startswith("REFUSED") and "FS-028" in out, out


def test_relock_refuses_a_file_that_was_not_unlocked_and_any_caste_but_the_queen(colony):
    c = locked(colony)
    assert c.relock_test("Queen", DIP, "FS-028").startswith("REFUSED")
    warned(c)
    c.unlock_test("Queen", DIP, "impassable", "Guardian WARN")
    results(colony, feature__test_diplomacy={"test_paying_for_peace": False, "test_strength": False})
    assert c.relock_test("Forager", DIP, "FS-028").startswith("REFUSED")


def test_a_test_moved_between_two_relocked_files_is_not_a_deletion(colony):
    c = unlocked(colony)
    other = "game/tests/feature/test_diplomacy_s5.gd"
    story(colony, "FS-028", feature=f"{DIP}, {other}")
    write(colony, DIP, PRICE[:PRICE.index("func test_strength")])
    write(colony, other, 'extends "res://tests/case.gd"\n\n\n' + PRICE[PRICE.index("func test_strength"):]
          .replace("_war()", 'make("res://src/rivals/diplomacy.gd")'))
    results(colony, feature__test_diplomacy={"test_paying_for_peace": False},
            feature__test_diplomacy_s5={"test_strength": False})
    out = c.relock_test("Queen", f"{DIP}, {other}", "FS-028")
    assert out.startswith("RELOCKED"), out
    assert other in locks(colony) and not any(p["weakened"] for p in locktools.unreported(colony))


def test_a_new_file_relocked_with_an_unlocked_one_is_judged_by_no_story_but_its_own(colony):
    """S2 replay, 2026-10-17: a new file listed by another story (FS-007) was called weakened by FS-028's list.
    Written after the fix, so it was not seen failing; the replay was the failing case."""
    c = unlocked(colony)
    other = "game/tests/unit/test_tools_s2.gd"
    story(colony, "FS-007", unit=other)
    write(colony, other, 'extends "res://tests/case.gd"\n\n\nfunc test_x():\n\tcheck_eq(1, 2, "pending")\n')
    results(colony, feature__test_diplomacy={"test_paying_for_peace": False, "test_strength": False},
            unit__test_tools_s2={"test_x": False})
    assert c.relock_test("Queen", f"{DIP}, {other}", "FS-028").startswith("RELOCKED")
    assert not any(p["weakened"] for p in locktools.unreported(colony))


def test_an_entry_from_before_this_version_still_unlocks_and_relocks(colony):
    """Backward compatibility: entries with only sha256, locked and green, as 12_1's locks.json holds."""
    write(colony, DIP, PRICE)
    (colony / ".apiary/tdd").mkdir(parents=True)
    (colony / ".apiary/tdd/locks.json").write_text(json.dumps({DIP: {
        "sha256": tdd._sha(DIP), "locked": "2026-10-17T17:58Z", "green": "2026-10-17T18:00Z"}}), encoding="utf-8")
    c = Colony(colony)
    warned(c)
    assert c.unlock_test("Queen", DIP, "impassable", "Guardian WARN").startswith("UNLOCKED")
    write(colony, DIP, PRICE.replace("2200", "2560"))
    results(colony, feature__test_diplomacy={"test_paying_for_peace": True, "test_strength": False})
    assert "test_strength" in c.relock_test("Queen", DIP, "FS-028")       # green before, unchanged, fails now
    results(colony, feature__test_diplomacy={"test_paying_for_peace": False, "test_strength": True})
    assert c.relock_test("Queen", DIP, "FS-028").startswith("RELOCKED")


def test_append_ledger_cannot_forge_unlock_or_relock_lines(colony):
    c = Colony(colony)
    for signal in ("UNLOCK", "RELOCK"):
        out = c.append_ledger("Queen", signal, DIP, "reason=impassable")
        assert out.startswith("REFUSED"), out


# --- lock_report -------------------------------------------------------------------------

def test_lock_report_has_one_short_line_per_change_with_its_token(colony):
    c = unlocked(colony)
    write(colony, DIP, PRICE.replace("2200", "2560"))
    results(colony, feature__test_diplomacy={"test_paying_for_peace": False, "test_strength": False})
    c.relock_test("Queen", DIP, "FS-028")
    report = c.lock_report("Queen")
    lines = report.splitlines()
    assert lines[0].startswith("LOCK REPORT")
    changes = [ln for ln in lines if ln.startswith("- [L")]
    assert len(changes) == 2, report
    assert "unlocked" in changes[0] and "impassable" in changes[0]
    assert "relocked" in changes[1] and "2200 → 2560" in changes[1] and "not weakened" in changes[1]
    assert all(len(ln) <= 240 for ln in changes), report


def test_lock_report_flags_a_self_evidenced_change_that_now_passes(colony):
    c = locked_other(colony)
    results(colony, unit__test_edge_roads={"test_free_link": True})
    c.append_ledger("Queen", "WARN", OTHER, "My test expects 20000 after the setup spent 210")
    c.unlock_test("Queen", OTHER, "impassable", "my WARN")
    write(colony, OTHER, EDGE.replace("check_eq(g.money, 20000", "check_eq(g.money, 19790"))
    assert c.relock_test("Queen", OTHER, "FS-025").startswith("RELOCKED")
    assert "self-evidenced" in c.lock_report("Queen")


def test_lock_report_lists_files_still_unlocked(colony):
    unlocked(colony)
    assert "Still unlocked: game/tests/feature/test_diplomacy.gd" in Colony(colony).lock_report("Queen")
