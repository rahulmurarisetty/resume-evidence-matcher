"""Data contracts shared by the pipeline and the API.

Every recommendation the app makes has to point back to a resume span (a line or
bullet with its location) or be marked as a gap. These models make that rule
explicit.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class FileType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"


class SuggestionStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ChangeKind(StrEnum):
    CORRECTION = "correction"  # the person fixed text the app read wrongly
    REWRITE = "rewrite"  # an accepted suggestion that passed the fact checker


class Section(StrEnum):
    HEADER = "header"  # name and contact block above the first heading
    SUMMARY = "summary"
    EXPERIENCE = "experience"
    PROJECTS = "projects"
    SKILLS = "skills"
    EDUCATION = "education"
    CERTIFICATIONS = "certifications"
    OTHER = "other"


class SpanKind(StrEnum):
    HEADING = "heading"
    BULLET = "bullet"
    LINE = "line"


class Span(BaseModel):
    """One heading, bullet or line of the resume, with where it came from."""

    id: str
    text: str
    kind: SpanKind
    section: Section
    page: int | None = Field(default=None, description="1-based page number; None for DOCX")
    order: int = Field(description="Position in reading order, starting at 0")


class ResumeDocument(BaseModel):
    file_type: FileType
    page_count: int | None
    spans: list[Span]

    @property
    def sections_found(self) -> list[Section]:
        seen: list[Section] = []
        for span in self.spans:
            if span.section not in seen:
                seen.append(span.section)
        return seen


class Priority(StrEnum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    CONTEXT = "context"  # responsibilities and other background lines


class MatchMode(StrEnum):
    ALL = "all"  # "Python and SQL": every skill is needed
    ANY = "any"  # "Snowflake or another warehouse": one is enough


class Requirement(BaseModel):
    id: str
    text: str
    priority: Priority
    skills: list[str] = Field(
        description=(
            "Skills named in the requirement: canonical catalog names, plus any free-text "
            "skills listed in free_text_skills"
        )
    )
    match_mode: MatchMode = MatchMode.ALL
    min_years: int | None = None
    free_text_skills: list[str] = Field(
        default_factory=list,
        description=(
            "Skills in `skills` that aren't in the catalog. Exact matching looks for each "
            "one in the resume as a whole phrase."
        ),
    )


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    UNKNOWN = "unknown"


class JobDescription(BaseModel):
    title: str | None
    seniority: Seniority
    min_years: int | None
    requirements: list[Requirement]


class EvidenceStrength(StrEnum):
    DEMONSTRATED = "demonstrated"  # appears in an experience, project or certification line
    LISTED = "listed"  # appears only in skills, summary or header


class Evidence(BaseModel):
    span_id: str
    text: str
    section: Section
    page: int | None
    matched_term: str
    strength: EvidenceStrength


class SkillMatch(BaseModel):
    skill: str
    strength: EvidenceStrength | None = Field(description="Best evidence found; None means missing")
    evidence: list[Evidence]


class MatchStatus(StrEnum):
    DIRECT = "direct"  # every skill is shown in experience or project work
    PARTIAL = "partial"  # some skills missing, or only listed in the skills section
    GAP = "gap"  # none of the skills appear anywhere
    ADJACENT = "adjacent"  # no exact evidence, but related work was found by meaning
    NOT_ASSESSED = "not_assessed"  # no recognizable skill; needs a human


class RelatedEvidence(BaseModel):
    """A resume span that matching by meaning found related to a requirement. It is
    never exact evidence: the person has to confirm it."""

    span_id: str
    text: str
    section: Section
    page: int | None
    score: float = Field(description="Reranker score from 0 to 1, rounded to 3 decimals")


class RequirementMatch(BaseModel):
    requirement: Requirement
    status: MatchStatus
    skills: list[SkillMatch]
    related_evidence: list[RelatedEvidence] = Field(
        default_factory=list, description="Empty when matching by meaning is off"
    )
    years_found: float | None = Field(
        default=None,
        description=(
            "For requirements that ask for years: the years the resume shows in total, or "
            "with the requirement's skills. None when no role dates could be read."
        ),
    )
    next_action: str


class CategoryCoverage(BaseModel):
    total: int = 0
    direct: int = 0
    partial: int = 0
    gap: int = 0
    adjacent: int = 0
    not_assessed: int = 0


class Role(BaseModel):
    """One job (or dated project) read from a header line such as
    'Senior Data Engineer, Example Mutual Insurance | Mar 2022 - Present'."""

    title: str | None
    employer: str | None
    section: Section
    start: str | None = Field(description="YYYY-MM, or None when no start date could be read")
    end: str | None = Field(description="YYYY-MM; None for a current role or an unread date")
    is_current: bool
    months: int | None = Field(
        description="Months in the role, counting the start and end months. None if unknown."
    )
    header_span_id: str
    bullet_span_ids: list[str] = Field(
        default_factory=list, description="Bullets and other body lines under this role"
    )


class Education(BaseModel):
    degree: str | None
    school: str | None
    year: int | None
    span_ids: list[str]


class Profile(BaseModel):
    """Structure read from the resume: roles with dates, education and measurable results."""

    roles: list[Role] = Field(default_factory=list)
    total_years: float | None = Field(
        default=None,
        description=(
            "Years across experience roles, with overlapping roles counted once. None when "
            "no role dates could be read."
        ),
    )
    education: list[Education] = Field(default_factory=list)
    metric_bullets: list[str] = Field(
        default_factory=list, description="Span ids of bullets that contain a measurable result"
    )
    metrics: dict[str, list[str]] = Field(
        default_factory=dict, description="The metric strings found, keyed by span id"
    )
    warnings: list[str] = Field(default_factory=list)


class MatchingMode(StrEnum):
    EXACT = "exact"  # skill catalog only
    SEMANTIC = "semantic"  # skill catalog plus matching by meaning


class JobParserName(StrEnum):
    RULES = "rules"
    CLAUDE = "claude"


class JobParserInfo(BaseModel):
    """Which job-description parser produced the requirements, and how."""

    name: JobParserName = JobParserName.RULES
    prompt_version: str | None = Field(
        default=None, description='The prompt file Claude used, such as "jd_parse_v1"'
    )
    model: str | None = None
    fallback_reason: str | None = Field(
        default=None,
        description=(
            "Set when Claude was tried and the rule parser ran instead: timeout, api_error "
            "or invalid_output"
        ),
    )
    dropped_requirements: int = Field(
        default=0,
        description="Requirements Claude returned whose text isn't in the job description",
    )


class AnalysisReport(BaseModel):
    pipeline_version: str
    matching_mode: MatchingMode = MatchingMode.EXACT
    job_parser: JobParserInfo = Field(default_factory=JobParserInfo)
    job: JobDescription
    resume_sections: list[Section]
    warnings: list[str] = Field(default_factory=list)
    coverage: dict[Priority, CategoryCoverage]
    missing_required_skills: list[str]
    listed_but_not_demonstrated: list[str]
    profile: Profile = Field(default_factory=Profile)
    matches: list[RequirementMatch]
