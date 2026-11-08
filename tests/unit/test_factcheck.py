"""The fact checker, one behavior at a time. Every case is written for these tests;
the v0.4 evaluation set in evals/ is not used here."""

import pytest

from app.services.factcheck import FactKind, check_rewrite
from app.services.skills import SkillCatalog


def _kinds(source: str, rewrite: str, catalog: SkillCatalog) -> list[FactKind]:
    return [fact.kind for fact in check_rewrite(source, rewrite, catalog).added]


def _passes(source: str, rewrite: str, catalog: SkillCatalog) -> bool:
    result = check_rewrite(source, rewrite, catalog)
    assert result.passed == (not result.added)
    return result.passed


# -- numbers -------------------------------------------------------------------


@pytest.mark.parametrize(
    "rewrite",
    [
        "Maintained 40 or more dbt models for finance reporting.",
        "Maintained over 40 dbt models for finance reporting.",
        "Maintained more than 40 dbt models for finance reporting.",
        "Maintained 40 dbt models for finance reporting.",  # dropping the "+" is a trim
    ],
)
def test_plus_and_or_more_are_the_same_number(catalog: SkillCatalog, rewrite: str) -> None:
    assert _passes("Maintained 40+ dbt models for finance reporting.", rewrite, catalog)


def test_adding_a_plus_is_a_new_claim(catalog: SkillCatalog) -> None:
    result = check_rewrite(
        "Maintained 40 dbt models for finance reporting.",
        "Maintained 40+ dbt models for finance reporting.",
        catalog,
    )
    assert not result.passed
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.NUMBER, "40+")]


def test_changed_number_fails(catalog: SkillCatalog) -> None:
    result = check_rewrite(
        "Maintained 40+ dbt models for finance reporting.",
        "Maintained 400+ dbt models for finance reporting.",
        catalog,
    )
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.NUMBER, "400+")]
    assert "400+" in result.added[0].reason


@pytest.mark.parametrize(
    ("source", "rewrite"),
    [
        (
            "Cut report generation from 5 hours to 90 minutes.",
            "Reduced report generation from five hours to 90 minutes.",
        ),
        (
            "Cut report generation from 5 hours to 90 minutes.",
            "Cut report generation from 5 hours to 1.5 hours.",
        ),
        ("Answered tickets in 2 days on average.", "Answered tickets in 48 hours on average."),
        (
            "Mentored 3 new hires on the claims codebase.",
            "Mentored three new hires on the claims codebase.",
        ),
        ("Closed thirty-five audit findings.", "Closed 35 audit findings."),
        ("Reviewed code for a dozen interns.", "Reviewed code for 12 interns."),
    ],
)
def test_number_words_and_units_are_normalized(
    catalog: SkillCatalog, source: str, rewrite: str
) -> None:
    assert _passes(source, rewrite, catalog)


def test_a_changed_unit_fails(catalog: SkillCatalog) -> None:
    assert _kinds(
        "Answered tickets in 2 days on average.",
        "Answered tickets in 2 hours on average.",
        catalog,
    ) == [FactKind.NUMBER]


def test_a_range_shares_its_unit(catalog: SkillCatalog) -> None:
    source = "Cut report generation from 5 hours to 90 minutes."
    # "from 5 to 90 minutes" means 5 minutes, which changes the fact.
    assert not _passes(source, "Cut report generation from 5 to 90 minutes.", catalog)
    assert _passes(
        "Cut build time from 25 minutes to 8 minutes.",
        "Cut build time from 25 to 8 minutes.",
        catalog,
    )


@pytest.mark.parametrize(
    ("rewrite", "passes"),
    [
        ("Raised test coverage from 35 percent to 70 percent.", True),
        ("Raised test coverage from 35 to 70%.", True),
        ("Raised test coverage from 35% to 75%.", False),
    ],
)
def test_percentages(catalog: SkillCatalog, rewrite: str, passes: bool) -> None:
    assert _passes("Raised test coverage from 35% to 70%.", rewrite, catalog) is passes


@pytest.mark.parametrize(
    ("rewrite", "passes"),
    [
        ("Found $1,200,000 in duplicate vendor payments.", True),
        ("Found 1.2 million dollars in duplicate vendor payments.", True),
        ("Found $1.5M in duplicate vendor payments.", False),
        ("Found $12M in duplicate vendor payments.", False),
        ("Found 1.2M in duplicate vendor payments.", True),  # dropping the currency
    ],
)
def test_currency(catalog: SkillCatalog, rewrite: str, passes: bool) -> None:
    assert _passes("Found $1.2M in duplicate vendor payments.", rewrite, catalog) is passes


@pytest.mark.parametrize(
    ("rewrite", "passes"),
    [
        ("Shipped 3 to 5 releases a month.", True),
        ("Shipped between 3 and 5 releases a month.", True),
        ("Shipped 3-6 releases a month.", False),
    ],
)
def test_ranges(catalog: SkillCatalog, rewrite: str, passes: bool) -> None:
    assert _passes("Shipped 3-5 releases a month.", rewrite, catalog) is passes


def test_vague_to_specific_team_size_fails(catalog: SkillCatalog) -> None:
    result = check_rewrite(
        "Led a team that rebuilt the billing service in Java.",
        "Led a team of 8 that rebuilt the billing service in Java.",
        catalog,
    )
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.NUMBER, "8")]


@pytest.mark.parametrize(
    "rewrite",
    [
        "Doubled query speed by tuning the search index.",
        "Tuned the search index, making queries twice as fast.",
        "Tuned the search index and halved query latency.",
    ],
)
def test_improved_to_a_multiplier_fails(catalog: SkillCatalog, rewrite: str) -> None:
    kinds = _kinds("Tuned the search index, which improved query latency.", rewrite, catalog)
    assert FactKind.NUMBER in kinds


@pytest.mark.parametrize(
    ("source", "rewrite"),
    [
        ("Made the nightly export 3x faster.", "Made the nightly export three times faster."),
        ("Made the nightly export 3x faster.", "Tripled the speed of the nightly export."),
        ("Labeled 2M support tickets.", "Labeled 2 million support tickets."),
        ("Grew the newsletter to 10k subscribers.", "Grew the newsletter to 10,000 subscribers."),
        ("Kept p95 latency under 200 ms.", "Kept 95th percentile latency below 200 milliseconds."),
    ],
)
def test_multipliers_scales_and_percentiles(
    catalog: SkillCatalog, source: str, rewrite: str
) -> None:
    assert _passes(source, rewrite, catalog)


@pytest.mark.parametrize(
    ("source", "rewrite"),
    [
        ("Kept p95 latency under 200 ms.", "Kept p99 latency under 200 ms."),
        ("Kept p95 latency under 200 ms.", "Kept p95 latency under 150 ms."),
        ("Grew the newsletter to 10k subscribers.", "Grew the newsletter to 100k subscribers."),
        ("Reviewed code for several interns.", "Reviewed code for 6 interns."),
        ("Upgraded the service to Python 3.", "Upgraded the service to Python 3.11."),
        (
            "Migrated the billing service to a new cluster.",
            "Migrated the billing service to a new cluster with zero downtime.",
        ),
        ("Reduced cloud costs.", "Reduced cloud costs by a third."),
    ],
)
def test_added_or_changed_numbers_fail(catalog: SkillCatalog, source: str, rewrite: str) -> None:
    assert FactKind.NUMBER in _kinds(source, rewrite, catalog)


def test_a_bound_must_match(catalog: SkillCatalog) -> None:
    source = "Cut end-to-end delay from 40 seconds to under 5 seconds."
    assert _passes(source, "Cut end-to-end delay from 40 seconds to below 5 seconds.", catalog)
    assert not _passes(source, "Cut end-to-end delay from 40 seconds to under 1 second.", catalog)
    assert not _passes(source, "Cut end-to-end delay from 40 seconds to over 5 seconds.", catalog)


# -- dates -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rewrite", "added"),
    [
        ("In 2021, rolled out SSO for the partner portal.", "2021"),
        ("Rolled out SSO for the partner portal since 2019.", "2019"),
        ("Rolled out SSO for the partner portal in March.", "March"),
        ("Rolled out SSO for the partner portal in Q3.", "Q3"),
    ],
)
def test_added_dates_fail(catalog: SkillCatalog, rewrite: str, added: str) -> None:
    result = check_rewrite("Rolled out SSO for the partner portal.", rewrite, catalog)
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.DATE, added)]


def test_dates_in_the_source_may_stay(catalog: SkillCatalog) -> None:
    assert _passes(
        "Rolled out SSO for the partner portal in March 2021.",
        "In March 2021, rolled out SSO for the partner portal.",
        catalog,
    )


# -- skills and tools ------------------------------------------------------------


def test_added_catalog_skill_fails(catalog: SkillCatalog) -> None:
    result = check_rewrite(
        "Deployed the claims API with Docker.",
        "Deployed the claims API with Docker and Kubernetes.",
        catalog,
    )
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.SKILL, "Kubernetes")]
    assert "Kubernetes" in result.added[0].reason


@pytest.mark.parametrize(
    ("source", "rewrite"),
    [
        (
            "Set up CI/CD for the mobile app.",
            "Set up continuous integration and delivery for the mobile app.",
        ),
        ("Set up continuous integration for the mobile app.", "Set up CI/CD for the mobile app."),
        (
            "Built a retrieval-augmented generation service for policy questions.",
            "Built a RAG service for policy questions.",
        ),
        ("Moved the data to Amazon Web Services.", "Moved the data to AWS."),
        ("Built REST APIs in FastAPI.", "Built RESTful APIs in FastAPI."),
        ("Trained ML models for churn.", "Trained machine learning models for churn."),
    ],
)
def test_acronym_and_expansion_are_the_same_skill(
    catalog: SkillCatalog, source: str, rewrite: str
) -> None:
    assert _passes(source, rewrite, catalog)


def test_a_different_product_in_the_same_family_fails(catalog: SkillCatalog) -> None:
    # The catalog files GitHub and GitLab under Git, but they are different products.
    result = check_rewrite(
        "Moved repositories from GitLab to Bitbucket.",
        "Moved repositories from GitHub to Bitbucket.",
        catalog,
    )
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.NAME, "GitHub")]


def test_free_text_tool_fails_as_a_name(catalog: SkillCatalog) -> None:
    # Soda Core isn't in the catalog, so it is caught as a capitalized name.
    result = check_rewrite(
        "Wrote Python data checks that run before each load.",
        "Wrote Python and Soda Core data checks that run before each load.",
        catalog,
    )
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.NAME, "Soda Core")]


def test_catalog_tools_fail_as_skills(catalog: SkillCatalog) -> None:
    # v0.5 added these to the catalog, so they are reported as skills, not names.
    result = check_rewrite(
        "Wrote Python data checks that run before each load.",
        "Wrote Python and Great Expectations data checks on S3 and EC2 before each load.",
        catalog,
    )
    assert [(f.kind, f.text) for f in result.added] == [
        (FactKind.SKILL, "Great Expectations"),
        (FactKind.SKILL, "S3"),
        (FactKind.SKILL, "EC2"),
    ]


# -- names -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rewrite", "names"),
    [
        ("Built the quoting engine in Python for Acme Corp.", ["Acme Corp"]),
        (
            "Built the quoting engine in Python for Example Mutual and Placeholder Bank.",
            ["Example Mutual", "Placeholder Bank"],
        ),
        ("Built Demo Health's quoting engine in Python.", ["Demo Health"]),
        ("Built the quoting engine in Python on R2 and B2.", ["R2", "B2"]),
    ],
)
def test_added_names_fail(catalog: SkillCatalog, rewrite: str, names: list[str]) -> None:
    result = check_rewrite("Built the quoting engine in Python.", rewrite, catalog)
    assert [f.text for f in result.added if f.kind is FactKind.NAME] == names


@pytest.mark.parametrize(
    ("source", "rewrite"),
    [
        (
            "Deployed services to Azure Kubernetes Service with Helm.",
            "Deployed services to AKS with Helm.",
        ),
        ("Ran batch jobs on EKS.", "Ran batch jobs on Amazon EKS."),
        (
            "Wrote Lambda functions for invoice parsing.",
            "Wrote AWS Lambda functions for invoice parsing.",
        ),
        (
            "Built a Kafka consumer for order events.",
            "Built an Apache Kafka consumer for order events.",
        ),
        ("Reviewed pull requests for the mobile team.", "Reviewed PRs for the mobile team."),
        (
            "Tracked SLAs for 14 vendor feeds.",
            "Tracked service level agreements for 14 vendor feeds.",
        ),
    ],
)
def test_acronyms_and_vendor_names_pass(catalog: SkillCatalog, source: str, rewrite: str) -> None:
    assert _passes(source, rewrite, catalog)


def test_vendor_name_without_its_product_fails(catalog: SkillCatalog) -> None:
    assert FactKind.NAME in _kinds(
        "Wrote functions for invoice parsing.",
        "Wrote Amazon functions for invoice parsing.",
        catalog,
    )


def test_sentence_start_verbs_are_not_names(catalog: SkillCatalog) -> None:
    source = "Analyzed churn with pandas and scikit-learn for the retention team."
    for rewrite in (
        "Operate churn analysis with pandas and scikit-learn for the retention team.",
        "Reconciled churn data with pandas and scikit-learn for the retention team.",
        "For the retention team, analyzed churn with scikit-learn and pandas.",
    ):
        assert FactKind.NAME not in _kinds(source, rewrite, catalog), rewrite


# -- certifications ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("rewrite", "added"),
    [
        (
            "As a Certified Scrum Master, ran sprint planning for the team.",
            "Certified Scrum Master",
        ),
        ("Ran sprint planning for the team as a PMP.", "PMP"),
        ("Ran sprint planning for the team as an Agile-certified lead.", "Agile-certified"),
    ],
)
def test_added_certifications_fail(catalog: SkillCatalog, rewrite: str, added: str) -> None:
    result = check_rewrite("Ran sprint planning for the team.", rewrite, catalog)
    certifications = [f.text for f in result.added if f.kind is FactKind.CERTIFICATION]
    assert certifications == [added]


def test_certification_in_the_source_may_stay(catalog: SkillCatalog) -> None:
    assert _passes(
        "Earned the AWS Certified Developer badge and deployed services to ECS.",
        "Deployed services to ECS and earned the AWS Certified Developer badge.",
        catalog,
    )


# -- scope -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "rewrite",
    [
        "Led the design of the event schema for claims intake.",
        "Architected the event schema for claims intake.",
        "Owned the event schema for claims intake.",
        "Single-handedly built the event schema for claims intake.",
    ],
)
def test_added_leadership_fails(catalog: SkillCatalog, rewrite: str) -> None:
    assert FactKind.SCOPE in _kinds("Built the event schema for claims intake.", rewrite, catalog)


@pytest.mark.parametrize(
    "rewrite",
    [
        "Set up CI/CD for all mobile apps.",
        "Set up CI/CD for the mobile app across the company.",
        "Set up company-wide CI/CD for the mobile app.",
        "Set up end-to-end CI/CD for the mobile app.",
        "Set up CI/CD for the mobile app, eliminating manual releases.",
        "Set up real-time CI/CD for the mobile app.",
        "Set up CI/CD for the mobile app used by executives.",
    ],
)
def test_widened_scope_fails(catalog: SkillCatalog, rewrite: str) -> None:
    assert FactKind.SCOPE in _kinds("Set up CI/CD for the mobile app.", rewrite, catalog)


@pytest.mark.parametrize(
    ("source", "rewrite"),
    [
        (
            "Wrote unit tests for the rating engine.",
            "Wrote unit tests for the rating engine, improving reliability.",
        ),
        (
            "Automated the monthly close checklist.",
            "Automated the monthly close checklist, saving the finance team time.",
        ),
        (
            "Built a cache for the pricing service.",
            "Built a cache for the pricing service, reducing load on the database.",
        ),
    ],
)
def test_added_result_fails(catalog: SkillCatalog, source: str, rewrite: str) -> None:
    assert _kinds(source, rewrite, catalog) == [FactKind.SCOPE]


def test_same_kind_of_result_in_other_words_passes(catalog: SkillCatalog) -> None:
    assert _passes(
        "Cut the nightly load from 3 hours to 40 minutes by partitioning tables.",
        "Reduced the nightly load from 3 hours to 40 minutes by partitioning tables.",
        catalog,
    )
    assert _passes(
        "Sped up the CI pipeline by caching Docker layers.",
        "Accelerated the CI pipeline by caching Docker layers.",
        catalog,
    )


def test_dropping_a_hedge_fails(catalog: SkillCatalog) -> None:
    source = "Helped migrate the warehouse to Snowflake."
    result = check_rewrite(source, "Migrated the warehouse to Snowflake.", catalog)
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.SCOPE, "Helped")]
    assert _passes(source, "Assisted with migrating the warehouse to Snowflake.", catalog)


def test_added_frequency_fails(catalog: SkillCatalog) -> None:
    source = "Processed 25,000 orders with a FastAPI service."
    result = check_rewrite(source, "Processed 25,000 orders daily with a FastAPI service.", catalog)
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.NUMBER, "daily")]
    assert _passes(
        "Processed 25,000 orders a day with a FastAPI service.",
        "Processed 25,000 orders daily with a FastAPI service.",
        catalog,
    )
    assert _passes("Ran weekly design reviews.", "Ran design reviews every week.", catalog)


# -- allowed rewording -------------------------------------------------------------


@pytest.mark.parametrize(
    "rewrite",
    [
        # stronger verb
        "Developed Power BI dashboards for store managers and regional directors.",
        # reordering
        "For store managers and regional directors, built Power BI dashboards.",
        # trimming
        "Built Power BI dashboards for store managers.",
        "Built Power BI dashboards.",
    ],
)
def test_reword_reorder_and_trim_pass(catalog: SkillCatalog, rewrite: str) -> None:
    assert _passes(
        "Built Power BI dashboards for store managers and regional directors.", rewrite, catalog
    )


def test_worked_on_to_a_plain_verb_passes(catalog: SkillCatalog) -> None:
    assert _passes(
        "Worked on building dashboards in Power BI for store managers.",
        "Built Power BI dashboards for store managers.",
        catalog,
    )


def test_bullets_quotes_and_spacing_are_ignored(catalog: SkillCatalog) -> None:
    assert _passes(
        "Built Power BI dashboards for store managers.",
        '- "Built  Power BI dashboards for store managers."',
        catalog,
    )


# -- length and empty --------------------------------------------------------------


def test_empty_and_very_long_rewrites_fail(catalog: SkillCatalog) -> None:
    assert _kinds("Fixed bugs in the billing service.", "", catalog) == [FactKind.LENGTH]
    long = (
        "Fixed bugs in the billing service and in the ledger, reporting, onboarding and "
        "notification services for the mobile and web teams."
    )
    assert FactKind.LENGTH in _kinds("Fixed bugs in the billing service.", long, catalog)


def test_one_fact_per_phrase(catalog: SkillCatalog) -> None:
    # The certification name also contains a catalog skill; it is reported once.
    result = check_rewrite(
        "Ran 14 production EKS clusters with Terraform.",
        "As a Certified Kubernetes Administrator, ran 14 production EKS clusters with Terraform.",
        catalog,
    )
    assert [(f.kind, f.text) for f in result.added] == [
        (FactKind.CERTIFICATION, "Certified Kubernetes Administrator")
    ]


def test_default_catalog_is_used() -> None:
    assert not check_rewrite("Built a service.", "Built a Kafka service.").passed


@pytest.mark.parametrize(
    ("source", "rewrite", "passes"),
    [
        ("Moved 2 TB of claims data to S3.", "Moved 2,000 GB of claims data to S3.", True),
        ("Moved 2 TB of claims data to S3.", "Moved 20 TB of claims data to S3.", False),
        ("Answered hundreds of tickets.", "Answered hundreds of support tickets.", True),
        ("Answered many tickets.", "Answered hundreds of tickets.", False),
        ("Answered a hundred tickets.", "Answered 100 tickets.", True),
        ("Raised USD 5M for the program.", "Raised $5M for the program.", True),
        ("Raised USD 5M for the program.", "Raised EUR 5M for the program.", False),
        ("Shipped the 3rd release of the app.", "Shipped the third release of the app.", True),
        ("Shipped the 3rd release of the app.", "Shipped the 4th release of the app.", False),
        ("Kept the 95th percentile under 2 seconds.", "Kept p95 under 2 seconds.", True),
        ("Kept the queue at 40 or fewer jobs.", "Kept the queue at under 40 jobs.", True),
        ("Kept the queue at 40 jobs.", "Kept the queue at 40 or fewer jobs.", False),
        ("Built 5G network test tools.", "Built 5G and LTE network test tools.", False),
        ("Built the first version of the app.", "Built the first app version.", True),
        ("Wrote tests.", "Wrote tests for Acme and later for Acme.", False),
    ],
)
def test_more_number_forms(catalog: SkillCatalog, source: str, rewrite: str, passes: bool) -> None:
    assert _passes(source, rewrite, catalog) is passes


def test_repeated_facts_are_listed_once(catalog: SkillCatalog) -> None:
    result = check_rewrite(
        "Wrote integration tests for the billing service.",
        "Wrote integration tests for Acme billing, then for the Acme service.",
        catalog,
    )
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.NAME, "Acme")]


def test_certification_name_stops_at_punctuation(catalog: SkillCatalog) -> None:
    result = check_rewrite(
        "Migrated the warehouse.", "Migrated the warehouse as a Certified Data Engineer.", catalog
    )
    assert [f.text for f in result.added] == ["Certified Data Engineer"]


# -- regressions: organizations next to known vendor or skill words -------------

MIGRATION = (
    "Migrated 120 stored procedures from SQL Server to Redshift and documented the data "
    "lineage for each."
)


@pytest.mark.parametrize(
    ("rewrite", "added"),
    [
        (
            "Migrated 120 stored procedures from SQL Server to Redshift at Amazon and "
            "documented the data lineage.",
            (FactKind.NAME, "Amazon"),
        ),
        (
            "At Amazon, migrated 120 stored procedures from SQL Server to Redshift.",
            (FactKind.NAME, "Amazon"),
        ),
        (
            "Migrated 120 stored procedures from SQL Server to AWS and documented the data "
            "lineage for each.",
            (FactKind.SKILL, "AWS"),
        ),
        (
            "Migrated 120 stored procedures from SQL Server to Redshift for Google.",
            (FactKind.NAME, "Google"),
        ),
        (
            "Migrated 120 stored procedures from SQL Server to Redshift with Microsoft.",
            (FactKind.NAME, "Microsoft"),
        ),
    ],
)
def test_vendor_word_on_its_own_is_a_new_name(
    catalog: SkillCatalog, rewrite: str, added: tuple[FactKind, str]
) -> None:
    result = check_rewrite(MIGRATION, rewrite, catalog)
    assert not result.passed
    assert added in [(f.kind, f.text) for f in result.added]


@pytest.mark.parametrize(
    ("source", "rewrite", "name"),
    [
        (
            "Built a claims dashboard in Tableau.",
            "Built a claims dashboard in Tableau for Northgate Health.",
            "Northgate Health",
        ),
        (
            "Rebuilt the payroll export in Python.",
            "Rebuilt the payroll export in Python at Pinecrest Logistics.",
            "Pinecrest Logistics",
        ),
        (
            "Audited access controls for the vendor portal.",
            "Audited access controls for the vendor portal with Brightwater Partners.",
            "Brightwater Partners",
        ),
        (
            "Wrote the incident runbook.",
            "Wrote the incident runbook reviewed by Deloitte.",
            "Deloitte",
        ),
        (
            "Moved nightly jobs to AWS.",
            "Moved nightly jobs to Acme Web Solutions.",
            "Acme Web Solutions",
        ),
    ],
)
def test_organizations_after_a_preposition_fail(
    catalog: SkillCatalog, source: str, rewrite: str, name: str
) -> None:
    result = check_rewrite(source, rewrite, catalog)
    assert (FactKind.NAME, name) in [(f.kind, f.text) for f in result.added]


@pytest.mark.parametrize(
    ("source", "rewrite"),
    [
        (
            MIGRATION,
            "Migrated 120 stored procedures from SQL Server to Amazon Redshift and "
            "documented the data lineage for each.",
        ),
        ("Streamed click events through Kafka.", "Streamed click events through Apache Kafka."),
        # The same word in another case is the same name.
        ("Tuned queries for the Billing team.", "Tuned queries for the billing team."),
        ("Tuned queries for the billing team.", "Tuned queries for the Billing team."),
    ],
)
def test_equivalent_names_still_pass(catalog: SkillCatalog, source: str, rewrite: str) -> None:
    assert _passes(source, rewrite, catalog)


def test_spelling_out_an_acronym_in_capitals_fails(catalog: SkillCatalog) -> None:
    # The checker can't tell a true expansion from an invented one, so it rejects both.
    assert FactKind.NAME in _kinds(
        "Deployed services to ACA with Helm.",
        "Deployed services to Azure Container Apps with Helm.",
        catalog,
    )


# -- regressions: "one" that isn't a count ---------------------------------------


@pytest.mark.parametrize(
    "rewrite",
    [
        "Migrated 120 SQL Server stored procedures to Redshift and documented data lineage "
        "for each one.",
        "Migrated 120 stored procedures to Redshift, one of the largest moves on the team.",
        "Migrated 120 stored procedures to Redshift so no one had to rerun them by hand.",
        "Migrated 120 stored procedures to Redshift so anyone could trace their lineage.",
        "Ran a one-time migration of 120 stored procedures from SQL Server to Redshift.",
    ],
)
def test_one_as_a_pronoun_is_not_a_number(catalog: SkillCatalog, rewrite: str) -> None:
    assert FactKind.NUMBER not in _kinds(MIGRATION, rewrite, catalog)


def test_one_as_a_count_is_still_a_number(catalog: SkillCatalog) -> None:
    result = check_rewrite(
        "Led a team that rebuilt the billing service.",
        "Led one team that rebuilt the billing service.",
        catalog,
    )
    assert [(f.kind, f.text) for f in result.added] == [(FactKind.NUMBER, "one")]
