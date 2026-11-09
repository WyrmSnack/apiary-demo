"""Build the public apiary-demo tree from the private apiary-sdk at one pinned commit.

  py tools/export.py                 # writes public/ (its own git repository), then scrub-scans it
  py tools/export.py --commit <sha>  # export another commit of apiary-sdk

Reads apiary-sdk with `git archive` (never writes there), copies only the ALLOWLIST, applies the listed
SUBSTITUTIONS (each must match exactly once, so an upstream change stops the export instead of slipping through),
adds this colony's own files from public-src/, writes EXPORT.md, and fails if the scrub scan finds anything.
public/.git is kept between exports; everything else in public/ is rebuilt.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SDK = HERE.parent / "12-apiary-sdk" / "apiary-sdk"
OUT = HERE / "public"
SRC = HERE / "public-src"
COMMIT = "e704dc9"

# (path in apiary-sdk, path in apiary-demo). A folder takes everything under it at the commit.
ALLOWLIST = [
    ("apiary", "apiary"),
    ("tests", "tests"),
    ("conformance", "conformance"),
    ("spec/vectors", "spec/vectors"),
    ("spec/LICENSE", "spec/LICENSE"),
    ("ci/clean_install_check.py", "ci/clean_install_check.py"),
    ("ci/annotate_junit.py", "ci/annotate_junit.py"),
    ("pyproject.toml", "pyproject.toml"),
    ("requirements-dev.txt", "requirements-dev.txt"),
    ("LICENSE", "LICENSE"),
    ("LICENSING.md", "LICENSING.md"),
    ("CONTRIBUTING.md", "CONTRIBUTING.md"),
    (".gitattributes", ".gitattributes"),
    ("MEASUREMENTS.md", "measurements/MEASUREMENTS.md"),
    ("docs/PHASE6.md", "measurements/method/PHASE6.md"),
    ("docs/PHASE7.md", "measurements/method/PHASE7.md"),
    ("docs/PHASE8.md", "measurements/method/PHASE8.md"),
    ("docs/PHASE9.md", "measurements/method/PHASE9.md"),
    ("bench/skirmish", "bench/skirmish"),
    ("bench/tally", "bench/tally"),
]
# Left out on purpose (see EXPORT.md): tests/test_bench.py needs bench/results, which hold private session paths.
EXCLUDE = {"tests/test_bench.py"}

# (file in apiary-demo, old, new, why). Each old string must occur exactly once.
SUBSTITUTIONS = [
    ("tests/test_hook.py", 'cd "C:/Users/james/AppData/Local/Temp/scratch/reaSASD"',
     'cd "C:/Users/dev/AppData/Local/Temp/scratch/demo"', "a fixture held the author's home folder"),
    ("tests/test_measure.py",
     'project_dir(r"C:\\Users\\james\\Desktop\\ForgeProjects\\my-colony").name == \\\n'
     '        "C--Users-james-Desktop-ForgeProjects-my-colony"',
     'project_dir(r"C:\\Users\\dev\\Desktop\\Projects\\my-colony").name == \\\n'
     '        "C--Users-dev-Desktop-Projects-my-colony"', "a fixture held the author's home folder"),
    ("tests/test_obsidian_guard.py",
     '"/etc/passwd", "C:/Windows/x.md"])\ndef test_an_escape_is_refused',
     '"/etc/passwd",\n'
     '                                 pytest.param("C:/Windows/x.md", marks=pytest.mark.skipif(\n'
     '                                     os.name != "nt", reason="on Linux and macOS this is a folder inside the vault"))])\n'
     'def test_an_escape_is_refused',
     "a Windows drive path is only an escape on Windows; elsewhere it names a folder inside the vault, so the "
     "guard rightly allows it (found by this repository's first Linux CI run)"),
    ("tests/test_migrate.py", "read-only survey of eight under Desktop/ForgeProjects",
     "read-only survey of eight on the author's machine", "a docstring named the author's folders"),
    ("conformance/README.md", "checks an implementation of `spec/SUBSTRATE_SPEC.md` from the outside",
     "checks an implementation of the Colony Substrate Specification (summary: `spec/SUMMARY.md`) from the outside",
     "the full spec text is not in this repository"),
    ("CONTRIBUTING.md", "no weakened tests\n(`authoring-kit/tools/test_weakening.py`)",
     "no weakened tests\n(checked by a tool in the private core)", "the authoring kit is not in this repository"),
]

# Anything matching these stops the export. Generic example addresses are allowed.
SCRUB = re.compile(r"C:[\\/]+Users[\\/]+(?!dev\b)|/Users/(?!dev\b)|/home/(?!runner\b)|\bjames\b|jameskwilkins|"
                   r"@gmail\.com|booz|ForgeProjects|Forge-of-WyrmSnack|gh[pousr]_[A-Za-z0-9]{20,}|sk-ant-|"
                   r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY", re.I)
ALLOWED_EMAILS = {"ci@example.com", "t@example.com", "noreply@anthropic.com"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+")


def archive(commit: str, paths: list[str]) -> tarfile.TarFile:
    data = subprocess.run(["git", "-C", str(SDK), "archive", "--format=tar", commit, *paths],
                          capture_output=True, check=True).stdout
    return tarfile.open(fileobj=io.BytesIO(data))


def scrub(root: Path) -> list[str]:
    hits = []
    for p in sorted(root.rglob("*")):
        if p.is_dir() or ".git" in p.relative_to(root).parts:
            continue
        text = p.read_bytes().decode("utf-8", "replace")
        rel = p.relative_to(root).as_posix()
        for n, line in enumerate(text.splitlines(), 1):
            if rel == "tools/export.py":
                continue
            if SCRUB.search(line) or any(e not in ALLOWED_EMAILS for e in EMAIL.findall(line)
                                         if not e.endswith((".py", ".md", ".json", ".toml"))):
                hits.append(f"{rel}:{n}: {line.strip()[:160]}")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", default=COMMIT)
    args = ap.parse_args()
    full = subprocess.run(["git", "-C", str(SDK), "rev-parse", args.commit], capture_output=True, text=True,
                          check=True).stdout.strip()
    OUT.mkdir(exist_ok=True)
    for child in OUT.iterdir():
        if child.name != ".git":
            shutil.rmtree(child) if child.is_dir() else child.unlink()

    copied: list[str] = []
    for src, dst in ALLOWLIST:
        with archive(full, [src]) as tar:
            for m in tar.getmembers():
                if not m.isfile() or m.name in EXCLUDE:
                    continue
                rel = dst + m.name[len(src):]
                target = OUT / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(m).read())
                copied.append(rel)

    for rel, old, new, _ in SUBSTITUTIONS:
        p = OUT / rel
        text = p.read_bytes().decode("utf-8")
        if text.count(old) != 1:
            print(f"refused: substitution in {rel} matched {text.count(old)} times, not once; upstream changed")
            return 1
        p.write_bytes(text.replace(old, new).encode("utf-8"))

    own: list[str] = []
    for p in sorted(SRC.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            rel = p.relative_to(SRC).as_posix()
            (OUT / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, OUT / rel)
            own.append(rel)
    (OUT / "tools").mkdir(exist_ok=True)
    shutil.copyfile(Path(__file__), OUT / "tools" / "export.py")
    own.append("tools/export.py")

    hits = scrub(OUT)
    digest = hashlib.sha256("".join(sorted(f"{r}\n" for r in copied)).encode()).hexdigest()[:16]
    lines = [
        "# EXPORT",
        "",
        "Written by `tools/export.py`. This repository is built from the private `apiary-sdk` repository; it is not",
        "a fork you can pull from, and it is regenerated rather than edited by hand.",
        "",
        f"- **Source commit:** `{full}` (apiary {re.search(r'version = \"([^\"]+)\"', (OUT / 'pyproject.toml').read_text(encoding='utf-8')).group(1)})",
        f"- **Files copied unchanged from that commit:** {len(copied) - len({s[0] for s in SUBSTITUTIONS})}; "
        f"changed by the substitutions below: {len({s[0] for s in SUBSTITUTIONS})}; written for this repository: {len(own)}",
        f"- **File-list digest:** `{digest}`",
        f"- **Scrub scan:** {'passed, 0 findings' if not hits else f'FAILED, {len(hits)} findings'} "
        "(home folders, the author's private folder names, e-mail addresses, GitHub, Anthropic and AWS tokens, "
        "private keys)",
        "",
        "## What is copied",
        "",
        "| From `apiary-sdk` | To |",
        "|---|---|",
        *[f"| `{s}` | `{d}` |" for s, d in ALLOWLIST],
        "",
        "## What is changed, and why",
        "",
        "| File | Why |",
        "|---|---|",
        *[f"| `{r}` | {why} |" for r, _, _, why in SUBSTITUTIONS],
        "",
        "## What is left out, and why",
        "",
        "| Left out | Why |",
        "|---|---|",
        "| `spec/SUBSTRATE_SPEC.md` (the full spec text) | decided 2026-10-19: the demo carries a summary (`spec/SUMMARY.md`); the vectors and the conformance suite are here in full |",
        "| `bench/results/`, `evidence/` | run records and logs that hold private session paths; their numbers are in `measurements/MEASUREMENTS.md` and the write-ups |",
        "| `tests/test_bench.py` | it reads `bench/results/` (16 tests); the other 673 unit tests are here |",
        "| `authoring-kit/`, `docs/` other than the measurement plans, the realm, the textbook | not part of the demo |",
        "",
    ]
    (OUT / "EXPORT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"exported {len(copied)} files from {full[:12]} and {len(own)} of this colony's own into {OUT}")
    if hits:
        print("SCRUB FAILED:\n" + "\n".join(hits))
        return 1
    print("scrub scan: 0 findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
