"""Conformance suite for the Colony Substrate Specification v0.9.0.

Each test name starts with the requirement it checks: test_P9_... checks P-9.
Run against any implementation:  python -m pytest conformance --impl "<command that starts it>"
"""
import asyncio
import hashlib
import os
import re

import pytest

from harness import LEDGER_LINE, RESULT_WORDS, first_word, token_of, vectors

T0 = "2026-10-14T12:00Z"
ACCEPT = vectors("acceptance")


def at(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"2026-10-14T{12 + h:02d}:{m:02d}Z"


# --- D, E: layout and encoding ----------------------------------------------

def test_D2_works_in_an_empty_directory(tmp_path, impl):
    from harness import Colony
    root = tmp_path / "empty"
    root.mkdir()
    async def go():
        async with impl.session(root) as s:
            return await s.call("append_ledger", caste="Queen", signal="DEPOSIT", path="dossier.md", note="seeded")
    assert first_word(asyncio.run(go())) == "APPENDED"
    assert all((root / "tasks" / d).is_dir() for d in ("pending", "active", "done"))


def test_E1_writes_utf8_without_bom_with_lf(colony):
    r = colony.call("append_ledger", caste="Scribe", signal="DEPOSIT", path="parts/ch01.md", note="Grassé, 1959")
    assert first_word(r) == "APPENDED", r
    data = colony.ledger_path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf") and b"\r\n" not in data and data.endswith(b"\n")
    assert "Grassé, 1959" in data.decode("utf-8")


def test_E2_reads_a_crlf_ledger(colony):
    p = colony.task("014-crlf.task", status="active")
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    colony.ledger_path.write_bytes((f"{T0} | Forager | CLAIM | tasks/active/014-crlf.task | "
                                    f"token=0123456789abcdef lease_until={at(60)} task_sha256={digest}\r\n").encode())
    r = colony.call("close_task", clock=at(1), task_file="014-crlf.task", token="0123456789abcdef")
    assert first_word(r) == "DONE", r


def test_E3_utf16_ledger_is_refused_not_corrupted(colony):
    original = "# ledger\n".encode("utf-16")
    colony.ledger_path.write_bytes(original)
    r = colony.call("append_ledger", caste="Forager", signal="DEPOSIT", path="a.py", note="x")
    assert first_word(r) == "REFUSED", r
    assert colony.ledger_path.read_bytes() == original


# --- L: the ledger ------------------------------------------------------------

def test_L1_every_line_written_matches_the_grammar(colony):
    colony.task("014-a.task")
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    colony.calls([
        ("renew_claim", {"task_file": "014-a.task", "token": tok}),
        ("append_ledger", {"caste": "Guardian", "signal": "WARN", "path": "engine/x.py", "note": "risk"}),
        ("write_trace", {"caste": "Queen", "key": "save-format", "value": "JSON"}),
        ("close_task", {"task_file": "014-a.task", "token": tok}),
        ("resume", {}),
    ])
    lines = colony.ledger()
    assert len(lines) >= 5
    bad = [ln for ln in lines if not LEDGER_LINE.match(ln)]
    assert not bad, bad


@pytest.mark.parametrize("signal", ["DEPOSIT", "REINFORCE", "EVAPORATE", "WARN", "SKILL", "TRACE", "ESCALATE"])
def test_L1_append_accepts_every_open_signal(colony, signal):
    r = colony.call("append_ledger", caste="Scribe", signal=signal, path="parts/ch07.md", note="x")
    assert first_word(r) == "APPENDED", r


@pytest.mark.parametrize("fields,why", [
    ({"caste": "Overlord"}, "unknown caste"),
    ({"caste": "Signal Sprite"}, "caste with a space"),
    ({"signal": "ISSUE"}, "unknown signal"),
    ({"note": "x" * 161}, "note too long"),
    ({"note": "a | b"}, "pipe in note"),
    ({"note": "line one\nDONE"}, "newline in note"),
    ({"note": ""}, "empty note"),
    ({"path": "engine\\save.py"}, "backslash path"),
    ({"path": "/etc/passwd"}, "absolute path"),
    ({"path": "C:/x.py"}, "drive letter"),
    ({"path": "tasks/../x"}, "dot-dot"),
    ({"path": "my file.py"}, "space in path"),
])
def test_O1_append_refuses_invalid_fields_and_never_cleans_them(colony, fields, why):
    args = {"caste": "Forager", "signal": "DEPOSIT", "path": "engine/save.py", "note": "ok", **fields}
    r = colony.call("append_ledger", **args)
    assert first_word(r) == "REFUSED", f"{why}: {r}"
    assert colony.ledger() == []


def test_L9_partial_last_line_is_quarantined_before_append(colony):
    good = f"{T0} | Forager | DEPOSIT | a.py | first"
    colony.ledger_path.write_bytes(f"{good}\n{T0} | Forager | DEP".encode())
    r = colony.call("append_ledger", caste="Forager", signal="DEPOSIT", path="b.py", note="second")
    assert first_word(r) == "APPENDED", r
    lines = colony.ledger()
    assert all(LEDGER_LINE.match(ln) for ln in lines), lines
    assert lines[0] == good and any(" | WARN | PHEROMONE_LEDGER.md | " in ln for ln in lines)
    q = colony.root / ".apiary" / "quarantine.log"
    assert q.exists() and f"{T0} | Forager | DEP" in q.read_text(encoding="utf-8")


def test_L10_a_claim_cannot_be_forged_through_append(colony):
    colony.task("014-a.task")
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    forged = "f" * 16
    r1, r2 = colony.calls([
        ("append_ledger", {"caste": "Forager", "signal": "CLAIM", "path": "tasks/active/014-a.task",
                           "note": f"token={forged} lease_until={at(600)}"}),
        ("close_task", {"task_file": "014-a.task", "token": forged}),
    ])
    assert first_word(r1) == "REFUSED", r1
    assert first_word(r2) == "CONFLICT", r2
    assert first_word(colony.call("close_task", task_file="014-a.task", token=tok)) == "DONE"


def test_L10_done_and_reserved_attributes_are_refused(colony):
    for args in ({"signal": "DONE", "note": "finished"},
                 {"signal": "REINFORCE", "note": f"renew token={'a' * 16} lease_until={at(600)}"},
                 {"signal": "DEPOSIT", "note": "lease_until=2099-01-01T00:00Z"}):
        r = colony.call("append_ledger", caste="Forager", path="tasks/active/014-a.task", **args)
        assert first_word(r) == "REFUSED", (args, r)


# --- T and P: claim ------------------------------------------------------------

def test_P3_claim_of_a_missing_task_is_a_conflict(colony):
    assert first_word(colony.call("claim_task", task_file="099-nothing.task")) == "CONFLICT"


@pytest.mark.parametrize("name", ["../014-x.task", "014_x.task", "14-x.task", "014-x.txt"])
def test_P4_claim_refuses_a_bad_task_name(colony, name):
    assert first_word(colony.call("claim_task", task_file=name)) == "REFUSED"


def test_P4_claim_refuses_a_malformed_task(colony):
    p = colony.root / "tasks" / "pending" / "014-a.task"
    p.write_text("objective: no acceptance line\n", encoding="utf-8")
    assert first_word(colony.call("claim_task", task_file="014-a.task")) == "REFUSED"
    assert colony.where("014-a.task") == "pending" and colony.signals("CLAIM") == []


def test_P4_depends_on_must_be_done_first(colony):
    colony.task("014-base.task")
    colony.task("015-next.task", extra="depends-on: 014\n")
    assert first_word(colony.call("claim_task", task_file="015-next.task")) == "REFUSED"
    assert colony.where("015-next.task") == "pending"
    tok = token_of(colony.call("claim_task", task_file="014-base.task"))
    assert first_word(colony.call("close_task", task_file="014-base.task", token=tok)) == "DONE"
    assert first_word(colony.call("claim_task", task_file="015-next.task")) == "CLAIMED"


def test_P5_claim_moves_the_file_and_writes_token_and_lease(colony):
    colony.task("014-a.task")
    r = colony.call("claim_task", clock=T0, task_file="014-a.task", lease_minutes=5)
    assert first_word(r) == "CLAIMED", r
    tok = token_of(r)
    assert tok, f"no token in claim result: {r!r}"
    assert colony.where("014-a.task") == "active"
    claims = colony.signals("CLAIM")
    assert len(claims) == 1
    assert claims[0].startswith(f"{T0} | ") and " | tasks/active/014-a.task | " in claims[0]
    assert f"token={tok}" in claims[0] and f"lease_until={at(5)}" in claims[0]


def test_P6_concurrent_claims_have_exactly_one_winner(colony, impl):
    colony.task("014-a.task")
    async def one():
        async with impl.session(colony.root) as s:
            return await s.call("claim_task", task_file="014-a.task")
    async def race():
        return await asyncio.gather(*[one() for _ in range(4)])
    words = sorted(first_word(r) for r in asyncio.run(race()))
    assert words == ["CLAIMED", "CONFLICT", "CONFLICT", "CONFLICT"], words
    assert len(colony.signals("CLAIM")) == 1


def _os_lock(path):
    """Spec P-1's lock, taken with the raw OS call, not through filelock: another implementation's view."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return fd, lambda: (os.lseek(fd, 0, 0), msvcrt.locking(fd, msvcrt.LK_UNLCK, 1), os.close(fd))
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd, lambda: (fcntl.flock(fd, fcntl.LOCK_UN), os.close(fd))


def test_P1_no_change_while_another_process_holds_the_colony_lock(colony, impl):
    colony.task("014-a.task")
    _, release = _os_lock(colony.root / ".colony.lock")
    async def scenario():
        async with impl.session(colony.root) as s:
            pending = asyncio.ensure_future(s.call("claim_task", task_file="014-a.task"))
            await asyncio.sleep(3)
            during = (colony.where("014-a.task"), len(colony.signals("CLAIM")))
            release()
            return during, await pending
    (where, claims), r = asyncio.run(scenario())
    assert (where, claims) == ("pending", 0), "claimed while another process held .colony.lock"
    assert first_word(r) in {"CLAIMED", "CONFLICT"}, r


def test_P7_claim_of_a_file_open_elsewhere_never_crashes(colony):
    p = colony.task("014-a.task")
    with open(p, encoding="utf-8"):
        r = colony.call("claim_task", task_file="014-a.task")
    if os.name == "nt":       # Windows cannot rename a file another handle holds open
        assert first_word(r) == "CONFLICT", r
        assert colony.where("014-a.task") == "pending" and colony.signals("CLAIM") == []
    else:
        assert first_word(r) == "CLAIMED", r


def test_T6_operations_never_change_task_content(colony):
    p = colony.task("014-a.task", extra="why: keep these bytes\nestimate: 2h\n")
    before = p.read_bytes()
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    colony.call("close_task", task_file="014-a.task", token=tok)
    assert (colony.root / "tasks" / "done" / "014-a.task").read_bytes() == before


# --- P: renew, close --------------------------------------------------------------

def test_P8_renew_extends_the_lease(colony):
    colony.task("014-a.task", acceptance='python -c "exit(1)"')
    tok = token_of(colony.call("claim_task", clock=T0, task_file="014-a.task", lease_minutes=1))
    r = colony.call("renew_claim", clock=T0, task_file="014-a.task", token=tok, lease_minutes=30)
    assert first_word(r) == "RENEWED", r
    assert first_word(colony.call("resume", clock=at(10))) == "RESUMED"
    assert colony.where("014-a.task") == "active"


def test_P8_renew_with_a_wrong_token_is_a_conflict(colony):
    colony.task("014-a.task")
    colony.call("claim_task", task_file="014-a.task")
    assert first_word(colony.call("renew_claim", task_file="014-a.task", token="0" * 16)) == "CONFLICT"


def test_P9_close_requires_the_current_token_and_does_not_run_acceptance_without_it(colony):
    colony.task("014-a.task", acceptance="python probe.py ran")
    colony.call("claim_task", task_file="014-a.task")
    for token in ("", "0" * 16):
        r = colony.call("close_task", task_file="014-a.task", token=token)
        assert first_word(r) == "CONFLICT", (token, r)
    assert colony.probe() is None and colony.where("014-a.task") == "active"


@pytest.mark.parametrize("case", [c for c in ACCEPT["invalid"] if c["line"].strip()], ids=lambda c: c["why"])
def test_P10_A2_invalid_acceptance_is_refused_and_never_run(colony, case):
    colony.task("014-a.task", acceptance=f"python probe.py {case['line']}")
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    r = colony.call("close_task", task_file="014-a.task", token=tok)
    assert first_word(r) == "REFUSED", r
    assert colony.probe() is None, "the command ran"
    assert colony.where("014-a.task") == "active" and colony.signals("DONE") == []


@pytest.mark.parametrize("case", ACCEPT["valid"], ids=lambda c: c["line"])
def test_A1_A4_acceptance_argv_is_exact_and_runs_in_the_colony_root(colony, case):
    colony.task("014-a.task", acceptance=f"python probe.py {case['line']}")
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    r = colony.call("close_task", task_file="014-a.task", token=tok)
    assert first_word(r) == "DONE", r
    got = colony.probe()
    assert got is not None and got["argv"] == case["argv"]
    assert os.path.samefile(got["cwd"], colony.root)


def test_A3_python_means_python_311_or_later(colony):
    colony.task("014-a.task", acceptance='python -c "import sys; sys.exit(sys.version_info < (3, 11))"')
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    assert first_word(colony.call("close_task", task_file="014-a.task", token=tok)) == "DONE"


def test_A3_a_missing_program_is_refused_without_a_warn(colony):
    colony.task("014-a.task", acceptance="no-such-program-apiary-xyz --version")
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    r = colony.call("close_task", task_file="014-a.task", token=tok)
    assert first_word(r) == "REFUSED", r
    assert colony.where("014-a.task") == "active" and colony.signals("WARN") == []


def test_P11_close_rechecks_the_claim_after_acceptance_runs(colony):
    # The acceptance command itself plays the part of a resume that runs while it is running.
    move = "import os; os.rename('tasks/active/014-a.task', 'tasks/pending/014-a.task')"
    colony.task("014-a.task", acceptance=f'python -c "{move}"')
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    r = colony.call("close_task", task_file="014-a.task", token=tok)
    assert first_word(r) == "CONFLICT", r
    assert colony.signals("DONE") == [] and colony.where("014-a.task") == "pending"


def test_P12_failing_acceptance_warns_and_keeps_the_task_active(colony):
    colony.task("014-a.task", acceptance='python -c "exit(3)"')
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    r = colony.call("close_task", task_file="014-a.task", token=tok)
    assert first_word(r) == "REFUSED", r
    assert colony.where("014-a.task") == "active"
    assert any(" | WARN | tasks/active/014-a.task | " in ln for ln in colony.ledger())


def test_P13_passing_acceptance_moves_to_done_with_one_done_line(colony):
    colony.task("014-a.task")
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    r1, r2 = colony.calls([("close_task", {"task_file": "014-a.task", "token": tok}),
                           ("close_task", {"task_file": "014-a.task", "token": tok})])
    assert first_word(r1) == "DONE" and first_word(r2) == "CONFLICT", (r1, r2)
    dones = colony.signals("DONE")
    assert len(dones) == 1 and " | tasks/done/014-a.task | " in dones[0] and f"token={tok}" in dones[0]
    assert colony.where("014-a.task") == "done"


def test_P18_claim_pins_the_task_file_by_hash(colony):
    p = colony.task("014-a.task")
    digest = hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    r = colony.call("claim_task", task_file="014-a.task")
    claims = colony.signals("CLAIM")
    assert len(claims) == 1 and f"task_sha256={digest}" in claims[0], (claims, r)


def test_P19_a_claim_returns_the_claimed_task_text(colony):
    # Phase 9: a Forager read the task file in a call of its own, re-reading 55k to 60k tokens of context to do it.
    p = colony.task("014-a.task", extra="writes: src/a.py\nwhy: line one é\n")
    text = p.read_text(encoding="utf-8")
    r = colony.call("claim_task", task_file="014-a.task")
    first, _, rest = r.partition("\n")
    assert first.startswith("CLAIMED ") and token_of(first), r
    assert rest == text, r
    assert first_word(colony.call("claim_task", task_file="014-a.task")) == "CONFLICT"   # a failed claim carries no text


def test_P18_editing_the_task_after_claiming_cannot_pass_the_gate(colony):
    """Found in review: a Forager rewrote its own acceptance line from exit(1) to exit(0) and closed the task."""
    colony.task("014-a.task", acceptance='python -c "exit(1)"')
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    assert first_word(colony.call("close_task", task_file="014-a.task", token=tok)) == "REFUSED"
    colony.task("014-a.task", acceptance='python -c "exit(0)"', status="active")      # an ordinary file write
    r = colony.call("close_task", task_file="014-a.task", token=tok)
    assert first_word(r) == "REFUSED", r
    assert colony.where("014-a.task") == "active" and colony.signals("DONE") == []
    assert any("task file changed since claim" in ln for ln in colony.signals("WARN")), colony.ledger()


def test_P18_a_claim_without_a_task_hash_cannot_close(colony):
    colony.task("014-a.task", status="active")
    colony.ledger_path.write_bytes(
        f"{T0} | Forager | CLAIM | tasks/active/014-a.task | token=0123456789abcdef lease_until={at(60)}\n".encode())
    r = colony.call("close_task", clock=at(1), task_file="014-a.task", token="0123456789abcdef")
    assert first_word(r) == "REFUSED", r
    assert colony.where("014-a.task") == "active"


def test_P13_close_of_a_file_open_elsewhere_never_crashes(colony):
    p = colony.task("014-a.task")
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    with open(colony.root / "tasks" / "active" / p.name, encoding="utf-8"):
        r = colony.call("close_task", task_file="014-a.task", token=tok)
    if os.name == "nt":
        assert first_word(r) == "CONFLICT", r
        assert colony.where("014-a.task") == "active" and colony.signals("DONE") == []
    else:
        assert first_word(r) == "DONE", r


# --- P: resume ----------------------------------------------------------------------

def test_P14_resume_returns_an_orphan(colony):
    colony.task("014-a.task", status="active")
    r = colony.call("resume")
    assert first_word(r) == "RESUMED", r
    assert colony.where("014-a.task") == "pending"
    assert any(" | EVAPORATE | tasks/pending/014-a.task | " in ln for ln in colony.ledger())


def test_P15_resume_leaves_a_live_claim_alone(colony):
    """Textbook correction C1: Ch 18.3's resume takes a live task whose acceptance does not pass yet."""
    colony.task("014-a.task", acceptance='python -c "exit(1)"')
    tok = token_of(colony.call("claim_task", clock=T0, task_file="014-a.task"))
    assert first_word(colony.call("resume", clock=at(5))) == "RESUMED"
    assert colony.where("014-a.task") == "active"
    assert colony.signals("EVAPORATE") == []
    assert first_word(colony.call("renew_claim", clock=at(6), task_file="014-a.task", token=tok)) == "RENEWED"


def test_P14_resume_returns_an_expired_lease_and_fences_the_old_token(colony):
    colony.task("014-a.task")
    old = token_of(colony.call("claim_task", clock=T0, task_file="014-a.task", lease_minutes=1))
    assert first_word(colony.call("resume", clock=at(1))) == "RESUMED"
    assert colony.where("014-a.task") == "active", "a lease lasts through its lease_until minute"
    r = colony.call("resume", clock=at(2))
    assert first_word(r) == "RESUMED" and colony.where("014-a.task") == "pending", r
    new = token_of(colony.call("claim_task", clock=at(3), task_file="014-a.task"))
    assert first_word(colony.call("close_task", clock=at(3), task_file="014-a.task", token=old)) == "CONFLICT"
    assert first_word(colony.call("close_task", clock=at(3), task_file="014-a.task", token=new)) == "DONE"
    assert len(colony.signals("DONE")) == 1


def test_P15_resume_never_runs_acceptance(colony):
    colony.task("014-a.task", acceptance="python probe.py resumed", status="active")
    colony.call("resume")
    assert colony.probe() is None


def test_P16_resume_reports_counts(colony):
    colony.task("014-a.task", status="active")
    colony.task("015-b.task")
    colony.call("claim_task", clock=T0, task_file="015-b.task")
    r = colony.call("resume", clock=at(5))
    assert r.split("\n")[0] == "RESUMED returned=1 kept=1", r


# --- R: TRACES ----------------------------------------------------------------------

def test_R1_R7_trace_entry_and_ledger_line(colony):
    r = colony.call("write_trace", caste="Queen", key="save-format", value="JSON, versioned")
    assert r == "TRACED save-format", r
    text = (colony.root / "TRACES.md").read_text(encoding="utf-8")
    assert "\n## KEY: save-format\n- by: Queen at " in text and "\n- VALUE: JSON, versioned\n" in text
    assert any(ln.endswith(" | TRACE | TRACES.md | KEY save-format") for ln in colony.ledger())


def test_R3_a_key_is_written_once(colony):
    colony.call("write_trace", caste="Queen", key="save-format", value="JSON")
    assert first_word(colony.call("write_trace", caste="Guardian", key="save-format", value="XML")) == "CONFLICT"


def test_R4_supersedes_must_name_an_existing_key(colony):
    r = colony.call("write_trace", caste="Queen", key="save-format-v2", value="x", supersedes="save-format")
    assert first_word(r) == "REFUSED", r
    colony.call("write_trace", caste="Queen", key="save-format", value="JSON")
    r = colony.call("write_trace", caste="Queen", key="save-format-v2", value="x", supersedes="save-format")
    assert first_word(r) == "TRACED", r
    assert "\n- SUPERSEDES: save-format\n" in (colony.root / "TRACES.md").read_text(encoding="utf-8")


def test_R5_value_is_one_line(colony):
    colony.call("write_trace", caste="Queen", key="units", value="metres,\n\n  seconds\tand kilograms")
    assert "\n- VALUE: metres, seconds and kilograms\n" in (colony.root / "TRACES.md").read_text(encoding="utf-8")


# --- O-3: create_task ----------------------------------------------------------------

def _created(r: str) -> str:
    assert first_word(r) == "CREATED", r
    return r.split()[1]


def test_O3_creates_a_valid_task_that_can_be_claimed_and_closed(colony):
    r = colony.call("create_task", caste="Queen", slug="save-slots", objective="Player can save to three slots.",
                    acceptance='python -c "exit(0)"', writes="engine/save.py, tests/test_save.py",
                    why="Players lose progress.")
    name = _created(r)
    assert name == "001-save-slots.task" and colony.where(name) == "pending"
    text = (colony.root / "tasks/pending" / name).read_text(encoding="utf-8")
    for line in ("objective: Player can save to three slots.", 'acceptance: python -c "exit(0)"',
                 "writes: engine/save.py, tests/test_save.py", "why: Players lose progress."):
        assert line in text.splitlines(), text
    assert any(" | DEPOSIT | tasks/pending/001-save-slots.task | " in ln for ln in colony.ledger())
    tok = token_of(colony.call("claim_task", task_file=name))
    assert first_word(colony.call("close_task", task_file=name, token=tok)) == "DONE"


def test_O3_ids_follow_the_highest_existing_id(colony):
    colony.task("014-a.task", status="done")
    colony.task("009-b.task")
    assert _created(colony.call("create_task", caste="Queen", slug="next", objective="x",
                                acceptance='python -c "exit(0)"')) == "015-next.task"


@pytest.mark.parametrize("args,why", [
    ({"slug": "Bad Slug"}, "slug"),
    ({"slug": "-x"}, "slug"),
    ({"objective": ""}, "objective"),
    ({"acceptance": ""}, "acceptance"),
    ({"acceptance": "cd x && npm test"}, "shell syntax"),
    ({"acceptance": "A fully sourced textbook that teaches an engineer"}, "not a command"),
    ({"depends_on": "999"}, "unknown dependency"),
    ({"caste": "Overlord"}, "caste"),
])
def test_O3_refuses_what_claim_or_close_would_refuse(colony, args, why):
    base = {"caste": "Queen", "slug": "x", "objective": "x", "acceptance": 'python -c "exit(0)"', **args}
    r = colony.call("create_task", **base)
    assert first_word(r) == "REFUSED", f"{why}: {r}"
    assert not [p for p in (colony.root / "tasks").rglob("*.task")], why


def test_O3_writes_a_new_gate_and_points_acceptance_at_it(colony):
    gate = "import sys\nsys.exit(0)\n"
    name = _created(colony.call("create_task", caste="Queen", slug="guide", objective="Write the guide.",
                                gate_code=gate, gate_args="docs/guide"))
    gate_path = colony.root / "gates" / "check_001.py"
    assert gate_path.read_text(encoding="utf-8") == gate
    text = (colony.root / "tasks/pending" / name).read_text(encoding="utf-8")
    assert "acceptance: python gates/check_001.py docs/guide" in text.splitlines(), text
    assert any(" | DEPOSIT | gates/check_001.py | " in ln for ln in colony.ledger())


def test_O3_never_replaces_an_existing_gate(colony):
    (colony.root / "gates").mkdir()
    (colony.root / "gates" / "check_001.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    r = colony.call("create_task", caste="Queen", slug="g", objective="x", gate_code="import sys\nsys.exit(0)\n")
    assert first_word(r) in {"REFUSED", "CONFLICT"}, r
    assert "exit(1)" in (colony.root / "gates" / "check_001.py").read_text(encoding="utf-8")


def test_O3_refuses_a_gate_that_does_not_compile(colony):
    r = colony.call("create_task", caste="Queen", slug="g", objective="x", gate_code="def broken(:\n")
    assert first_word(r) == "REFUSED", r
    assert not (colony.root / "gates").exists() or not list((colony.root / "gates").iterdir())


# --- Lanes, no-overlap, plan_status (spec 0.5.0) ------------------------------------

OK = 'python -c "exit(0)"'


def _make(colony, slug, writes="", lane="", depends_on=""):
    return colony.call("create_task", caste="Queen", slug=slug, objective=f"{slug} done", acceptance=OK,
                       writes=writes, lane=lane, depends_on=depends_on)


def test_T4_O3_a_task_carries_its_lane(colony):
    name = _created(_make(colony, "geometry", writes="art/geometry.py", lane="geometry"))
    assert "lane: geometry" in (colony.root / "tasks/pending" / name).read_text(encoding="utf-8").splitlines()
    assert first_word(_make(colony, "x", writes="a.py", lane="Bad Lane")) == "REFUSED"


@pytest.mark.parametrize("first,second", [
    ("art/logo/", "art/logo/look.png"),
    ("art/logo/look.png", "art/logo/"),
    ("art/logo/look.png", "art/logo/look.png"),
    ("docs/a.md, art/x.py", "art/x.py"),
])
def test_O3_two_tasks_that_can_run_at_once_never_write_the_same_file(colony, first, second):
    _created(_make(colony, "first", writes=first))
    r = _make(colony, "second", writes=second)
    assert first_word(r) == "REFUSED" and "overlap" in r, r
    assert len(list((colony.root / "tasks/pending").glob("*.task"))) == 1


def test_O3_overlap_is_allowed_when_one_task_waits_for_the_other(colony):
    _created(_make(colony, "parts", writes="art/logo/parts/"))
    assert first_word(_make(colony, "combine", writes="art/logo/", depends_on="1")) == "CREATED"


def test_O3_disjoint_writes_and_finished_tasks_do_not_block(colony):
    colony.task("009-old.task", status="done", extra="writes: art/logo/\n")
    assert first_word(_make(colony, "a", writes="art/logo/a.png")) == "CREATED"
    assert first_word(_make(colony, "b", writes="art/logo/b.png")) == "CREATED"
    assert first_word(_make(colony, "docs", writes="art/logo-notes.md")) == "CREATED"      # a prefix of a name is not a folder


def test_O4_plan_status_says_what_can_start_now(colony):
    a = _created(_make(colony, "geometry", writes="art/g.py", lane="geometry"))
    b = _created(_make(colony, "look", writes="art/l.py", lane="look"))
    c = _created(_make(colony, "combine", writes="art/final.png", lane="final", depends_on="1, 2"))
    token_of(colony.call("claim_task", task_file=b))
    r = colony.call("plan_status")
    assert first_word(r) == "PLAN", r
    head = r.splitlines()[0]
    assert "ready=1" in head and "blocked=1" in head and "active=1" in head, head
    lines = r.splitlines()[1:]
    assert any(a in ln and "ready" in ln and "geometry" in ln for ln in lines), r
    assert any(b in ln and "active" in ln and "look" in ln for ln in lines), r
    assert any(c in ln and "blocked" in ln and "001" in ln and "002" in ln for ln in lines), r


# --- O-5: create_plan (spec 0.6.0) --------------------------------------------------

def _t(slug, writes="", depends_on=(), **more):
    return {"slug": slug, "objective": f"{slug} done", "acceptance": OK, "writes": writes,
            "depends_on": list(depends_on), **more}


def _files(colony):
    return sorted(p.name for p in (colony.root / "tasks").rglob("*.task"))


def test_O5_one_call_records_the_decisions_and_creates_every_task(colony):
    # Listed whole-first: ids still follow dependency order, so every task's id is above its dependencies'.
    r = colony.call("create_plan", caste="Queen", decisions=[{"key": "import-graph", "value": "movement never imports state"}],
                    tasks=[_t("cli", "app/cli.py", ["grid", "units"], lane="cli"),
                           _t("grid", "app/grid.py", lane="grid"), _t("units", "app/units.py", lane="units")])
    assert first_word(r) == "CREATED", r
    assert r.splitlines()[0] == "CREATED 3 tasks 1 decisions", r
    assert _files(colony) == ["001-grid.task", "002-units.task", "003-cli.task"], r
    assert {"grid 001-grid.task", "units 002-units.task", "cli 003-cli.task"} <= set(r.splitlines()), r
    cli = (colony.root / "tasks/pending/003-cli.task").read_text(encoding="utf-8").splitlines()
    assert "depends-on: 001, 002" in cli and "lane: cli" in cli, cli
    assert "## KEY: import-graph" in (colony.root / "TRACES.md").read_text(encoding="utf-8")
    led = colony.ledger()
    trace_at = next(i for i, ln in enumerate(led) if " | TRACE | TRACES.md | KEY import-graph" in ln)
    first_task = next(i for i, ln in enumerate(led) if " | DEPOSIT | tasks/pending/" in ln)
    assert trace_at < first_task, led                                  # decisions before any task
    assert sum(" | DEPOSIT | tasks/pending/" in ln for ln in led) == 3
    for name in ("001-grid.task", "002-units.task", "003-cli.task"):   # each one claims and closes as O-3's would
        tok = token_of(colony.call("claim_task", task_file=name))
        assert first_word(colony.call("close_task", task_file=name, token=tok)) == "DONE"


@pytest.mark.parametrize("tasks,decisions,why", [
    ([_t("a", "a.py"), _t("b", "b.py", acceptance="cd x && npm test")], [], "one invalid task"),
    ([_t("a", "a.py"), _t("b", "b.py", ["nope"])], [], "unknown slug in depends_on"),
    ([_t("a", "a.py"), _t("a", "b.py")], [], "repeated slug"),
    ([_t("a", "a.py", ["b"]), _t("b", "b.py", ["a"])], [], "a cycle"),
    ([_t("a", "app/"), _t("b", "app/b.py")], [], "two plan tasks that can run at once overlap"),
    ([_t("a", "a.py")], [{"key": "Bad Key", "value": "x"}], "an invalid decision"),
    ([], [], "no tasks"),
])
def test_O5_all_or_nothing(colony, tasks, decisions, why):
    r = colony.call("create_plan", caste="Queen", tasks=tasks, decisions=decisions)
    assert first_word(r) in {"REFUSED", "CONFLICT"}, f"{why}: {r}"
    assert _files(colony) == [], why
    assert not (colony.root / "TRACES.md").exists() or "## KEY:" not in (colony.root / "TRACES.md").read_text("utf-8")
    assert not [ln for ln in colony.ledger() if " | DEPOSIT | " in ln or " | TRACE | " in ln], why


def test_O5_overlap_is_allowed_along_a_chain_of_dependencies(colony):
    r = colony.call("create_plan", caste="Queen", tasks=[
        _t("parts", "art/logo/parts/"), _t("mid", "art/mid.py", ["parts"]), _t("whole", "art/logo/", ["mid"])])
    assert first_word(r) == "CREATED", r


def test_O5_plans_build_on_existing_tasks_and_respect_their_writes(colony):
    colony.task("004-base.task", extra="writes: core/base.py\n")
    r = colony.call("create_plan", caste="Queen", tasks=[_t("next", "core/", ["4"])])
    assert first_word(r) == "CREATED" and _files(colony)[-1] == "005-next.task", r
    r = colony.call("create_plan", caste="Queen", tasks=[_t("clash", "core/base.py")])
    assert first_word(r) == "REFUSED" and "overlap" in r, r
    assert first_word(colony.call("create_plan", caste="Queen", tasks=[_t("x", "x.py", ["999"])])) == "REFUSED"


def test_O5_an_existing_decision_key_refuses_the_plan(colony):
    colony.call("write_trace", caste="Queen", key="units", value="metres")
    r = colony.call("create_plan", caste="Queen", tasks=[_t("a", "a.py")], decisions=[{"key": "units", "value": "feet"}])
    assert first_word(r) in {"REFUSED", "CONFLICT"}, r
    assert _files(colony) == []


def test_O5_a_plan_task_can_carry_a_new_gate(colony):
    r = colony.call("create_plan", caste="Queen", tasks=[
        {"slug": "guide", "objective": "Write the guide.", "gate_code": "import sys\nsys.exit(0)\n",
         "gate_args": "docs/guide"}])
    assert first_word(r) == "CREATED", r
    assert "acceptance: python gates/check_001.py docs/guide" in \
        (colony.root / "tasks/pending/001-guide.task").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("args", [{"tasks": "not a list"}, {"tasks": [42]}, {"tasks": [{"slug": "a"}]},
                                  {"tasks": [_t("a")], "decisions": ["x"]}, {"tasks": [_t("a")], "caste": "Overlord"}])
def test_O5_M2_malformed_plans_get_a_defined_result(colony, args):
    r = colony.call("create_plan", **{"caste": "Queen", **args})
    assert first_word(r) in {"REFUSED", "CONFLICT"}, r
    assert _files(colony) == []


# --- C: connectors (section 13) -----------------------------------------------------

def _run_record(colony, result):
    import json
    assert first_word(result) == "RAN", result
    m = re.match(r"RAN (runs/\d{8}T\d{4}Z-[a-z0-9-]+-[0-9a-f]{4}\.json) exit=(-?\d+)", result)
    assert m, result
    return json.loads((colony.root / m.group(1)).read_text(encoding="utf-8")), m.group(1), int(m.group(2))


def test_C1_C3_a_run_leaves_a_record_with_version_and_output_hashes(colony):
    colony.connector()
    r = colony.call("run_connector", caste="Forager", connector="fake", args="make_output.py out/a.txt hello",
                    outputs="out/a.txt", task_file="014-a.task")
    rec, path, code = _run_record(colony, r)
    assert code == 0 and rec["exit_code"] == 0 and rec["connector"] == "fake" and rec["version"] == "1.2.3"
    assert rec["argv"][1:] == ["make_output.py", "out/a.txt", "hello"]
    assert rec["task_file"] == "014-a.task" and rec["caste"] == "Forager"
    digest = hashlib.sha256((colony.root / "out/a.txt").read_bytes()).hexdigest()
    assert rec["outputs"] == [{"path": "out/a.txt", "sha256": digest}]
    assert any(ln.endswith(f" | DEPOSIT | {path} | fake 1.2.3 exit 0, 1 of 1 outputs") for ln in colony.ledger()), \
        colony.ledger()


def test_C3_a_failing_run_is_still_recorded(colony):
    colony.connector()
    r = colony.call("run_connector", caste="Forager", connector="fake", args="make_output.py out/b.txt x 3",
                    outputs="out/b.txt, out/never.txt")
    rec, path, code = _run_record(colony, r)
    assert code == 3 and rec["exit_code"] == 3
    assert {o["path"]: o["sha256"] is None for o in rec["outputs"]} == {"out/b.txt": False, "out/never.txt": True}
    assert any(f" | DEPOSIT | {path} | fake 1.2.3 exit 3, 1 of 2 outputs" in ln for ln in colony.ledger())


@pytest.mark.parametrize("args,why", [({"connector": "nope"}, "unknown connector"),
                                      ({"args": "make_output.py a | b"}, "shell syntax"),
                                      ({"connector": "../fake"}, "bad name")])
def test_C3_refusals_write_no_record(colony, args, why):
    colony.connector()
    r = colony.call("run_connector", **{"caste": "Forager", "connector": "fake", "args": "make_output.py x", **args})
    assert first_word(r) == "REFUSED", f"{why}: {r}"
    assert colony.runs() == []


def test_C2_acceptance_commands_resolve_connector_names(colony):
    colony.connector()
    colony.task("014-a.task", acceptance="fake probe.py via-connector")
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    assert first_word(colony.call("close_task", task_file="014-a.task", token=tok)) == "DONE"
    assert colony.probe()["argv"] == ["via-connector"]


@pytest.mark.parametrize("recorded,changed", [("1.2.3", False), ("1.0.0", True)])
def test_C5_version_drift_is_recorded(colony, recorded, changed):
    colony.connector(recorded=recorded)
    rec, _, _ = _run_record(colony, colony.call("run_connector", caste="Forager", connector="fake",
                                                 args="make_output.py out/c.txt"))
    assert rec["version_changed"] is changed


# C-6 (spec 0.8.0): programs that exit 0 after a failure, or never exit (Measured: Godot 4.7.2, Aseprite 1.3.18.3).
PATTERNS = ["error_patterns = ['^SCRIPT ERROR', 'No documents to export']"]


def test_C6_a_clean_run_is_ok_and_its_result_is_unchanged(colony):
    colony.connector(extra=PATTERNS + ["timeout_s = 60"])
    r = colony.call("run_connector", caste="Forager", connector="fake", args="make_output.py out/a.txt",
                    outputs="out/a.txt")
    rec, path, _ = _run_record(colony, r)
    assert r == f"RAN {path} exit=0", r
    assert rec["ok"] is True and rec["errors"] == [] and rec["missing_outputs"] == []
    assert any(ln.endswith(f" | {path} | fake 1.2.3 exit 0, 1 of 1 outputs") for ln in colony.ledger())


def test_C6_an_error_pattern_makes_an_exit_0_run_not_ok(colony):
    colony.connector(extra=PATTERNS)
    r = colony.call("run_connector", caste="Forager", connector="fake", args="say.py SCRIPT ERROR: Nil has no foo")
    rec, path, code = _run_record(colony, r)
    assert code == 0 and rec["ok"] is False, rec
    assert rec["errors"] == ["SCRIPT ERROR: Nil has no foo"], rec["errors"]
    assert r.startswith(f"RAN {path} exit=0 NOT OK"), r
    assert any(ln.endswith(f" | {path} | fake 1.2.3 exit 0, 0 of 0 outputs, NOT OK") for ln in colony.ledger()), \
        colony.ledger()


def test_C6_a_missing_output_makes_a_run_not_ok_without_any_c6_keys(colony):
    colony.connector()
    r = colony.call("run_connector", caste="Forager", connector="fake", args="say.py nothing written",
                    outputs="out/sheet.png")
    rec, path, code = _run_record(colony, r)
    assert code == 0 and rec["ok"] is False and rec["missing_outputs"] == ["out/sheet.png"], rec
    assert r.startswith(f"RAN {path} exit=0 NOT OK") and "out/sheet.png" in r, r


def test_C6_a_nonzero_exit_is_not_ok(colony):
    colony.connector()
    rec, _, code = _run_record(colony, colony.call("run_connector", caste="Forager", connector="fake",
                                                   args="make_output.py out/b.txt x 3", outputs="out/b.txt"))
    assert code == 3 and rec["ok"] is False and rec["missing_outputs"] == []


def test_C6_timeout_s_stops_a_run_that_never_exits(colony):
    colony.connector(extra=["timeout_s = 2"])
    r = colony.call("run_connector", caste="Forager", connector="fake", args="sleepy.py 60")
    rec, _, _ = _run_record(colony, r)
    assert rec["timed_out"] is True and rec["ok"] is False and rec["seconds"] < 30, rec
    assert "NOT OK" in r and "timed out" in r, r


def test_C6_an_acceptance_command_fails_on_an_error_pattern_despite_exit_0(colony):
    colony.connector(extra=PATTERNS)
    colony.task("014-a.task", acceptance="fake say.py SCRIPT ERROR: test_jump failed")
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    r = colony.call("close_task", task_file="014-a.task", token=tok)
    assert first_word(r) == "REFUSED" and "SCRIPT ERROR" in r, r


def test_C6_an_acceptance_command_uses_the_connectors_timeout(colony):
    import time
    colony.connector(extra=["timeout_s = 2"])
    colony.task("014-a.task", acceptance="fake sleepy.py 60")
    tok = token_of(colony.call("claim_task", task_file="014-a.task"))
    t0 = time.monotonic()
    r = colony.call("close_task", task_file="014-a.task", token=tok)
    assert first_word(r) == "REFUSED" and "timed out" in r and time.monotonic() - t0 < 30, r


@pytest.mark.parametrize("bad", ["timeout_s = 0", "timeout_s = 3601", "timeout_s = 'ten'",
                                 "error_patterns = '^ERROR'", "error_patterns = ['(unclosed']"])
def test_C1_C6_a_malformed_c6_key_is_refused(colony, bad):
    colony.connector(extra=[bad])
    r = colony.call("run_connector", caste="Forager", connector="fake", args="say.py hi")
    assert first_word(r) == "REFUSED", f"{bad}: {r}"
    assert colony.runs() == []


# --- K, B: human checkpoints and the board (spec 0.9.0) -----------------------------

CASTES_BY = ["Queen", "Forager", "Nurse", "Guardian", "Human"]


@pytest.mark.parametrize("by", CASTES_BY)
def test_K1_create_task_records_who_does_the_task(colony, by):
    name = _created(colony.call("create_task", caste="Queen", slug="x", objective="x", acceptance=OK, by=by))
    assert f"by: {by}" in (colony.root / "tasks/pending" / name).read_text(encoding="utf-8").splitlines()


def test_K1_without_by_a_task_file_is_unchanged(colony):
    name = _created(colony.call("create_task", caste="Queen", slug="x", objective="x", acceptance=OK))
    assert not [ln for ln in (colony.root / "tasks/pending" / name).read_text(encoding="utf-8").splitlines()
                if ln.startswith("by:")]


def test_K1_create_plan_records_by_for_each_task(colony):
    r = colony.call("create_plan", caste="Queen", tasks=[_t("build", "a.py", by="Forager"),
                                                          _t("review", "", ["build"], by="Human")])
    assert first_word(r) == "CREATED", r
    assert "by: Forager" in (colony.root / "tasks/pending/001-build.task").read_text(encoding="utf-8").splitlines()
    assert "by: Human" in (colony.root / "tasks/pending/002-review.task").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("by", ["Overlord", "human", "Kevin", "SignalSprite", 7])
def test_K1_an_unknown_by_is_refused(colony, by):
    assert first_word(colony.call("create_plan", caste="Queen", tasks=[_t("x", "x.py", by=by)])) == "REFUSED"
    if isinstance(by, str):
        assert first_word(colony.call("create_task", caste="Queen", slug="x", objective="x", acceptance=OK,
                                      by=by)) == "REFUSED"
    assert _files(colony) == []


def test_K1_readers_ignore_a_by_they_do_not_know(colony):
    colony.task("001-a.task", extra="by: Somebody Else\n")
    tok = token_of(colony.call("claim_task", task_file="001-a.task"))
    assert first_word(colony.call("close_task", task_file="001-a.task", token=tok)) == "DONE"


def test_K2_closing_a_checkpoint_records_that_the_human_approved(colony):
    r = colony.call("create_plan", caste="Queen", tasks=[_t("build", "a.py"), _t("look", "", ["build"], by="Human")])
    assert first_word(r) == "CREATED", r
    for name in ("001-build.task", "002-look.task"):
        tok = token_of(colony.call("claim_task", task_file=name, caste="Queen"))
        assert first_word(colony.call("close_task", task_file=name, token=tok, caste="Queen")) == "DONE"
    done = colony.signals("DONE")
    look = [ln for ln in done if "tasks/done/002-look.task" in ln]
    build = [ln for ln in done if "tasks/done/001-build.task" in ln]
    assert len(look) == 1 and "human approved" in look[0], done
    assert len(build) == 1 and "human approved" not in build[0], done


def _snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None) for p in root.rglob("*")}


def _board(colony, tasks, decisions=None, **more):
    args = {"tasks": tasks, **more}
    if decisions is not None:
        args["decisions"] = decisions
    r = colony.call("plan_board", **args)
    assert first_word(r) in {"BOARD", "REFUSED"}, r
    return r


def test_B1_plan_board_reads_and_never_writes_the_substrate(colony):
    colony.task("004-base.task", extra="writes: core/base.py\n")
    colony.call("write_trace", caste="Queen", key="units", value="metres")
    before = _snapshot(colony.root)
    r = _board(colony, [_t("a", "a.py", ["4"]), _t("b", "core/base.py")], [{"key": "units", "value": "feet"}])
    assert first_word(r) == "BOARD", r
    assert _snapshot(colony.root) == before


@pytest.mark.parametrize("tasks,decisions,why", [
    ([_t("a", "a.py"), _t("b", "b.py", acceptance="cd x && npm test")], [], "one invalid task"),
    ([_t("a", "a.py"), _t("b", "b.py", ["nope"])], [], "unknown slug in depends_on"),
    ([_t("a", "a.py"), _t("a", "b.py")], [], "repeated slug"),
    ([_t("a", "a.py", ["b"]), _t("b", "b.py", ["a"])], [], "a cycle"),
    ([_t("a", "app/"), _t("b", "app/b.py")], [], "two plan tasks that can run at once overlap"),
    ([_t("a", "a.py")], [{"key": "Bad Key", "value": "x"}], "an invalid decision"),
    ([_t("a", "a.py", by="Overlord")], [], "an unknown by"),
    ([], [], "no tasks"),
])
def test_B1_plan_board_returns_the_refusal_create_plan_would_give(colony, tasks, decisions, why):
    board = _board(colony, tasks, decisions)
    refused = colony.call("create_plan", caste="Queen", tasks=tasks, decisions=decisions)
    assert first_word(refused) in {"REFUSED", "CONFLICT"}, f"{why}: {refused}"
    assert refused.splitlines()[0] in board.splitlines(), f"{why}: {board}"


def test_B1_a_plan_create_plan_accepts_has_no_refusal(colony):
    tasks = [_t("grid", "app/grid.py"), _t("units", "app/units.py"), _t("cli", "app/cli.py", ["grid", "units"])]
    board = _board(colony, tasks)
    assert first_word(board) == "BOARD", board
    assert not [ln for ln in board.splitlines() if first_word(ln) in {"REFUSED", "CONFLICT"}], board
    assert first_word(colony.call("create_plan", caste="Queen", tasks=tasks)) == "CREATED"


def _chain(*by):
    out, prev = [], []
    for i, who in enumerate(by):
        slug = f"s{i}"
        out.append(_t(slug, f"f{i}.py", prev, **({"by": who} if who else {})))
        prev = [slug]
    return out


def test_B1_run_is_the_longest_chain_of_agent_tasks_without_a_human(colony):
    lines = _board(colony, _chain("Forager", None, "Nurse", "Queen")).splitlines()
    assert "longest_run=4" in lines[0] and "limit=3" in lines[0], lines[0]
    assert any(ln.startswith("RUN 4 > 3") for ln in lines), lines
    assert any(ln.startswith("NO-HUMAN") for ln in lines), lines
    lines = _board(colony, _chain("Forager", None, "Human", "Nurse", "Queen")).splitlines()
    assert "longest_run=2" in lines[0], lines[0]
    assert not any(ln.startswith(("RUN ", "NO-HUMAN")) for ln in lines), lines


def test_B1_the_limit_is_the_callers(colony):
    lines = _board(colony, _chain("Forager", None, "Nurse", "Queen"), limit=4).splitlines()
    assert "limit=4" in lines[0] and not any(ln.startswith("RUN ") for ln in lines), lines
    lines = _board(colony, _chain("Forager", "Forager"), limit=1).splitlines()
    assert any(ln.startswith("RUN 2 > 1") for ln in lines), lines


@pytest.mark.parametrize("research_by,verify_by,flagged", [
    ("Nurse", "Guardian", False),
    ("Nurse", "Nurse", True),
    ("Nurse", None, True),
    ("Guardian", "Guardian", True),
    ("Nurse", "Forager", True),
])
def test_B1_verify_by_flags_a_verify_task_not_done_by_a_different_guardian(colony, research_by, verify_by, flagged):
    tasks = [_t("research", "research/x/", by=research_by, lane="research"),
             _t("check-research", "", ["research"], lane="verify", **({"by": verify_by} if verify_by else {})),
             _t("human-ok", "", ["check-research"], by="Human")]
    lines = _board(colony, tasks).splitlines()
    assert any(ln.startswith("VERIFY-BY check-research") for ln in lines) is flagged, lines


def test_B1_the_board_draws_the_plan_as_mermaid(colony):
    tasks = [_t("grid", "app/grid.py", by="Forager"), _t("units", "app/units.py"),
             _t("cli", "app/cli.py", ["grid", "units"]), _t("look", "", ["cli"], by="Human")]
    lines = _board(colony, tasks).splitlines()
    start = lines.index("flowchart LR")
    mermaid = "\n".join(lines[start:])
    for slug in ("grid", "units", "cli", "look"):
        assert slug in mermaid, mermaid
    assert mermaid.count("-->") == 3, mermaid


@pytest.mark.parametrize("args", [{"tasks": "not a list"}, {"tasks": [42]}, {"tasks": [_t("a")], "limit": 0},
                                  {"tasks": [_t("a")], "limit": "three"}, {"tasks": [_t("a")], "decisions": ["x"]}])
def test_B1_M2_malformed_input_gets_a_defined_result(colony, args):
    before = _snapshot(colony.root)
    r = colony.call("plan_board", **args)
    assert first_word(r) in {"BOARD", "REFUSED"}, r
    assert _snapshot(colony.root) == before


# --- M: tool interface -------------------------------------------------------------

@pytest.mark.parametrize("tool,args", [
    ("claim_task", {"task_file": ""}),
    ("claim_task", {"task_file": "x" * 5000}),
    ("claim_task", {"task_file": "014-a.task", "caste": "Nobody"}),
    ("claim_task", {"task_file": "014-a.task", "lease_minutes": 0}),
    ("renew_claim", {"task_file": "../../etc/passwd", "token": "x"}),
    ("close_task", {"task_file": "014-a.task", "token": "\u0000"}),
    ("resume", {"caste": "Overlord"}),
    ("append_ledger", {"caste": "", "signal": "", "path": "", "note": ""}),
    ("write_trace", {"caste": "Queen", "key": "Bad Key", "value": "x"}),
    ("write_trace", {"caste": "Queen", "key": "ok-key", "value": "   "}),
])
def test_M1_M2_every_input_gets_a_defined_result(colony, tool, args):
    r = colony.call(tool, **args)
    assert first_word(r) in RESULT_WORDS, r
    assert first_word(r) in {"REFUSED", "CONFLICT"}, r
