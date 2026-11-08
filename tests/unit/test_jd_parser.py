import pytest

from app.models import MatchMode, Priority, Seniority
from app.services.jd_parser import parse_job_description
from app.services.skills import SkillCatalog


def _by_text(jd_text: str, catalog: SkillCatalog) -> dict[str, tuple[Priority, list[str]]]:
    job = parse_job_description(jd_text, catalog)
    return {r.text: (r.priority, r.skills) for r in job.requirements}


def test_sample_data_engineer_job(catalog: SkillCatalog, data_engineer_jd: str) -> None:
    job = parse_job_description(data_engineer_jd, catalog)
    assert job.title == "Senior Data Engineer"
    assert job.seniority is Seniority.SENIOR
    assert job.min_years == 5

    reqs = {r.text: r for r in job.requirements}
    assert reqs["Strong Python and SQL"].priority is Priority.REQUIRED
    assert reqs["Experience with dbt"].priority is Priority.PREFERRED
    assert reqs["Insurance industry experience is a plus"].priority is Priority.PREFERRED
    assert reqs["Orchestrate workflows with Airflow and keep them observable"].priority is (
        Priority.CONTEXT
    )
    # Company background, benefits and the EEO line are not requirements.
    texts = " ".join(reqs)
    assert "401(k)" not in texts
    assert "remote-first" not in texts
    assert "equal opportunity" not in texts


def test_sample_dotnet_job(catalog: SkillCatalog, dotnet_jd: str) -> None:
    job = parse_job_description(dotnet_jd, catalog)
    assert job.title == "Full Stack .NET Developer"
    assert job.min_years == 3
    assert job.seniority is Seniority.MID
    reqs = {r.text: r for r in job.requirements}
    # A bullet that contains a heading word is still an item, not a heading.
    assert reqs["Excellent communication skills"].priority is Priority.REQUIRED
    assert reqs["Docker and Kubernetes"].priority is Priority.PREFERRED
    assert all("1962" not in text for text in reqs)


def test_line_level_wording_overrides_section(catalog: SkillCatalog) -> None:
    text = """Responsibilities
- Build data pipelines in Python
- Experience with Kafka is a plus
- Must have strong SQL skills
"""
    reqs = _by_text(text, catalog)
    assert reqs["Build data pipelines in Python"][0] is Priority.CONTEXT
    assert reqs["Experience with Kafka is a plus"][0] is Priority.PREFERRED
    assert reqs["Must have strong SQL skills"][0] is Priority.REQUIRED


def test_alternatives_use_any_of(catalog: SkillCatalog) -> None:
    job = parse_job_description(
        "Requirements\n- Experience with Snowflake or Redshift\n- Python and SQL\n", catalog
    )
    modes = {r.text: r.match_mode for r in job.requirements}
    assert modes["Experience with Snowflake or Redshift"] is MatchMode.ANY
    assert modes["Python and SQL"] is MatchMode.ALL


def test_prose_job_description_is_split_into_sentences(catalog: SkillCatalog) -> None:
    paragraph = (
        "We are hiring a backend engineer to join our platform team and help us scale. "
        "You will build services in Go and PostgreSQL that handle millions of requests. "
        "Experience with Kubernetes is required. Knowledge of Terraform is a plus."
    )
    job = parse_job_description("Backend Engineer\n\nAbout the role\n" + paragraph, catalog)
    reqs = {r.text: r for r in job.requirements}
    assert reqs["Experience with Kubernetes is required."].priority is Priority.REQUIRED
    assert reqs["Knowledge of Terraform is a plus."].priority is Priority.PREFERRED


def test_years_ranges_and_plus(catalog: SkillCatalog) -> None:
    job = parse_job_description(
        "Qualifications\n- 3-5 years of experience\n- 7+ yrs with Java\n", catalog
    )
    assert [r.min_years for r in job.requirements] == [3, 7]


def test_empty_description(catalog: SkillCatalog) -> None:
    job = parse_job_description("", catalog)
    assert job.requirements == []
    assert job.seniority is Seniority.UNKNOWN


# ---------------------------------------------------------------------------
# v0.5: more headings, and lines that aren't requirements
# ---------------------------------------------------------------------------


def _priorities(text: str, catalog: SkillCatalog) -> dict[str, Priority]:
    return {r.text: r.priority for r in parse_job_description(text, catalog).requirements}


@pytest.mark.parametrize(
    ("heading", "priority"),
    [
        ("What you'll need", Priority.REQUIRED),
        ("What we need:", Priority.REQUIRED),
        ("Who you are", Priority.REQUIRED),
        ("You have", Priority.REQUIRED),
        ("YOUR BACKGROUND", Priority.REQUIRED),
        ("Bonus points", Priority.PREFERRED),
        ("Extra credit:", Priority.PREFERRED),
        ("Our stack", Priority.CONTEXT),
        ("In this role, you will:", Priority.CONTEXT),
        ("Essential duties and responsibilities", Priority.CONTEXT),
    ],
)
def test_more_headings_set_the_priority(
    catalog: SkillCatalog, heading: str, priority: Priority
) -> None:
    text = f"Benefits\n- Paid parking\n{heading}\n- Python and Docker\n"
    assert _priorities(text, catalog) == {"Python and Docker": priority}


@pytest.mark.parametrize(
    "heading",
    [
        "What we offer",
        "Perks",
        "Benefits and perks",
        "Compensation",
        "Pay transparency",
        "Location",
        "Work authorization",
        "About the team",
        "About Harbor Insurance Group",
        "WHY JOIN US",
    ],
)
def test_skipped_sections(catalog: SkillCatalog, heading: str) -> None:
    text = f"Requirements\n- Strong SQL\n{heading}\n- Python lunch and learn sessions\n"
    assert _priorities(text, catalog) == {"Strong SQL": Priority.REQUIRED}


def test_unknown_colon_and_capital_headings_end_the_section(catalog: SkillCatalog) -> None:
    text = """Requirements
- Strong SQL
Team Rituals:
- Founded in 2009 to modernize claims with Python
LIFE ON THE TEAM
- Weekly Kafka guild meetups
"""
    priorities = _priorities(text, catalog)
    assert priorities["Strong SQL"] is Priority.REQUIRED
    assert priorities["Founded in 2009 to modernize claims with Python"] is Priority.CONTEXT
    assert priorities["Weekly Kafka guild meetups"] is Priority.CONTEXT


@pytest.mark.parametrize(
    "line",
    [
        "- The base salary range is $120,000 - $145,000.",
        "- Pay: $55/hr on W2",
        "- 401(k) with a 4% match",
        "- Generous PTO and paid holidays",
        "- Medical, dental and vision insurance from day one",
        "- We are an equal opportunity employer.",
        "- We are unable to provide visa sponsorship for this role.",
        "- Candidates must be authorized to work in the United States.",
        "- Reasonable accommodations are available on request.",
        "- Offers are contingent on a background check.",
        "- To apply, email your resume to hiring@example.com.",
        "- Location: Remote (US)",
        "- Employment type: Contract to hire",
    ],
)
def test_boilerplate_is_dropped_without_a_heading(catalog: SkillCatalog, line: str) -> None:
    text = f"Requirements\n- Strong Python skills\n{line}\n"
    assert list(_priorities(text, catalog)) == ["Strong Python skills"]


@pytest.mark.parametrize(
    "line",
    [
        "Experience with health insurance claims data",
        "Ability to apply statistical methods to pricing",
        "Work with executive sponsors to set priorities in Jira",
        "Knowledge of workers' compensation claims in Guidewire ClaimCenter",
        "Experience building payroll and benefits integrations with Workday",
    ],
)
def test_requirements_with_benefit_words_are_kept(catalog: SkillCatalog, line: str) -> None:
    text = f"Requirements\n- {line}\n"
    assert list(_priorities(text, catalog)) == [line]


def test_boilerplate_sentences_are_cut_from_a_mixed_line(catalog: SkillCatalog) -> None:
    text = (
        "Requirements\n"
        "Experience with Snowflake is required. We offer a competitive salary and benefits. "
        "Send your resume to jobs@example.com.\n"
    )
    assert _priorities(text, catalog) == {
        "Experience with Snowflake is required.": Priority.REQUIRED
    }


def test_posting_lines_and_company_sentences_are_dropped(catalog: SkillCatalog) -> None:
    text = """Job Title: Platform Engineer
Company: Harbor Insurance Group
Client: Example Bank
About the role
Harbor Insurance Group is growing the team that runs its quoting platform.
In this role you will build Kafka consumers in Java.
"""
    job = parse_job_description(text, catalog)
    assert job.title == "Platform Engineer"
    assert [r.text for r in job.requirements] == [
        "In this role you will build Kafka consumers in Java."
    ]


def test_prose_wording_sets_the_priority(catalog: SkillCatalog) -> None:
    paragraph = (
        "You will build the checkout pages in React. We are looking for someone with 3+ years "
        "of front-end experience. You should understand web accessibility standards such as "
        "WCAG. It would be great if you have used GraphQL. Clear writing is essential on our "
        "remote team."
    )
    priorities = _priorities(f"Frontend Engineer\n\n{paragraph}\n", catalog)
    assert priorities == {
        "You will build the checkout pages in React.": Priority.CONTEXT,
        "We are looking for someone with 3+ years of front-end experience.": Priority.REQUIRED,
        "You should understand web accessibility standards such as WCAG.": Priority.REQUIRED,
        "It would be great if you have used GraphQL.": Priority.PREFERRED,
        "Clear writing is essential on our remote team.": Priority.REQUIRED,
    }


def test_familiarity_under_requirements_stays_required(catalog: SkillCatalog) -> None:
    text = "Requirements\n- Familiarity with Git\nResponsibilities\n- Familiarity with Jira\n"
    assert _priorities(text, catalog) == {
        "Familiarity with Git": Priority.REQUIRED,
        "Familiarity with Jira": Priority.PREFERRED,
    }


def test_nested_catalog_terms_ask_for_the_longer_skill(catalog: SkillCatalog) -> None:
    text = (
        "Requirements\n- Experience with Azure DevOps or GitHub Actions\n"
        "- SQL Server and React Native\n- Git and GitHub Actions\n"
    )
    skills = {r.text: r.skills for r in parse_job_description(text, catalog).requirements}
    assert skills == {
        "Experience with Azure DevOps or GitHub Actions": ["Azure DevOps", "GitHub Actions"],
        "SQL Server and React Native": ["SQL Server", "React Native"],
        "Git and GitHub Actions": ["Git", "GitHub Actions"],
    }


def test_all_caps_first_line_is_the_title(catalog: SkillCatalog) -> None:
    text = (
        "SENIOR QA ENGINEER\nJOB SUMMARY\nThe Senior QA Engineer owns test quality.\n"
        "QUALIFICATIONS\n- 5 years of QA experience\n"
    )
    job = parse_job_description(text, catalog)
    assert job.title == "SENIOR QA ENGINEER"
    assert [(r.priority, r.text) for r in job.requirements] == [
        (Priority.CONTEXT, "The Senior QA Engineer owns test quality."),
        (Priority.REQUIRED, "5 years of QA experience"),
    ]


def test_prose_lines_are_split_into_sentences(catalog: SkillCatalog) -> None:
    text = (
        "Data Scientist\nResponsibilities:\n"
        "Build forecasting models in Python. Work with stakeholders to define metrics.\n"
        "Requirements:\n3+ years with SQL and Python. Experience with XGBoost or LightGBM.\n"
    )
    job = parse_job_description(text, catalog)
    assert [(r.priority, r.text, r.min_years) for r in job.requirements] == [
        (Priority.CONTEXT, "Build forecasting models in Python.", None),
        (Priority.CONTEXT, "Work with stakeholders to define metrics.", None),
        (Priority.REQUIRED, "3+ years with SQL and Python.", 3),
        (Priority.REQUIRED, "Experience with XGBoost or LightGBM.", None),
    ]


def test_company_and_logistics_sentences_in_the_preamble(catalog: SkillCatalog) -> None:
    text = (
        "Site Reliability Engineer\n"
        "Northwind Cloud runs a payments platform for 300 banks. The role is remote within "
        "the United States.\n"
        "Experience in financial services is required.\n"
    )
    job = parse_job_description(text, catalog)
    assert [r.text for r in job.requirements] == ["Experience in financial services is required."]
