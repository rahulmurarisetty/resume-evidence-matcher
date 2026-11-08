"""The downloadable match report, as HTML and as Markdown.

Both are built from the same Document, so they always say the same thing. The
HTML is meant to be accessible on its own: it declares its language, has one h1
and headings in order, gives every table a caption and header cells with scope,
writes each status in words (never color alone), uses dark text on a white
background, and loads nothing: no scripts, fonts, images or other files. Its only
style is one inline <style> block.
"""

import html
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.models import (
    AnalysisReport,
    MatchStatus,
    Priority,
    RequirementMatch,
    Section,
)
from app.services.questions import GapQuestion

STATUS_WORDS = {
    MatchStatus.DIRECT: "Proven",
    MatchStatus.PARTIAL: "Partly shown",
    MatchStatus.ADJACENT: "Related, please check",
    MatchStatus.GAP: "Missing",
    MatchStatus.NOT_ASSESSED: "Check it yourself",
}
PRIORITY_WORDS = {
    Priority.REQUIRED: "Required",
    Priority.PREFERRED: "Preferred",
    Priority.CONTEXT: "Job duties",
}
SECTION_WORDS = {
    Section.HEADER: "top of the resume",
    Section.SUMMARY: "summary",
    Section.EXPERIENCE: "experience",
    Section.PROJECTS: "projects",
    Section.SKILLS: "skills",
    Section.EDUCATION: "education",
    Section.CERTIFICATIONS: "certifications",
    Section.OTHER: "other",
}
EMPLOYER_SYSTEMS_NOTE = (
    "Employers use different applicant tracking systems and different criteria, so "
    "there is no universal ATS score, and this app doesn't produce one. This report "
    "shows which lines of your resume support each requirement of this one job "
    "description. It is not a prediction of any employer's decision."
)
TERMS_NOTE = (
    "These lines describe how the job is contracted or who may apply. They are not "
    "requirements, and the app didn't use them to score anything."
)
QUESTIONS_NOTE = (
    "Your answers are kept with this analysis and never added to your resume. The app "
    "never fills in a number for you."
)
ADVICE_NOTE = (
    "Advice about order only. Nothing in your resume was moved: you decide whether to "
    "move anything."
)


@dataclass
class Table:
    caption: str
    headers: list[str]
    rows: list[list[str]]


@dataclass
class Item:
    """One requirement or question: a heading and its lines."""

    title: str
    fields: list[tuple[str, str]] = field(default_factory=list)
    quotes: list[tuple[str, str]] = field(default_factory=list)  # (label, quote)
    closing: list[tuple[str, str]] = field(default_factory=list)  # after the quotes


@dataclass
class Part:
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    table: Table | None = None
    bullets: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    subparts: list["Part"] = field(default_factory=list)


@dataclass
class Document:
    title: str
    intro: list[str]
    parts: list[Part]


def where(section: Section, page: int | None) -> str:
    place = SECTION_WORDS.get(section, section.value)
    return f"{place}, page {page}" if page else place


def _coverage(report: AnalysisReport) -> Part:
    statuses = list(STATUS_WORDS)
    rows = []
    for priority, label in PRIORITY_WORDS.items():
        counts = report.coverage.get(priority)
        if counts is None or not counts.total:
            continue
        rows.append([label, str(counts.total), *(str(getattr(counts, s.value)) for s in statuses)])
    return Part(
        heading="Coverage by priority",
        paragraphs=[
            "How many requirements of each priority the resume proves. Each status is "
            "explained with every requirement below."
        ],
        table=Table(
            caption="Requirements per priority and status",
            headers=["Priority", "Total", *(STATUS_WORDS[s] for s in statuses)],
            rows=rows,
        ),
    )


def _requirement(match: RequirementMatch) -> Item:
    requirement = match.requirement
    item = Item(title=requirement.text)
    item.fields.append(("Status", STATUS_WORDS[match.status]))
    if requirement.skills:
        item.fields.append(("Skills asked for", ", ".join(requirement.skills)))
    if match.years_found is not None:
        item.fields.append(("Years the resume shows", f"about {match.years_found:g}"))
    seen: set[str] = set()
    for skill in match.skills:
        for evidence in skill.evidence:
            if evidence.span_id in seen:
                continue
            seen.add(evidence.span_id)
            label = f"Evidence for {skill.skill} ({where(evidence.section, evidence.page)})"
            item.quotes.append((label, evidence.text))
    for related in match.related_evidence:
        label = (
            f"Related by meaning, confirm it ({where(related.section, related.page)}, "
            f"score {related.score:.2f})"
        )
        item.quotes.append((label, related.text))
    if not seen and not match.related_evidence:
        item.fields.append(("Evidence", "No resume line was cited."))
    item.closing.append(("Next step", match.next_action))
    return item


def _requirements(report: AnalysisReport) -> Part:
    part = Part(
        heading="Requirements",
        paragraphs=[
            "Each requirement as written in the job description, with its status, the "
            "resume lines that support it and the next step."
        ],
    )
    for priority, label in PRIORITY_WORDS.items():
        matches = [m for m in report.matches if m.requirement.priority is priority]
        if matches:
            part.subparts.append(Part(heading=label, items=[_requirement(m) for m in matches]))
    if not report.matches:
        part.paragraphs.append("No requirements were found in the job description.")
    return part


def _roles(report: AnalysisReport) -> Part:
    profile = report.profile
    rows = [
        [
            role.title or "not read",
            role.employer or "not read",
            role.client or "none",
            role.start or "not read",
            "present" if role.is_current else role.end or "not read",
        ]
        for role in profile.roles
    ]
    paragraphs = []
    if profile.total_years is not None:
        paragraphs.append(
            f"Years of experience read from the role dates: about {profile.total_years:g}."
        )
    paragraphs.append(
        "Check these against your resume. If one is wrong, fix the line in the app before "
        "you rely on the years."
    )
    return Part(
        heading="Roles read from your resume",
        paragraphs=paragraphs,
        table=Table(
            caption="Roles with their dates",
            headers=["Title", "Employer", "Client", "Start", "End"],
            rows=rows,
        )
        if rows
        else None,
    )


def _advice(report: AnalysisReport) -> Part:
    advice = [a.message for a in report.section_advice]
    return Part(
        heading="Section order advice",
        paragraphs=[ADVICE_NOTE] if advice else ["No advice about order for this resume."],
        bullets=advice,
    )


def _questions(questions: Sequence[GapQuestion], answers: Mapping[str, str]) -> Part:
    gap = [q for q in questions if q.kind == "gap"]
    metric = [q for q in questions if q.kind == "metric"]
    part = Part(heading="Questions for you", paragraphs=[QUESTIONS_NOTE])

    def item(question: GapQuestion) -> Item:
        title = question.requirement_text if question.kind == "gap" else question.line
        entry = Item(title=title or question.question)
        entry.fields.append(("Question", question.question))
        entry.fields.append(("Your answer", answers.get(question.id) or "Not answered yet."))
        return entry

    if gap:
        part.subparts.append(
            Part(heading="Missing or related requirements", items=[item(q) for q in gap])
        )
    if metric:
        part.subparts.append(
            Part(heading="Bullets without a number", items=[item(q) for q in metric])
        )
    if not questions:
        part.paragraphs.append("No questions for this analysis.")
    return part


def build_document(
    report: AnalysisReport,
    questions: Sequence[GapQuestion],
    answers: Mapping[str, str],
    *,
    created_at: datetime,
    expires_at: datetime,
) -> Document:
    job = report.job.title or "the job description"
    terms = report.job.employment_terms
    warnings = [*report.warnings, *report.profile.warnings]
    parser = report.job_parser.name.value
    return Document(
        title=f"Match report: {job}",
        intro=[
            f"Made {created_at:%Y-%m-%d %H:%M} UTC. The analysis is deleted at "
            f"{expires_at:%Y-%m-%d %H:%M} UTC, or sooner if you delete it.",
            f"Matching: {report.matching_mode.value}. Job description read by: {parser}. "
            f"Pipeline version {report.pipeline_version}.",
        ],
        parts=[
            Part(heading="About this report", paragraphs=[EMPLOYER_SYSTEMS_NOTE]),
            _coverage(report),
            _requirements(report),
            _advice(report),
            _questions(questions, answers),
            Part(
                heading="Terms noticed in the posting",
                paragraphs=[TERMS_NOTE] if terms else ["None noticed."],
                bullets=list(terms),
            ),
            _roles(report),
            Part(
                heading="Warnings",
                paragraphs=[] if warnings else ["None."],
                bullets=warnings,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

# Dark text on white (contrast 17.4:1), and borders at 7:1 against white.
STYLE = (
    "body{font-family:system-ui,-apple-system,'Segoe UI',Arial,sans-serif;line-height:1.5;"
    "color:#1a1a1a;background:#ffffff;margin:0}"
    "main{max-width:52rem;margin:0 auto;padding:1.5rem}"
    "h1{font-size:1.75rem}h2{font-size:1.4rem;margin-top:2rem;border-bottom:1px solid #595959}"
    "h3{font-size:1.15rem;margin-top:1.5rem}h4{font-size:1rem;margin-top:1.25rem}"
    "table{border-collapse:collapse;margin:1rem 0}caption{text-align:left;font-weight:bold;"
    "padding:0.25rem 0}th,td{border:1px solid #595959;padding:0.3rem 0.6rem;text-align:left;"
    "vertical-align:top}blockquote{margin:0.25rem 0 0.75rem;padding-left:0.75rem;"
    "border-left:3px solid #595959}dt{font-weight:bold}dd{margin:0 0 0.5rem 0}"
)


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _html_table(table: Table) -> list[str]:
    lines = ["<table>", f"<caption>{_e(table.caption)}</caption>", "<thead><tr>"]
    lines += [f'<th scope="col">{_e(h)}</th>' for h in table.headers]
    lines += ["</tr></thead>", "<tbody>"]
    for row in table.rows:
        cells = [f'<th scope="row">{_e(row[0])}</th>', *(f"<td>{_e(c)}</td>" for c in row[1:])]
        lines.append("<tr>" + "".join(cells) + "</tr>")
    lines += ["</tbody>", "</table>"]
    return lines


def _html_item(item: Item, level: int) -> list[str]:
    lines = [f"<h{level}>{_e(item.title)}</h{level}>"]
    if item.fields:
        lines.append("<dl>")
        for label, value in item.fields:
            lines.append(f"<dt>{_e(label)}</dt><dd>{_e(value)}</dd>")
        lines.append("</dl>")
    for label, quote in item.quotes:
        lines.append(f"<p>{_e(label)}:</p>")
        lines.append(f"<blockquote><p>{_e(quote)}</p></blockquote>")
    if item.closing:
        lines.append("<dl>")
        for label, value in item.closing:
            lines.append(f"<dt>{_e(label)}</dt><dd>{_e(value)}</dd>")
        lines.append("</dl>")
    return lines


def _html_part(part: Part, level: int) -> list[str]:
    lines = [f"<section><h{level}>{_e(part.heading)}</h{level}>"]
    lines += [f"<p>{_e(p)}</p>" for p in part.paragraphs]
    if part.table is not None:
        lines += _html_table(part.table)
    if part.bullets:
        lines += ["<ul>", *(f"<li>{_e(b)}</li>" for b in part.bullets), "</ul>"]
    for item in part.items:
        lines += _html_item(item, level + 1)
    for sub in part.subparts:
        lines += _html_part(sub, level + 1)
    lines.append("</section>")
    return lines


def render_html(document: Document) -> str:
    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_e(document.title)}</title>",
        f"<style>{STYLE}</style>",
        "</head>",
        "<body>",
        "<main>",
        f"<h1>{_e(document.title)}</h1>",
        *(f"<p>{_e(p)}</p>" for p in document.intro),
    ]
    for part in document.parts:
        lines += _html_part(part, 2)
    lines += ["</main>", "</body>", "</html>"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|$])")


def _md_text(text: str) -> str:
    """Resume and job text as Markdown that shows the characters as written: "*",
    "_", "$" and the like don't turn into formatting."""
    return _MD_SPECIAL.sub(r"\\\1", text).replace("\n", " ")


def _md_table(table: Table) -> list[str]:
    lines = [
        f"Table: {table.caption}",
        "",
        "| " + " | ".join(table.headers) + " |",
        "| " + " | ".join("---" for _ in table.headers) + " |",
    ]
    lines += ["| " + " | ".join(_md_text(c) for c in row) + " |" for row in table.rows]
    return [*lines, ""]


def _md_part(part: Part, level: int) -> list[str]:
    lines = [f"{'#' * level} {_md_text(part.heading)}", ""]
    for paragraph in part.paragraphs:
        lines += [_md_text(paragraph), ""]
    if part.table is not None:
        lines += _md_table(part.table)
    if part.bullets:
        lines += [*(f"- {_md_text(b)}" for b in part.bullets), ""]
    for item in part.items:
        lines += [f"{'#' * (level + 1)} {_md_text(item.title)}", ""]
        lines += [f"- {label}: {_md_text(value)}" for label, value in item.fields]
        if item.fields:
            lines.append("")
        for label, quote in item.quotes:
            lines += [f"{label}:", "", f"> {_md_text(quote)}", ""]
        if item.closing:
            lines += [f"- {label}: {_md_text(value)}" for label, value in item.closing]
            lines.append("")
    for sub in part.subparts:
        lines += _md_part(sub, level + 1)
    return lines


def render_markdown(document: Document) -> str:
    lines = [f"# {_md_text(document.title)}", ""]
    for paragraph in document.intro:
        lines += [paragraph, ""]
    for part in document.parts:
        lines += _md_part(part, 2)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"
