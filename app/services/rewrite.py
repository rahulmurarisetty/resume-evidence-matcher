"""Rewrite suggestions for resume bullets.

For a requirement the resume already supports (direct, partial or adjacent), the
best supporting bullet goes to Claude, which suggests up to two clearer versions
that use the job description's wording where the bullet supports it. Every
candidate then goes through the fact checker. Candidates that add a fact are
discarded and counted; the rest are returned as suggestions for the person to
accept or reject.

Only work bullets are rewritten. Headings, the contact block, role header lines
and any line holding a date range are never sent.
"""

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.llm.client import LLMClient, LLMError
from app.llm.prompts import REWRITE, Prompt, load_prompt
from app.models import (
    AnalysisReport,
    EvidenceStrength,
    MatchStatus,
    RequirementMatch,
    ResumeDocument,
    Section,
    SpanKind,
)
from app.services.factcheck import check_rewrite
from app.services.skills import SkillCatalog, get_catalog
from app.services.structure import RANGE_RE
from app.services.text import normalize, strip_bullet

logger = logging.getLogger("app.rewrite")

ELIGIBLE = {MatchStatus.DIRECT, MatchStatus.PARTIAL, MatchStatus.ADJACENT}
MAX_PER_REQUIREMENT = 2
MAX_OUTPUT_TOKENS = 1024
_WORK_SECTIONS = {Section.EXPERIENCE, Section.PROJECTS}
_CONTACT_RE = re.compile(
    r"\S+@\S+\.\w+|https?://|www\.|linkedin\.com|github\.com"
    r"|\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}",
    re.IGNORECASE,
)


class RewriteOutput(BaseModel):
    rewrites: list[str] = Field(
        default_factory=list, description="Improved versions of the bullet, best first"
    )


@dataclass(frozen=True)
class Target:
    requirement_id: str
    requirement_text: str
    span_id: str
    source_text: str


@dataclass(frozen=True)
class Skip:
    requirement_id: str
    reason: str
    message: str


@dataclass(frozen=True)
class Candidate:
    requirement_id: str
    span_id: str
    source_text: str
    text: str


@dataclass
class RewriteRun:
    kept: list[Candidate] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)
    calls: int = 0
    requested: int = 0  # candidates asked for; counts toward the per-analysis cap
    returned: int = 0
    rejected: int = 0  # failed the fact checker
    unchanged: int = 0  # empty, the same as the bullet, or a repeat
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    prompt_version: str = ""


_SKIP_MESSAGES = {
    "not_eligible": "Only requirements with supporting evidence get rewrite suggestions.",
    "years_only": "Asks only for years of experience, which a rewrite can't change.",
    "no_bullet": "No work bullet supports this requirement, so there's nothing to rewrite.",
    "already_suggested": "Already has suggestions. Ask for this requirement by id for more.",
    "limit_reached": "The suggestion limit for this analysis has been reached.",
    "timeout": "Claude didn't answer in time.",
    "api_error": "The call to Claude failed.",
    "invalid_output": "Claude's answer couldn't be read.",
    "not_attempted": "Skipped because an earlier call to Claude failed.",
}


def _skip(requirement_id: str, reason: str) -> Skip:
    return Skip(requirement_id, reason, _SKIP_MESSAGES[reason])


def rewritable_span_ids(resume: ResumeDocument, report: AnalysisReport) -> set[str]:
    """Work bullets that may be rewritten: never headings, the contact block, role
    header lines or lines with dates."""
    has_headings = any(span.kind is SpanKind.HEADING for span in resume.spans)
    headers = {role.header_span_id for role in report.profile.roles}
    allowed: set[str] = set()
    for span in resume.spans:
        if span.kind is not SpanKind.BULLET or span.id in headers:
            continue
        if has_headings and span.section not in _WORK_SECTIONS:
            continue
        if RANGE_RE.search(span.text) or _CONTACT_RE.search(span.text):
            continue
        allowed.add(span.id)
    return allowed


def _best_span(match: RequirementMatch, allowed: set[str]) -> str | None:
    """The bullet to rewrite: the first demonstrated exact evidence, else the
    best-scoring related line."""
    for skill in match.skills:
        for evidence in skill.evidence:
            if evidence.strength is EvidenceStrength.DEMONSTRATED and evidence.span_id in allowed:
                return evidence.span_id
    related = sorted(match.related_evidence, key=lambda r: r.score, reverse=True)
    return next((r.span_id for r in related if r.span_id in allowed), None)


def choose_targets(
    report: AnalysisReport,
    resume: ResumeDocument,
    current_text: Mapping[str, str],
    requirement_ids: list[str] | None = None,
    already_suggested: Iterable[str] = (),
) -> tuple[list[Target], list[Skip]]:
    """Which bullet to rewrite for each requested requirement.

    `requirement_ids` None means every eligible requirement that has no
    suggestions yet. `current_text` is each span's text with corrections applied.
    """
    allowed = rewritable_span_ids(resume, report)
    done = set(already_suggested)
    wanted = set(requirement_ids) if requirement_ids is not None else None
    targets: list[Target] = []
    skipped: list[Skip] = []
    for match in report.matches:
        requirement = match.requirement
        if wanted is not None and requirement.id not in wanted:
            continue
        if match.status not in ELIGIBLE:
            if wanted is not None:
                skipped.append(_skip(requirement.id, "not_eligible"))
            continue
        if requirement.min_years and not requirement.skills:
            if wanted is not None:
                skipped.append(_skip(requirement.id, "years_only"))
            continue
        if wanted is None and requirement.id in done:
            skipped.append(_skip(requirement.id, "already_suggested"))
            continue
        span_id = _best_span(match, allowed)
        if span_id is None:
            skipped.append(_skip(requirement.id, "no_bullet"))
            continue
        targets.append(Target(requirement.id, requirement.text, span_id, current_text[span_id]))
    return targets, skipped


def _clean(text: str) -> str:
    text = strip_bullet(normalize(text))[0]
    return text.strip().strip("\"'“”").strip()


def generate_rewrites(
    targets: list[Target],
    *,
    client: LLMClient,
    model: str,
    budget: int,
    existing: Mapping[str, Iterable[str]] | None = None,
    catalog: SkillCatalog | None = None,
    prompt: Prompt | None = None,
) -> RewriteRun:
    """Ask Claude for rewrites until the targets or the budget run out.

    `budget` is how many more candidates this analysis may ask for. `existing`
    maps a span id to suggestion texts it already has, so repeats are dropped.
    """
    catalog = catalog or get_catalog()
    prompt = prompt or load_prompt(*REWRITE)
    run = RewriteRun(model=model, prompt_version=prompt.id)
    seen: dict[str, set[str]] = {
        span: {t.lower() for t in texts} for span, texts in (existing or {}).items()
    }
    stopped = False
    for target in targets:
        if stopped:
            run.skipped.append(_skip(target.requirement_id, "not_attempted"))
            continue
        wanted = min(MAX_PER_REQUIREMENT, budget - run.requested)
        if wanted <= 0:
            run.skipped.append(_skip(target.requirement_id, "limit_reached"))
            continue
        user = (
            f"<requirement>\n{target.requirement_text}\n</requirement>\n"
            f"<bullet>\n{target.source_text}\n</bullet>\n"
            f"Suggest at most {wanted} rewrites of the bullet."
        )
        run.calls += 1
        try:
            result = client.generate(
                system=prompt.text,
                user=user,
                output_type=RewriteOutput,
                model=model,
                prompt_version=prompt.id,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except LLMError as exc:
            if exc.reason == "invalid_output":
                # The call was made and paid for, so it counts toward the cap.
                run.requested += wanted
            else:
                # A timeout or API error will most likely repeat. Stop here rather
                # than wait on every remaining requirement.
                stopped = True
            run.skipped.append(_skip(target.requirement_id, exc.reason))
            continue

        run.requested += wanted
        run.model = result.model
        run.input_tokens += result.usage.input_tokens
        run.output_tokens += result.usage.output_tokens
        candidates = result.output.rewrites[:wanted]
        run.returned += len(candidates)
        known = seen.setdefault(target.span_id, set())
        for raw in candidates:
            text = _clean(raw)
            if not text or text.lower() == target.source_text.lower() or text.lower() in known:
                run.unchanged += 1
                continue
            if not check_rewrite(target.source_text, text, catalog).passed:
                run.rejected += 1
                continue
            known.add(text.lower())
            run.kept.append(
                Candidate(target.requirement_id, target.span_id, target.source_text, text)
            )

    logger.info(
        "rewrite run",
        extra={
            "model": run.model,
            "prompt_version": run.prompt_version,
            "calls": run.calls,
            "generated": run.returned,
            "rejected": run.rejected,
            "suggestions": len(run.kept),
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
        },
    )
    return run
