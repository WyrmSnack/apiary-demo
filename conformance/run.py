"""Run the suite against one implementation and summarise it per spec requirement.

  python conformance/run.py reference            # or: naive | kit | "<command>"
  python conformance/run.py naive --expect-fail   # exit 0 only if the implementation does NOT conform

Writes evidence/conformance-<name>-<platform>.md. Exit status: 0 if the result matches the expectation.
"""
from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def requirement_ids(test_name: str) -> list[str]:
    head = re.match(r"test_((?:[A-Z]\d+_)+)", test_name)
    return [f"{m[0]}-{m[1:]}" for m in head.group(1).strip("_").split("_")] if head else ["?"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("impl")
    ap.add_argument("--expect-fail", action="store_true")
    args = ap.parse_args()
    name = re.sub(r"[^a-z0-9]+", "-", args.impl.lower()).strip("-")[:40] or "custom"
    plat = f"{platform.system().lower()}-py{sys.version_info[0]}{sys.version_info[1]}"
    xml = REPO / "evidence" / f".conformance-{name}.xml"
    xml.parent.mkdir(exist_ok=True)
    try:
        import xdist  # noqa: F401  # each check starts real server processes; run them in parallel
        parallel = ["-n", "auto"]
    except ImportError:
        parallel = []
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *parallel,
                    str(REPO / "conformance"), "--impl", args.impl, f"--junitxml={xml}"], cwd=REPO)

    by_req: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for case in ET.parse(xml).getroot().iter("testcase"):
        ok = not any(child.tag in ("failure", "error") for child in case)
        for req in requirement_ids(case.get("name")):
            by_req[req].append((case.get("name"), ok))
    xml.unlink()

    def key(r: str):
        return (r[0], int(r[2:]) if r[2:].isdigit() else 0)
    total = sum(len(v) for v in by_req.values())
    passed_reqs = [r for r in by_req if all(ok for _, ok in by_req[r])]
    lines = [f"# Conformance: `{args.impl}` on {plat}", "",
             f"Spec v0.9.0. {len(passed_reqs)} of {len(by_req)} requirements tested pass "
             f"({sum(ok for v in by_req.values() for _, ok in v)} of {total} results pass, counting a test "
             "once for each requirement it checks).", "",
             "| Requirement | Result | Failing checks |", "|---|---|---|"]
    for req in sorted(by_req, key=key):
        fails = [n for n, ok in by_req[req] if not ok]
        lines.append(f"| {req} | {'pass' if not fails else 'FAIL'} | {', '.join(fails)} |")
    out = REPO / "evidence" / f"conformance-{name}-{plat}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines[:3]))
    print(f"written: {out.relative_to(REPO)}")

    conforms = len(passed_reqs) == len(by_req)
    if args.expect_fail:
        return 0 if not conforms else 1
    return 0 if conforms else 1


if __name__ == "__main__":
    sys.exit(main())
