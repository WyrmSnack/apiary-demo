"""The reference grammar against the language-neutral vectors in spec/vectors/."""
import json
from pathlib import Path

import pytest

from apiary import grammar as g

VEC = Path(__file__).resolve().parents[1] / "spec" / "vectors"
load = lambda name: json.loads((VEC / f"{name}.json").read_text(encoding="utf-8"))
LEDGER, ACCEPT, TASKS, TRACES = load("ledger_lines"), load("acceptance"), load("task_files"), load("traces")


@pytest.mark.parametrize("line", LEDGER["valid"])
def test_valid_ledger_lines_parse_and_round_trip(line):
    assert str(g.parse_ledger_line(line)) == line


@pytest.mark.parametrize("case", LEDGER["invalid"], ids=lambda c: c["why"])
def test_invalid_ledger_lines_are_rejected_under_the_right_rule(case):
    with pytest.raises(g.GrammarError) as e:
        g.parse_ledger_line(case["line"])
    assert e.value.rule == case["rule"]


@pytest.mark.parametrize("line", LEDGER["comments"])
def test_comment_lines(line):
    assert g.is_comment(line)


@pytest.mark.parametrize("case", ACCEPT["valid"], ids=lambda c: c["line"])
def test_acceptance_tokenizes(case):
    assert g.tokenize_acceptance(case["line"]) == case["argv"]


@pytest.mark.parametrize("case", ACCEPT["invalid"], ids=lambda c: c["why"])
def test_acceptance_rejects(case):
    with pytest.raises(g.GrammarError) as e:
        g.tokenize_acceptance(case["line"])
    assert e.value.rule == "A-2"


@pytest.mark.parametrize("name", TASKS["valid_names"])
def test_valid_task_names(name):
    assert g.task_id(name) == int(name.split("-")[0])


@pytest.mark.parametrize("name", TASKS["invalid_names"])
def test_invalid_task_names(name):
    with pytest.raises(g.GrammarError) as e:
        g.task_id(name)
    assert e.value.rule == "T-1"


@pytest.mark.parametrize("case", TASKS["valid_contents"])
def test_valid_task_contents(case):
    t = g.parse_task(case["text"])
    assert t.fields == case["fields"] and t.depends_on == case["depends_on"]


@pytest.mark.parametrize("case", TASKS["invalid_contents"], ids=lambda c: c["why"])
def test_invalid_task_contents(case):
    with pytest.raises(g.GrammarError) as e:
        g.parse_task(case["text"])
    assert e.value.rule == case["rule"]


@pytest.mark.parametrize("key", TRACES["valid_keys"])
def test_valid_trace_keys(key):
    g.check_trace_key(key)


@pytest.mark.parametrize("key", TRACES["invalid_keys"])
def test_invalid_trace_keys(key):
    with pytest.raises(g.GrammarError):
        g.check_trace_key(key)


@pytest.mark.parametrize("text", TRACES["valid_documents"])
def test_valid_traces(text):
    g.parse_traces(text)


@pytest.mark.parametrize("case", TRACES["invalid_documents"], ids=lambda c: c["why"])
def test_invalid_traces(case):
    with pytest.raises(g.GrammarError) as e:
        g.parse_traces(case["text"])
    assert e.value.rule == case["rule"]


def test_a_written_trace_entry_parses_back():
    doc = "# TRACES\n" + g.make_trace_entry("2026-10-14T12:00Z", "Queen", "save-format", "JSON,\n  versioned")
    doc += g.make_trace_entry("2026-10-14T12:05Z", "Guardian", "save-format-v2", "atomic", "save-format")
    entries = g.parse_traces(doc)
    assert [e.key for e in entries] == ["save-format", "save-format-v2"]
    assert entries[0].value == "JSON, versioned" and entries[1].supersedes == "save-format"


@pytest.mark.parametrize("data", [b"\xef\xbb\xbfx", "x".encode("utf-16"), "x".encode("utf-16-le"), b"\xff\x00x"])
def test_encoding_problems_are_reported_not_guessed(data):
    with pytest.raises(g.GrammarError) as e:
        g.decode_strict(data)
    assert e.value.rule == "E-3"


def test_crlf_reads_as_lf():
    assert g.decode_strict(b"a\r\nb\r\n") == "a\nb\n"
