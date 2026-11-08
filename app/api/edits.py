"""Suggestions, corrections, gap answers and export for a stored analysis.

Everything here is stored with the analysis, expires with it after
RETENTION_HOURS and is deleted with it.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Request, Response

from app.api.deps import SessionDep, SettingsDep
from app.api.errors import ApiError
from app.api.schemas import (
    ChangeOut,
    ChangesResponse,
    ErrorResponse,
    GapAnswerRequest,
    GapQuestionOut,
    GapQuestionsResponse,
    SkippedRequirement,
    SpanCorrectionRequest,
    SpanListResponse,
    SpanOut,
    SuggestionBatchResponse,
    SuggestionListResponse,
    SuggestionOut,
    SuggestionsRequest,
    SuggestionUsage,
)
from app.config import Settings
from app.llm.client import LLMClient
from app.models import AnalysisReport, ChangeKind, ResumeDocument, Span, SuggestionStatus
from app.services.export import DOCX_MIME, AcceptedRewrite, build_docx, list_changes
from app.services.questions import GapQuestion, gap_questions
from app.services.rewrite import choose_targets, generate_rewrites
from app.services.text import normalize
from app.storage.db import SuggestionRecord, SuggestionRunRecord, utcnow
from app.storage.repository import AnalysisRepository, aware

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/api/v1/analyses/{analysis_id}", tags=["edits"])

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorResponse} for code in (404, 409, 422, 503)
}
_CHANGE_LABELS = {ChangeKind.CORRECTION: "User correction", ChangeKind.REWRITE: "Accepted rewrite"}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _report(repo: AnalysisRepository, analysis_id: str) -> AnalysisReport:
    record = repo.get(analysis_id)
    if record is None:
        raise ApiError(404, "not_found", "No analysis with that id, or it has expired.")
    return AnalysisReport.model_validate_json(record.report_json)


def _resume(repo: AnalysisRepository, analysis_id: str) -> ResumeDocument:
    resume = repo.get_resume(analysis_id)
    if resume is None:
        raise ApiError(
            409,
            "resume_not_stored",
            "This analysis was made before v0.3, so its resume lines weren't stored. Run "
            "the analysis again to use suggestions, corrections and export.",
        )
    return resume


def _span(resume: ResumeDocument, span_id: str) -> Span:
    span = next((s for s in resume.spans if s.id == span_id), None)
    if span is None:
        raise ApiError(404, "span_not_found", "No line with that id in this analysis.")
    return span


def _suggestion_out(record: SuggestionRecord) -> SuggestionOut:
    return SuggestionOut(
        id=record.id,
        requirement_id=record.requirement_id,
        span_id=record.span_id,
        original=record.source_text,
        text=record.text,
        status=SuggestionStatus(record.status),
        prompt_version=record.prompt_version,
        model=record.model,
        created_at=aware(record.created_at),
        updated_at=aware(record.updated_at),
    )


def _usage(repo: AnalysisRepository, analysis_id: str, settings: Settings) -> SuggestionUsage:
    requested, rejected = repo.suggestion_usage(analysis_id)
    limit = settings.llm_max_suggestions
    return SuggestionUsage(
        requested=requested,
        limit=limit,
        remaining=max(0, limit - requested),
        rejected=rejected,
    )


def _current_text(
    repo: AnalysisRepository, analysis_id: str, resume: ResumeDocument
) -> dict[str, str]:
    corrections = repo.corrections(analysis_id)
    return {
        span.id: corrections[span.id].text if span.id in corrections else span.text
        for span in resume.spans
    }


def _accepted(repo: AnalysisRepository, analysis_id: str) -> dict[str, SuggestionRecord]:
    return {
        s.span_id: s
        for s in repo.suggestions(analysis_id)
        if s.status == SuggestionStatus.ACCEPTED.value
    }


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


@router.get("/suggestions", response_model=SuggestionListResponse, responses=_ERRORS)
def list_suggestions(
    analysis_id: str, session: SessionDep, settings: SettingsDep
) -> SuggestionListResponse:
    repo = AnalysisRepository(session)
    _report(repo, analysis_id)
    return SuggestionListResponse(
        suggestions=[_suggestion_out(s) for s in repo.suggestions(analysis_id)],
        usage=_usage(repo, analysis_id, settings),
    )


@router.post(
    "/suggestions",
    response_model=SuggestionBatchResponse,
    responses=_ERRORS,
    summary="Ask Claude for rewrites of the bullets that support the chosen requirements.",
)
def create_suggestions(
    analysis_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    body: Annotated[SuggestionsRequest | None, Body()] = None,
) -> SuggestionBatchResponse:
    repo = AnalysisRepository(session)
    report = _report(repo, analysis_id)
    llm: LLMClient | None = request.app.state.llm
    if llm is None:
        raise ApiError(
            409,
            "llm_disabled",
            "Rewrite suggestions need Claude, which is off on this server. Set "
            "ANTHROPIC_API_KEY (with LLM_ENABLED=auto or on) and restart the API to turn "
            "them on.",
        )
    resume = _resume(repo, analysis_id)

    requirement_ids = body.requirement_ids if body is not None else None
    if requirement_ids is not None:
        known = {m.requirement.id for m in report.matches}
        unknown = sorted(set(requirement_ids) - known)
        if unknown:
            raise ApiError(
                422, "unknown_requirement", f"No requirement with id {', '.join(unknown)}."
            )

    usage = _usage(repo, analysis_id, settings)
    if usage.remaining <= 0:
        raise ApiError(
            409,
            "suggestion_limit_reached",
            f"This analysis has used its limit of {usage.limit} rewrite suggestions.",
        )

    existing = repo.suggestions(analysis_id)
    existing_texts: dict[str, list[str]] = defaultdict(list)
    for suggestion in existing:
        existing_texts[suggestion.span_id].append(suggestion.text)
    targets, skipped = choose_targets(
        report,
        resume,
        _current_text(repo, analysis_id, resume),
        requirement_ids,
        already_suggested={s.requirement_id for s in existing},
    )
    # End the read transaction before the slow calls to Claude.
    session.commit()

    run = generate_rewrites(
        targets,
        client=llm,
        model=settings.llm_rewrite_model,
        budget=usage.remaining,
        existing=existing_texts,
    )
    if run.calls and run.requested == 0:
        # Every call that was attempted failed before Claude answered.
        raise ApiError(503, "llm_unavailable", "Claude couldn't be reached. Try again shortly.")

    now = utcnow()
    records = [
        SuggestionRecord(
            id=uuid.uuid4().hex,
            analysis_id=analysis_id,
            requirement_id=c.requirement_id,
            span_id=c.span_id,
            source_text=c.source_text,
            text=c.text,
            status=SuggestionStatus.PROPOSED.value,
            prompt_version=run.prompt_version,
            model=run.model,
            position=position,
            created_at=now,
            updated_at=now,
        )
        for position, c in enumerate(run.kept)
    ]
    if run.calls:
        repo.add_suggestions(
            records,
            SuggestionRunRecord(
                analysis_id=analysis_id,
                created_at=now,
                model=run.model,
                prompt_version=run.prompt_version,
                calls=run.calls,
                requested=run.requested,
                returned=run.returned,
                rejected=run.rejected,
                kept=len(run.kept),
                input_tokens=run.input_tokens,
                output_tokens=run.output_tokens,
            ),
        )
    logger.info(
        "suggestions created",
        extra={
            "analysis_id": analysis_id,
            "calls": run.calls,
            "generated": run.returned,
            "rejected": run.rejected,
            "suggestions": len(records),
        },
    )
    return SuggestionBatchResponse(
        suggestions=[_suggestion_out(r) for r in records],
        returned=run.returned,
        rejected=run.rejected,
        skipped=[
            SkippedRequirement(requirement_id=s.requirement_id, reason=s.reason, message=s.message)
            for s in [*skipped, *run.skipped]
        ],
        usage=_usage(repo, analysis_id, settings),
    )


def _load_suggestion(
    repo: AnalysisRepository, analysis_id: str, suggestion_id: str
) -> SuggestionRecord:
    _report(repo, analysis_id)
    record = repo.get_suggestion(analysis_id, suggestion_id)
    if record is None:
        raise ApiError(404, "suggestion_not_found", "No suggestion with that id.")
    return record


@router.post("/suggestions/{suggestion_id}/accept", response_model=SuggestionOut, responses=_ERRORS)
def accept_suggestion(analysis_id: str, suggestion_id: str, session: SessionDep) -> SuggestionOut:
    repo = AnalysisRepository(session)
    record = _load_suggestion(repo, analysis_id, suggestion_id)
    if record.status == SuggestionStatus.ACCEPTED.value:
        return _suggestion_out(record)
    other = _accepted(repo, analysis_id).get(record.span_id)
    if other is not None:
        raise ApiError(
            409,
            "line_has_accepted_rewrite",
            "Another rewrite of this line is already accepted. Reject it first.",
        )
    resume = _resume(repo, analysis_id)
    if _current_text(repo, analysis_id, resume).get(record.span_id) != record.source_text:
        raise ApiError(
            409,
            "line_changed",
            "The line was corrected after this suggestion was made. Ask for new suggestions.",
        )
    repo.set_suggestion_status(record, SuggestionStatus.ACCEPTED)
    return _suggestion_out(record)


@router.post("/suggestions/{suggestion_id}/reject", response_model=SuggestionOut, responses=_ERRORS)
def reject_suggestion(analysis_id: str, suggestion_id: str, session: SessionDep) -> SuggestionOut:
    repo = AnalysisRepository(session)
    record = _load_suggestion(repo, analysis_id, suggestion_id)
    repo.set_suggestion_status(record, SuggestionStatus.REJECTED)
    return _suggestion_out(record)


# ---------------------------------------------------------------------------
# Spans and corrections
# ---------------------------------------------------------------------------


def _span_out(span: Span, corrected: str | None) -> SpanOut:
    return SpanOut(
        id=span.id,
        kind=span.kind,
        section=span.section,
        page=span.page,
        order=span.order,
        text=corrected if corrected is not None else span.text,
        original_text=span.text,
        source="user_correction" if corrected is not None else "extracted",
    )


@router.get("/spans", response_model=SpanListResponse, responses=_ERRORS)
def list_spans(analysis_id: str, session: SessionDep) -> SpanListResponse:
    repo = AnalysisRepository(session)
    _report(repo, analysis_id)
    resume = _resume(repo, analysis_id)
    corrections = repo.corrections(analysis_id)
    return SpanListResponse(
        spans=[
            _span_out(s, corrections[s.id].text if s.id in corrections else None)
            for s in resume.spans
        ]
    )


@router.patch(
    "/spans/{span_id}",
    response_model=SpanOut,
    responses=_ERRORS,
    summary="Correct a line the app read wrongly. Sending the original text removes the fix.",
)
def correct_span(
    analysis_id: str, span_id: str, body: SpanCorrectionRequest, session: SessionDep
) -> SpanOut:
    repo = AnalysisRepository(session)
    _report(repo, analysis_id)
    span = _span(_resume(repo, analysis_id), span_id)
    text = normalize(body.text)
    if not text:
        raise ApiError(422, "empty_text", "A corrected line can't be empty.")
    if span_id in _accepted(repo, analysis_id):
        raise ApiError(
            409,
            "line_has_accepted_rewrite",
            "This line has an accepted rewrite. Reject it before correcting the line.",
        )
    corrected = None if text == span.text else text
    repo.set_correction(analysis_id, span_id, corrected)
    logger.info("line corrected", extra={"analysis_id": analysis_id})
    return _span_out(span, corrected)


# ---------------------------------------------------------------------------
# Gap questions
# ---------------------------------------------------------------------------


def _question_out(
    question: GapQuestion, answer: str | None, answered_at: datetime | None
) -> GapQuestionOut:
    return GapQuestionOut(
        requirement_id=question.requirement_id,
        requirement_text=question.requirement_text,
        priority=question.priority,
        status=question.status,
        question=question.question,
        answer=answer,
        answered_at=answered_at,
    )


@router.get("/gap-questions", response_model=GapQuestionsResponse, responses=_ERRORS)
def list_gap_questions(analysis_id: str, session: SessionDep) -> GapQuestionsResponse:
    repo = AnalysisRepository(session)
    report = _report(repo, analysis_id)
    answers = repo.gap_answers(analysis_id)
    out: list[GapQuestionOut] = []
    for question in gap_questions(report):
        answer = answers.get(question.requirement_id)
        out.append(
            _question_out(
                question,
                answer.answer if answer else None,
                aware(answer.updated_at) if answer else None,
            )
        )
    return GapQuestionsResponse(questions=out)


@router.put(
    "/gap-answers/{requirement_id}",
    response_model=GapQuestionOut,
    responses=_ERRORS,
    summary="Answer a gap question. Answers are stored, never added to the resume.",
)
def put_gap_answer(
    analysis_id: str, requirement_id: str, body: GapAnswerRequest, session: SessionDep
) -> GapQuestionOut:
    repo = AnalysisRepository(session)
    report = _report(repo, analysis_id)
    question = next((q for q in gap_questions(report) if q.requirement_id == requirement_id), None)
    if question is None:
        raise ApiError(404, "no_gap_question", "That requirement has no gap question.")
    answer = body.answer.strip() or None
    repo.set_gap_answer(analysis_id, requirement_id, answer)
    stored = repo.gap_answers(analysis_id).get(requirement_id)
    return _question_out(question, answer, aware(stored.updated_at) if stored else None)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _edits(
    repo: AnalysisRepository, analysis_id: str
) -> tuple[ResumeDocument, dict[str, str], dict[str, AcceptedRewrite]]:
    resume = _resume(repo, analysis_id)
    corrections = {span_id: c.text for span_id, c in repo.corrections(analysis_id).items()}
    rewrites = {
        span_id: AcceptedRewrite(s.id, s.requirement_id, s.text)
        for span_id, s in _accepted(repo, analysis_id).items()
    }
    return resume, corrections, rewrites


@router.get(
    "/export.docx",
    responses={200: {"content": {DOCX_MIME: {}}}, **_ERRORS},
    response_class=Response,
    summary="A clean Word file with corrections and accepted rewrites applied.",
)
def export_docx(analysis_id: str, session: SessionDep) -> Response:
    repo = AnalysisRepository(session)
    report = _report(repo, analysis_id)
    resume, corrections, rewrites = _edits(repo, analysis_id)
    data = build_docx(
        resume,
        corrections,
        rewrites,
        role_header_ids={role.header_span_id for role in report.profile.roles},
    )
    logger.info("export built", extra={"analysis_id": analysis_id})
    return Response(
        content=data,
        media_type=DOCX_MIME,
        headers={
            "Content-Disposition": 'attachment; filename="resume.docx"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/export/changes", response_model=ChangesResponse, responses=_ERRORS)
def export_changes(analysis_id: str, session: SessionDep) -> ChangesResponse:
    repo = AnalysisRepository(session)
    _report(repo, analysis_id)
    resume, corrections, rewrites = _edits(repo, analysis_id)
    return ChangesResponse(
        changes=[
            ChangeOut(
                span_id=c.span_id,
                section=c.section,
                kind=c.kind,
                label=_CHANGE_LABELS[c.kind],
                before=c.before,
                after=c.after,
                suggestion_id=c.suggestion_id,
                requirement_id=c.requirement_id,
            )
            for c in list_changes(resume, corrections, rewrites)
        ]
    )
