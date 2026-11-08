"""Claude parsing and rewrites, run only with --llm and an ANTHROPIC_API_KEY.

With a key, the Claude parser reads every job description (once each), and for
every pair the app's own rewrite step picks the bullets to rewrite and asks
Claude for candidates. Each candidate is recorded with the fact checker's verdict
and reasons, so a person can review them in llm_candidates.json. Without a key
the mode is skipped and nothing is sent anywhere.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from app.config import Settings
from app.llm.client import LLMClient, LLMResult, OutputT
from app.services.factcheck import check_rewrite
from app.services.rewrite import (
    MAX_PER_REQUIREMENT,
    RewriteOutput,
    choose_targets,
    generate_rewrites,
)
from app.services.skills import SkillCatalog
from app.services.text import normalize, strip_bullet
from evals.metrics import Rate
from evals.pipeline import PairRun

_STOPPING = {"timeout", "api_error"}


def claude_from_env() -> tuple[LLMClient, Settings] | str:
    """The Anthropic client built from the environment or a local .env file, or the
    reason it can't be built. LLM_ENABLED is ignored: --llm is the opt-in."""
    try:
        settings = Settings()
    except ValidationError as exc:
        return f"the settings in the environment aren't valid ({exc.error_count()} errors)."
    key = settings.anthropic_api_key
    if key is None:
        return "ANTHROPIC_API_KEY isn't set."
    from app.llm.anthropic_client import AnthropicClient

    client = AnthropicClient(key.get_secret_value(), timeout_seconds=settings.llm_timeout_seconds)
    return client, settings


class RecordingClient:
    """Passes calls through and keeps every rewrite list Claude returned, including
    the candidates the fact checker later discards."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.rewrites: list[list[str]] = []

    def generate(
        self,
        *,
        system: str,
        user: str,
        output_type: type[OutputT],
        model: str,
        prompt_version: str,
        max_tokens: int = 2048,
    ) -> LLMResult[OutputT]:
        result = self.inner.generate(
            system=system,
            user=user,
            output_type=output_type,
            model=model,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
        )
        if isinstance(result.output, RewriteOutput):
            self.rewrites.append(list(result.output.rewrites))
        return result


def _clean(text: str) -> str:
    """The same cleaning the rewrite step applies before checking a candidate."""
    return strip_bullet(normalize(text))[0].strip().strip("\"'\u201c\u201d").strip()


def run_rewrites(
    runs: Sequence[PairRun],
    client: LLMClient,
    *,
    model: str,
    budget: int,
    catalog: SkillCatalog,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Generate and check rewrites for every pair. Returns the summary and every
    candidate with its verdict."""
    candidates: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    rejected_kinds: Counter[str] = Counter()
    totals = Counter[str]()
    per_pair: list[dict[str, Any]] = []
    consistent = True
    for run in runs:
        pair_counts = Counter[str]()
        pair_kinds: Counter[str] = Counter()
        current = {span.id: span.text for span in run.resume.spans}
        targets, skips = choose_targets(run.report, run.resume, current)
        skipped.update(skip.reason for skip in skips)
        remaining = budget
        kept_by_span: dict[str, list[str]] = {}
        stopped = False
        for target in targets:
            if stopped:
                skipped["not_attempted"] += 1
                continue
            wanted = min(MAX_PER_REQUIREMENT, remaining)
            if wanted <= 0:
                skipped["limit_reached"] += 1
                continue
            recorder = RecordingClient(client)
            result = generate_rewrites(
                [target],
                client=recorder,
                model=model,
                budget=remaining,
                existing=kept_by_span,
                catalog=catalog,
            )
            remaining -= result.requested
            totals.update(
                calls=result.calls,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            skipped.update(skip.reason for skip in result.skipped)
            if any(skip.reason in _STOPPING for skip in result.skipped):
                stopped = True
            raw = recorder.rewrites[0][:wanted] if recorder.rewrites else []
            seen = {t.lower() for t in kept_by_span.get(target.span_id, [])}
            counts = Counter[str]()
            for candidate in raw:
                text = _clean(candidate)
                record: dict[str, Any] = {
                    "pair": run.pair.key,
                    "format": run.format,
                    "requirement_id": target.requirement_id,
                    "requirement": target.requirement_text,
                    "span_id": target.span_id,
                    "source": target.source_text,
                    "candidate": candidate,
                    "model": result.model,
                    "prompt_version": result.prompt_version,
                    "reasons": [],
                    # For a person to fill in after reading the candidate: "faithful" or
                    # "adds_fact". The checker can miss an added fact.
                    "manual_review": None,
                }
                if not text or text.lower() == target.source_text.lower() or text.lower() in seen:
                    record["verdict"] = "unchanged"
                else:
                    check = check_rewrite(target.source_text, text, catalog)
                    if check.passed:
                        record["verdict"] = "kept"
                        seen.add(text.lower())
                        kept_by_span.setdefault(target.span_id, []).append(text)
                    else:
                        record["verdict"] = "rejected"
                        record["reasons"] = [
                            {"kind": f.kind.value, "text": f.text, "reason": f.reason}
                            for f in check.added
                        ]
                        kinds = {f.kind.value for f in check.added}
                        rejected_kinds.update(kinds)
                        pair_kinds.update(kinds)
                counts[record["verdict"]] += 1
                candidates.append(record)
            totals.update(counts)
            pair_counts.update(counts)
            consistent = consistent and (
                counts["kept"] == len(result.kept)
                and counts["rejected"] == result.rejected
                and counts["unchanged"] == result.unchanged
            )
        per_pair.append(
            {
                "pair": run.pair.key,
                "targets": len(targets),
                "candidates": sum(pair_counts.values()),
                "kept": pair_counts["kept"],
                "rejected": pair_counts["rejected"],
                "unchanged": pair_counts["unchanged"],
                "rejections_by_kind": dict(sorted(pair_kinds.items())),
            }
        )
    checked = totals["kept"] + totals["rejected"]
    summary = {
        "pairs": len(runs),
        "calls": totals["calls"],
        "candidates": len(candidates),
        "kept": totals["kept"],
        "rejected": totals["rejected"],
        "unchanged": totals["unchanged"],
        "rejection_rate": Rate(totals["rejected"], checked).to_dict(),
        "rejections_by_kind": dict(sorted(rejected_kinds.items())),
        "skipped": dict(sorted(skipped.items())),
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"],
        "matches_app_counts": consistent,
        "per_pair": per_pair,
    }
    return summary, candidates
