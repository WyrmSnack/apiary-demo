"""`apiary gamedev`: helpers for game projects (Phase 10). The GDScript test runner needs no Godot add-on."""
from __future__ import annotations

from pathlib import Path

GODOT_TEMPLATES = Path(__file__).parent / "templates" / "godot"
RUNNER_FILES = ("case.gd", "run_tests.gd")


def godot_tests(project: str | Path) -> tuple[int, list[str]]:
    """Write tests/case.gd and tests/run_tests.gd into a Godot project. Never overwrites a file that differs."""
    project = Path(project)
    if not (project / "project.godot").is_file():
        return 1, [f"refused: {project} has no project.godot. Make the Godot project first (skill godot-project)."]
    wanted = {name: (GODOT_TEMPLATES / name).read_text(encoding="utf-8") for name in RUNNER_FILES}
    changed = [n for n, text in wanted.items() if (project / "tests" / n).exists()
               and (project / "tests" / n).read_text(encoding="utf-8").replace("\r\n", "\n") != text]
    if changed:
        return 1, [f"refused: tests/{n} exists and differs from apiary's runner; nothing written. Move it aside "
                   "or delete it to get apiary's version." for n in changed]
    report = []
    for name, text in wanted.items():
        path = project / "tests" / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        report.append(f"wrote tests/{name}")
    report.append("run: godot --headless --path <project> --script res://tests/run_tests.gd (through run_connector)")
    return 0, report
