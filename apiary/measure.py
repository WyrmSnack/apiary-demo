"""Tokens, time and interventions for one Claude Code session, counted from its transcripts (Phase 6).

Claude Code writes each session to ~/.claude/projects/<folder>/<session>.jsonl and each subagent to
<session>/subagents/agent-*.jsonl. One model call can appear on several lines, so calls are counted once by
(message id, request id).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path

TOKEN_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
# Calls that only do colony bookkeeping (Phase 9): loading tools, resume, claim, renew, close, status, the hand-back.
BOOKKEEPING = {"ToolSearch", "SubagentHandback", *(f"mcp__colony__{n}" for n in
               ("resume", "claim_task", "renew_claim", "close_task", "plan_status"))}


def project_dir(cwd: str | Path) -> Path:
    """Where Claude Code keeps transcripts for sessions started in `cwd`."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def latest_session(cwd: str | Path) -> Path | None:
    files = sorted(project_dir(cwd).glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def _time(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _is_human(m: dict) -> bool:
    if m.get("type") != "user" or m.get("isSidechain") or m.get("isMeta"):
        return False
    content = (m.get("message") or {}).get("content")
    if isinstance(content, str):
        return bool(content.strip()) and not content.lstrip().startswith("<")
    if isinstance(content, list):
        return any(c.get("type") == "text" and c.get("text", "").strip() and not c["text"].lstrip().startswith("<")
                   for c in content if isinstance(c, dict))
    return False


def human_replies(transcript: str | Path) -> int:
    """Replies from the human after their first message, in one transcript: typed messages and answers in the
    question dialog. The guard reads this before task creation (apiary.hook)."""
    human = answers = 0
    asked: set = set()
    for raw in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(m, dict):
            continue
        if _is_human(m):
            human += 1
        content = (m.get("message") or {}).get("content") if isinstance(m.get("message"), dict) else None
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion":
                asked.add(c.get("id"))
            elif isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in asked:
                answers += 1
    return max(human - 1, 0) + answers


def human_reply_texts(transcript: str | Path) -> list[str]:
    """What the human wrote after their first message (typed, or answered in the question dialog). The guard reads
    this for the approval of a weakened test (apiary.hook)."""
    out: list[str] = []
    typed = 0
    asked: set = set()
    for raw in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(m, dict):
            continue
        content = (m.get("message") or {}).get("content") if isinstance(m.get("message"), dict) else None
        if _is_human(m):
            typed += 1
            if typed > 1:
                out.append(content if isinstance(content, str) else
                           " ".join(c.get("text", "") for c in content if isinstance(c, dict)))
        if m.get("isSidechain"):
            continue
        for c in content if isinstance(content, list) else []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion":
                asked.add(c.get("id"))
            elif isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in asked:
                out.append(c["content"] if isinstance(c.get("content"), str) else json.dumps(c.get("content")))
    return out


def human_messages_since(transcript: str | Path, since: dt.datetime) -> list[str]:
    """What the human typed in the main session at or after `since` (to the minute, as the ledger records it). Answers
    in the question dialog are left out: their words are options the agent wrote. The guard reads this before a human
    checkpoint closes (spec K-2, apiary.hook)."""
    out: list[str] = []
    for raw in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(m, dict) or not _is_human(m) or not isinstance(m.get("timestamp"), str):
            continue
        try:
            when = _time(m["timestamp"]).replace(second=0, microsecond=0)
        except ValueError:
            continue
        if when < since:
            continue
        content = (m.get("message") or {}).get("content")
        out.append(content if isinstance(content, str) else
                   " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"))
    return out


def measure(session: str | Path) -> dict:
    session = Path(session)
    subagents = sorted((session.with_suffix("") / "subagents").glob("*.jsonl"))
    totals = {k: 0 for k in TOKEN_KEYS}
    web = {"web_search_requests": 0, "web_fetch_requests": 0}
    models: Counter = Counter()
    seen: dict = {}
    times: list[dt.datetime] = []
    human = answers = compactions = 0
    first_context: list[int] = []
    started: set = set()
    tools_of: dict = {}                 # subagent call -> tool names it used
    asked: set = set()
    for path in [session, *subagents]:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                m = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if m.get("timestamp"):
                times.append(_time(m["timestamp"]))
            if m.get("type") == "system" and m.get("subtype") == "compact_boundary":
                compactions += 1          # the context ran full and was summarised
            if path == session and _is_human(m):
                human += 1
            msg = m.get("message") if isinstance(m.get("message"), dict) else {}
            if path != session and msg.get("usage") and isinstance(msg.get("content"), list):
                names = tools_of.setdefault((msg.get("id"), m.get("requestId")), set())
                names.update(c.get("name") for c in msg["content"] if isinstance(c, dict) and c.get("type") == "tool_use")
            if path == session and isinstance(msg.get("content"), list):
                # The human can also answer in the question dialog; that comes back as a tool result.
                for c in msg["content"]:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "tool_use" and c.get("name") == "AskUserQuestion":
                        asked.add(c.get("id"))
                    elif c.get("type") == "tool_result" and c.get("tool_use_id") in asked:
                        answers += 1
            usage = msg.get("usage")
            if not usage:
                continue
            key = (msg.get("id"), m.get("requestId"), path.name if msg.get("id") is None else "")
            out = usage.get("output_tokens") or 0
            if key in seen:
                # A line written mid-stream can carry a partial output count; keep the call's largest.
                if out > seen[key]:
                    totals["output_tokens"] += out - seen[key]
                    seen[key] = out
                continue
            seen[key] = out
            if path != session and path.name not in started:
                started.add(path.name)
                first_context.append(sum(usage.get(k) or 0 for k in TOKEN_KEYS[:3]))
            models[msg.get("model", "unknown")] += 1
            for k in TOKEN_KEYS:
                totals[k] += usage.get(k) or 0
            for k in web:
                web[k] += (usage.get("server_tool_use") or {}).get(k) or 0
    return {"session": str(session), "subagents": len(subagents), "calls": len(seen), "compactions": compactions,
            "subagent_first_context": first_context, "subagent_calls": len(tools_of),
            "bookkeeping_calls": sum(1 for names in tools_of.values() if names and names <= BOOKKEEPING),
            **totals,
            "total_tokens": sum(totals.values()), **web,
            "wall_seconds": round((max(times) - min(times)).total_seconds()) if times else 0,
            "started": min(times).isoformat() if times else "", "human_messages": human,
            "question_answers": answers, "interventions": max(human - 1, 0) + answers, "models": dict(models)}
