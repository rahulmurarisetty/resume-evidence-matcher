"""Deterministic stand-ins for the sentence-transformers models.

The fake encoder hashes word stems into a fixed-size vector, with a small synonym
table so a few different words count as the same idea. The fake reranker scores
the share of the query's words that a passage covers. Neither needs a download,
and both give the same answer on every run and every machine.
"""

import hashlib
import re

import numpy as np
from numpy.typing import NDArray

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "our",
    "so",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "up",
    "use",
    "used",
    "we",
    "with",
    "you",
    "your",
}
# Stems that mean the same thing for these tests.
SYNONYMS = {
    "coach": "mentor",
    "train": "mentor",
    "guide": "mentor",
    "kafka": "stream",
    "kinesi": "stream",
    "event": "stream",
    "partner": "collaborat",
    "work": "collaborat",
    "dashboard": "report",
    "tableau": "report",
}
DIMENSIONS = 512


def stems(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out: list[str] = []
    for word in words:
        if word in _STOPWORDS:
            continue
        for suffix in ("ing", "ed", "es", "s", "e"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 4:
                word = word[: -len(suffix)]
                break
        out.append(SYNONYMS.get(word, word))
    return out


def _bucket(token: str) -> int:
    # hashlib, not hash(): Python salts str hashes per process.
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest(), "big")


class FakeEncoder:
    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        self.calls += 1
        vectors = np.zeros((len(texts), DIMENSIONS), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in stems(text):
                vectors[row, _bucket(token) % DIMENSIONS] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        unit: NDArray[np.float32] = vectors / norms
        return unit


class FakeReranker:
    """Score = share of the query's distinct stems found in the passage."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.queries.append(query)
        wanted = set(stems(query))
        if not wanted:
            return [0.0 for _ in passages]
        return [len(wanted & set(stems(p))) / len(wanted) for p in passages]


class BrokenEncoder:
    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        raise RuntimeError("model failed")
