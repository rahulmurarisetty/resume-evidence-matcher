from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import (
    AnalysisReport,
    CategoryCoverage,
    ChangeKind,
    MatchStatus,
    Priority,
    ResumeDocument,
    Section,
    SpanKind,
    SuggestionStatus,
)

MAX_CORRECTION_CHARS = 2000
MAX_ANSWER_CHARS = 4000
# Request field caps, above the rules in app/services/accounts.py so a value just
# over a rule gets that rule's message.
MAX_EMAIL_FIELD = 1000
MAX_PASSWORD_FIELD = 1000


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class ConsentOut(BaseModel):
    given_at: datetime | None = Field(
        description="When the person agreed. None for analyses made before consent was asked"
    )
    version: str | None = Field(description='The consent text they saw, such as "consent_v1"')
    llm: bool = Field(description="Whether Claude may see this person's resume and job text")


class AnalysisResponse(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    consent: ConsentOut
    report: AnalysisReport


class ConsentNoticeOut(BaseModel):
    """What the screen shows before an upload. Built from this server's settings."""

    version: str
    points: list[str] = Field(description="What is stored, for how long, who sees it, scanning")
    checkbox: str = Field(description="The label of the required box (consent=true)")
    llm_available: bool = Field(description="Whether Claude is on, so the second box is shown")
    llm_points: list[str] = Field(description="What goes to Anthropic. Empty when Claude is off")
    llm_checkbox: str | None = Field(description="The label of the optional box (llm_consent)")


class AnalysisSummary(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    job_title: str | None
    pipeline_version: str
    required: CategoryCoverage | None = Field(
        description="Coverage of the required requirements, when the job has any"
    )


class AnalysisListResponse(BaseModel):
    analyses: list[AnalysisSummary] = Field(description="Your analyses that haven't expired")


class ExtractResponse(BaseModel):
    """The text the app read from the resume, so a user can check it before trusting
    any match."""

    resume: ResumeDocument


class HealthResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


class CredentialsRequest(BaseModel):
    # Lengths are checked in the route, so the messages can say what is wrong.
    email: str = Field(max_length=MAX_EMAIL_FIELD)
    password: str = Field(max_length=MAX_PASSWORD_FIELD)


class MessageResponse(BaseModel):
    message: str


class UserOut(BaseModel):
    id: str
    email: str
    created_at: datetime
    auth_mode: Literal["required", "disabled"]


class LoginResponse(BaseModel):
    token: str = Field(description='Send as "Authorization: Bearer <token>". Shown only once.')
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    user: UserOut


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


class SuggestionsRequest(BaseModel):
    requirement_ids: list[str] | None = Field(
        default=None,
        description=(
            "Requirements to suggest rewrites for. Leave out for every eligible requirement "
            "that has no suggestions yet."
        ),
        max_length=100,
    )


class SuggestionOut(BaseModel):
    id: str
    kind: Literal["rewrite"] = "rewrite"
    requirement_id: str
    span_id: str
    original: str = Field(description="The line the rewrite was made from")
    text: str = Field(description="The rewrite. It passed the fact checker.")
    status: SuggestionStatus
    prompt_version: str
    model: str
    created_at: datetime
    updated_at: datetime


class SuggestionUsage(BaseModel):
    requested: int = Field(description="Rewrite candidates asked of Claude for this analysis")
    limit: int
    remaining: int
    rejected: int = Field(description="Candidates the fact checker discarded")


class SkippedRequirement(BaseModel):
    requirement_id: str
    reason: str
    message: str


class SuggestionBatchResponse(BaseModel):
    suggestions: list[SuggestionOut] = Field(description="New suggestions from this request")
    returned: int = Field(description="Candidates Claude returned in this request")
    rejected: int = Field(description="Candidates the fact checker discarded in this request")
    skipped: list[SkippedRequirement]
    usage: SuggestionUsage


class SuggestionListResponse(BaseModel):
    suggestions: list[SuggestionOut]
    usage: SuggestionUsage


# ---------------------------------------------------------------------------
# Spans and corrections
# ---------------------------------------------------------------------------


class SpanOut(BaseModel):
    id: str
    kind: SpanKind
    section: Section
    page: int | None
    order: int
    text: str = Field(description="The line as it will be exported, before any rewrite")
    original_text: str = Field(description="The line as the app read it")
    source: Literal["extracted", "user_correction"]


class SpanListResponse(BaseModel):
    spans: list[SpanOut]


class SpanCorrectionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_CORRECTION_CHARS)


# ---------------------------------------------------------------------------
# Gap questions
# ---------------------------------------------------------------------------


class GapQuestionOut(BaseModel):
    id: str = Field(
        description=(
            "Send answers to /gap-answers/{id}: the requirement id for a gap question, "
            '"metric-<span id>" for a metric question'
        )
    )
    kind: Literal["gap", "metric"] = Field(
        description='"gap": a missing or related requirement. "metric": a bullet with no number'
    )
    requirement_id: str | None = Field(
        description="The requirement asked about. For a metric question, the most important "
        "requirement the bullet supports, or None"
    )
    requirement_text: str | None
    priority: Priority | None
    status: MatchStatus | None
    span_id: str | None = Field(default=None, description="The bullet a metric question is about")
    line: str | None = Field(default=None, description="That bullet's text")
    question: str
    answer: str | None
    answered_at: datetime | None


class GapQuestionsResponse(BaseModel):
    questions: list[GapQuestionOut]


class GapAnswerRequest(BaseModel):
    answer: str = Field(
        max_length=MAX_ANSWER_CHARS, description="Free text. An empty answer removes it."
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class ChangeOut(BaseModel):
    span_id: str
    section: Section
    kind: ChangeKind
    label: str = Field(description='"User correction" or "Accepted rewrite"')
    before: str
    after: str
    suggestion_id: str | None = None
    requirement_id: str | None = None


class ChangesResponse(BaseModel):
    changes: list[ChangeOut]
