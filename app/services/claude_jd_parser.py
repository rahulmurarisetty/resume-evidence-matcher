"""Claude-based job-description parser, behind the same JobParser interface as the
rule parser.

Claude reads the job description and returns its requirements as structured
output. Nothing it returns is trusted as is:

- Every requirement's text must appear in the job description, after whitespace
  normalization. Requirements that don't are dropped and counted.
- Every skill must be named in the requirement's own text. One that matches a
  catalog term becomes that catalog skill. Any other is kept as a free-text skill,
  and exact matching then looks for it in the resume as a whole phrase.
- Catalog skills in the requirement text that Claude left out are added, so the
  result never knows fewer catalog skills than the rule parser would.
- Years are kept only when the requirement's text states that number of years.

On a missing client, a timeout, an API error or output that fails these checks,
the rule parser runs instead and the report says why.
"""

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.llm.client import LLMClient, LLMError
from app.llm.prompts import JD_PARSE, Prompt, load_prompt
from app.models import (
    JobDescription,
    JobParserInfo,
    JobParserName,
    MatchMode,
    Priority,
    Requirement,
    Seniority,
)
from app.services.jd_parser import (
    JobParser,
    ParsedJob,
    RuleJobParser,
    job_min_years,
    min_years_in,
    seniority_for,
)
from app.services.skills import SkillCatalog, phrase_pattern
from app.services.text import normalize, strip_bullet

logger = logging.getLogger("app.jd_parser")

MAX_OUTPUT_TOKENS = 4096

_REASON_TEXT = {
    "timeout": "it didn't answer in time",
    "api_error": "the API call failed",
    "invalid_output": "its answer didn't pass the checks",
}
_YEARS_WORD = re.compile(r"\b(?:years?|yrs?)\b", re.IGNORECASE)
_NUMBER_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    15: "fifteen",
    20: "twenty",
}


class ClaudeRequirement(BaseModel):
    text: str = Field(
        description="The requirement copied exactly from the job description, without its bullet"
    )
    priority: Literal["required", "preferred", "context"]
    skills: list[str] = Field(
        default_factory=list,
        description="Technologies, tools, methods and domains named in the text, as written",
    )
    match_mode: Literal["all", "any"] = "all"
    min_years: int | None = Field(default=None, ge=0, le=60)


class ClaudeJobOutput(BaseModel):
    title: str | None = None
    seniority: Literal["intern", "junior", "mid", "senior", "lead", "unknown"] = "unknown"
    requirements: list[ClaudeRequirement]


def _states_years(text: str, years: int) -> bool:
    if not _YEARS_WORD.search(text):
        return False
    if re.search(rf"(?<!\d){years}(?!\d)", text):
        return True
    word = _NUMBER_WORDS.get(years)
    return word is not None and re.search(rf"\b{word}\b", text, re.IGNORECASE) is not None


def _skills(
    claude_skills: list[str], text: str, catalog: SkillCatalog
) -> tuple[list[str], list[str], int]:
    """Canonical and free-text skills for one requirement, and how many of Claude's
    skills were dropped because the requirement's text doesn't name them.

    A skill counts as named when the catalog finds it in the text, or when Claude's
    term appears in the text as a whole phrase.
    """
    in_text = catalog.requirement_skills(text)
    skills: list[str] = []
    free_text: list[str] = []
    dropped = 0

    def add(name: str) -> None:
        if name.lower() not in {s.lower() for s in skills}:
            skills.append(name)

    for raw in claude_skills:
        name = normalize(raw).strip(" .,;:")
        if not name:
            continue
        found = phrase_pattern(name).search(text)
        mapped = catalog.requirement_skills(name)
        if mapped:
            grounded = [skill for skill in mapped if skill in in_text or found is not None]
            for skill in grounded:
                add(skill)
            if not grounded:
                dropped += 1
            continue
        if found is None:
            dropped += 1
            continue
        phrase = found.group()  # the requirement's own spelling
        if phrase.lower() not in {s.lower() for s in skills}:
            skills.append(phrase)
            free_text.append(phrase)
    for skill in in_text:
        add(skill)
    return skills, free_text, dropped


def build_job(
    output: ClaudeJobOutput, raw: str, catalog: SkillCatalog, rules: JobDescription
) -> tuple[JobDescription, int]:
    """Check Claude's output against the job description. Returns the job and the
    number of requirements dropped because their text isn't in the description."""
    source = normalize(raw)
    requirements: list[Requirement] = []
    seen: set[str] = set()
    dropped = 0
    dropped_skills = 0
    for item in output.requirements:
        text = strip_bullet(normalize(item.text))[0]
        if not text or text not in source:
            dropped += 1
            continue
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        skills, free_text, lost = _skills(item.skills, text, catalog)
        dropped_skills += lost
        years = item.min_years
        if years is None or not _states_years(text, years):
            years = min_years_in(text)
        requirements.append(
            Requirement(
                id=f"r{len(requirements)}",
                text=text,
                priority=Priority(item.priority),
                skills=skills,
                match_mode=MatchMode(item.match_mode),
                min_years=years,
                free_text_skills=free_text,
            )
        )
    if dropped or dropped_skills:
        logger.warning(
            "claude output trimmed",
            extra={"dropped": dropped, "dropped_skills": dropped_skills},
        )

    title = normalize(output.title) if output.title else None
    if not title or title.lower() not in source.lower():
        title = rules.title
    job_years = job_min_years(requirements)
    seniority = Seniority(output.seniority)
    if seniority is Seniority.UNKNOWN:
        seniority = seniority_for(title, job_years)
    job = JobDescription(
        title=title, seniority=seniority, min_years=job_years, requirements=requirements
    )
    return job, dropped


class ClaudeJobParser:
    def __init__(
        self,
        client: LLMClient,
        model: str,
        *,
        fallback: JobParser | None = None,
        prompt: Prompt | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.fallback = fallback or RuleJobParser()
        self.prompt = prompt or load_prompt(*JD_PARSE)

    def parse(self, raw: str, catalog: SkillCatalog) -> ParsedJob:
        rules = self.fallback.parse(raw, catalog)
        try:
            result = self.client.generate(
                system=self.prompt.text,
                user=f"<job_description>\n{raw}\n</job_description>",
                output_type=ClaudeJobOutput,
                model=self.model,
                prompt_version=self.prompt.id,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            job, dropped = build_job(result.output, raw, catalog, rules.job)
        except LLMError as exc:
            return self._fall_back(rules, exc.reason)
        if not job.requirements and rules.job.requirements:
            return self._fall_back(rules, "invalid_output")

        warnings: list[str] = []
        if dropped:
            noun = "requirement" if dropped == 1 else "requirements"
            warnings.append(
                f"Claude returned {dropped} {noun} whose text isn't in the job description, "
                "so they were left out."
            )
        info = JobParserInfo(
            name=JobParserName.CLAUDE,
            prompt_version=self.prompt.id,
            model=result.model,
            dropped_requirements=dropped,
        )
        logger.info(
            "job description parsed",
            extra={
                "parser": "claude",
                "prompt_version": self.prompt.id,
                "requirements": len(job.requirements),
                "dropped": dropped,
            },
        )
        return ParsedJob(job=job, parser=info, warnings=warnings)

    def _fall_back(self, rules: ParsedJob, reason: str) -> ParsedJob:
        logger.warning(
            "claude parser fell back to rules",
            extra={"parser": "rules", "prompt_version": self.prompt.id, "error": reason},
        )
        info = rules.parser.model_copy(update={"fallback_reason": reason})
        warning = (
            "The Claude job-description parser wasn't used for this analysis "
            f"({_REASON_TEXT.get(reason, reason)}), so the rule-based parser read the job "
            "description."
        )
        return ParsedJob(job=rules.job, parser=info, warnings=[*rules.warnings, warning])
