"""Hidden integration tests for bench/tally/SPEC.md, through `python -m tally run SCRIPT`. Worked out by hand."""
import json


def test_set_print_raw_show(cli):
    code, out, _ = cli("set A1 1\nset B1 hello\nset A2 =a1 * 20\nprint A2\nraw A2\nshow A1:B2\n")
    assert code == 0
    assert out == "20\n=A1*20\n  | A  | B\n--+----+------\n1 |  1 | hello\n2 | 20 |"


def test_input_is_kept_exactly_and_empty_input_clears(cli):
    code, out, _ = cli("set A1  two spaces\nraw A1\nset A1 \nprint A1\nraw A1\nprint B1\nset Z1 end\nprint Z1\n")
    assert code == 0
    assert out.split("\n") == [" two spaces", "", "", "", "end"]


def test_failed_commands_report_their_line_and_the_script_goes_on(cli):
    script = "# a comment\n\nset A1 =1+\nfrobnicate\nprint A1\nset A2 3\nprint A2\nprint Q0\n"
    code, out, _ = cli(script)
    lines = out.split("\n")
    assert code == 1
    assert lines[0].startswith("error line 3: ") and lines[1].startswith("error line 4: ")
    assert lines[2] == "" and lines[3] == "3" and lines[4].startswith("error line 8: ")
    assert len(lines) == 5


def test_recalc(cli):
    script = "set A1 1\nset B1 =A1+1\nset C1 =B1+A1\nset A2 =C1*2\nset B2 =5\nset A1 2\nrecalc\nprint A2\nset B2 7\nrecalc\n"
    code, out, _ = cli(script)
    assert code == 0
    assert out == "recalc: Sheet1!B1 Sheet1!C1 Sheet1!A2\n10\nrecalc:"


def test_cycles_show_as_errors(cli):
    code, out, _ = cli("set A1 =B1\nset B1 =A1*2\nset C1 =IFERROR(A1,\"loop\")\nprint A1\nprint C1\nset B1 4\nprint A1\n")
    assert code == 0
    assert out == "#CYCLE!\nloop\n4"


def test_structural_edits(cli):
    script = ("set A1 1\nset A2 2\nset A3 3\nset A4 =SUM(A1:A3)\nset B1 =A3*2\n"
              "insert-rows Sheet1 2 1\nraw A5\nraw B1\nprint A5\n"
              "delete-rows Sheet1 4 1\nraw A4\nraw B1\nprint A4\n"
              "insert-cols Sheet1 A 1\nraw C1\nprint B4\ndelete-cols Sheet1 B 1\nraw B1\n")
    code, out, _ = cli(script)
    assert code == 0
    assert out.split("\n") == ["=SUM(A1:A4)", "=A4*2", "6", "=SUM(A1:A3)", "=#REF!*2", "3", "=#REF!*2", "3", "=#REF!*2"]


def test_fill(cli):
    script = "set B1 1\nset B2 2\nset B3 3\nset C1 10\nset A1 =B1*$C$1\nfill A1 A2:A3\nraw A3\nprint A3\nshow A1:A3\n"
    code, out, _ = cli(script)
    assert code == 0
    assert out == "=B3*$C$1\n30\n  | A\n--+---\n1 | 10\n2 | 20\n3 | 30"


def test_sheets_rename_and_names(cli):
    script = ("sheet Data\nset Data!A1 7\nset Data!A2 8\nname Stock Data!$A$1:$A$2\nset A1 =SUM(Stock)*2\n"
              "set A2 =Data!A1\nrename Data Input\nraw A2\nprint A1\nset Input!A2 10\nprint A1\nsheet Data\n"
              "sheet Input\nprint Nope!A1\n")
    code, out, _ = cli(script)
    lines = out.split("\n")
    assert code == 1
    assert lines[:3] == ["=Input!A1", "30", "34"]
    assert lines[3].startswith("error line 13: ") and lines[4].startswith("error line 14: ") and len(lines) == 5


def test_save_and_load(cli):
    code, out, _ = cli("set A1 2\nset B1 =A1^2\nsheet Two\nset Two!A1 '007\nname Base Sheet1!$A$1\nsave book.json\n")
    assert code == 0 and out == ""
    data = json.loads((cli.dir / "book.json").read_text(encoding="utf-8"))
    assert data["format"] == "tally" and data["version"] == 1 and data["names"] == {"Base": "Sheet1!$A$1"}
    assert data["sheets"][0] == {"name": "Sheet1", "cells": {"A1": "2", "B1": "=A1^2"}}
    code, out, _ = cli("load book.json\nprint B1\nprint Two!A1\nset A1 5\nprint B1\nload missing.json\nprint B1\n")
    lines = out.split("\n")
    assert code == 1
    assert lines[:3] == ["4", "007", "25"] and lines[3].startswith("error line 6: ") and lines[4] == "25"


def test_csv_export_and_import(cli):
    script = 'set A1 1\nset B1 x,y\nset A2 =A1*2\nset C3 say "hi"\nexport Sheet1 out.csv\nsheet In\nimport In in.csv\nprint In!B1\nprint In!A2\n'
    code, out, _ = cli(script, files={"in.csv": "4,=A1*3\n,ok\n"})
    assert code == 0
    assert out == "12"
    assert (cli.dir / "out.csv").read_text(encoding="utf-8") == '1,"x,y",\n2,,\n,,"say ""hi"""\n'


def test_a_missing_script_exits_2(cli, tmp_path):
    import os
    import subprocess
    import sys
    from conftest import IMPL
    r = subprocess.run([sys.executable, "-m", "tally", "run", "nope.txt"], cwd=tmp_path, capture_output=True,
                       text=True, env={**os.environ, "PYTHONPATH": IMPL}, timeout=60)
    assert r.returncode == 2 and r.stderr.strip() != ""


def test_budget_end_to_end(cli):
    script = """# a small budget
set A1 Item
set B1 Cost
set C1 Qty
set D1 Total
set A2 Paint
set B2 12.5
set C2 4
set A3 Brushes
set B3 3.25
set C3 2
set D2 =B2*C2
fill D2 D3:D3
set A4 Total
set D4 =SUM(D2:D3)
set E2 =IF(D2>$D$4/2,"big","small")
fill E2 E3:E3
insert-rows Sheet1 4 1
set A4 Tape
set B4 2
set C4 =COUNTIF(A2:A4,"*")
set D4 =B4*C4
raw D5
print D5
show A1:E5
"""
    code, out, _ = cli(script)
    assert code == 0
    assert out == ("=SUM(D2:D3)\n56.5\n"
                   "  | A       | B    | C   | D     | E\n"
                   "--+---------+------+-----+-------+------\n"
                   "1 | Item    | Cost | Qty | Total |\n"
                   "2 | Paint   | 12.5 |   4 |    50 | big\n"
                   "3 | Brushes | 3.25 |   2 |   6.5 | small\n"
                   "4 | Tape    |    2 |   0 |     0 |\n"
                   "5 | Total   |      |     |  56.5 |")
