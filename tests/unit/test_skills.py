import pytest

from app.services.skills import SkillCatalog


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Built REST APIs in FastAPI", ["REST APIs", "FastAPI"]),
        ("JavaScript and TypeScript", ["JavaScript", "TypeScript"]),
        ("Java/J2EE services", ["Java"]),
        ("C# and C++ code", ["C#", "C++"]),
        ("machine-learning models", ["Machine learning"]),
        ("Python, Go, SQL", ["Python", "Go", "SQL"]),
        ("Tools: Python, R, SAS", ["Python", "R"]),
    ],
)
def test_finds_skills(catalog: SkillCatalog, text: str, expected: list[str]) -> None:
    assert catalog.skills_in(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "We value the rest of the team",  # 'rest' is not REST
        "React quickly to incidents",  # sentence-start verb, but 'quickly' follows
        "Ideas spark innovation",
        "You will excel in a fast paced team",
        "Go-to-market planning",
        "We go to the office twice a week",
        "Our R&D group",
        "Signed by John R. Smith",
        "Traverse each graph node",
    ],
)
def test_ignores_ordinary_words(catalog: SkillCatalog, text: str) -> None:
    hits = catalog.skills_in(text)
    assert "REST APIs" not in hits
    assert "Spark" not in hits
    assert "Excel" not in hits
    assert "Go" not in hits
    assert "R" not in hits
    assert "Node.js" not in hits


def test_react_capitalised_mid_sentence_counts(catalog: SkillCatalog) -> None:
    assert "React" in catalog.skills_in("Built the front end in React and Redux")


def test_does_not_match_inside_longer_words(catalog: SkillCatalog) -> None:
    hits = catalog.skills_in("JavaScript, NoSQL and MySQL")
    assert "Java" not in hits
    assert "SQL" not in hits
    assert {"JavaScript", "NoSQL", "MySQL"} <= set(hits)


def test_variants_map_to_one_skill(catalog: SkillCatalog) -> None:
    hits = catalog.find("ASP.NET Core APIs and VB.NET tools")
    by_skill = {h.skill: h.term for h in hits}
    assert by_skill[".NET"] == "ASP.NET"
    assert by_skill["ASP.NET"] == "ASP.NET Core"


def test_reports_matched_term_and_position(catalog: SkillCatalog) -> None:
    [hit] = catalog.find("Deployed on k8s clusters")
    assert (hit.skill, hit.term) == ("Kubernetes", "k8s")
    assert "Deployed on k8s clusters"[hit.start : hit.end] == "k8s"


def test_catalog_entries_are_valid(catalog: SkillCatalog) -> None:
    names = catalog.skill_names
    assert len(names) == len(set(names)), "duplicate skill names in skills.json"
    assert all(catalog.skills_in(name) or name in {"Go", "R"} for name in names), (
        "every skill name should match itself"
    )
