"""Acceptance check for a Nurse's research topic (castes/nurse.md).

  python -m apiary.gates.research research/<topic> [--min-cards 5] [--min-sites 2] [--verified]

A topic folder holds one claim card per file (the authoring kit's CARD_TEMPLATE.md format) and a BRIEF.md for the
Foragers. The check is structural: it cannot tell whether a source says what a card claims. That is what the
Guardian's verification (--verified) is for, done by a different agent.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REQUIRED = ("id", "claim", "source_url", "source_title", "quote", "status", "written_by")
STATUSES = ("unverified", "verified", "rejected")
SECTIONS = ("## Findings", "## Recommendation", "## Legal and licensing", "## Open questions")
MAX_QUOTE_WORDS = 40
CITE = re.compile(r"\[card:\s*([A-Za-z0-9_-]+)\]")


def front_matter(text: str) -> dict[str, str] | None:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return None


def check(topic: str | Path, min_cards: int = 5, min_sites: int = 2, verified: bool = False) -> list[str]:
    topic = Path(topic)
    if not topic.is_dir():
        return [f"{topic} does not exist"]
    problems: list[str] = []
    cards: dict[str, dict[str, str]] = {}
    for p in sorted(topic.glob("*.md")):
        if p.name.upper() == "BRIEF.MD":
            continue
        fm = front_matter(p.read_text(encoding="utf-8", errors="replace"))
        if fm is None:
            problems.append(f"{p.name}: no front matter (a card starts and ends its fields with '---' lines)")
            continue
        missing = [k for k in REQUIRED if not fm.get(k)]
        if missing:
            problems.append(f"{p.name}: missing {', '.join(missing)}")
        if fm.get("id") and fm["id"] != p.stem:
            problems.append(f"{p.name}: id {fm['id']!r} does not match the file name")
        if fm.get("source_url") and not re.match(r"https?://[^\s/]+", fm["source_url"]):
            problems.append(f"{p.name}: source_url is not an http(s) link")
        words = len(fm.get("quote", "").split())
        if words > MAX_QUOTE_WORDS:
            problems.append(f"{p.name}: quote is {words} words; keep quotes to {MAX_QUOTE_WORDS} words or fewer")
        if fm.get("status") and fm["status"] not in STATUSES:
            problems.append(f"{p.name}: status must be one of {', '.join(STATUSES)}")
        if verified and fm.get("status") == "unverified":
            problems.append(f"{p.name}: still unverified; a Guardian must verify or reject it")
        if verified and fm.get("status") == "verified":
            by = fm.get("verified_by", "")
            if not by:
                problems.append(f"{p.name}: verified but verified_by is empty")
            elif by == fm.get("written_by"):
                problems.append(f"{p.name}: verified by the agent that wrote it; a different agent must verify")
        cards[p.stem] = fm
    usable = {cid: fm for cid, fm in cards.items() if fm.get("status") != "rejected"}
    if len(usable) < min_cards:
        problems.append(f"topic: {len(usable)} usable cards (needs {min_cards} cards)")
    sites = {re.sub(r"^www\.", "", m.group(1).lower()) for fm in usable.values()
             if (m := re.match(r"https?://([^\s/:]+)", fm.get("source_url", "")))}
    if len(sites) < min_sites:
        problems.append(f"topic: sources from {len(sites)} sites (needs {min_sites} different sites)")
    brief = topic / "BRIEF.md"
    if not brief.exists():
        problems.append("BRIEF.md: missing (the summary Foragers read)")
    else:
        text = brief.read_text(encoding="utf-8", errors="replace")
        for section in SECTIONS:
            if not re.search(rf"^{re.escape(section)}\s*$", text, re.M):
                problems.append(f"BRIEF.md: no '{section}' section")
        cited = CITE.findall(text)
        if not cited:
            problems.append("BRIEF.md: cites no cards; mark each finding with [card: <id>]")
        for cid in sorted(set(cited) - set(cards)):
            problems.append(f"BRIEF.md: cites [card: {cid}], which does not exist")
        for cid in sorted(set(cited) & {c for c, fm in cards.items() if fm.get("status") == "rejected"}):
            problems.append(f"BRIEF.md: cites [card: {cid}], which a Guardian rejected")
        if re.search(r"\b(TODO|TBD|FIXME)\b", text):
            problems.append("BRIEF.md: contains a placeholder")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m apiary.gates.research")
    ap.add_argument("topic")
    ap.add_argument("--min-cards", type=int, default=5)
    ap.add_argument("--min-sites", type=int, default=2)
    ap.add_argument("--verified", action="store_true", help="every card verified or rejected by a different agent")
    a = ap.parse_args(argv)
    found = check(a.topic, a.min_cards, a.min_sites, a.verified)
    for line in found:
        print(line)
    print(f"{len(found)} problem(s)" if found else f"research topic {a.topic}: all checks pass")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
