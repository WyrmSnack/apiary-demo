"""Acceptance check for the colony's knowledge base (castes/nurse.md, "Organise what you learned").

  python -m apiary.gates.knowledge knowledge [--cards Tools/Blender.md ...] [--allow-missing-links]

Cards follow the format of Kevin's Digital-ToolBox (Data-Engineering-Vault): one folder per kind of knowledge,
front matter with type, layer, complexity, ai_consumable, tags and use_cases, a "# <Kind> Card: <Name>" title,
"## " sections, and [[Name]] links between cards. The colony adds one field: `sources`, so every card can be traced
to its evidence (web links, or the Nurse's claim cards under research/).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

KINDS = {  # folder -> (type, layer, required sections)
    "Concepts": ("concept", "atomic", ("Definition", "Core Principles", "Examples in Practice", "References",
                                       "Related Cards")),
    "Tools": ("tool", "atomic", ("Definition", "Installation & Setup", "Core Capabilities", "Limitations & Gotchas",
                                 "References", "Related Cards")),
    "Workflows": ("workflow", "molecular", ("Definition", "Typical Pipeline Stages", "Quick Notes & Best Practices",
                                            "References", "Related Cards")),
    "Playbooks": ("playbook", "organism", ("Definition", "Scope & Assumptions", "Constituent Cards",
                                           "End-to-End Pipeline Stages", "References", "Related Cards")),
}
COMPLEXITY = ("beginner", "intermediate", "advanced")
LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
TEMPLATE_TEXT = re.compile(r"^\s*(?:[-*]\s*)?(?:Tip|Capability|Limitation|Principle|Operation|Stage|Doc|Key Term)"
                           r" \d*\s*(?:Title)?\s*$|^\s*…\s*$|One-sentence description", re.M)


def front_matter(text: str) -> dict | None:
    """The YAML subset the cards use: `key: value`, `key:` followed by `- item` lines, and `key: [a, b]`."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    out: dict = {}
    key = None
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        item = re.match(r"^\s*-\s*(.*)$", line)
        if item and key is not None:
            if not isinstance(out.get(key), list):
                out[key] = []
            value = item.group(1).strip().strip("'\"")
            if value:
                out[key].append(value)
            continue
        m = re.match(r"^([A-Za-z_][\w ]*):\s*(.*)$", line)
        if m:
            key, value = m.group(1).strip(), m.group(2).strip()
            if value.startswith("[") and value.endswith("]"):
                out[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            else:
                out[key] = value.strip("'\"") if value else []
    return None


def _cards(kb: Path) -> dict[str, Path]:
    return {p.stem.lower(): p for folder in KINDS for p in sorted((kb / folder).glob("*.md"))}


def _target(link: str) -> str:
    return re.sub(r"^(?:Concept|Tool|Workflow|Playbook) Card:\s*", "", link.strip()).strip().strip("*").lower()


def check(kb: str | Path, cards: list[str] | None = None, allow_missing_links: bool = False) -> list[str]:
    kb = Path(kb)
    if not kb.is_dir():
        return [f"{kb} does not exist"]
    root = kb.parent
    known = _cards(kb)
    targets = [kb / c for c in cards] if cards else list(known.values())
    problems: list[str] = []
    for p in targets:
        rel = p.relative_to(kb).as_posix() if p.is_relative_to(kb) else str(p)
        if p.parent.name not in KINDS or p.parent.parent != kb:
            problems.append(f"{rel}: cards live in {', '.join(KINDS)} directly under {kb.name}/")
            continue
        if not p.exists():
            problems.append(f"{rel}: does not exist")
            continue
        kind, layer, sections = KINDS[p.parent.name]
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = front_matter(text)
        if fm is None:
            problems.append(f"{rel}: no front matter")
            continue
        if fm.get("type") != kind:
            problems.append(f"{rel}: type is {fm.get('type')!r} but the card is in the {p.parent.name} folder")
        if fm.get("layer") != layer:
            problems.append(f"{rel}: layer must be {layer} for a {kind} card")
        if fm.get("complexity") not in COMPLEXITY:
            problems.append(f"{rel}: complexity must be one of {', '.join(COMPLEXITY)}")
        for field in ("ai_consumable", "tags", "use_cases"):
            if not fm.get(field):
                problems.append(f"{rel}: {field} is missing or empty")
        sources = fm.get("sources") if isinstance(fm.get("sources"), list) else []
        if not sources:
            problems.append(f"{rel}: sources is empty; list the web pages or research cards this card rests on")
        for s in sources:
            if re.match(r"https?://\S+", s):
                continue
            path = root / s
            if not (path.exists() or path.with_suffix(".md").exists()):
                problems.append(f"{rel}: source {s} is neither a link nor a file in the colony")
        title = re.search(r"^# (Concept|Tool|Workflow|Playbook) Card:\s*(.+?)\s*$", text, re.M)
        if not title or title.group(1).lower() != kind or title.group(2).strip("* ") != p.stem:
            problems.append(f"{rel}: title must be '# {kind.title()} Card: {p.stem}'")
        for section in sections:
            if not re.search(rf"^## {re.escape(section)}\s*$", text, re.M):
                problems.append(f"{rel}: no '## {section}' section")
        if TEMPLATE_TEXT.search(text):
            problems.append(f"{rel}: template text left in ({TEMPLATE_TEXT.search(text).group(0).strip()!r})")
        written = {_target(m): m.strip() for m in LINK.findall(text)}
        links = set(written)
        if not allow_missing_links:
            for t in sorted(links - set(known)):
                problems.append(f"{rel}: links to [[{written[t]}]], which is not a card in {kb.name}/")
        if kind == "playbook" and len(links) < 2:
            problems.append(f"{rel}: a playbook links at least 2 constituent cards")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m apiary.gates.knowledge")
    ap.add_argument("knowledge", nargs="?", default="knowledge")
    ap.add_argument("--cards", nargs="*", help="check only these cards (paths relative to the knowledge folder)")
    ap.add_argument("--allow-missing-links", action="store_true")
    a = ap.parse_args(argv)
    found = check(a.knowledge, a.cards, a.allow_missing_links)
    for line in found:
        print(line)
    print(f"{len(found)} problem(s)" if found else f"knowledge base {a.knowledge}: all checks pass")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
