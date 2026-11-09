#!/usr/bin/env python3
"""Turn pytest JUnit XML failures into GitHub check-run annotations.

Annotations are readable through the API (and in the PR UI) without downloading logs.
Usage: python ci/annotate_junit.py report.xml
"""
import sys
import xml.etree.ElementTree as ET


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(path: str) -> int:
    n = 0
    for case in ET.parse(path).getroot().iter("testcase"):
        for kind in ("failure", "error"):
            el = case.find(kind)
            if el is None:
                continue
            title = f"{case.get('classname')}::{case.get('name')} ({kind})"
            body = ((el.get("message") or "") + "\n" + (el.text or ""))[-3000:]
            print(f"::error title={esc(title)}::{esc(body)}")
            n += 1
    print(f"{n} failing test(s) annotated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
