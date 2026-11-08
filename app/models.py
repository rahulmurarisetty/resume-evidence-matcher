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
    skills: list[str] = Field(description="Canonical skill names recognized in the requirement")
    match_mode: MatchMode = MatchMode.ALL
    min_years: int | None = None


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
    NOT_ASSESSED = "not_assessed"  # no recognizable skill; needs a human (or matching by meaning)


class RequirementMatch(BaseModel):
    requirement: Requirement
    status: MatchStatus
    skills: list[SkillMatch]
    next_action: str


class CategoryCoverage(BaseModel):
    total: int = 0
    direct: int = 0
    partial: int = 0
    gap: int = 0
    not_assessed: int = 0


class AnalysisReport(BaseModel):
    pipeline_version: str
    job: JobDescription
    resume_sections: list[Section]
    warnings: list[str] = Field(default_factory=list)
    coverage: dict[Priority, CategoryCoverage]
    missing_required_skills: list[str]
    listed_but_not_demonstrated: list[str]
    matches: list[RequirementMatch]
