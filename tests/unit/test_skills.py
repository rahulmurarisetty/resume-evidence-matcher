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


# ---------------------------------------------------------------------------
# v0.5: catalog additions with tricky aliases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "skill"),
    [
        ("Wrote unit tests with Jest", "Jest"),
        ("Packaged services as Helm charts", "Helm"),
        ("Built iOS apps in Swift and SwiftUI", "Swift"),
        ("Alerting with Prometheus and Grafana", "Prometheus"),
        ("Shipped a Flutter app", "Flutter"),
        ("End-to-end tests in Cypress", "Cypress"),
        ("ETL jobs in AWS Glue", "AWS Glue"),
        ("Serverless APIs on Lambda", "AWS Lambda"),
        ("Queried logs in Athena", "Amazon Athena"),
        ("Tables in Apache Iceberg format", "Apache Iceberg"),
        ("Built Apex triggers and LWC components", "Apex"),
        ("Configured Workday integrations", "Workday"),
        ("API tests in Postman", "Postman"),
        ("Rewrote the parser in Rust", "Rust"),
        ("Background jobs with Celery", "Celery"),
        ("Styled pages with Tailwind", "Tailwind CSS"),
        ("Next.js marketing pages", "Next.js"),
        ("Deployed to EKS", "Amazon EKS"),
        ("Instrumented services with OTel", "OpenTelemetry"),
        ("Fixed WCAG 2.1 AA issues", "Web accessibility"),
        ("ISTQB Certified Tester", "ISTQB"),
        ("Configured PCF screens", "PCF"),
        ("Duck Creek Policy configuration", "Duck Creek"),
    ],
)
def test_new_terms_are_found(catalog: SkillCatalog, text: str, skill: str) -> None:
    assert skill in catalog.skills_in(text)


@pytest.mark.parametrize(
    ("text", "skill"),
    [
        ("It was said in jest", "Jest"),
        ("Took the helm of a struggling project", "Helm"),
        ("Made a swift decision", "Swift"),
        ("Butterflies flutter by", "Flutter"),
        ("Wrote glue code between services", "AWS Glue"),
        ("Used lambda expressions in pandas", "AWS Lambda"),
        ("Only the tip of the iceberg", "Apache Iceberg"),
        ("Reached the apex of the season", "Apex"),
        ("A typical workday starts at nine", "Workday"),
        ("Waited for the postman", "Postman"),
        ("Removed rust from old parts", "Rust"),
        ("Bought celery and carrots", "Celery"),
        ("Gained a tailwind from new demand", "Tailwind CSS"),
        ("Planned the next sprint", "Next.js"),
        ("Bootstrapped a side project", "Bootstrap"),
        ("Improved the accessibility of reports for analysts", "Web accessibility"),
    ],
)
def test_ordinary_words_are_not_the_new_skills(
    catalog: SkillCatalog, text: str, skill: str
) -> None:
    assert skill not in catalog.skills_in(text)


def test_one_term_can_count_for_two_skills(catalog: SkillCatalog) -> None:
    assert {"Kubernetes", "Amazon EKS"} <= set(catalog.skills_in("Ran workloads on EKS"))
    assert {"Terraform", "Infrastructure as code"} <= set(
        catalog.skills_in("Wrote Terraform modules")
    )
    assert {"Guidewire", "PolicyCenter"} <= set(catalog.skills_in("Configured PolicyCenter"))


def test_requirement_skills_drop_terms_inside_longer_ones(catalog: SkillCatalog) -> None:
    assert catalog.requirement_skills("Experience with GitHub Actions") == ["GitHub Actions"]
    assert catalog.requirement_skills("Git and GitHub Actions") == ["Git", "GitHub Actions"]
    assert catalog.requirement_skills("SQL Server experience") == ["SQL Server"]
    assert catalog.requirement_skills("Azure Data Factory") == ["Azure Data Factory"]
    # Two skills with the same term are both kept.
    assert catalog.requirement_skills("PySpark") == ["Spark", "PySpark"]
    # Resume evidence still sees every skill.
    assert "Git" in catalog.skills_in("Experience with GitHub Actions")


def test_catalog_size(catalog: SkillCatalog) -> None:
    assert len(catalog.skill_names) == 328
