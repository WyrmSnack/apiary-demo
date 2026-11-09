"""The story ladder (Phase 10 gate f): manual sections -> user stories -> feature stories -> feature tests -> unit tests.

  python -m apiary.gates.stories docs/stories --stage user  --manual docs/source/manual.html
  python -m apiary.gates.stories docs/stories --stage feature --slice S1
  python -m apiary.gates.stories docs/stories --stage tests   --slice S1     (feature tests named and present)
  python -m apiary.gates.stories docs/stories --stage units   --slice S1     (unit tests named and present)

One story per Markdown file, with front matter:

  ---
  id: US-001                  # US-nnn for a user story, FS-nnn for a feature story
  kind: user                  # user | feature
  title: Zone the city
  slice: S1                   # user stories: the vertical slice that builds it
  source: Building the city; Zones; Power        # user stories: the manual headings it covers, ;-separated
  parent: US-001              # feature stories: the user story it serves
  feature_tests: game/tests/feature/test_zoning.gd          # feature stories, from stage "tests"
  unit_tests: game/tests/unit/test_grid.gd, game/tests/unit/test_zone.gd   # from stage "units"
  ---
  As a <player>, I want <goal>, so that <reason>.

  ## Acceptance criteria
  - ...

Each stage includes the ones before it. The check is structural: it cannot tell whether a story says the right
thing or a test tests it; a Guardian review task does that.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

STAGES = ["user", "feature", "tests", "units"]
ID = re.compile(r"^(US|FS)-\d{3,4}$")


def front(text: str) -> tuple[dict[str, str] | None, str]:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text
    out: dict[str, str] = {}
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return out, "\n".join(lines[i + 1:])
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.split(" #", 1)[0].strip()
    return None, text


def headings(manual: Path) -> list[str]:
    t = manual.read_text(encoding="utf-8", errors="replace")
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", t)
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", h))).strip()
            for h in re.findall(r"(?is)<h[23][^>]*>(.*?)</h[23]>", t)]


def _list(value: str) -> list[str]:
    return [x.strip() for x in re.split(r"[;,]", value or "") if x.strip()]


def check(folder: str | Path, stage: str = "user", manual: str | Path | None = None,
          slice_: str | None = None, story: str | None = None) -> list[str]:
    folder = Path(folder)
    if stage not in STAGES:
        return [f"unknown stage {stage!r} (one of {', '.join(STAGES)})"]
    if not folder.is_dir():
        return [f"{folder} does not exist"]
    problems: list[str] = []
    found: dict[str, tuple[dict, str, str]] = {}
    for p in sorted(folder.rglob("*.md")):
        fm, body = front(p.read_text(encoding="utf-8", errors="replace"))
        name = p.relative_to(folder).as_posix()
        if fm is None:
            problems.append(f"{name}: no front matter (--- ... ---)")
            continue
        sid, kind = fm.get("id", ""), fm.get("kind", "")
        bad = []
        if not ID.match(sid):
            bad.append(f"{name}: id {sid!r} is not US-nnn or FS-nnn")
        if kind not in ("user", "feature"):
            bad.append(f"{name}: kind {kind!r} is not user or feature")
        elif not bad and (kind == "user") != sid.startswith("US"):
            bad.append(f"{name}: kind {kind!r} does not fit id {sid} (US is user, FS is feature)")
        if bad:
            problems += bad
            continue
        if sid in found:
            problems.append(f"{sid} is used twice ({found[sid][2]} and {name})")
            continue
        found[sid] = (fm, body, name)
    users = {k: v for k, v in found.items() if v[0]["kind"] == "user"}
    features = {k: v for k, v in found.items() if v[0]["kind"] == "feature"}
    for sid, (fm, body, name) in users.items():
        if not re.search(r"\bAs an? .+?, I want .+?, so that ", body, re.S):
            problems.append(f"{sid}: needs the story form 'As a <player>, I want <goal>, so that <reason>.'")
        if not re.search(r"(?im)^#+ *Acceptance criteria\s*\n(?:\s*\n)*\s*[-*] \S", body):
            problems.append(f"{sid}: needs an '## Acceptance criteria' list")
        if not fm.get("slice"):
            problems.append(f"{sid}: needs a slice (S1, S2, ...)")
    if manual:
        # ';' only: manual headings contain commas ("Garrisons, bases and forts")
        covered = {s.strip().lower() for v in users.values() for s in v[0].get("source", "").split(";") if s.strip()}
        for h in headings(Path(manual)):
            if h.lower() not in covered:
                problems.append(f"manual section {h!r} is not the source of any user story")
    if stage == "user":
        return problems
    for sid, (fm, body, name) in features.items():
        if fm.get("parent") not in users:
            problems.append(f"{sid}: parent {fm.get('parent')!r} is not a user story")
    if story:                       # one feature story's own rung: its parent, its tests
        if story not in features:
            return [f"no story {story} among the feature stories in {folder}"]
        problems = [p for p in problems if p.startswith(story)]
        wanted = [(story, features[story][0])]
    else:
        in_slice = {k for k, v in users.items() if not slice_ or v[0].get("slice") == slice_}
        for uid in sorted(in_slice):
            if not any(f[0].get("parent") == uid for f in features.values()):
                problems.append(f"{uid}: no feature story has it as parent")
        wanted = [(sid, fm) for sid, (fm, _, _) in features.items() if fm.get("parent") in in_slice]
    for field, from_stage in (("feature_tests", "tests"), ("unit_tests", "units")):
        if STAGES.index(stage) < STAGES.index(from_stage):
            break
        for sid, fm in wanted:
            files = _list(fm.get(field, ""))
            if not files:
                problems.append(f"{sid}: names no {field.replace('_', ' ')}")
            for f in files:
                if not Path(f).is_file():
                    problems.append(f"{sid}: {field} {f} does not exist")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m apiary.gates.stories", description=__doc__.split("\n\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--stage", choices=STAGES, default="user")
    ap.add_argument("--manual")
    ap.add_argument("--slice", dest="slice_")
    ap.add_argument("--story", help="check one feature story only (its parent and its tests)")
    a = ap.parse_args(argv)
    problems = check(a.folder, a.stage, a.manual, a.slice_, a.story)
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        print(f"PASS stories {a.stage}" + (f" {a.slice_}" if a.slice_ else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
