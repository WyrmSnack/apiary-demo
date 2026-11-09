"""`apiary measure`: tokens and time for one Claude Code session, its subagents included (Phase 6).

Claude Code logs one model call on several transcript lines (measured on Kevin's REA website session: 438 usage
lines, 191 calls), so calls are counted once by (message id, request id).
"""
import json

from apiary.measure import measure, project_dir


def line(mid, rid, ts, inp=1, cc=10, cr=100, out=5, user=None, tool_result=False):
    if user is not None:
        content = [{"type": "tool_result", "content": "x"}] if tool_result else user
        return json.dumps({"type": "user", "timestamp": ts, "message": {"role": "user", "content": content}})
    return json.dumps({"type": "assistant", "timestamp": ts, "requestId": rid,
                       "message": {"id": mid, "model": "claude-opus-5-5", "usage": {
                           "input_tokens": inp, "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr,
                           "output_tokens": out, "server_tool_use": {"web_search_requests": 1}}}})


def test_counts_each_call_once_across_session_and_subagents(tmp_path):
    session = tmp_path / "abc.jsonl"
    session.write_text("\n".join([
        line(None, None, "2026-10-16T01:00:00Z", user="Build the project in SPEC.md."),
        line("m1", "r1", "2026-10-16T01:00:05Z"),
        line("m1", "r1", "2026-10-16T01:00:05Z"),                      # the same call, logged twice
        line(None, None, "2026-10-16T01:00:06Z", user="", tool_result=True),
        line(None, None, "2026-10-16T01:05:00Z", user="Yes, go ahead."),
        line("m2", "r2", "2026-10-16T01:10:00Z", out=7),
    ]) + "\n", encoding="utf-8")
    sub = tmp_path / "abc" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(line("m3", "r3", "2026-10-16T01:06:00Z", out=11) + "\n", encoding="utf-8")
    m = measure(session)
    assert m["calls"] == 3 and m["subagents"] == 1
    assert m["output_tokens"] == 5 + 7 + 11 and m["cache_read_input_tokens"] == 300
    assert m["total_tokens"] == 3 * (1 + 10 + 100) + 23
    assert m["web_search_requests"] == 3
    assert m["wall_seconds"] == 600
    assert m["human_messages"] == 2 and m["interventions"] == 1     # the first message is the task itself
    assert m["models"] == {"claude-opus-5-5": 3}


def test_output_tokens_take_the_largest_count_logged_for_a_call(tmp_path):
    # Measured on serial run 1: a Forager call logged on two lines with output_tokens 4, then the final count. The
    # first line is written while the reply is still streaming; input and cache counts are the same on every line.
    session = tmp_path / "abc.jsonl"
    session.write_text("\n".join([
        line("m1", "r1", "2026-10-16T01:00:05Z", out=4),
        line("m1", "r1", "2026-10-16T01:00:09Z", out=1800),
        line("m1", "r1", "2026-10-16T01:00:09Z", out=4),
    ]) + "\n", encoding="utf-8")
    m = measure(session)
    assert m["calls"] == 1
    assert m["output_tokens"] == 1800
    assert m["input_tokens"] == 1 and m["cache_read_input_tokens"] == 100
    assert m["total_tokens"] == 1 + 10 + 100 + 1800


def test_an_answer_in_the_question_dialog_is_an_intervention(tmp_path):
    # Measured on parallel run 3: Kevin approved the plan in Claude Code's question dialog, which comes back as a tool
    # result, not a typed message, and the count said 0.
    session = tmp_path / "abc.jsonl"
    ask = json.dumps({"type": "assistant", "timestamp": "2026-10-16T01:00:05Z", "requestId": "r1", "message": {
        "id": "m1", "content": [{"type": "tool_use", "id": "tu1", "name": "AskUserQuestion", "input": {}},
                                {"type": "tool_use", "id": "tu2", "name": "Bash", "input": {}}],
        "usage": {"input_tokens": 1, "output_tokens": 1}}})
    answer = lambda tid: json.dumps({"type": "user", "timestamp": "2026-10-16T01:01:00Z", "message": {
        "role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": "answered"}]}})
    session.write_text("\n".join([line(None, None, "2026-10-16T01:00:00Z", user="Build the project in SPEC.md."),
                                  ask, answer("tu1"), answer("tu2")]) + "\n", encoding="utf-8")
    m = measure(session)
    assert m["human_messages"] == 1 and m["question_answers"] == 1
    assert m["interventions"] == 1


def test_compactions_are_counted(tmp_path):
    # Measured on this SDK's own long session: Claude Code marks a compacted context with a compact_boundary line.
    session = tmp_path / "abc.jsonl"
    boundary = json.dumps({"type": "system", "subtype": "compact_boundary", "timestamp": "2026-10-16T01:00:09Z"})
    other = json.dumps({"type": "system", "subtype": "stop_hook_summary", "timestamp": "2026-10-16T01:00:10Z"})
    session.write_text("\n".join([line("m1", "r1", "2026-10-16T01:00:05Z"), boundary, other]) + "\n", encoding="utf-8")
    sub = tmp_path / "abc" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(boundary + "\n", encoding="utf-8")
    assert measure(session)["compactions"] == 2


def test_subagent_start_up_and_bookkeeping_calls(tmp_path):
    # Phase 9 reports a subagent's first-call context and the calls that do only colony bookkeeping.
    def call(mid, ctx, tools, ts):
        return json.dumps({"type": "assistant", "timestamp": ts, "requestId": "r" + mid, "message": {
            "id": mid, "content": [{"type": "tool_use", "id": f"t{mid}{i}", "name": n, "input": {}}
                                   for i, n in enumerate(tools)],
            "usage": {"input_tokens": 1, "cache_creation_input_tokens": ctx - 1, "cache_read_input_tokens": 0,
                      "output_tokens": 5}}})
    session = tmp_path / "abc.jsonl"
    session.write_text(call("q1", 70000, ["Agent"], "2026-10-17T01:00:00Z") + "\n", encoding="utf-8")
    sub = tmp_path / "abc" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text("\n".join([
        call("a1", 12000, ["mcp__colony__claim_task"], "2026-10-17T01:00:05Z"),
        call("a2", 13000, ["Write", "Write"], "2026-10-17T01:00:09Z"),
        call("a3", 14000, ["Bash", "mcp__colony__close_task"], "2026-10-17T01:00:12Z"),
        call("a4", 15000, ["mcp__colony__close_task"], "2026-10-17T01:00:15Z")]) + "\n", encoding="utf-8")
    (sub / "agent-2.jsonl").write_text(call("b1", 20000, ["ToolSearch"], "2026-10-17T01:00:06Z") + "\n", encoding="utf-8")
    m = measure(session)
    assert m["subagent_first_context"] == [12000, 20000]
    assert m["bookkeeping_calls"] == 3 and m["subagent_calls"] == 5


def test_project_dir_matches_claude_codes_folder_naming():
    assert project_dir(r"C:\Users\dev\Desktop\Projects\my-colony").name == \
        "C--Users-dev-Desktop-Projects-my-colony"
