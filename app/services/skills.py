"""Exact skill recognition against a curated catalog.

This is the deterministic baseline. v0.2 adds matching by meaning on top of it;
this module stays as the source of exact evidence.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

# A term must not touch a letter, digit or underscore on either side, and must not
# be followed by + or # (so "C" never matches inside "C++" or "C#").
_BEFORE = r"(?<![A-Za-z0-9_])"
_AFTER = r"(?![A-Za-z0-9_+#])"
# List-only terms ("Go", "R") must sit between list separators: "Python, Go, SQL".
_LIST_BEFORE = r"(?:^|[,;:/(|]|\band\b|\bor\b)\s*"
_LIST_AFTER = r"\s*(?=[,;/)|]|$|\band\b|\bor\b)"


@dataclass(frozen=True)
class SkillHit:
    skill: str
    term: str  # the text as it appears in the source
    start: int
    end: int


@dataclass(frozen=True)
class _Pattern:
    skill: str
    regex: re.Pattern[str]
    group: int


def _term_regex(term: str) -> str:
    # Spaces in a catalog term also match hyphens and repeated whitespace.
    parts = [re.escape(p) for p in term.split()]
    return r"[\s\-]+".join(parts)


def phrase_pattern(phrase: str) -> re.Pattern[str]:
    """A free-text skill ("Great Expectations") as a case-insensitive whole phrase.
    It must not touch a letter or digit on either side, like catalog terms."""
    return re.compile(f"{_BEFORE}{_term_regex(phrase)}{_AFTER}", re.IGNORECASE)


class SkillCatalog:
    def __init__(self, entries: list[dict[str, object]]) -> None:
        self.categories: dict[str, str] = {}
        self._patterns: list[_Pattern] = []
        for entry in entries:
            name = str(entry["name"])
            self.categories[name] = str(entry.get("category", "other"))
            cs_terms = [str(t) for t in entry.get("cs_aliases", [])]  # type: ignore[attr-defined]
            list_terms = [str(t) for t in entry.get("list_only", [])]  # type: ignore[attr-defined]
            ci_terms = [str(t) for t in entry.get("aliases", [])]  # type: ignore[attr-defined]
            if name not in cs_terms and name not in list_terms:
                ci_terms.append(name)
            self._add(name, ci_terms, flags=re.IGNORECASE)
            self._add(name, cs_terms, flags=0)
            for term in list_terms:
                regex = re.compile(f"{_LIST_BEFORE}({_term_regex(term)}){_LIST_AFTER}")
                self._patterns.append(_Pattern(name, regex, group=1))

    def _add(self, skill: str, terms: list[str], flags: int) -> None:
        if not terms:
            return
        # Longest first so "ASP.NET Core" wins over "ASP.NET".
        ordered = sorted(set(terms), key=len, reverse=True)
        body = "|".join(_term_regex(t) for t in ordered)
        regex = re.compile(f"{_BEFORE}(?:{body}){_AFTER}", flags)
        self._patterns.append(_Pattern(skill, regex, group=0))

    @property
    def skill_names(self) -> list[str]:
        return list(self.categories)

    def knows(self, skill: str) -> bool:
        """Is this a canonical catalog name (not a free-text skill)?"""
        return skill in self.categories

    def find(self, text: str) -> list[SkillHit]:
        """Every catalog skill mentioned in the text, first mention per skill, in
        order of appearance."""
        best: dict[str, SkillHit] = {}
        for pattern in self._patterns:
            for match in pattern.regex.finditer(text):
                start, end = match.span(pattern.group)
                hit = SkillHit(pattern.skill, match.group(pattern.group), start, end)
                current = best.get(pattern.skill)
                if current is None or hit.start < current.start:
                    best[pattern.skill] = hit
                break  # first match of this pattern is enough
        return sorted(best.values(), key=lambda h: h.start)

    def skills_in(self, text: str) -> list[str]:
        return [hit.skill for hit in self.find(text)]


def load_catalog_entries() -> list[dict[str, object]]:
    raw = resources.files("app.data").joinpath("skills.json").read_text(encoding="utf-8")
    entries: list[dict[str, object]] = json.loads(raw)["skills"]
    return entries


@lru_cache
def get_catalog() -> SkillCatalog:
    return SkillCatalog(load_catalog_entries())
