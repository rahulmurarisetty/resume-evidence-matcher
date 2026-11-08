from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import (
    AnalysisReport,
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


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class AnalysisResponse(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    report: AnalysisReport


class ExtractResponse(BaseModel):
    """The text the app read from the resume, so a user can check it before trusting
    any match."""

    resume: ResumeDocument


class HealthResponse(BaseModel):
    status: str


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
    requirement_id: str
    requirement_text: str
    priority: Priority
    status: MatchStatus
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
