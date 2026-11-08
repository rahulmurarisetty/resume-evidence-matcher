"""Version requirements: "Angular 12 or later", "Java 11+", ".NET 6 or newer".

A requirement that names a minimum version is direct only when a line that shows the
skill also gives a version at least that high. Without one it is partial at most, and
the next step asks the person to add the version if it is true.
"""

import re
from dataclasses import dataclass

from app.models import Evidence, EvidenceStrength
from app.services.skills import SkillCatalog

_MINIMUM = re.compile(
    r"(?P<version>\d{1,3}(?:\.\d{1,3})?)\s*(?:\+(?!\s*(?:years?|yrs)\b)|or\s+(?:later|newer|higher"
    r"|above|greater|more\s+recent)\b|and\s+(?:above|up|later|newer)\b)",
    re.IGNORECASE,
)
_VERSION_AFTER = re.compile(r"^\s*(?:v(?:ersion)?\.?\s*)?(?P<version>\d{1,3}(?:\.\d{1,3})?)\b")


@dataclass(frozen=True)
class VersionAsk:
    skill: str
    term: str  # the requirement's own spelling ("Angular")
    minimum: tuple[int, ...]


def _number(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def version_asks(text: str, catalog: SkillCatalog) -> list[VersionAsk]:
    """The minimum versions a requirement asks for, one per skill."""
    asks: list[VersionAsk] = []
    for hit in catalog.find(text):
        found = _MINIMUM.match(text[hit.end :].lstrip())
        if found is None or text[hit.end : hit.end + 1] not in {" ", ""}:
            continue
        asks.append(VersionAsk(hit.skill, hit.term, _number(found.group("version"))))
    return asks


def shown_version(evidence: list[Evidence], ask: VersionAsk, catalog: SkillCatalog) -> bool:
    """Does a line that shows the skill give a version at least the minimum?"""
    for item in evidence:
        if item.strength is not EvidenceStrength.DEMONSTRATED:
            continue
        for hit in catalog.find(item.text):
            if hit.skill != ask.skill:
                continue
            found = _VERSION_AFTER.match(item.text[hit.end :])
            if found is not None and _number(found.group("version")) >= ask.minimum:
                return True
        # A later mention of the same term ("Angular 9, then Angular 14").
        later = re.compile(rf"\b{re.escape(ask.term)}\s*v?(\d{{1,3}}(?:\.\d{{1,3}})?)\b")
        if any(_number(found.group(1)) >= ask.minimum for found in later.finditer(item.text)):
            return True
    return False


def version_note(ask: VersionAsk) -> str:
    version = ".".join(str(part) for part in ask.minimum)
    return (
        f"Asks for {ask.term} {version} or later. The lines that show {ask.term} don't say "
        f"which version, so this is partial at most. If you used {version} or later, add "
        "the version to that bullet."
    )
