# tally: a spreadsheet engine

Build a Python package named `tally` in this folder: a spreadsheet engine with formulas, a dependency graph,
structural edits, fill, files, a text grid and a command line. Python 3.11 or later, **standard library only**.
Write tests for it.

Everything below is exact. Where this spec gives a name, a signature, an output format or an error message prefix,
use it as written: other code will import these names and read this output. Anything the spec does not state is
yours to decide.

## 1. Values

A cell's value is one of five kinds:

| Kind | Python |
|---|---|
| number | `float` (always a float, never an `int`) |
| text | `str` |
| boolean | `bool` |
| blank | the singleton `tally.values.BLANK` |
| error | `tally.values.CellError` |

`tally.values` provides:

- `BLANK`: a singleton; `repr(BLANK) == "BLANK"`.
- `CellError(code)`: a frozen dataclass with one field `code: str`, one of `#DIV/0!`, `#VALUE!`, `#REF!`, `#NAME?`,
  `#N/A`, `#CYCLE!`, `#NUM!`. Two `CellError`s are equal when their codes are equal.
- `format_number(x: float) -> str`: if `x` is a whole number and `abs(x) < 1e15`, the integer with no decimal point
  (`3.0` gives `"3"`, `-0.0` gives `"0"`). Otherwise `format(x, ".10g")` (`1/3` gives `"0.3333333333"`, `1e20` gives
  `"1e+20"`, `0.1 + 0.2` gives `"0.3"`).
- `parse_number(text: str) -> float | None`: the number written in `text`, or `None`. Leading and trailing spaces are
  ignored. A number is an optional `+` or `-`, then digits with an optional fraction (`12`, `12.`, `12.5`, `.5`), then
  an optional exponent (`e` or `E`, an optional sign, digits). Nothing else: `"1,000"`, `"$5"`, `"inf"`, `"nan"`, `""`
  give `None`.
- `to_number(v)`: number: itself. Boolean: `1.0` or `0.0`. Blank: `0.0`. Text: `parse_number(text)`, or
  `CellError("#VALUE!")` if that is `None`. Error: the error itself.
- `to_text(v)`: text: itself. Number: `format_number`. Boolean: `"TRUE"` or `"FALSE"`. Blank: `""`. Error: itself.
- `to_bool(v)`: boolean: itself. Number: `v != 0`. Blank: `False`. Text: `"TRUE"` or `"FALSE"` in any case give the
  boolean; any other text gives `CellError("#VALUE!")`. Error: itself.
- `display(v) -> str`: what a cell shows. Number: `format_number`. Text: itself. Boolean: `TRUE` or `FALSE`. Blank:
  `""`. Error: its code.

A number result that is infinite or not a number becomes `CellError("#NUM!")`.

## 2. Cell references

Columns are letters: `A` is column 0, `Z` is 25, `AA` is 26, `AZ` is 51, `BA` is 52, up to `ZZ` (701). Rows are
written from 1 to 9999 and stored 0-based. `tally.refs` provides:

- `col_to_index(letters: str) -> int` and `index_to_col(index: int) -> str`. Letters are upper case. Anything outside
  `A` to `ZZ` (or 0 to 701) raises `ValueError`.
- `CellRef`: a frozen dataclass with fields `sheet: str | None`, `col: int`, `row: int`, `col_abs: bool`,
  `row_abs: bool` (row and column 0-based).
- `parse_ref(text: str) -> CellRef`: an optional sheet prefix `Name!`, an optional `$`, one or two letters, an
  optional `$`, a row number. Letters may be lower case and are read as upper case. A sheet name is a letter followed
  by letters, digits or `_`; sheet names are case-sensitive. A row of 0 or above 9999, a column beyond `ZZ`, or any
  other text raises `ValueError`. `parse_ref("$b$7")` is `CellRef(None, 1, 6, True, True)`.
- `format_ref(ref: CellRef) -> str`: the reverse, upper case, with `$` where absolute and `Name!` when `sheet` is set.
- `RangeRef`: a frozen dataclass with fields `start: CellRef` and `end: CellRef`, as written.
- `parse_range(text: str) -> RangeRef`: two references joined by `:`. Only the first may carry a sheet prefix, which
  then applies to both (both `CellRef`s get that sheet). A sheet prefix on the second raises `ValueError`.
- `format_range(r: RangeRef) -> str`: `format_ref(start)` + `:` + the second reference without a sheet prefix.
- `range_cells(r: RangeRef) -> list[tuple[int, int]]`: the `(col, row)` of every cell in the rectangle the two
  corners span, whichever corner is written first, row by row from the top-left: `B2:A1` gives
  `[(0, 0), (1, 0), (0, 1), (1, 1)]`.

An **address** names one cell of a workbook: a reference without `$`, with or without a sheet prefix (`B3`,
`Sheet2!B3`). Without a prefix it means the first sheet.

## 3. Formulas

A cell whose input starts with `=` holds a formula: an expression after the `=`.

### 3.1 Tokens

Spaces between tokens are ignored. The tokens are:

- **number**: as in `parse_number` but without a sign (`3`, `2.5`, `.5`, `1e3`, `1E-2`).
- **text**: in double quotes; `""` inside is one double quote (`"say ""hi"""` is `say "hi"`).
- **boolean**: `TRUE` or `FALSE`, any case.
- **error**: one of the seven error codes as written in section 1 (`#REF!`).
- **function name**: a word (a letter or `_`, then letters, digits or `_`) directly followed by `(`. Names are read
  in upper case.
- **reference**: as in `parse_ref`, including `$` and a sheet prefix (`Sheet2!$A$1`). A word that is not a function
  name is a reference if it has this form (`A1`, `zz99`), otherwise a **name** (`Sales`, `rate_2`). A word followed by
  `!` is a sheet prefix and must be followed by a reference.
- **operators**: `+ - * / ^ & = <> < > <= >= %`, and `( ) , :`.

Anything else is an error (section 3.4).

### 3.2 Grammar

From lowest to highest precedence:

1. comparison `= <> < > <= >=` (left to right)
2. concatenation `&` (left to right)
3. `+ -` (left to right)
4. `* /` (left to right)
5. `^` (left to right: `2^3^2` is 64)
6. prefix `-` and `+` (`-2^2` is 4)
7. postfix `%` (`50%` is 0.5)
8. a number, text, boolean, error, reference, range, name, function call `NAME(arg, ...)` (zero or more arguments,
   none empty), or `( expression )`.

A **range** is two references joined by `:` (`A1:B3`, `Sheet2!A1:B3`). A `:` anywhere else is an error.

### 3.3 Canonical form

`tally.parser.parse(text: str)` parses an expression (the text after `=`) and returns a tree; the tree's classes
are yours. `tally.parser.to_formula(tree) -> str` prints it back in canonical form, without the `=`:

- numbers by `format_number`; text in double quotes with `"` doubled; `TRUE`, `FALSE`; error codes as written;
- references and ranges by `format_ref` and `format_range`; names as written in the input (case kept);
- function calls as `NAME(a,b)`, upper case, no spaces;
- operators with no spaces (`A1+2`, `A1<>3`, `"a"&B2`, `-A1`, `50%`);
- parentheses only where needed: around a child operator of lower precedence than its parent, and around a right
  child of equal precedence (`(1+2)*3`, `1-(2-3)`, `1-2-3`, `-(1+2)`, `(1+2)%`, `(-2)^2` prints as `-2^2`).

When a workbook stores a formula it stores the canonical form: `set("A1", "= sum( b1 : b3 ) * 2")` makes `raw("A1")`
equal `=SUM(B1:B3)*2`.

### 3.4 Formula errors

`tally.parser.FormulaError` is a subclass of `ValueError`. `parse` raises it for any text that is not an expression
under 3.1 and 3.2. Setting a cell to such a formula raises it and leaves the cell unchanged.

## 4. Evaluation

### 4.1 Rules

- A reference's value is that cell's value. A formula whose result is blank gives `0.0` (`=A9` with `A9` blank, or a
  lookup that lands on a blank cell); inside a formula a blank stays blank (`=A9&"x"` is `x`).
- A reference to a sheet that does not exist gives `#REF!`. A name that is not defined gives `#NAME?`. An unknown
  function gives `#NAME?`. A function called with the wrong number of arguments gives `#VALUE!`.
- A range used anywhere except as a function argument where this spec allows a range gives `#VALUE!`.
- Errors propagate: an operator or function that receives an error returns it, taking the first error from left to
  right (inside a range, row by row), unless this spec says otherwise for that function.
- Arithmetic `+ - * / ^`, prefix `-` and `+`, and `%` convert operands with `to_number`. `x/0` gives `#DIV/0!`.
  `0^-1` gives `#DIV/0!`. A result that is complex, infinite or not a number gives `#NUM!`. `%` divides by 100.
- `&` converts both operands with `to_text` and joins them.
- Comparison never converts text to numbers. If one side is blank, it is replaced by `0.0`, `""` or `FALSE` to match
  the other side's kind (both blank: equal). If the kinds still differ, any number < any text < any boolean. Numbers
  compare by value, text without regard to case (`casefold`), `FALSE < TRUE`. The result is a boolean.

### 4.2 Reference arguments and value arguments

In a function call, an argument that is written as a reference, a range or a name is a **reference argument**.
Any other argument is a **value argument**, and is evaluated as an expression.

### 4.3 Functions

Arguments in brackets are optional. "Numbers in" an argument means: for a reference argument, the cells holding
numbers (text, booleans and blanks are skipped, errors propagate); for a value argument, `to_number` of its value
(errors, including `#VALUE!` for non-numeric text, propagate).

**Math**

| Function | Result |
|---|---|
| `SUM(x, ...)` | the sum of the numbers in all arguments; `0` if none |
| `PRODUCT(x, ...)` | the product of the numbers in all arguments; `0` if none |
| `MIN(x, ...)`, `MAX(x, ...)` | the smallest or largest of the numbers in all arguments; `0` if none |
| `AVERAGE(x, ...)` | the mean of the numbers in all arguments; `#DIV/0!` if none |
| `MEDIAN(x, ...)` | the median of the numbers in all arguments (the mean of the middle two for an even count); `#NUM!` if none |
| `ABS(x)`, `INT(x)`, `SQRT(x)` | absolute value; the largest whole number not above `x`; square root (`#NUM!` if `x < 0`) |
| `ROUND(x, [d])` | `x` rounded to `d` decimal places (default 0; `d` truncated toward zero, may be negative), half away from zero, on the decimal that `repr(x)` writes: `ROUND(2.675, 2)` is 2.68, `ROUND(-2.5)` is -3, `ROUND(1234, -2)` is 1200 |
| `MOD(a, b)` | `a - b * INT(a / b)`; `#DIV/0!` if `b` is 0 (`MOD(-7, 3)` is 2) |
| `POWER(a, b)` | as `a ^ b` |

`ABS`, `INT`, `SQRT`, `ROUND`, `MOD` and `POWER` convert each argument with `to_number`; a range argument gives
`#VALUE!`; a single-cell reference argument is that cell's value.

**Counting**

| Function | Result |
|---|---|
| `COUNT(x, ...)` | how many numbers are in reference arguments, plus how many value arguments are numbers, booleans or text that `parse_number` reads; never an error |
| `COUNTA(x, ...)` | how many cells in reference arguments are not blank (errors count), plus the number of value arguments |
| `COUNTBLANK(range)` | how many cells in the range are blank or hold the text `""` |
| `COUNTIF(range, criterion)` | how many cells in the range match the criterion (4.4) |
| `SUMIF(range, criterion, [sum_range])` | the sum of the numbers in `sum_range` (default `range`) at the positions where `range` matches; `#VALUE!` if the two ranges differ in size; non-numbers in `sum_range` are skipped |

**Logic**

| Function | Result |
|---|---|
| `IF(c, a, [b])` | `to_bool(c)` (an error propagates); then the value of `a` if true, else `b` (default `FALSE`). Only the chosen argument is evaluated |
| `AND(x, ...)`, `OR(x, ...)` | over every value: in reference arguments, booleans and numbers (non-zero is true; text and blanks skipped); value arguments by `to_bool`. Errors propagate. `#VALUE!` if there are no values |
| `NOT(x)` | the opposite of `to_bool(x)` |
| `IFERROR(v, alt)` | `v` unless it is an error, then `alt`. `alt` is evaluated only when needed |

**Text** (`to_text` on text arguments, `to_number` truncated toward zero on counts and positions)

| Function | Result |
|---|---|
| `LEN(t)`, `UPPER(t)`, `LOWER(t)` | length; upper case; lower case |
| `TRIM(t)` | spaces removed from both ends, and each run of spaces inside replaced by one space (only the space character) |
| `LEFT(t, [n])`, `RIGHT(t, [n])` | the first or last `n` characters (default 1; all of `t` if `n` is longer); `#VALUE!` if `n < 0` |
| `MID(t, start, n)` | `n` characters from position `start` (1-based); `#VALUE!` if `start < 1` or `n < 0` |
| `CONCAT(x, ...)` | every value joined by `to_text`, reference arguments cell by cell, row by row (blanks are `""`) |
| `FIND(needle, hay, [start])` | the 1-based position of `needle` in `hay` at or after `start` (default 1), case-sensitive; `#VALUE!` if not found or if `start < 1` or `start > LEN(hay) + 1` |
| `SUBSTITUTE(t, old, new)` | `t` with every `old` replaced by `new`; `t` unchanged if `old` is `""` |

**Lookup**

| Function | Result |
|---|---|
| `VLOOKUP(key, table, col)` | finds the first row of `table` whose first cell equals `key` (4.4 equality) and returns that row's cell in column `col` (1-based); `#VALUE!` if `col < 1`, `#REF!` if `col` is beyond the table, `#N/A` if no row matches |
| `INDEX(range, i, [j])` | the cell at row `i`, column `j` (1-based; `j` defaults to 1). If `j` is left out and the range is one row of several columns, `i` counts columns. `#REF!` if out of range or below 1 |
| `MATCH(key, range)` | the 1-based position of the first cell equal to `key` in a one-row or one-column range; `#N/A` if not found or if the range has several rows and several columns |

### 4.4 Equality and criteria

**Equality** for `VLOOKUP` and `MATCH`: numbers by value, text without regard to case, booleans by value; different
kinds are never equal; a blank key gives `#N/A`.

A **criterion** for `COUNTIF` and `SUMIF` is a value `c`:

- a number: matches cells holding an equal number;
- a boolean: matches cells holding the same boolean;
- text: take off a leading operator, the longest of `>= <= <> > < =`, leaving `r`. If `parse_number(r)` reads a
  number `n`: the criterion is numeric: with `=` (or no operator) it matches cells holding numbers equal to `n`; with
  `<>` it matches every cell except those holding numbers equal to `n` (blanks and text match); with `< > <= >=` it
  matches cells holding numbers that compare that way with `n`. Otherwise the criterion is text: with `=` or no
  operator it matches text cells equal to `r` without regard to case (and if `r` is `""`, blank cells too); with `<>`
  it matches every cell except text cells equal to `r` without regard to case; with `< > <= >=` it matches text cells
  that compare that way with `r`, compared by `casefold`.
- an error: `COUNTIF` and `SUMIF` return it.

## 5. Workbook

`tally.workbook.Workbook()` creates a workbook with one sheet, `Sheet1`.

| Method | Effect |
|---|---|
| `add_sheet(name)` | adds a sheet after the others; `ValueError` if the name is taken or not a sheet name |
| `sheet_names() -> list[str]` | in order |
| `rename_sheet(old, new)` | renames, and rewrites every reference to `old` in every formula (and every name's target) to `new`; `ValueError` if `old` is missing or `new` is taken or invalid |
| `set(address, raw)` | sets a cell's input (5.1); `ValueError` for a bad address or a missing sheet |
| `value(address)` | the cell's current value |
| `raw(address) -> str` | the cell's input as stored: a formula in canonical form with its `=`; other input as given; `""` for a blank cell |
| `display(address) -> str` | `tally.values.display` of the value |
| `define_name(name, target)` | defines (or redefines) a name for a reference or range, written with a sheet prefix, `$` optional (`Sheet1!$B$2:$B$9`); names are matched without regard to case; a name must not look like a reference; `ValueError` otherwise |
| `last_recalc() -> list[str]` | the addresses recalculated by the most recent change (5.2), each with its sheet prefix |

### 5.1 Input

- `""` makes the cell blank.
- Text starting with `=` is a formula (3.4 for errors).
- Text that `parse_number` reads is that number. `TRUE` or `FALSE`, in any case and with no spaces, is that boolean.
- Text starting with `'` is the text after the `'` (`'007` is the text `007`).
- Anything else is that text exactly, spaces included. `#N/A` typed in is text.

### 5.2 Recalculation

After any change, every value is current. Dependencies are read from formulas as written: a formula depends on every
cell it references, every cell in every range it mentions (blank or not), and every cell of every name it mentions;
the branch `IF` does not take still counts. A name's dependents change when the name is redefined.

Cells that depend on themselves, directly or through other cells, are **in a cycle**; their value is `#CYCLE!`.
Cells that depend on a cycle get whatever their formula gives with `#CYCLE!` as input.

`last_recalc()` lists, after:

- `set(address, raw)`: that cell if it now holds a formula, plus every formula cell that depends on it, directly or
  through others;
- `define_name`: every formula cell that mentions the name, plus the cells that depend on those;
- `rename_sheet` and the operations of section 6: every formula cell in the workbook.

The order: precedents before dependents, counting only dependencies between listed cells. Each cycle (a group of cells that depend on each other) is one group,
placed where its smallest cell would be; among groups that could come next, the one with the smallest key comes
first; inside a group, cells come in key order. A cell's **key** is (its sheet's position, row, column).

## 6. Structural edits

`tally.ops` provides, for a workbook `wb`, a sheet name, a 1-based row number or a column's letters, and a count of
at least 1 (`ValueError` otherwise):

- `insert_rows(wb, sheet, at, count)`: rows from `at` down move down by `count`.
- `delete_rows(wb, sheet, at, count)`: rows `at` to `at + count - 1` are removed; rows below move up.
- `insert_cols(wb, sheet, at, count)`, `delete_cols(wb, sheet, at, count)`: the same for columns, `at` given as
  letters (`"C"`).

Every reference to that sheet, in every formula of every sheet and in every name's target, is updated, absolute or
not (a reference without a sheet prefix refers to its own formula's sheet):

- A reference to a moved cell follows it. A reference to a deleted cell becomes `#REF!` (the reference is replaced in
  the formula, so `=A3+1` with row 3 deleted becomes `=#REF!+1`).
- A range keeps the cells that remain: inserting inside it (after its first row or column, up to and including its
  last) makes it bigger; deleting part of it makes it smaller; deleting all of it turns it into `#REF!`. Inserting at
  its first row moves it.
- A reference moved beyond row 9999 or column `ZZ` becomes `#REF!`.

Formulas that change are stored in canonical form. A name whose target is deleted keeps `#REF!` as its target and
evaluates to `#REF!`.

## 7. Fill

`tally.fill.fill(wb, source, target)`: `source` is an address and `target` a range (on the source's sheet unless it
carries a prefix). Every cell of `target` gets the source's input. In a formula, each relative part of each
reference (row or column, without `$`) moves by the distance from the source to that cell; absolute parts stay. A
reference moved before row 1 or column `A`, or beyond the edges, becomes `#REF!`. Names are not changed.
`fill(wb, "A1", "A2:A4")` with `A1` = `=B1*$C$1` gives `A3` = `=B3*$C$1`.

## 8. Files

`tally.csvio`:

- `export_csv(wb, sheet) -> str`: the rectangle from `A1` to the last row and column that hold a non-blank cell, each
  cell as `display`, written by `csv.writer` with `lineterminator="\n"`. An empty sheet gives `""`.
- `import_csv(wb, sheet, text)`: reads `text` with `csv.reader` and sets each field as the input (5.1) of its cell,
  from `A1`. Fields that are `""` leave their cell blank.

`tally.store`:

- `save(wb) -> str`: JSON:
  `{"format": "tally", "version": 1, "sheets": [{"name": "Sheet1", "cells": {"A1": "=B1+1", ...}}, ...],
  "names": {"Sales": "Sheet1!$B$2:$B$9"}}`. Cells hold `raw`; blank cells are left out.
- `load(text) -> Workbook`: the reverse. Anything else (bad JSON, another format or version, a bad address, a formula
  that does not parse) raises `ValueError`.

## 9. Text grid

`tally.render.render(wb, range_text) -> str` draws a range (with an optional sheet prefix; otherwise the first sheet):

- A header line: a blank row-number cell, then the column letters. Then a line of `-`. Then one line per row: the row
  number, then each cell's `display`.
- Every column is as wide as its widest entry, its header included (the row-number column: its widest row number).
  Row numbers and cells holding numbers are right-aligned; column letters and all other cells are left-aligned.
- Columns are joined by ` | `. The `-` line has, for each column, as many `-` as the column is wide, joined by `-+-`.
- Trailing spaces are removed from every line. Lines end with `\n`.

`A1` = 1, `B1` = `hello`, `A2` = `=A1*20`, `B2` blank: `render(wb, "A1:B2")` is

```
  | A  | B
--+----+------
1 |  1 | hello
2 | 20 |
```

## 10. Command line

`python -m tally run SCRIPT` runs a script file and prints what its commands print. One command per line; blank
lines and lines starting with `#` are skipped. A command's word is followed by one space and its arguments.

| Command | Prints |
|---|---|
| `set ADDRESS INPUT` | nothing. `INPUT` is the rest of the line after the space after the address, kept exactly (may be empty) |
| `print ADDRESS` | `display` of the cell |
| `raw ADDRESS` | `raw` of the cell |
| `show RANGE` | `render` of the range (no extra blank line) |
| `sheet NAME` | nothing; adds a sheet |
| `rename OLD NEW` | nothing |
| `name NAME TARGET` | nothing; `define_name` |
| `insert-rows SHEET AT COUNT`, `delete-rows SHEET AT COUNT` | nothing |
| `insert-cols SHEET COLUMN COUNT`, `delete-cols SHEET COLUMN COUNT` | nothing |
| `fill SOURCE TARGET` | nothing |
| `recalc` | `recalc:` then a space and each address of `last_recalc()`, separated by spaces (`recalc:` alone if empty) |
| `save PATH`, `load PATH` | nothing; `load` replaces the workbook |
| `export SHEET PATH`, `import SHEET PATH` | nothing |

A command that fails (unknown command, wrong arguments, a `ValueError` including a `FormulaError`, a file that
cannot be read or written) prints `error line N: ` and a message, where `N` is the line's number in the file, and the
script goes on. The exit status is 0, or 1 if any command failed. If `SCRIPT` cannot be read, print a message to
stderr and exit with status 2.
