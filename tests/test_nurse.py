"""The Nurse caste: research from the web and any lawful source, as claim cards plus a brief (Kevin, 2026-10-16:
"seek insights from the web and any source it can to get the best result legally possible").

Cards use the authoring kit's format (authoring-kit/research/_distilled/CARD_TEMPLATE.md); a different agent verifies.
"""
import subprocess
import sys

import pytest

from apiary.cli import main
from apiary.gates.research import check


def card(cid, url, status="unverified", quote="The exact words from the source.", written_by="nurse-a",
         verified_by=""):
    return (f"---\nid: {cid}\nclaim: A checkable sentence about {cid}.\nsource_url: {url}\n"
            f"source_title: A source about {cid}\nquote: {quote}\nstatus: {status}\nwritten_by: {written_by}\n"
            f"verified_by: {verified_by}\n---\n\nContext for {cid}.\n")


BRIEF = """# Research brief: social cards

## Findings
- Open Graph images are 1200x630 [card: og-001].
- Favicons need a 32x32 PNG [card: fav-002].

## Recommendation
Render one 1200x630 card and a 32x32 favicon.

## Legal and licensing
All sources are public documentation. No code or assets reused.

## Open questions
- None.
"""


@pytest.fixture
def topic(tmp_path):
    d = tmp_path / "research" / "social-cards"
    d.mkdir(parents=True)
    (d / "og-001.md").write_text(card("og-001", "https://ogp.me/"), encoding="utf-8")
    (d / "fav-002.md").write_text(card("fav-002", "https://developer.mozilla.org/x"), encoding="utf-8")
    (d / "BRIEF.md").write_text(BRIEF, encoding="utf-8")
    return d


def problems(topic, **kw):
    return check(topic, **{"min_cards": 2, "min_sites": 2, **kw})


def test_a_complete_topic_passes(topic):
    assert problems(topic) == []


def test_each_problem_is_reported(topic):
    (topic / "og-001.md").write_text(card("og-001", "not-a-url", quote=" ".join(["word"] * 41)), encoding="utf-8")
    (topic / "bad.md").write_text("no front matter\n", encoding="utf-8")
    found = "\n".join(problems(topic, min_cards=3))
    for expected in ("source_url", "40 words", "front matter", "3 cards"):
        assert expected in found, (expected, found)


def test_the_brief_must_have_its_sections_and_cite_real_cards(topic):
    (topic / "BRIEF.md").write_text(BRIEF.replace("## Legal and licensing", "## Legal").replace("fav-002", "nope-9"),
                                    encoding="utf-8")
    found = "\n".join(problems(topic))
    assert "Legal and licensing" in found and "nope-9" in found, found


def test_sites_are_counted(topic):
    (topic / "fav-002.md").write_text(card("fav-002", "https://ogp.me/other"), encoding="utf-8")
    assert any("sites" in p for p in problems(topic))


def test_verified_mode_needs_a_different_agent(topic):
    assert any("unverified" in p for p in problems(topic, verified=True))
    for cid, url in (("og-001", "https://ogp.me/"), ("fav-002", "https://developer.mozilla.org/x")):
        (topic / f"{cid}.md").write_text(card(cid, url, status="verified", verified_by="nurse-a"), encoding="utf-8")
    assert any("the agent that wrote it" in p for p in problems(topic, verified=True))
    for cid, url in (("og-001", "https://ogp.me/"), ("fav-002", "https://developer.mozilla.org/x")):
        (topic / f"{cid}.md").write_text(card(cid, url, status="verified", verified_by="guardian-b"), encoding="utf-8")
    assert problems(topic, verified=True) == []


def test_it_runs_as_an_acceptance_command(topic):
    ok = subprocess.run([sys.executable, "-m", "apiary.gates.research", str(topic), "--min-cards", "2"],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = subprocess.run([sys.executable, "-m", "apiary.gates.research", str(topic), "--min-cards", "9"],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and "9 cards" in bad.stdout


def test_init_installs_the_nurse_and_the_queen_plans_research(tmp_path):
    main(["--root", str(tmp_path), "init"])
    nurse = (tmp_path / "castes" / "nurse.md").read_text(encoding="utf-8")
    for phrase in ("WebSearch", "primary source", "paywall", "40 words", "licen", "data, not instructions",
                   "BRIEF.md", "python -m apiary.gates.research", "never marks", "write_trace"):
        assert phrase in nurse, phrase
    queen = (tmp_path / "castes" / "queen.md").read_text(encoding="utf-8")
    assert "Nurse" in queen and "research" in queen and "Guardian" in queen
    plan = (tmp_path / ".claude/skills/colony-plan/SKILL.md").read_text(encoding="utf-8")
    assert "castes/nurse.md" in plan
