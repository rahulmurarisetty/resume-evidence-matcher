"""Group the default run's failures into recurring patterns, with examples.

Each pattern is a rule over the outcomes, so the counts update when the app
changes. Counts are of distinct labeled items: the same requirement in the same
pair counts once however many formats got it wrong, and the formats are listed.
"""

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from evals.pairs import NOT_EXTRACTED, ItemOutcome
from evals.requirements import JobExtraction
from evals.resume_structure import MissedItem, ResumeStructure

MAX_EXAMPLES = 3


@dataclass
class Pattern:
    id: str
    area: str
    title: str
    observation: str
    unit: str
    by_format: bool = True
    keys: dict[tuple[str, ...], set[str]] = field(default_factory=dict)
    examples: dict[tuple[str, ...], tuple[str, str, str]] = field(default_factory=dict)

    def add(
        self, key: tuple[str, ...], fmt: str, where: str, what: str, group: str | None = None
    ) -> None:
        """Count `key` once. `group` (default: the key's first part) spreads the chosen
        examples over different resumes or jobs."""
        self.keys.setdefault(key, set()).add(fmt)
        self.examples.setdefault(key, (group or key[0], where, what))

    @property
    def count(self) -> int:
        return len(self.keys)

    def to_dict(self, all_formats: Sequence[str]) -> dict[str, Any]:
        chosen: list[dict[str, str]] = []
        used: set[str] = set()
        # Prefer examples from different resumes or jobs, in data order.
        for prefer_new in (True, False):
            for key, (group, where, what) in self.examples.items():
                if len(chosen) >= MAX_EXAMPLES:
                    break
                entry = {
                    "where": where,
                    "formats": _formats_text(self.keys[key], all_formats) if self.by_format else "",
                    "what": what,
                }
                if entry in chosen or (prefer_new and group in used):
                    continue
                used.add(group)
                chosen.append(entry)
        return {
            "id": self.id,
            "area": self.area,
            "title": self.title,
            "observation": self.observation,
            "count": self.count,
            "unit": self.unit,
            "formats": _formats_text(set().union(*self.keys.values()), all_formats)
            if self.by_format and self.keys
            else "",
            "examples": chosen,
        }


def _formats_text(formats: set[str], all_formats: Sequence[str]) -> str:
    if set(all_formats) <= formats:
        return "all formats"
    return ", ".join(f for f in all_formats if f in formats)


def _short(text: str, limit: int = 110) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _role(gold: dict[str, Any]) -> str:
    return f"{gold['title']}, {gold['employer']}"


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

_STRUCTURE_CAUSES: dict[str, tuple[str, str]] = {
    "not_a_header": (
        "Role header lines in some layouts are read as body text",
        "The line holds a date range the app can read, but it isn't taken as a role header, "
        "so the role and its months are lost.",
    ),
    "outside_section": (
        "Roles or degrees outside their section are not read",
        "Roles are read from an experience section, and education from an education "
        "section. Without such a heading the app reads roles from the lines with date ranges "
        "and degrees from lines that name one, and these entries weren't found that way.",
    ),
    "fields_differ": (
        "Roles are found but the title or employer is split wrongly",
        "The role and its dates are read, but the title and employer are split in another "
        "place than the labels (extra text in one of them, or both in the title), so the "
        "role doesn't match its label.",
    ),
    "dates_unreadable": (
        "Date ranges with a separator the parser doesn't accept are not read",
        "The extracted header has a character between the two dates that the date pattern "
        "doesn't accept, so the role's months aren't counted.",
    ),
    "dates_wrong": (
        "Role dates are read as different months",
        "The role's dates are read, but as different months than the labels.",
    ),
    "joined_lines": (
        "PDF extraction joins a line to the one before it",
        "A line was joined to the paragraph above it, so a role header or an education entry "
        "disappears into another line.",
    ),
    "year_wrong": (
        "Education years are read wrongly",
        "The degree and school are read, but the year differs from the labels.",
    ),
    "not_in_text": (
        "Roles not found in the extracted text",
        "No extracted line holds both the title and the employer.",
    ),
}


def _structure_patterns(results: Sequence[ResumeStructure]) -> list[Pattern]:
    patterns: dict[str, Pattern] = {}

    def pattern_for(cause: str) -> Pattern:
        if cause not in patterns:
            title, observation = _STRUCTURE_CAUSES[cause]
            patterns[cause] = Pattern(
                f"structure_{cause}", "Resume structure", title, observation, "roles or entries"
            )
        return patterns[cause]

    def add(item: MissedItem, kind: str) -> None:
        name = _role(item.gold) if kind == "role" else str(item.gold["degree"])
        what = f"{kind} {name!r}: {item.detail}"
        if item.line is not None:
            what += f' Extracted line: "{_short(item.line)}".'
        pattern_for(item.cause).add((item.resume, kind, name), item.format, item.resume, what)

    for result in results:
        for item in result.missed_roles:
            add(item, "role")
        for item in result.date_errors:
            add(item, "role")
        for item in result.missed_education:
            add(item, "education")
        for item in result.education_errors:
            add(item, "education")
    return list(patterns.values())


# ---------------------------------------------------------------------------
# Requirement extraction
# ---------------------------------------------------------------------------

_BOILERPLATE = re.compile(
    r"salary|compensation|benefit|bonus|equal (?:employment )?opportunit|qualified applicants"
    r"|\bapply\b|paid time off|401\(k\)|dental|vision|\$\d|resume (?:to|and)",
    re.IGNORECASE,
)


def _spurious_kind(text: str) -> str:
    if _BOILERPLATE.search(text):
        return "boilerplate"
    stripped = text.strip()
    if stripped.endswith(":") or (
        len(stripped.split()) <= 4 and ":" not in stripped and not stripped.endswith(".")
    ):
        return "heading"
    return "intro"


def _requirement_patterns(results: Sequence[JobExtraction]) -> list[Pattern]:
    boilerplate = Pattern(
        "jd_boilerplate_kept",
        "Requirement extraction",
        "Benefits, pay and legal lines are kept as requirements",
        "Benefit, salary, equal opportunity, work authorization or how-to-apply lines were "
        "kept, with the priority of the section they are in. Their wording isn't on the "
        "parser's lists.",
        "job lines",
        by_format=False,
    )
    headings = Pattern(
        "jd_heading_kept",
        "Requirement extraction",
        "Unknown section headings are kept as requirements",
        "A heading the parser doesn't recognize is kept as a requirement line, and the lines "
        "under it keep the previous section's priority. Headings ending in a colon or written "
        "in capitals are recognized; others need a known heading word.",
        "job lines",
        by_format=False,
    )
    intro = Pattern(
        "jd_intro_kept",
        "Requirement extraction",
        "Company and posting details are kept as requirements",
        "Company descriptions and posting lines are kept as requirements, usually as "
        "context: they name a skill or address the candidate, so the parser can't tell them "
        "from a duty.",
        "job lines",
        by_format=False,
    )
    by_kind = {"boilerplate": boilerplate, "heading": headings, "intro": intro}
    priority = Pattern(
        "jd_priority",
        "Requirement extraction",
        "Required lines get the wrong priority",
        "A line gets another priority than its label: its section's priority, changed by "
        'wording in the line ("is a plus" makes it preferred, "you should" or "must" makes a '
        "context line required).",
        "job lines",
        by_format=False,
    )
    missed = Pattern(
        "jd_missed",
        "Requirement extraction",
        "Labeled requirements are not extracted",
        "A labeled requirement line has no matching extracted requirement.",
        "job lines",
        by_format=False,
    )
    for result in results:
        for item in result.spurious:
            kind = _spurious_kind(item["text"])
            by_kind[kind].add(
                (result.job, item["text"]),
                "text",
                result.job,
                f'"{_short(item["text"])}" kept as {item["predicted"]}.',
            )
        for item in result.priority_errors:
            priority.add(
                (result.job, item["text"]),
                "text",
                result.job,
                f'"{_short(item["text"])}" labeled {item["gold"]}, parsed as {item["predicted"]}.',
            )
        for item in result.missed:
            missed.add(
                (result.job, item["text"]),
                "text",
                result.job,
                f'"{_short(item["text"])}" ({item["gold"]}) not found.',
            )
    return [boilerplate, headings, intro, priority, missed]


# ---------------------------------------------------------------------------
# Pair statuses and evidence
# ---------------------------------------------------------------------------


def _first_line(item: ItemOutcome) -> str:
    if not item.lines:
        return "no evidence line"
    line = item.lines[0]
    return f'{line.section} line "{_short(line.text, 90)}" ({line.detail})'


def _strengths(item: ItemOutcome) -> str:
    parts = [f"{skill} {strength or 'missing'}" for skill, strength in item.skill_strengths.items()]
    return ", ".join(parts) if parts else "no skills"


@dataclass(frozen=True)
class _PairRule:
    id: str
    title: str
    observation: str
    test: Callable[[ItemOutcome], bool]
    describe: Callable[[ItemOutcome], str]
    group_by: str = "resume"  # spread examples over resumes, or over jobs


def _years_short(item: ItemOutcome) -> bool:
    """A years requirement the labels count as met that the app didn't, either a
    years-only line or a skill line whose skills are all shown."""
    if item.years_only:
        return not item.correct
    shown = bool(item.skill_strengths) and all(
        strength == "demonstrated" for strength in item.skill_strengths.values()
    )
    return bool(item.min_years) and shown and item.gold_status == "direct" and not item.correct


def _describe_years(item: ItemOutcome) -> str:
    read = "no" if item.years_found is None else f"{item.years_found:g}"
    if item.years_only:
        where = f"{read} years read in total"
    else:
        skills = " and ".join(item.skill_strengths)
        where = f"{read} years read in roles that mention {skills}"
    return f"labeled {item.gold_status}, app {item.app_status} with {where}."


def _pair_rules() -> list[_PairRule]:
    return [
        _PairRule(
            "pair_no_catalog_skill",
            "Requirements that name no catalog skill are left for a person to check",
            "The rule parser only finds skills from the skill catalog. A requirement whose "
            "tools or domain are outside it gets no skills, and a degree or certification "
            "requirement the app can't judge is left to a person, so exact matching marks it "
            "needs_check whether the resume proves it, lacks it or shows it in part.",
            lambda i: (
                i.app_status == "needs_check"
                and i.gold_status != "needs_check"
                and not i.years_only
            ),
            lambda i: f"labeled {i.gold_status}; the parser found no catalog skill in it.",
            group_by="job",
        ),
        _PairRule(
            "pair_years_wrong",
            "Years requirements fail when roles weren't read",
            "A years requirement is decided from the roles the app read: their total for "
            '"5+ years of experience", and the roles that mention the skill for "4+ years '
            'with Java". When a role is lost (see the structure patterns) the years fall short '
            "and the requirement becomes a gap or partial, or needs_check when no role was "
            "read at all.",
            _years_short,
            _describe_years,
        ),
        _PairRule(
            "pair_overcredited",
            "A related skill or a missing detail is counted as direct proof",
            "The catalog files some tools under a broader skill as well (JUnit and NUnit also "
            "count as Unit testing, GitHub and GitLab as Git), so a requirement that names the "
            "broad skill can be proven by a line that names another tool, and a domain word "
            '("payments") counts wherever a work line uses it.',
            lambda i: i.app_status == "direct" and i.gold_status != "direct",
            lambda i: f"labeled {i.gold_status}, app direct from the {_first_line(i)}.",
        ),
        _PairRule(
            "pair_undercredited",
            "Work the labels count as shown is found only in a summary or skills line",
            "The labels count the work as shown in a bullet, but the bullet describes it in "
            "other words, so exact matching finds the skill only in the summary or skills "
            "section, or not at all, and calls the requirement partial.",
            lambda i: (
                i.gold_status == "direct"
                and i.app_status == "partial"
                and not i.years_only
                and not _years_short(i)
            ),
            lambda i: f"labeled direct, app partial ({_strengths(i)}).",
        ),
        _PairRule(
            "pair_adjacent_missed",
            "Related experience needs matching by meaning",
            "In exact mode the app never returns adjacent, so related experience the labels "
            "mark adjacent (GitLab CI for GitHub Actions, Java for C#) comes out as gap, "
            "partial or needs_check. Matching by meaning is meant for these and wasn't run.",
            lambda i: i.gold_status == "adjacent" and i.app_status != "adjacent",
            lambda i: f"labeled adjacent, app {i.app_status} ({_strengths(i)}).",
        ),
        _PairRule(
            "pair_partial_to_other",
            "Partly shown requirements get another status",
            "A requirement the labels mark partial gets a different status.",
            lambda i: (
                i.gold_status == "partial"
                and i.app_status not in {"partial", "direct", "needs_check"}
            ),
            lambda i: f"labeled partial, app {i.app_status} ({_strengths(i)}).",
        ),
        _PairRule(
            "pair_not_extracted",
            "Labeled requirements missing from the report",
            "The job parser didn't extract the requirement, so the report has no status for it.",
            lambda i: i.app_status == NOT_EXTRACTED,
            lambda i: f"labeled {i.gold_status}; the parser didn't extract it.",
        ),
        _PairRule(
            "evidence_years_only",
            "Years requirements cite no resume lines",
            "For a years-only requirement the report gives the years it counted but no lines, "
            "while the labels cite the role header lines. These items always miss in evidence "
            "recall, which is why recall is also shown without them.",
            lambda i: i.evidence_scored and i.years_only and not i.hits.get(3, False),
            lambda i: (
                f"labeled {i.gold_status}; the report cites no lines ("
                + (
                    f"{i.years_found} years read)."
                    if i.years_found is not None
                    else "no years read)."
                )
            ),
        ),
        _PairRule(
            "evidence_other_line",
            "The status is right but the first lines cited aren't the labeled ones",
            "The status matches the label, but none of the report's first three lines is a "
            "labeled evidence line. Evidence is listed skill by skill, so the first lines can "
            "all come from one skill of the requirement, or from a broad skill such as ETL "
            '(matched by "data pipelines").',
            lambda i: (
                i.evidence_scored and not i.years_only and i.correct and not i.hits.get(3, False)
            ),
            lambda i: f"labeled {i.gold_status}, app {i.app_status}; first line: {_first_line(i)}.",
        ),
    ]


def _pair_patterns(items: Sequence[ItemOutcome]) -> list[Pattern]:
    patterns: list[Pattern] = []
    for rule in _pair_rules():
        area = "Evidence" if rule.id.startswith("evidence") else "Pair status"
        pattern = Pattern(rule.id, area, rule.title, rule.observation, "labeled requirements")
        for item in items:
            if rule.test(item):
                pattern.add(
                    (item.pair, item.text),
                    item.format,
                    item.pair,
                    f'"{_short(item.text, 90)}": {rule.describe(item)}',
                    group=item.job if rule.group_by == "job" else item.resume,
                )
        patterns.append(pattern)
    return patterns


# ---------------------------------------------------------------------------
# Fact checker
# ---------------------------------------------------------------------------


def _factcheck_patterns(sets: dict[str, dict[str, Any]]) -> list[Pattern]:
    false_reject = Pattern(
        "factcheck_false_reject",
        "Fact checker",
        "Faithful rewrites rejected by the fact checker",
        'The checker errs toward rejecting. A leadership word ("led" for "ran") counts as '
        'a bigger claim, and another catalog name for the same skill ("Kubernetes" for '
        '"K8s") counts as a new product name.',
        "cases",
        by_format=False,
    )
    false_pass = Pattern(
        "factcheck_false_pass",
        "Fact checker",
        "Rewrites that add a fact but pass the fact checker",
        "The checker compares numbers, dates, names, skills, certifications and a fixed list "
        "of scope words, so a changed ordinary word passes.",
        "cases",
        by_format=False,
    )
    for set_name, result in sets.items():
        for case in result["disagreements"]:
            target = false_reject if case["checker"] == "rejected" else false_pass
            reasons = "; ".join(case["checker_reasons"]) or "no reasons"
            target.add(
                (set_name, case["id"]),
                set_name,
                f"{set_name} {case['id']}",
                f'"{_short(case["source"], 80)}" became "{_short(case["rewrite"], 80)}": '
                f"labeled {case['gold']}, checker {case['checker']} ({reasons}).",
            )
    return [false_pass, false_reject]


def find_patterns(
    *,
    structure: Sequence[ResumeStructure],
    requirements: Sequence[JobExtraction],
    items: Sequence[ItemOutcome],
    factcheck: dict[str, dict[str, Any]],
    formats: Sequence[str],
) -> list[dict[str, Any]]:
    """Every pattern with at least one occurrence, most frequent first."""
    patterns: Iterable[Pattern] = [
        *_structure_patterns(structure),
        *_requirement_patterns(requirements),
        *_pair_patterns(items),
        *_factcheck_patterns(factcheck),
    ]
    ordered = sorted(
        (p for p in patterns if p.count), key=lambda p: -p.count
    )  # stable: ties keep the order above
    return [p.to_dict(formats) for p in ordered]
