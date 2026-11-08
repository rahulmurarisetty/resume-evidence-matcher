from collections.abc import Sequence
from datetime import date

import pytest

from app.models import (
    FileType,
    MatchStatus,
    Priority,
    Requirement,
    ResumeDocument,
    Section,
    Span,
    SpanKind,
)
from app.services.credentials import (
    CredentialContext,
    DegreeLevel,
    combine,
    credential_ask,
    degree_level,
)
from app.services.jd_parser import parse_job_description
from app.services.matcher import build_report, index_evidence, match_requirement
from app.services.questions import question_for
from app.services.skills import SkillCatalog
from app.services.structure import parse_profile

TODAY = date(2026, 11, 1)
H, B, L = SpanKind.HEADING, SpanKind.BULLET, SpanKind.LINE


def _resume(*spans: tuple[str, Section, SpanKind]) -> ResumeDocument:
    return ResumeDocument(
        file_type=FileType.DOCX,
        page_count=None,
        spans=[
            Span(id=f"s{i}", text=text, kind=kind, section=section, page=None, order=i)
            for i, (text, section, kind) in enumerate(spans)
        ],
    )


def _with(education: Sequence[str] = (), certifications: Sequence[str] = ()) -> ResumeDocument:
    spans: list[tuple[str, Section, SpanKind]] = [
        ("EXPERIENCE", Section.EXPERIENCE, H),
        ("Data Engineer, Example Corp | Jan 2019 - Present", Section.EXPERIENCE, L),
        ("Built Python pipelines on AWS and Kubernetes", Section.EXPERIENCE, B),
    ]
    if education:
        spans.append(("EDUCATION", Section.EDUCATION, H))
        spans += [(line, Section.EDUCATION, L) for line in education]
    if certifications:
        spans.append(("CERTIFICATIONS", Section.CERTIFICATIONS, H))
        spans += [(line, Section.CERTIFICATIONS, B) for line in certifications]
    return _resume(*spans)


def _status(catalog: SkillCatalog, requirement: str, resume: ResumeDocument) -> MatchStatus:
    job = parse_job_description(f"Requirements\n- {requirement}\n", catalog)
    report = build_report(resume, job, catalog, today=TODAY)
    [match] = report.matches
    return match.status


# ---------------------------------------------------------------------------
# What a requirement asks for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "level", "fields"),
    [
        (
            "Bachelor's degree in Computer Science or related field",
            DegreeLevel.BACHELOR,
            ("Computer Science",),
        ),
        ("Master's preferred", DegreeLevel.MASTER, ()),
        (
            "BS/MS in Computer Science or Engineering",
            DegreeLevel.BACHELOR,
            ("Computer Science", "Engineering"),
        ),
        ("A master's degree or PhD in a quantitative field", DegreeLevel.MASTER, ()),
        ("PhD in Statistics", DegreeLevel.DOCTORATE, ("Statistics",)),
        ("Degree in Mathematics and 3+ years of Python", DegreeLevel.BACHELOR, ("Mathematics",)),
        ("Associate degree or higher", DegreeLevel.ASSOCIATE, ()),
        ("Bachelor\u2019s degree required", DegreeLevel.BACHELOR, ()),
    ],
)
def test_degree_asks(
    catalog: SkillCatalog, text: str, level: DegreeLevel, fields: tuple[str, ...]
) -> None:
    ask = credential_ask(text, catalog)
    assert ask is not None and ask.kind == "degree"
    assert (ask.level, ask.fields) == (level, fields)


@pytest.mark.parametrize(
    "text",
    [
        "Experience with MS Excel and MS SQL",
        "Scrum Master experience",
        "Experience managing SSL certificates",
        "Strong Python skills",
        "5+ years of experience",
        "Built 360-degree feedback tools",
        "Master data management with Informatica",
    ],
)
def test_not_credential_asks(catalog: SkillCatalog, text: str) -> None:
    assert credential_ask(text, catalog) is None


def test_certification_asks(catalog: SkillCatalog) -> None:
    aws = credential_ask("AWS Certified Solutions Architect", catalog)
    assert aws is not None and aws.kind == "certification"
    assert (aws.name, aws.keys, aws.any_cert) == ("AWS certification", {"AWS"}, False)
    cka = credential_ask("Certified Kubernetes Administrator (CKA) or similar", catalog)
    assert cka is not None and cka.keys == {"Kubernetes", "CKA"} and cka.any_cert
    generic = credential_ask("Relevant certifications are a plus", catalog)
    assert generic is not None and generic.keys == frozenset() and generic.name == "Certification"
    pmp = credential_ask("PMP or Scrum Master certification", catalog)
    assert pmp is not None and pmp.kind == "certification" and "PMP" in pmp.keys


def test_degree_levels_in_education_lines() -> None:
    assert degree_level("B.S. Computer Science") is DegreeLevel.BACHELOR
    assert degree_level("Master of Science in Data Science") is DegreeLevel.MASTER
    assert degree_level("MBA") is DegreeLevel.MASTER
    assert degree_level("Ph.D. Physics") is DegreeLevel.DOCTORATE
    assert degree_level("B.Tech Electronics") is DegreeLevel.BACHELOR
    assert degree_level("Associate of Applied Science") is DegreeLevel.ASSOCIATE
    assert degree_level("High School Diploma") is None


# ---------------------------------------------------------------------------
# Matching degrees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requirement", "education", "status"),
    [
        # A named field, at the asked level or higher
        (
            "Bachelor's degree in Computer Science",
            ["B.S. Computer Science, Example University, 2018"],
            MatchStatus.DIRECT,
        ),
        (
            "Bachelor's degree in Computer Science",
            ["M.S. Computer Science, Example University, 2020"],
            MatchStatus.DIRECT,
        ),
        # A related field when the job accepts one
        (
            "Bachelor's degree in Computer Science or a related field",
            ["B.S. Information Systems, Example University, 2018"],
            MatchStatus.DIRECT,
        ),
        (
            "A master's degree in a quantitative field",
            ["M.S. Data Science, Example University, 2019"],
            MatchStatus.DIRECT,
        ),
        ("Bachelor's degree required", ["B.A. History, Example College, 2012"], MatchStatus.DIRECT),
        # A field the rules can't judge: a person checks it
        (
            "Bachelor's degree in Computer Science",
            ["B.A. History, Example College, 2012"],
            MatchStatus.NOT_ASSESSED,
        ),
        (
            "Master's degree in a quantitative field",
            ["M.A. History, Example College, 2014"],
            MatchStatus.NOT_ASSESSED,
        ),
        # Clearly absent: the degrees are at a lower level, or there are none
        (
            "A master's degree or PhD in a quantitative field",
            ["B.S. Mathematics, Example University, 2015"],
            MatchStatus.GAP,
        ),
        ("Bachelor's degree in Computer Science", [], MatchStatus.GAP),
        # Equivalent experience is accepted instead
        (
            "Bachelor's degree in Computer Science or equivalent experience",
            [],
            MatchStatus.NOT_ASSESSED,
        ),
        # The level can't be read
        (
            "Bachelor's degree",
            ["Example University, 2010 - 2014"],
            MatchStatus.NOT_ASSESSED,
        ),
    ],
)
def test_degree_matching(
    catalog: SkillCatalog, requirement: str, education: list[str], status: MatchStatus
) -> None:
    assert _status(catalog, requirement, _with(education=education)) is status


def test_degree_evidence_and_next_step(catalog: SkillCatalog) -> None:
    resume = _with(education=["B.S. Computer Science, Example University, 2018"])
    job = parse_job_description("Requirements\n- Bachelor's degree in Computer Science\n", catalog)
    [match] = build_report(resume, job, catalog, today=TODAY).matches
    [skill] = match.skills
    assert skill.skill == "Bachelor's degree"
    assert [e.text for e in skill.evidence] == ["B.S. Computer Science, Example University, 2018"]
    assert skill.evidence[0].section is Section.EDUCATION
    assert match.next_action.startswith("Shown by your education")


def test_degree_with_years_combines_both_parts(catalog: SkillCatalog) -> None:
    resume = _with(education=["B.S. Computer Science, Example University, 2018"])
    years = "Bachelor's degree in Computer Science and 5+ years of experience"
    assert _status(catalog, years, resume) is MatchStatus.DIRECT  # 7.8 years since 2019
    longer = "Bachelor's degree in Computer Science and 10+ years of experience"
    assert _status(catalog, longer, resume) is MatchStatus.PARTIAL
    java = "Degree in Computer Science and 3+ years of Java"
    assert _status(catalog, java, resume) is MatchStatus.PARTIAL  # no Java in the resume


def test_combine() -> None:
    d, p, g, n = (
        MatchStatus.DIRECT,
        MatchStatus.PARTIAL,
        MatchStatus.GAP,
        MatchStatus.NOT_ASSESSED,
    )
    assert combine([d, d]) is d
    assert combine([g, g]) is g
    assert combine([d, n]) is n
    assert combine([d, g]) is p
    assert combine([n, g]) is p


# ---------------------------------------------------------------------------
# Matching certifications
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requirement", "certifications", "status"),
    [
        (
            "AWS Certified Solutions Architect",
            ["AWS Certified Solutions Architect - Associate, 2024"],
            MatchStatus.DIRECT,
        ),
        # Another certification from the same vendor: a person checks it
        (
            "AWS Certified Solutions Architect",
            ["AWS Certified Developer - Associate"],
            MatchStatus.NOT_ASSESSED,
        ),
        # "or similar" accepts any certification for the skill
        (
            "Certified Kubernetes Administrator (CKA) or similar certification",
            ["Certified Kubernetes Application Developer (CKAD)"],
            MatchStatus.DIRECT,
        ),
        ("ISTQB certification", ["ISTQB Certified Tester Foundation Level"], MatchStatus.DIRECT),
        (
            "Snowflake SnowPro certification (Core or Advanced)",
            ["SnowPro Advanced: Data Engineer, Snowflake"],
            MatchStatus.DIRECT,
        ),
        ("PMP or Scrum Master certification", ["PMP, 2021"], MatchStatus.DIRECT),
        # Clearly absent
        ("AWS Certified Solutions Architect", ["Certified ScrumMaster (CSM)"], MatchStatus.GAP),
        ("ISTQB certification", [], MatchStatus.GAP),
        # A certification without a name: a person decides
        (
            "Relevant certifications are a plus",
            ["Certified ScrumMaster (CSM)"],
            MatchStatus.NOT_ASSESSED,
        ),
        ("Relevant certifications are a plus", [], MatchStatus.GAP),
    ],
)
def test_certification_matching(
    catalog: SkillCatalog, requirement: str, certifications: list[str], status: MatchStatus
) -> None:
    resume = _with(certifications=certifications)
    assert _status(catalog, requirement, resume) is status


def test_a_skill_in_experience_is_not_a_certification(catalog: SkillCatalog) -> None:
    # The resume uses AWS and Kubernetes at work but lists no certification.
    resume = _with()
    assert _status(catalog, "AWS Certified Solutions Architect", resume) is MatchStatus.GAP
    report = build_report(
        resume,
        parse_job_description("Requirements\n- AWS Certified Solutions Architect\n", catalog),
        catalog,
        today=TODAY,
    )
    assert report.missing_required_skills == ["AWS certification"]


def test_certification_lines_outside_their_section(catalog: SkillCatalog) -> None:
    resume = _resume(
        ("SUMMARY", Section.SUMMARY, H),
        (
            "AWS Certified Solutions Architect with eight years on data platforms",
            Section.SUMMARY,
            L,
        ),
    )
    assert _status(catalog, "AWS Certified Solutions Architect", resume) is MatchStatus.DIRECT


def test_match_requirement_without_credentials_is_unchanged(catalog: SkillCatalog) -> None:
    # Callers that don't pass credentials keep the skill rules.
    resume = _with()
    requirement = Requirement(
        id="r0",
        text="AWS Certified Solutions Architect",
        priority=Priority.REQUIRED,
        skills=["AWS"],
    )
    index = index_evidence(resume, ["AWS"], catalog)
    assert match_requirement(requirement, index).status is MatchStatus.DIRECT
    context = CredentialContext(resume, parse_profile(resume, today=TODAY), catalog)
    assert match_requirement(requirement, index, credentials=context).status is MatchStatus.GAP


def test_gap_questions_for_credentials(catalog: SkillCatalog) -> None:
    resume = _with()
    job = parse_job_description(
        "Requirements\n- Master's degree in Statistics\n- ISTQB certification\n", catalog
    )
    report = build_report(resume, job, catalog, today=TODAY)
    questions = [question_for(m, catalog) for m in report.matches]
    assert questions == [
        "Do you have a master's degree in Statistics? If yes, add it to your education "
        "section with the school and the year.",
        "Do you hold an ISTQB certification? If yes, add it with its full name and the year "
        "you earned it.",
    ]


def test_with_article() -> None:
    from app.services.credentials import with_article

    assert with_article("ISTQB certification") == "an ISTQB certification"
    assert with_article("AWS certification") == "an AWS certification"
    assert with_article("PMP certification") == "a PMP certification"
    assert with_article("Kubernetes certification") == "a Kubernetes certification"
    assert with_article("Master's degree") == "a master's degree"
    assert with_article("Associate degree") == "an associate degree"
    assert with_article("Doctorate") == "a doctorate"
    assert with_article("Certification") == "a certification"
