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
