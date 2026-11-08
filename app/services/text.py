"""Text helpers shared by resume extraction and job-description parsing."""

import re
import unicodedata

from app.models import Section

# Bullet glyphs seen in real resumes, including the private-use characters that
# Word's Symbol and Wingdings fonts produce when exported to PDF.
_BULLET_CHARS = "•●▪■◦‣∙·*\u2013\u2014➢►▶✓✔❖→-"
BULLET_RE = re.compile(rf"^\s*(?:[{re.escape(_BULLET_CHARS)}]|o(?=\s)|\d{{1,2}}[.)])\s+")
BULLET_ONLY_RE = re.compile(rf"^\s*[{re.escape(_BULLET_CHARS)}o]\s*$")
PAGE_FOOTER_RE = re.compile(r"^\s*page\s+\d+(\s+of\s+\d+)?\s*$", re.IGNORECASE)

_SECTION_HEADINGS: dict[Section, tuple[str, ...]] = {
    Section.SUMMARY: (
        "summary",
        "professional summary",
        "career summary",
        "executive summary",
        "profile",
        "professional profile",
        "objective",
        "career objective",
        "about me",
        "summary of qualifications",
        "qualifications summary",
        "professional overview",
        "career profile",
    ),
    Section.EXPERIENCE: (
        "experience",
        "work experience",
        "professional experience",
        "relevant experience",
        "employment",
        "employment history",
        "work history",
        "career history",
        "professional background",
        "professional history",
        "career experience",
        "employment experience",
        "industry experience",
        "technical experience",
        "relevant work experience",
        "internships",
        "internship experience",
        "work experience and internships",
    ),
    Section.PROJECTS: (
        "projects",
        "personal projects",
        "academic projects",
        "key projects",
        "selected projects",
    ),
    Section.SKILLS: (
        "skills",
        "technical skills",
        "core skills",
        "key skills",
        "core competencies",
        "technologies",
        "tech stack",
        "technical proficiencies",
        "skills and tools",
        "skills summary",
        "technical skills summary",
        "areas of expertise",
        "technical expertise",
        "tools and technologies",
        "key competencies",
        "competencies",
        "skill set",
        "tools",
        "software",
        "technical tools",
        "software and tools",
    ),
    Section.EDUCATION: (
        "education",
        "academic background",
        "education and training",
        "educational background",
        "academic qualifications",
        "educational qualifications",
        "education and certifications",
    ),
    Section.CERTIFICATIONS: (
        "certifications",
        "certificates",
        "licenses and certifications",
        "certifications and training",
        "certifications and licenses",
        "professional certifications",
        "training and certifications",
        "licenses",
    ),
    Section.OTHER: (
        "awards",
        "honors",
        "awards and honors",
        "publications",
        "volunteer experience",
        "volunteering",
        "languages",
        "interests",
        "achievements",
        "activities",
        "references",
        "honors and awards",
        "volunteer work",
        "affiliations",
        "professional affiliations",
        "memberships",
    ),
}

_HEADING_LOOKUP: dict[str, Section] = {
    name: section for section, names in _SECTION_HEADINGS.items() for name in names
}


def normalize(text: str) -> str:
    """NFKC-normalize (splits ligatures, turns non-breaking spaces into spaces) and
    collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_bullet(text: str) -> tuple[str, bool]:
    """Return the text without its leading bullet glyph and whether it had one."""
    match = BULLET_RE.match(text)
    if match:
        return text[match.end() :].strip(), True
    return text.strip(), False


def section_for_heading(line: str) -> Section | None:
    """Map a heading line such as 'PROFESSIONAL EXPERIENCE' or 'Skills:' to a section.

    Only whole-line headings count. 'Languages: Python, Java' inside a skills
    section is content, not a new section.
    """
    key = line.strip().rstrip(":").strip().lower()
    key = key.replace("&", "and").replace("/", " and ")
    key = re.sub(r"\s+", " ", key)
    return _HEADING_LOOKUP.get(key)
