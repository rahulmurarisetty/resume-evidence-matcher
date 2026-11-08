"""Text normalization and one-to-one alignment of predictions with labels.

Two kinds of comparison are used:

- Requirement texts are compared after normalizing case, whitespace and
  punctuation. A prediction matches a label when the two are equal, when one
  contains the other, or when their fuzzy ratio is at least FUZZY_THRESHOLD.
- Fields such as a role's title or employer match when they are equal after the
  same normalization, or when their fuzzy ratio is at least FUZZY_THRESHOLD.

The fuzzy ratio is difflib's SequenceMatcher ratio (2 * matches / total length),
with autojunk off so long and short strings are treated alike. It is in the
standard library and gives the same answer on every machine.
"""

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from typing import TypeVar

FUZZY_THRESHOLD = 0.85

_NOT_WORD = re.compile(r"[\W_]+")
_SPACE = re.compile(r"\s+")

P = TypeVar("P")
G = TypeVar("G")


def normalize_text(text: str | None) -> str:
    """Lowercase, NFKC, every run of punctuation or whitespace turned into one space."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).casefold()
    return _NOT_WORD.sub(" ", text).strip()


def normalize_space(text: str | None) -> str:
    """NFKC and collapsed whitespace, case and punctuation kept. Used for evidence
    strings, which the labels copy exactly from the resume."""
    if not text:
        return ""
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


class MatchKind(StrEnum):
    EXACT = "exact"
    CONTAINS = "contains"
    FUZZY = "fuzzy"


@dataclass(frozen=True)
class TextMatch:
    kind: MatchKind
    ratio: float

    @property
    def score(self) -> float:
        """Used to rank candidate pairs: an exact match first, then by ratio."""
        return self.ratio + (1.0 if self.kind is MatchKind.EXACT else 0.0)


def text_match(predicted: str, gold: str, threshold: float = FUZZY_THRESHOLD) -> TextMatch | None:
    """How a predicted requirement text matches a gold one, or None."""
    a, b = normalize_text(predicted), normalize_text(gold)
    if not a or not b:
        return None
    if a == b:
        return TextMatch(MatchKind.EXACT, 1.0)
    similarity = ratio(a, b)
    if a in b or b in a:
        return TextMatch(MatchKind.CONTAINS, similarity)
    if similarity >= threshold:
        return TextMatch(MatchKind.FUZZY, similarity)
    return None


def field_score(
    predicted: str | None, gold: str | None, threshold: float = FUZZY_THRESHOLD
) -> float | None:
    """1.0 when two fields are equal after normalization, their ratio when it reaches
    the threshold, and None otherwise. Two empty fields are equal."""
    a, b = normalize_text(predicted), normalize_text(gold)
    if a == b:
        return 1.0
    if not a or not b:
        return None
    similarity = ratio(a, b)
    return similarity if similarity >= threshold else None


def all_fields_score(
    pairs: Sequence[tuple[str | None, str | None]], threshold: float = FUZZY_THRESHOLD
) -> float | None:
    """Mean field score when every field matches, else None."""
    scores: list[float] = []
    for predicted, gold in pairs:
        score = field_score(predicted, gold, threshold)
        if score is None:
            return None
        scores.append(score)
    return sum(scores) / len(scores) if scores else None


@dataclass(frozen=True)
class Alignment:
    """Which prediction was matched to which label. Indexes refer to the input lists."""

    matched: tuple[tuple[int, int, float], ...]  # (predicted index, gold index, score)
    unmatched_predicted: tuple[int, ...]
    unmatched_gold: tuple[int, ...]

    def gold_to_predicted(self) -> dict[int, int]:
        return {g: p for p, g, _ in self.matched}

    def predicted_to_gold(self) -> dict[int, int]:
        return {p: g for p, g, _ in self.matched}


def align(
    predicted: Sequence[P],
    gold: Sequence[G],
    scorer: Callable[[P, G], float | None],
) -> Alignment:
    """Match each prediction to at most one label and each label to at most one
    prediction. Every pair the scorer accepts is a candidate; the best-scoring
    candidates are taken first, ties broken by list order, so the result is the
    same on every run."""
    candidates: list[tuple[float, int, int]] = []
    for p_index, p_item in enumerate(predicted):
        for g_index, g_item in enumerate(gold):
            score = scorer(p_item, g_item)
            if score is not None:
                candidates.append((score, p_index, g_index))
    candidates.sort(key=lambda c: (-c[0], c[2], c[1]))
    used_p: set[int] = set()
    used_g: set[int] = set()
    matched: list[tuple[int, int, float]] = []
    for score, p_index, g_index in candidates:
        if p_index in used_p or g_index in used_g:
            continue
        used_p.add(p_index)
        used_g.add(g_index)
        matched.append((p_index, g_index, round(score, 6)))
    matched.sort(key=lambda m: m[1])
    return Alignment(
        matched=tuple(matched),
        unmatched_predicted=tuple(i for i in range(len(predicted)) if i not in used_p),
        unmatched_gold=tuple(i for i in range(len(gold)) if i not in used_g),
    )


def align_texts(
    predicted: Sequence[str], gold: Sequence[str], threshold: float = FUZZY_THRESHOLD
) -> Alignment:
    def scorer(p: str, g: str) -> float | None:
        found = text_match(p, g, threshold)
        return found.score if found is not None else None

    return align(predicted, gold, scorer)


def evidence_hit(lines: Sequence[str], gold_evidence: Sequence[str], k: int) -> bool:
    """Whether one of the first k lines contains a gold evidence string, or is
    contained in one, after whitespace normalization."""
    golds = [normalize_space(g) for g in gold_evidence if normalize_space(g)]
    for line in lines[:k]:
        text = normalize_space(line)
        if text and any(g in text or text in g for g in golds):
            return True
    return False
