"""Hidden unit tests for bench/tally/SPEC.md. Expected values were worked out by hand from the spec."""
import json

import pytest

from tally import csvio, ops, store
from tally.fill import fill
from tally.parser import FormulaError, parse, to_formula
from tally.refs import (CellRef, RangeRef, col_to_index, format_range, format_ref, index_to_col, parse_range,
                        parse_ref, range_cells)
from tally.render import render
from tally.values import BLANK, CellError, display, format_number, parse_number, to_bool, to_number, to_text


def E(code):
    return CellError(code)


def calc(wb, formula, cells=None):
    for address, raw in (cells or {}).items():
        wb.set(address, raw)
    wb.set("Z99", formula)
    return wb.value("Z99")


def same(got, want):
    if isinstance(want, float) and isinstance(got, float):
        return got == pytest.approx(want)
    return type(got) is type(want) and got == want


# --- 1. values ----------------------------------------------------------------------

@pytest.mark.parametrize("x,text", [(3.0, "3"), (-0.0, "0"), (1 / 3, "0.3333333333"), (1e20, "1e+20"),
                                    (0.1 + 0.2, "0.3"), (2.5, "2.5"), (-12.0, "-12"), (1e15, "1e+15")])
def test_format_number(x, text):
    assert format_number(x) == text


@pytest.mark.parametrize("text,want", [("12", 12.0), (" 12.5 ", 12.5), (".5", 0.5), ("12.", 12.0), ("-3e2", -300.0),
                                       ("+1E-2", 0.01), ("1,000", None), ("$5", None), ("inf", None), ("nan", None),
                                       ("", None), ("1e", None), ("--1", None)])
def test_parse_number(text, want):
    assert parse_number(text) == want


def test_conversions_and_display():
    assert to_number("abc") == E("#VALUE!") and to_number(True) == 1.0 and to_number(BLANK) == 0.0
    assert to_number(" 4 ") == 4.0 and to_number(E("#N/A")) == E("#N/A")
    assert to_text(2.0) == "2" and to_text(False) == "FALSE" and to_text(BLANK) == ""
    assert to_bool("true") is True and to_bool("yes") == E("#VALUE!") and to_bool(0.0) is False
    assert to_bool(BLANK) is False and to_bool(-2.0) is True
    assert display(E("#N/A")) == "#N/A" and display(True) == "TRUE" and display(BLANK) == "" and display(7.0) == "7"
    assert repr(BLANK) == "BLANK" and E("#REF!") == CellError("#REF!")


# --- 2. references ------------------------------------------------------------------

@pytest.mark.parametrize("letters,index", [("A", 0), ("Z", 25), ("AA", 26), ("AZ", 51), ("BA", 52), ("ZZ", 701)])
def test_columns(letters, index):
    assert col_to_index(letters) == index and index_to_col(index) == letters


@pytest.mark.parametrize("bad", ["AAA", "a", "", "A1"])
def test_bad_column_letters(bad):
    with pytest.raises(ValueError):
        col_to_index(bad)


@pytest.mark.parametrize("bad", [702, -1])
def test_bad_column_index(bad):
    with pytest.raises(ValueError):
        index_to_col(bad)


def test_parse_and_format_ref():
    assert parse_ref("$b$7") == CellRef(None, 1, 6, True, True)
    assert parse_ref("Sheet2!C$10") == CellRef("Sheet2", 2, 9, False, True)
    assert format_ref(parse_ref("$b$7")) == "$B$7" and format_ref(parse_ref("Sheet2!C$10")) == "Sheet2!C$10"
    assert parse_ref("zz9999") == CellRef(None, 701, 9998, False, False)


@pytest.mark.parametrize("bad", ["A0", "A10000", "AAA1", "1A", "A1B", "Sheet 2!A1", "A", "$$A1", "2x!A1"])
def test_bad_refs(bad):
    with pytest.raises(ValueError):
        parse_ref(bad)


def test_ranges():
    r = parse_range("Sheet2!A1:$B$3")
    assert r == RangeRef(CellRef("Sheet2", 0, 0, False, False), CellRef("Sheet2", 1, 2, True, True))
    assert format_range(r) == "Sheet2!A1:$B$3"
    assert range_cells(parse_range("B2:A1")) == [(0, 0), (1, 0), (0, 1), (1, 1)]
    with pytest.raises(ValueError):
        parse_range("A1:Sheet2!B3")


# --- 3. formulas --------------------------------------------------------------------

@pytest.mark.parametrize("text,canonical", [
    ("1+2*3", "1+2*3"), ("(1+2)*3", "(1+2)*3"), ("1-(2-3)", "1-(2-3)"), ("(1-2)-3", "1-2-3"),
    ("-(1+2)", "-(1+2)"), ("(1+2)%", "(1+2)%"), ("(-2)^2", "-2^2"), ("2^(3^2)", "2^(3^2)"),
    ("sum( a1 : b2 , 3 )", "SUM(A1:B2,3)"), ('"say ""hi"""', '"say ""hi"""'), ("a1 <> 3", "A1<>3"),
    ("true", "TRUE"), ("#REF!+1", "#REF!+1"), ("1.50", "1.5"), (".5e1", "5"), ("Sales*2", "Sales*2"),
    ("sheet2!a1", "sheet2!A1"), ('$a$1&"x"', '$A$1&"x"'), ("-A1%", "-A1%"), ("2^-1", "2^-1"),
    ("(1&2)=3", "1&2=3"), ("1&(2=3)", "1&(2=3)"), ("now()", "NOW()"), ("((A1))", "A1"),
])
def test_canonical_form(text, canonical):
    assert to_formula(parse(text)) == canonical


@pytest.mark.parametrize("bad", ["1+", "(1", "SUM(1,,2)", "A1:3", "A1:Sheet2!B2", "@", '"abc', "1 2", "Sheet2!",
                                 "#ref!", ":", "SUM(1", ""])
def test_formula_errors(bad):
    assert issubclass(FormulaError, ValueError)
    with pytest.raises(FormulaError):
        parse(bad)


# --- 5.1 input and storage ----------------------------------------------------------

@pytest.mark.parametrize("raw,value", [("42", 42.0), ("  7 ", 7.0), ("true", True), ("'007", "007"), ("#N/A", "#N/A"),
                                       ("hello world ", "hello world "), ("TRUE ", "TRUE "), ("'", ""),
                                       ("-1.5e1", -15.0)])
def test_input_kinds(wb, raw, value):
    wb.set("A1", raw)
    assert same(wb.value("A1"), value) and wb.raw("A1") == raw


def test_blank_and_canonical_storage(wb):
    wb.set("A1", "5")
    wb.set("A1", "")
    assert wb.value("A1") is BLANK and wb.raw("A1") == "" and wb.display("A1") == ""
    wb.set("A2", "= sum( b1 : b3 ) * 2")
    assert wb.raw("A2") == "=SUM(B1:B3)*2"


def test_a_bad_formula_leaves_the_cell_unchanged(wb):
    wb.set("A1", "5")
    with pytest.raises(FormulaError):
        wb.set("A1", "=1+")
    assert wb.value("A1") == 5.0 and wb.raw("A1") == "5"


@pytest.mark.parametrize("bad", ["$A$1", "A0", "Nope!A1", "hello"])
def test_bad_addresses(wb, bad):
    with pytest.raises(ValueError):
        wb.set(bad, "1")


# --- 4.1 evaluation -----------------------------------------------------------------

@pytest.mark.parametrize("formula,want", [
    ("=A9", 0.0), ('=A9&"x"', "x"), ('=A9=""', True), ("=A9=0", True), ("=A9=FALSE", True),
    ("=1+2*3", 7.0), ("=2^3^2", 64.0), ("=-2^2", 4.0), ("=50%", 0.5), ("=-50%", -0.5), ('="3"+1', 4.0),
    ('="x"+1', E("#VALUE!")), ("=1/0", E("#DIV/0!")), ("=0^-1", E("#DIV/0!")), ("=(-8)^(1/3)", E("#NUM!")),
    ("=10^400", E("#NUM!")), ("=TRUE+1", 2.0), ("=1&2", "12"), ("=1=1.0", True), ("=2.5&TRUE", "2.5TRUE"),
    ('="abc"="ABC"', True), ('=1<"a"', True), ('="z"<TRUE', True), ('=2>"10"', False), ("=A9<1", True),
    ('="b">"A"', True), ("=FALSE<TRUE", True), ('="1"=1', False),
    ("=Nope", E("#NAME?")), ("=NOFUNC(1)", E("#NAME?")), ("=ABS(1,2)", E("#VALUE!")), ("=Sheet9!A1", E("#REF!")),
    ("=A1:A3", E("#VALUE!")), ("=A1:A3+1", E("#VALUE!")), ("=#N/A", E("#N/A")), ("=#N/A&(1/0)", E("#N/A")),
])
def test_evaluation(wb, formula, want):
    assert same(calc(wb, formula), want)


def test_errors_propagate_left_to_right(wb):
    wb.set("A1", "=1/0")
    wb.set("B1", "=A1+NOFUNC()")
    wb.set("C1", "=NOFUNC()+A1")
    assert wb.value("B1") == E("#DIV/0!") and wb.value("C1") == E("#NAME?")
    assert wb.display("B1") == "#DIV/0!"


def test_display_of_results(wb):
    wb.set("A1", "=0.1+0.2")
    wb.set("A2", "=1/3")
    wb.set("A3", "=2*3")
    assert (wb.display("A1"), wb.display("A2"), wb.display("A3")) == ("0.3", "0.3333333333", "6")
    assert isinstance(wb.value("A3"), float)


# --- 4.3 functions ------------------------------------------------------------------

MATH = {"A1": "1", "A2": "2", "A3": "x", "A4": "TRUE", "A6": "'3", "A7": "4", "B1": "=1/0"}


@pytest.mark.parametrize("formula,want", [
    ("=SUM(A1:A7)", 7.0), ('=SUM(A1,"3",TRUE)', 5.0), ('=SUM(A1:A7,"x")', E("#VALUE!")), ("=SUM()", E("#VALUE!")),
    ("=SUM(A3)", 0.0), ("=SUM(A1:B1)", E("#DIV/0!")), ("=PRODUCT(A1:A7)", 8.0), ("=PRODUCT(A3)", 0.0),
    ("=MIN(A1:A7)", 1.0), ("=MAX(A1:A7)", 4.0), ("=MAX(A3:A4)", 0.0), ("=AVERAGE(A1:A7)", 7 / 3),
    ("=AVERAGE(A3)", E("#DIV/0!")), ("=MEDIAN(A1:A7)", 2.0), ("=MEDIAN(A1,A2,A7,10)", 3.0), ("=MEDIAN(A3)", E("#NUM!")),
    ("=ABS(-3)", 3.0), ("=INT(-2.5)", -3.0), ("=SQRT(16)", 4.0), ("=SQRT(-1)", E("#NUM!")),
    ("=ABS(A1:A2)", E("#VALUE!")), ("=ABS(A3)", E("#VALUE!")), ("=ABS(A5)", 0.0),
    ("=ROUND(2.675,2)", 2.68), ("=ROUND(-2.5)", -3.0), ("=ROUND(1234,-2)", 1200.0), ("=ROUND(2.5)", 3.0),
    ("=ROUND(1.005,2)", 1.01), ("=ROUND(3.14159,2.9)", 3.14), ("=MOD(-7,3)", 2.0), ("=MOD(7,-3)", -2.0),
    ("=MOD(5,0)", E("#DIV/0!")), ("=MOD(5.5,2)", 1.5), ("=POWER(2,10)", 1024.0), ("=POWER(0,-1)", E("#DIV/0!")),
])
def test_math(wb, formula, want):
    assert same(calc(wb, formula, MATH), want)


COUNTS = {"A1": "1", "A2": "x", "A3": "TRUE", "A5": "=1/0", "A6": "'", "A7": "3"}


@pytest.mark.parametrize("formula,want", [
    ("=COUNT(A1:A7)", 2.0), ('=COUNT(1,"2","x",TRUE,1/0)', 3.0), ("=COUNTA(A1:A7)", 6.0), ('=COUNTA(1,"",A4)', 2.0),
    ("=COUNTBLANK(A1:A7)", E("#DIV/0!")), ("=COUNTBLANK(A1:A4)", 1.0),
])
def test_counting(wb, formula, want):
    assert same(calc(wb, formula, COUNTS), want)


CRIT = {"B1": "5", "B2": "10", "B3": "apple", "B4": "Apple", "B6": "15", "B7": "'10", "B8": "TRUE",
        **{f"C{i}": str(i) for i in range(1, 9)}}


@pytest.mark.parametrize("formula,want", [
    ("=COUNTIF(B1:B8,10)", 1.0), ('=COUNTIF(B1:B8,">5")', 2.0), ('=COUNTIF(B1:B8,">=5")', 3.0),
    ('=COUNTIF(B1:B8,"<>10")', 7.0), ('=COUNTIF(B1:B8,"apple")', 2.0), ('=COUNTIF(B1:B8,"=APPLE")', 2.0),
    ('=COUNTIF(B1:B8,"<>apple")', 6.0), ('=COUNTIF(B1:B8,"<b")', 3.0), ("=COUNTIF(B1:B8,TRUE)", 1.0),
    ('=COUNTIF(B1:B8,"")', 1.0), ('=COUNTIF(B1:B8,"=10")', 1.0), ('=COUNTIF(B1:B8,"10")', 1.0),
    ("=COUNTIF(B1:B8,1/0)", E("#DIV/0!")),
    ('=SUMIF(B1:B8,">5",C1:C8)', 8.0), ('=SUMIF(B1:B8,">5")', 25.0), ('=SUMIF(B1:B8,"apple",C1:C8)', 7.0),
    ('=SUMIF(B1:B8,">5",C1:C7)', E("#VALUE!")),
])
def test_criteria(wb, formula, want):
    assert same(calc(wb, formula, CRIT), want)


LOGIC = {"A1": "x", "A2": "0", "A3": "TRUE"}


@pytest.mark.parametrize("formula,want", [
    ('=IF(1>2,"a","b")', "b"), ('=IF(0,"a")', False), ('=IF("x",1,2)', E("#VALUE!")), ("=IF(TRUE,1,1/0)", 1.0),
    ("=IF(FALSE,NOFUNC(),2)", 2.0), ("=IF(TRUE,A9)", 0.0), ("=AND(TRUE,1)", True), ("=AND(TRUE,0)", False),
    ("=OR(A1:A3)", True), ("=AND(A1:A3)", False), ("=AND(A1)", E("#VALUE!")), ('=AND("TRUE",1)', True),
    ("=OR(1/0,TRUE)", E("#DIV/0!")), ("=NOT(0)", True), ('=IFERROR(1/0,"bad")', "bad"), ("=IFERROR(5,1/0)", 5.0),
    ("=IFERROR(NOFUNC(),A9)", 0.0),
])
def test_logic(wb, formula, want):
    assert same(calc(wb, formula, LOGIC), want)


TEXT = {"A1": "x", "C1": "2"}


@pytest.mark.parametrize("formula,want", [
    ('=LEN("héllo")', 5.0), ('=UPPER("abc")', "ABC"), ('=LOWER("ABC")', "abc"), ('=TRIM("  a   b  ")', "a b"),
    ('=LEFT("hello")', "h"), ('=LEFT("hello",3)', "hel"), ('=LEFT("hi",10)', "hi"), ('=LEFT("hi",-1)', E("#VALUE!")),
    ('=RIGHT("hello",2)', "lo"), ('=RIGHT("hello",0)', ""), ('=MID("hello",2,3)', "ell"),
    ('=MID("hello",0,1)', E("#VALUE!")), ('=MID("hello",4,10)', "lo"), ('=CONCAT("a",1,TRUE)', "a1TRUE"),
    ("=CONCAT(A1:C1)", "x2"), ('=FIND("l","hello")', 3.0), ('=FIND("l","hello",4)', 4.0),
    ('=FIND("L","hello")', E("#VALUE!")), ('=FIND("o","hello",7)', E("#VALUE!")), ('=FIND("","abc",4)', 4.0),
    ('=SUBSTITUTE("a-b-c","-","+")', "a+b+c"), ('=SUBSTITUTE("abc","","x")', "abc"), ("=LEN(12.50)", 4.0),
    ('=CONCAT("a",1/0)', E("#DIV/0!")), ('=LEFT("hello",2.9)', "he"),
])
def test_text(wb, formula, want):
    assert same(calc(wb, formula, TEXT), want)


TABLE = {"D1": "apple", "E1": "1", "F1": "red", "D2": "Banana", "E2": "2", "D3": "3", "E3": "30", "F3": "x"}


@pytest.mark.parametrize("formula,want", [
    ('=VLOOKUP("banana",D1:F3,2)', 2.0), ('=VLOOKUP("banana",D1:F3,3)', 0.0), ("=VLOOKUP(3,D1:F3,3)", "x"),
    ('=VLOOKUP("3",D1:F3,2)', E("#N/A")), ('=VLOOKUP("kiwi",D1:F3,2)', E("#N/A")),
    ('=VLOOKUP("apple",D1:F3,4)', E("#REF!")), ('=VLOOKUP("apple",D1:F3,0)', E("#VALUE!")),
    ("=VLOOKUP(G9,D1:F3,2)", E("#N/A")),
    ("=INDEX(D1:F3,2,1)", "Banana"), ("=INDEX(D1:F3,3)", 3.0), ("=INDEX(D1:F1,3)", "red"),
    ("=INDEX(D1:F3,4,1)", E("#REF!")), ("=INDEX(D1:F3,0,1)", E("#REF!")), ("=INDEX(D1:F3,2,3)", 0.0),
    ('=MATCH("BANANA",D1:D3)', 2.0), ("=MATCH(30,E1:E3)", 3.0), ('=MATCH("zzz",D1:D3)', E("#N/A")),
    ("=MATCH(1,D1:E3)", E("#N/A")), ("=MATCH(2,E1:G1)", E("#N/A")),
])
def test_lookup(wb, formula, want):
    assert same(calc(wb, formula, TABLE), want)


# --- 5. workbook: names and sheets --------------------------------------------------

def test_names(wb):
    for a, v in TABLE.items():
        wb.set(a, v)
    wb.define_name("Prices", "Sheet1!$E$1:$E$3")
    wb.set("A1", "=SUM(Prices)")
    wb.set("A2", "=SUM(PRICES)+1")
    wb.set("A3", "=Prices+1")
    assert wb.value("A1") == 33.0 and wb.value("A2") == 34.0 and wb.value("A3") == E("#VALUE!")
    wb.define_name("prices", "Sheet1!E1:E2")
    assert wb.value("A1") == 3.0
    assert wb.last_recalc() == ["Sheet1!A1", "Sheet1!A2", "Sheet1!A3"]
    wb.set("B1", "0.5")
    wb.define_name("Rate", "Sheet1!$B$1")
    wb.set("A4", "=Rate*10")
    assert wb.value("A4") == 5.0


@pytest.mark.parametrize("name,target", [("A1", "Sheet1!B1"), ("TRUE", "Sheet1!B1"), ("x", "B1"), ("2x", "Sheet1!B1"),
                                         ("ok", "Sheet1!B1+1"), ("zz12", "Sheet1!B1")])
def test_bad_names(wb, name, target):
    with pytest.raises(ValueError):
        wb.define_name(name, target)


def test_sheets(wb):
    wb.add_sheet("Data")
    assert wb.sheet_names() == ["Sheet1", "Data"]
    wb.set("Data!A1", "7")
    wb.set("A1", "=Data!A1*2")
    wb.define_name("D", "Data!$A$1")
    wb.set("A3", "=D+1")
    assert wb.value("A1") == 14.0
    wb.set("A2", "=Later!A1")
    assert wb.value("A2") == E("#REF!")
    wb.add_sheet("Later")
    assert wb.value("A2") == 0.0
    for bad in ("Data", "1x", "a b"):
        with pytest.raises(ValueError):
            wb.add_sheet(bad)
    wb.rename_sheet("Data", "Input")
    assert wb.sheet_names() == ["Sheet1", "Input", "Later"]
    assert wb.raw("A1") == "=Input!A1*2" and wb.value("A1") == 14.0 and wb.value("A3") == 8.0
    assert wb.value("Input!A1") == 7.0
    with pytest.raises(ValueError):
        wb.rename_sheet("Input", "Later")
    with pytest.raises(ValueError):
        wb.rename_sheet("Missing", "Other")


# --- 5.2 recalculation --------------------------------------------------------------

def test_recalc_lists_dependents_in_order(wb):
    for a, v in {"A1": "1", "B1": "=A1+1", "C1": "=B1+A1", "A2": "=C1*2", "B2": "=5"}.items():
        wb.set(a, v)
    wb.set("A1", "2")
    assert wb.last_recalc() == ["Sheet1!B1", "Sheet1!C1", "Sheet1!A2"]
    assert wb.value("A2") == 10.0
    wb.set("D1", "=A1*3")
    assert wb.last_recalc() == ["Sheet1!D1"]


def test_recalc_ties_go_by_sheet_row_column(wb):
    for a, v in {"A1": "1", "C1": "=A1", "B2": "=A1", "A3": "=A1"}.items():
        wb.set(a, v)
    wb.set("A1", "2")
    assert wb.last_recalc() == ["Sheet1!C1", "Sheet1!B2", "Sheet1!A3"]
    wb.set("C1", "9")
    assert wb.last_recalc() == []
    wb.add_sheet("Data")
    wb.set("Data!A1", "=Sheet1!Z9")
    wb.set("B5", "=Sheet1!Z9")
    wb.set("Z9", "1")
    assert wb.last_recalc() == ["Sheet1!B5", "Data!A1"]


def test_recalc_order_counts_only_listed_cells(wb):
    for a, v in {"P100": "=1", "B50": "=C1", "A1": "=C1+P100"}.items():
        wb.set(a, v)
    wb.set("C1", "5")
    assert wb.last_recalc() == ["Sheet1!A1", "Sheet1!B50"]
    assert wb.value("A1") == 6.0


def test_cycles(wb):
    for a, v in {"A1": "=B1", "B1": "=A1", "C1": "=A1+1", "D1": "=IFERROR(A1,5)", "E1": "=E1+1",
                 "F1": "=IF(TRUE,1,F1)"}.items():
        wb.set(a, v)
    for a in ("A1", "B1", "C1", "E1", "F1"):
        assert wb.value(a) == E("#CYCLE!"), a
    assert wb.value("D1") == 5.0 and wb.display("A1") == "#CYCLE!"
    wb.set("B1", "3")
    assert wb.value("A1") == 3.0 and wb.value("C1") == 4.0 and wb.value("D1") == 3.0


def test_recalc_order_with_cycles(wb):
    for a, v in {"Z1": "1", "B1": "=A1+Z1", "A1": "=B1", "C1": "=A1"}.items():
        wb.set(a, v)
    wb.set("Z1", "2")
    assert wb.last_recalc() == ["Sheet1!A1", "Sheet1!B1", "Sheet1!C1"]
    wb2 = type(wb)()
    for a, v in {"D5": "=Z1", "B2": "=C2+Z1", "C2": "=B2", "A9": "=C2"}.items():
        wb2.set(a, v)
    wb2.set("Z1", "4")
    assert wb2.last_recalc() == ["Sheet1!B2", "Sheet1!C2", "Sheet1!D5", "Sheet1!A9"]


def test_ranges_and_names_are_dependencies(wb):
    wb.set("A1", "=SUM(B1:B3)")
    wb.define_name("Cell", "Sheet1!$C$5")
    wb.set("A2", "=Cell*2")
    wb.set("B2", "4")
    assert wb.last_recalc() == ["Sheet1!A1"] and wb.value("A1") == 4.0
    wb.set("C5", "3")
    assert wb.last_recalc() == ["Sheet1!A2"] and wb.value("A2") == 6.0


# --- 6. structural edits ------------------------------------------------------------

@pytest.mark.parametrize("formula,op,at,count,want", [
    ("=A2", "insert_rows", 2, 1, "=A3"), ("=A1", "insert_rows", 2, 1, "=A1"),
    ("=SUM(A2:A4)", "insert_rows", 3, 2, "=SUM(A2:A6)"), ("=SUM(A2:A4)", "insert_rows", 2, 1, "=SUM(A3:A5)"),
    ("=SUM(A2:A4)", "insert_rows", 5, 1, "=SUM(A2:A4)"), ("=SUM(A2:A4)", "insert_rows", 4, 1, "=SUM(A2:A5)"),
    ("=$A$4", "insert_rows", 2, 1, "=$A$5"), ("=SUM(A4:A2)", "insert_rows", 3, 1, "=SUM(A5:A2)"),
    ("=A9999", "insert_rows", 2, 1, "=#REF!"),
    ("=A3+1", "delete_rows", 3, 1, "=#REF!+1"), ("=A5", "delete_rows", 2, 2, "=A3"),
    ("=SUM(A2:A6)", "delete_rows", 3, 2, "=SUM(A2:A4)"), ("=SUM(A2:A4)", "delete_rows", 2, 3, "=SUM(#REF!)"),
    ("=SUM(A3:A6)", "delete_rows", 2, 2, "=SUM(A2:A4)"), ("=SUM(A2:A4)", "delete_rows", 4, 2, "=SUM(A2:A3)"),
    ("=$A$9", "delete_rows", 2, 3, "=$A$6"),
])
def test_row_edits_rewrite_formulas(wb, formula, op, at, count, want):
    wb.set("Z1", formula)
    getattr(ops, op)(wb, "Sheet1", at, count)
    assert wb.raw("Z1") == want


@pytest.mark.parametrize("formula,op,at,count,want", [
    ("=C1", "insert_cols", "B", 1, "=D1"), ("=SUM(B1:D1)", "delete_cols", "C", 1, "=SUM(B1:C1)"),
    ("=B1*C1", "delete_cols", "B", 1, "=#REF!*B1"), ("=ZZ1", "insert_cols", "B", 1, "=#REF!"),
    ("=SUM($B$1:C9)", "insert_cols", "C", 2, "=SUM($B$1:E9)"),
])
def test_column_edits_rewrite_formulas(wb, formula, op, at, count, want):
    wb.set("A99", formula)
    getattr(ops, op)(wb, "Sheet1", at, count)
    assert wb.raw("A99") == want


def test_edits_move_cells_and_keep_values(wb):
    for a, v in {"A1": "1", "A2": "2", "A3": "3", "A4": "=SUM(A1:A3)", "B1": "=A2*10", "C1": "=$A$3",
                 "D1": "=Sheet1!A2"}.items():
        wb.set(a, v)
    ops.insert_rows(wb, "Sheet1", 2, 2)
    assert wb.raw("A6") == "=SUM(A1:A5)" and wb.value("A6") == 6.0
    assert wb.raw("B1") == "=A4*10" and wb.value("B1") == 20.0
    assert wb.raw("C1") == "=$A$5" and wb.raw("D1") == "=Sheet1!A4"
    assert wb.value("A2") is BLANK and wb.value("A4") == 2.0
    assert wb.last_recalc() == ["Sheet1!B1", "Sheet1!C1", "Sheet1!D1", "Sheet1!A6"]
    wb.set("F9", "=A1*2")
    ops.delete_rows(wb, "Sheet1", 1, 1)
    assert wb.value("A3") == 2.0 and wb.raw("A5") == "=SUM(A1:A4)" and wb.value("A5") == 5.0
    assert wb.raw("F8") == "=#REF!*2" and wb.value("F8") == E("#REF!") and wb.raw("B1") == ""


def test_edits_on_other_sheets_and_names(wb):
    wb.add_sheet("Data")
    wb.set("Z1", "=Data!A2+A2")
    wb.set("Data!B1", "=A2")
    wb.set("Data!A2", "5")
    wb.define_name("N", "Data!$A$2:$A$3")
    wb.set("Z2", "=SUM(N)")
    ops.insert_rows(wb, "Data", 1, 1)
    assert wb.raw("Z1") == "=Data!A3+A2" and wb.raw("Data!B2") == "=A3"
    assert wb.value("Z1") == 5.0 and wb.value("Data!B2") == 5.0 and wb.value("Z2") == 5.0
    assert json.loads(store.save(wb))["names"] == {"N": "Data!$A$3:$A$4"}
    ops.delete_rows(wb, "Data", 3, 2)
    assert wb.value("Z2") == E("#REF!")


@pytest.mark.parametrize("call", [lambda wb: ops.insert_rows(wb, "Sheet1", 0, 1),
                                  lambda wb: ops.insert_rows(wb, "Sheet1", 1, 0),
                                  lambda wb: ops.delete_rows(wb, "Nope", 1, 1),
                                  lambda wb: ops.insert_cols(wb, "Sheet1", "AAA", 1)])
def test_bad_edits(wb, call):
    with pytest.raises(ValueError):
        call(wb)


# --- 7. fill ------------------------------------------------------------------------

def test_fill(wb):
    wb.set("B2", "2")
    wb.set("B3", "3")
    wb.set("C1", "10")
    wb.set("A1", "=B1*$C$1")
    fill(wb, "A1", "A2:A4")
    assert [wb.raw(a) for a in ("A2", "A3", "A4")] == ["=B2*$C$1", "=B3*$C$1", "=B4*$C$1"]
    assert wb.value("A3") == 30.0
    wb.set("E1", "=E$2+$B3")
    fill(wb, "E1", "F1:G1")
    assert wb.raw("F1") == "=F$2+$B3" and wb.raw("G1") == "=G$2+$B3"
    wb.set("H2", "=H1")
    fill(wb, "H2", "H1:H1")
    assert wb.raw("H1") == "=#REF!"
    wb.set("B9", "hello")
    fill(wb, "B9", "C9:D9")
    assert wb.value("D9") == "hello"
    wb.set("A5", "=SUM(B1:B3)")
    fill(wb, "A5", "B5:B5")
    assert wb.raw("B5") == "=SUM(C1:C3)"
    wb.define_name("Rate", "Sheet1!$C$1")
    wb.set("J1", "=Rate*B1")
    fill(wb, "J1", "J2:J3")
    assert wb.raw("J3") == "=Rate*B3" and wb.value("J3") == 30.0


# --- 8. files -----------------------------------------------------------------------

def test_csv(wb):
    assert csvio.export_csv(wb, "Sheet1") == ""
    wb.set("A1", "1")
    wb.set("B1", "x,y")
    wb.set("A2", "=A1*2")
    wb.set("C3", 'say "hi"')
    wb.set("B2", "TRUE")
    assert csvio.export_csv(wb, "Sheet1") == '1,"x,y",\n2,TRUE,\n,,"say ""hi"""\n'
    wb.add_sheet("In")
    csvio.import_csv(wb, "In", "1,=A1+1\n,hello\n")
    assert wb.value("In!B1") == 2.0 and wb.value("In!A2") is BLANK and wb.value("In!B2") == "hello"
    assert wb.raw("In!B1") == "=A1+1"


def test_store_round_trip(wb):
    wb.set("A1", "1")
    wb.set("B1", "=A1+1")
    wb.add_sheet("Two")
    wb.set("Two!C2", "'007")
    wb.define_name("Rate", "Sheet1!$A$1")
    data = json.loads(store.save(wb))
    assert data["format"] == "tally" and data["version"] == 1
    assert data["sheets"] == [{"name": "Sheet1", "cells": {"A1": "1", "B1": "=A1+1"}},
                              {"name": "Two", "cells": {"C2": "'007"}}]
    assert data["names"] == {"Rate": "Sheet1!$A$1"}
    back = store.load(store.save(wb))
    assert back.sheet_names() == ["Sheet1", "Two"] and back.value("B1") == 2.0 and back.value("Two!C2") == "007"
    back.set("A1", "5")
    assert back.value("B1") == 6.0
    main = store.load(json.dumps({"format": "tally", "version": 1, "sheets": [{"name": "Main", "cells": {"A1": "5"}}],
                                  "names": {}}))
    assert main.sheet_names() == ["Main"] and main.value("A1") == 5.0


@pytest.mark.parametrize("text", [
    "not json", '{"format": "other", "version": 1, "sheets": []}',
    '{"format": "tally", "version": 2, "sheets": [{"name": "Sheet1", "cells": {}}], "names": {}}',
    '{"format": "tally", "version": 1, "sheets": [{"name": "Sheet1", "cells": {"A0": "1"}}], "names": {}}',
    '{"format": "tally", "version": 1, "sheets": [{"name": "Sheet1", "cells": {"A1": "=1+"}}], "names": {}}',
])
def test_store_refuses_bad_files(text):
    with pytest.raises(ValueError):
        store.load(text)


# --- 9. text grid -------------------------------------------------------------------

def test_render_spec_example(wb):
    wb.set("A1", "1")
    wb.set("B1", "hello")
    wb.set("A2", "=A1*20")
    assert render(wb, "A1:B2") == "  | A  | B\n--+----+------\n1 |  1 | hello\n2 | 20 |\n"


def test_render_alignment(wb):
    wb.set("A1", "-1.5")
    wb.set("A2", "TRUE")
    wb.set("B1", "=1/0")
    wb.set("B2", "'12")
    assert render(wb, "A1:B2") == "  | A    | B\n--+------+--------\n1 | -1.5 | #DIV/0!\n2 | TRUE | 12\n"
    wb.set("A9", "5")
    wb.set("A10", "x")
    assert render(wb, "A9:A10") == "   | A\n---+--\n 9 | 5\n10 | x\n"
    wb.add_sheet("Data")
    wb.set("Data!B1", "7")
    assert render(wb, "Data!B1:B1") == "  | B\n--+--\n1 | 7\n"
