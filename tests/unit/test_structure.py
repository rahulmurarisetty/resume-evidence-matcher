from datetime import date

import pytest

from app.models import FileType, ResumeDocument, Role, Section, Span, SpanKind
from app.services.extraction import extract_resume
from app.services.structure import (
    find_metrics,
    merged_months,
    parse_profile,
    split_title_employer,
    to_years,
)
from tests.builders import build_docx, build_pdf

TODAY = date(2026, 11, 8)

H, B, L = SpanKind.HEADING, SpanKind.BULLET, SpanKind.LINE


def _resume(*spans: tuple[str, Section, SpanKind]) -> ResumeDocument:
    return ResumeDocument(
        file_type=FileType.PDF,
        page_count=1,
        spans=[
            Span(id=f"s{i}", text=text, kind=kind, section=section, page=1, order=i)
            for i, (text, section, kind) in enumerate(spans)
        ],
    )


def _experience(*lines: tuple[str, SpanKind]) -> ResumeDocument:
    return _resume(
        ("EXPERIENCE", Section.EXPERIENCE, H),
        *((text, Section.EXPERIENCE, kind) for text, kind in lines),
    )


def _one_role(header: str) -> Role:
    profile = parse_profile(_experience((header, L), ("Built things", B)), today=TODAY)
    assert len(profile.roles) == 1, profile
    return profile.roles[0]


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "start", "end", "months"),
    [
        ("Data Engineer, Example Corp | Mar 2022 - May 2024", "2022-03", "2024-05", 27),
        ("Data Engineer, Example Corp | March 2022 - May 2024", "2022-03", "2024-05", 27),
        ("Data Engineer, Example Corp | 03/2022 - 05/2024", "2022-03", "2024-05", 27),
        ("Data Engineer, Example Corp | 2022-03 - 2024-05", "2022-03", "2024-05", 27),
        ("Data Engineer, Example Corp | Mar 2022 \u2013 May 2024", "2022-03", "2024-05", 27),
        ("Data Engineer, Example Corp | Mar 2022 to May 2024", "2022-03", "2024-05", 27),
        ("Data Engineer, Example Corp | Sept. 2019 - Jan 2020", "2019-09", "2020-01", 5),
        ("Data Engineer, Example Corp | Jan 2020 - Jan 2020", "2020-01", "2020-01", 1),
        # A year without a month: January for the start, December for the end.
        ("Data Engineer, Example Corp | 2019 - 2021", "2019-01", "2021-12", 36),
        ("Data Engineer, Example Corp | 2019-2021", "2019-01", "2021-12", 36),
    ],
)
def test_date_formats(header: str, start: str, end: str, months: int) -> None:
    role = _one_role(header)
    assert (role.start, role.end, role.months, role.is_current) == (start, end, months, False)


@pytest.mark.parametrize("word", ["Present", "Current", "Now", "Till date", "present"])
def test_current_role_runs_to_today(word: str) -> None:
    role = _one_role(f"Data Engineer, Example Corp | Mar 2022 - {word}")
    assert role.is_current
    assert role.end is None
    # March 2022 through November 2026, both months counted.
    assert role.months == 57


def test_today_is_injectable() -> None:
    resume = _experience(("Data Engineer, Example Corp | Jan 2020 - Present", L))
    assert parse_profile(resume, today=date(2020, 12, 31)).total_years == 1.0
    assert parse_profile(resume, today=date(2022, 6, 1)).total_years == 2.5
    assert parse_profile(resume).total_years is not None  # defaults to the real date


def test_year_only_dates_warn() -> None:
    profile = parse_profile(
        _experience(("Example Corp - Data Analyst (2019 - 2021)", L), ("Built things", B)),
        today=TODAY,
    )
    assert any("year without a month" in w for w in profile.warnings)


# ---------------------------------------------------------------------------
# Header variants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "title", "employer"),
    [
        (
            "Senior Data Engineer, Example Mutual Insurance | Mar 2022 - Present",
            "Senior Data Engineer",
            "Example Mutual Insurance",
        ),
        ("Example Corp - Data Analyst (2019 - 2021)", "Data Analyst", "Example Corp"),
        ("Data Analyst at Example Corp, Jun 2019 \u2013 Feb 2022", "Data Analyst", "Example Corp"),
        (
            "Data Analyst | Example Corp | Jun 2019 - Feb 2022 | Tampa, FL",
            "Data Analyst",
            "Example Corp",
        ),
        ("Example Corp | Data Analyst | Jun 2019 - Feb 2022", "Data Analyst", "Example Corp"),
        ("Jun 2019 - Feb 2022 | Data Analyst, Example Corp", "Data Analyst", "Example Corp"),
        ("Data Analyst Jun 2019 - Feb 2022", "Data Analyst", None),
    ],
)
def test_header_variants(header: str, title: str, employer: str | None) -> None:
    role = _one_role(header)
    assert (role.title, role.employer) == (title, employer)
    assert role.months is not None


def test_split_title_employer_edge_cases() -> None:
    assert split_title_employer("") == (None, None)
    assert split_title_employer("Example Corp, Inc.") == ("Example Corp", "Inc.")


def test_dates_on_their_own_line_after_the_header() -> None:
    profile = parse_profile(
        _experience(
            ("Data Engineer, Example Corp", L),
            ("Jun 2019 - Feb 2022", L),
            ("Built pipelines", B),
            ("Analyst, Sample Group", L),
            ("Mar 2017 - May 2019 | Tampa, FL", L),
            ("Wrote reports", B),
        ),
        today=TODAY,
    )
    first, second = profile.roles
    assert (first.title, first.employer, first.start, first.end) == (
        "Data Engineer",
        "Example Corp",
        "2019-06",
        "2022-02",
    )
    assert first.header_span_id == "s1"
    assert "s3" in first.bullet_span_ids
    assert (second.title, second.start, second.end) == ("Analyst", "2017-03", "2019-05")
    assert second.bullet_span_ids[-1] == "s6"


def test_styled_heading_role_lines_count_as_headers() -> None:
    # Word resumes often style role lines as "Heading 2"; extraction keeps them as
    # headings inside the experience section.
    profile = parse_profile(
        _experience(("Data Engineer, Example Corp | Mar 2022 - Present", H), ("Built it", B)),
        today=TODAY,
    )
    assert profile.roles[0].title == "Data Engineer"
    assert profile.roles[0].bullet_span_ids == ["s2"]


def test_bullets_attach_to_the_right_role(data_engineer_markup: str) -> None:
    profile = parse_profile(extract_resume(build_pdf(data_engineer_markup)), today=TODAY)
    senior, earlier = profile.roles
    assert senior.header_span_id == "s5"
    assert senior.bullet_span_ids == ["s6", "s7", "s8", "s9", "s10"]
    assert earlier.header_span_id == "s11"
    assert earlier.bullet_span_ids == ["s12", "s13", "s14"]


def test_body_lines_are_not_headers() -> None:
    profile = parse_profile(
        _experience(
            ("Data Engineer, Example Corp | Mar 2022 - Present", L),
            ("Promoted to team lead in 2024", L),
            ("Tech stack: Python, SQL, Airflow", L),
            ("Led the migration of the claims warehouse from 2023 - 2024 with three teams.", L),
            ("Built things", B),
        ),
        today=TODAY,
    )
    assert len(profile.roles) == 1
    assert profile.roles[0].bullet_span_ids == ["s2", "s3", "s4", "s5"]
    assert profile.warnings == []


def test_section_change_ends_the_role() -> None:
    resume = _resume(
        ("EXPERIENCE", Section.EXPERIENCE, H),
        ("Data Engineer, Example Corp | Mar 2022 - Present", Section.EXPERIENCE, L),
        ("Built things", Section.EXPERIENCE, B),
        ("SKILLS", Section.SKILLS, H),
        ("Python, SQL", Section.SKILLS, L),
    )
    assert parse_profile(resume, today=TODAY).roles[0].bullet_span_ids == ["s2"]


# ---------------------------------------------------------------------------
# Years
# ---------------------------------------------------------------------------


def test_overlapping_roles_are_counted_once() -> None:
    profile = parse_profile(
        _experience(
            ("Data Engineer, Example Corp | Jan 2020 - Dec 2021", L),
            ("Built things", B),
            ("Instructor, Sample College | Jun 2021 - Jun 2022", L),
            ("Taught things", B),
            ("Analyst, Demo Labs | Jan 2018 - Jun 2018", L),
        ),
        today=TODAY,
    )
    assert [r.months for r in profile.roles] == [24, 13, 6]
    # Jan 2020 to Jun 2022 is 30 months, plus 6 separate months in 2018.
    assert merged_months(profile.roles) == 36
    assert profile.total_years == 3.0


def test_months_math() -> None:
    assert to_years(90) == 7.5
    assert to_years(59) == 4.9
    assert to_years(3) == 0.3  # half up, not to even
    assert merged_months([]) == 0


def test_sample_resumes(data_engineer_markup: str, dotnet_markup: str) -> None:
    jordan = parse_profile(extract_resume(build_pdf(data_engineer_markup)), today=TODAY)
    assert [(r.title, r.employer, r.start, r.end, r.months) for r in jordan.roles] == [
        ("Senior Data Engineer", "Example Mutual Insurance", "2022-03", None, 57),
        ("Data Engineer", "Sample Retail Group", "2019-06", "2022-02", 33),
    ]
    assert jordan.total_years == 7.5
    assert jordan.warnings == []

    riley = parse_profile(extract_resume(build_docx(dotnet_markup)), today=TODAY)
    assert [r.months for r in riley.roles] == [47, 18]
    assert riley.total_years == 5.4


def test_projects_with_dates_are_roles_but_not_years() -> None:
    resume = _resume(
        ("EXPERIENCE", Section.EXPERIENCE, H),
        ("Data Engineer, Example Corp | Jan 2024 - Dec 2024", Section.EXPERIENCE, L),
        ("PROJECTS", Section.PROJECTS, H),
        ("Claims Dashboard | 2020 - 2021", Section.PROJECTS, L),
        ("Built a dashboard in Python", Section.PROJECTS, B),
    )
    profile = parse_profile(resume, today=TODAY)
    project = profile.roles[1]
    assert (project.section, project.title, project.bullet_span_ids) == (
        Section.PROJECTS,
        "Claims Dashboard",
        ["s4"],
    )
    assert profile.total_years == 1.0  # the project's two years aren't experience


def test_projects_without_dates_are_not_roles() -> None:
    resume = _resume(
        ("PROJECTS", Section.PROJECTS, H),
        ("Claims Dashboard, Python", Section.PROJECTS, L),
        ("Built a dashboard", Section.PROJECTS, B),
    )
    assert parse_profile(resume, today=TODAY).roles == []


# ---------------------------------------------------------------------------
# Dates that can't be used
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "warning"),
    [
        ("Data Engineer, Example Corp | Spring 2020 - Fall 2021", "Couldn't read the dates"),
        ("Data Engineer, Example Corp | 13/2020 - Present", "Couldn't read the dates"),
        ("Data Engineer, Example Corp | Mar '22 - Present", "Couldn't read the dates"),
        ("Data Engineer, Example Corp | Mar 2023 - Jan 2021", "ends before it starts"),
        ("Data Engineer, Example Corp | Jan 2027 - Present", "starts after today"),
    ],
)
def test_unusable_dates_warn_instead_of_crashing(header: str, warning: str) -> None:
    profile = parse_profile(_experience((header, L), ("Built things", B)), today=TODAY)
    role = profile.roles[0]
    assert role.months is None
    assert role.title == "Data Engineer"
    assert role.bullet_span_ids == ["s2"]
    assert profile.total_years is None
    assert any(warning in w for w in profile.warnings)
    assert any("No role dates could be read" in w for w in profile.warnings)


def test_future_end_is_counted_up_to_today() -> None:
    profile = parse_profile(
        _experience(("Data Engineer, Example Corp | Jan 2026 - Dec 2027", L)), today=TODAY
    )
    assert profile.roles[0].months == 11
    assert any("ends after today" in w for w in profile.warnings)


def test_no_experience_section() -> None:
    resume = _resume(("SKILLS", Section.SKILLS, H), ("Python, SQL", Section.SKILLS, L))
    profile = parse_profile(resume, today=TODAY)
    assert profile.roles == []
    assert profile.total_years is None
    assert any("No experience section" in w for w in profile.warnings)


# ---------------------------------------------------------------------------
# Education
# ---------------------------------------------------------------------------


def test_education_entries() -> None:
    resume = _resume(
        ("EDUCATION", Section.EDUCATION, H),
        ("B.S. Computer Science, Example State University | 2019", Section.EDUCATION, L),
        ("Master of Science in Data Science", Section.EDUCATION, L),
        ("Sample University, Boston, MA", Section.EDUCATION, L),
        ("Aug 2020 - May 2022", Section.EDUCATION, L),
        ("Relevant coursework: databases, statistics", Section.EDUCATION, L),
        ("MBA, Demo Business School, 2024", Section.EDUCATION, L),
    )
    entries = parse_profile(resume, today=TODAY).education
    assert [(e.degree, e.school, e.year, e.span_ids) for e in entries] == [
        ("B.S. Computer Science", "Example State University", 2019, ["s1"]),
        ("Master of Science in Data Science", "Sample University", 2022, ["s2", "s3", "s4"]),
        ("MBA", "Demo Business School", 2024, ["s6"]),
    ]


# ---------------------------------------------------------------------------
# Measurable results
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "metrics"),
    [
        ("Cut the batch window from 5 hours to 90 minutes.", ["5 hours to 90 minutes"]),
        ("Scheduled and monitored 40+ Airflow DAGs", ["40+"]),
        ("Raised coverage from 35% to 70%.", ["35% to 70%"]),
        ("Saved $1.2M a year in licence fees", ["$1.2M"]),
        ("Made the nightly load 3x faster", ["3x"]),
        ("Migrated 120 stored procedures and 14 reports", ["120", "14"]),
        ("Served about 30,000 monthly users with 99.9% uptime", ["30,000", "99.9%"]),
        ("Answered tickets within 2 days", ["2 days"]),
        ("Grew revenue to \u20ac3.5 million", ["\u20ac3.5 million"]),
        ("Processed 2M records a day", ["2M"]),
    ],
)
def test_finds_metrics(text: str, metrics: list[str]) -> None:
    assert find_metrics(text) == metrics


@pytest.mark.parametrize(
    "text",
    [
        "Moved services to Python 3 and Windows 10",
        "Loaded files from S3 into EC2 jobs",
        "Ran 24/7 on-call in Q3",
        "Worked there from 2019 to 2021",
        "Joined in 2021 and ran two-week sprints",
        "Ran a Tier 1 support rota",
    ],
)
def test_ignores_numbers_that_are_not_results(text: str) -> None:
    assert find_metrics(text) == []


def test_multiplier_needs_the_x_next_to_the_number() -> None:
    assert "3 x" not in find_metrics("Laid out a 3 x 4 grid")
    assert find_metrics("Made it 10\u00d7 faster") == ["10\u00d7"]


def test_metric_bullets_on_the_sample(data_engineer_markup: str) -> None:
    profile = parse_profile(extract_resume(build_pdf(data_engineer_markup)), today=TODAY)
    assert profile.metric_bullets == ["s6", "s7", "s8", "s13"]
    assert profile.metrics["s6"] == ["5 hours to 90 minutes"]
    assert profile.metrics["s8"] == ["40+"]


def test_metrics_only_from_work_bullets_unless_there_are_no_headings() -> None:
    with_headings = _resume(
        ("EXPERIENCE", Section.EXPERIENCE, H),
        ("Cut costs by 20%", Section.EXPERIENCE, B),
        ("AWARDS", Section.OTHER, H),
        ("Top 5 of 200 teams", Section.OTHER, B),
    )
    assert parse_profile(with_headings, today=TODAY).metric_bullets == ["s1"]
    without = _resume(("Cut costs by 20%", Section.HEADER, B), ("Python", Section.HEADER, L))
    assert parse_profile(without, today=TODAY).metric_bullets == ["s0"]
