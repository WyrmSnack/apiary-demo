"""Knowledge cards: the Nurse organises what it learns as Concept, Tool, Workflow and Playbook cards, in the format of
Kevin's Digital-ToolBox (Data-Engineering-Vault, surveyed read-only 2026-10-16), so the toolbox can be absorbed later.
"""
import subprocess
import sys

import pytest

from apiary.cli import main
from apiary.gates.knowledge import check, front_matter
from apiary.hook import decide


def card(kind, name, sections, related="", sources=("https://docs.blender.org/manual/",), extra=""):
    folder = {"concept": "Concepts", "tool": "Tools", "workflow": "Workflows", "playbook": "Playbooks"}[kind]
    layer = {"concept": "atomic", "tool": "atomic", "workflow": "molecular", "playbook": "organism"}[kind]
    src = "\n".join(f"- {s}" for s in sources)
    body = "\n\n".join(f"## {s}\n\nReal content about {name} and {s.lower()}." for s in sections)
    return folder, (f"---\ntype: {kind}\nlayer: {layer}\ncomplexity: intermediate\nai_consumable: true\n"
                    f"tags:\n- {kind}\nuse_cases:\n- Why {name} matters.\nmas_integration:\n- orchestration\n"
                    f"sources:\n{src}\n{extra}---\n\n# {kind.title()} Card: {name}\n\n{body}\n\n"
                    f"## Related Cards\n\n{related}\n")


TOOL = ["Definition", "Installation & Setup", "Core Capabilities", "Limitations & Gotchas", "References"]
CONCEPT = ["Definition", "Core Principles", "Examples in Practice", "References"]
WORKFLOW = ["Definition", "Typical Pipeline Stages", "Quick Notes & Best Practices", "References"]
PLAYBOOK = ["Definition", "Scope & Assumptions", "Constituent Cards", "End-to-End Pipeline Stages", "References"]


def write(root, kind, name, sections, **kw):
    folder, text = card(kind, name, sections, **kw)
    p = root / "knowledge" / folder / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def kb(tmp_path):
    write(tmp_path, "tool", "Blender", TOOL, related="- [[Headless Rendering]]")
    write(tmp_path, "concept", "Headless Rendering", CONCEPT, related="- [[Blender]]")
    write(tmp_path, "workflow", "Render a Logo in Blender", WORKFLOW, related="- [[Blender]]\n- [[Headless Rendering]]")
    write(tmp_path, "playbook", "Brand Asset Pipeline", PLAYBOOK,
          related="- [[Render a Logo in Blender]]\n- [[Blender]]")
    return tmp_path / "knowledge"


def test_a_well_formed_knowledge_base_passes(kb):
    assert check(kb) == []


def test_front_matter_lists_and_scalars_parse(kb):
    fm = front_matter((kb / "Tools" / "Blender.md").read_text(encoding="utf-8"))
    assert fm["type"] == "tool" and fm["tags"] == ["tool"] and fm["sources"] == ["https://docs.blender.org/manual/"]


@pytest.mark.parametrize("mutate,expected", [
    (lambda t: t.replace("type: tool", "type: concept"), "folder"),
    (lambda t: t.replace("layer: atomic", "layer: organism"), "layer"),
    (lambda t: t.replace("complexity: intermediate", "complexity: expert"), "complexity"),
    (lambda t: t.replace("- https://docs.blender.org/manual/", ""), "sources"),
    (lambda t: t.replace("## Limitations & Gotchas", "## Caveats"), "Limitations & Gotchas"),
    (lambda t: t.replace("# Tool Card: Blender", "# Tool Card: Blendr"), "title"),
    (lambda t: t.replace("[[Headless Rendering]]", "[[No Such Card]]"), "No Such Card"),
    (lambda t: t + "\nCapability 1\n", "template"),
])
def test_each_problem_is_reported(kb, mutate, expected):
    p = kb / "Tools" / "Blender.md"
    p.write_text(mutate(p.read_text(encoding="utf-8")), encoding="utf-8")
    found = "\n".join(check(kb))
    assert expected in found, (expected, found)


def test_a_playbook_names_at_least_two_constituent_cards(kb):
    p = kb / "Playbooks" / "Brand Asset Pipeline.md"
    p.write_text(p.read_text(encoding="utf-8").replace("- [[Render a Logo in Blender]]\n", ""), encoding="utf-8")
    assert any("Constituent" in x or "at least 2" in x for x in check(kb))


def test_toolbox_style_links_resolve(kb):
    p = kb / "Workflows" / "Render a Logo in Blender.md"
    p.write_text(p.read_text(encoding="utf-8").replace("[[Blender]]", "[[Tool Card: Blender|the tool]]"),
                 encoding="utf-8")
    assert check(kb) == []


def test_research_card_sources_must_exist(kb, tmp_path):
    write(tmp_path, "concept", "Open Graph", CONCEPT, sources=("research/social/og-001",))
    assert any("og-001" in x for x in check(kb))
    (tmp_path / "research" / "social").mkdir(parents=True)
    (tmp_path / "research" / "social" / "og-001.md").write_text("---\nid: og-001\n---\n", encoding="utf-8")
    assert check(kb) == []


def test_runs_as_an_acceptance_command_and_can_check_named_cards(kb):
    ok = subprocess.run([sys.executable, "-m", "apiary.gates.knowledge", str(kb)], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    one = subprocess.run([sys.executable, "-m", "apiary.gates.knowledge", str(kb), "--cards", "Tools/Blender.md"],
                         capture_output=True, text=True)
    assert one.returncode == 0, one.stdout


def test_init_lays_out_the_knowledge_base_and_index_lists_it(tmp_path, capsys):
    main(["--root", str(tmp_path), "init"])
    for folder in ("Concepts", "Tools", "Workflows", "Playbooks"):
        assert (tmp_path / "knowledge" / folder).is_dir()
    for kind in ("Concept", "Tool", "Workflow", "Playbook"):
        assert (tmp_path / "knowledge" / "_templates" / f"{kind} Card Template.md").exists()
    ev = {"tool_name": "Edit", "cwd": str(tmp_path),
          "tool_input": {"file_path": str(tmp_path / "knowledge/_templates/Tool Card Template.md")}}
    assert not decide(ev, tmp_path)[0]
    write(tmp_path, "tool", "Blender", TOOL)
    capsys.readouterr()
    assert main(["--root", str(tmp_path), "knowledge", "index"]) == 0
    index = (tmp_path / "knowledge" / "INDEX.md").read_text(encoding="utf-8")
    assert "## Tools" in index and "[[Blender]]" in index and "Why Blender matters." in index


def test_the_queen_plans_a_knowledge_step_after_verification(tmp_path):
    """Phase 5 gate (c): the research lane wrote research/ only, so no knowledge cards were filed. The Queen must plan
    the filing step, with named card files in writes and the knowledge check as its acceptance."""
    main(["--root", str(tmp_path), "init"])
    queen = (tmp_path / "castes" / "queen.md").read_text(encoding="utf-8")
    plan = (tmp_path / ".claude/skills/colony-plan/SKILL.md").read_text(encoding="utf-8")
    for text in (queen, plan):
        assert "python -m apiary.gates.knowledge" in text and "knowledge/Tools/" in text


def test_the_nurse_files_knowledge_by_kind(tmp_path):
    main(["--root", str(tmp_path), "init"])
    nurse = (tmp_path / "castes" / "nurse.md").read_text(encoding="utf-8")
    for phrase in ("knowledge/", "Concept", "Tool", "Workflow", "Playbook", "python -m apiary.gates.knowledge",
                   "update the existing card", "_templates"):
        assert phrase in nurse, phrase
