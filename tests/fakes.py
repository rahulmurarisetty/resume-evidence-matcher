"""Deterministic stand-ins for the sentence-transformers models and for Claude.

The fake encoder hashes word stems into a fixed-size vector, with a small synonym
table so a few different words count as the same idea. The fake reranker scores
the share of the query's words that a passage covers. Neither needs a download,
and both give the same answer on every run and every machine.

FakeLLMClient replays scripted answers instead of calling the Anthropic API.
"""

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ValidationError

from app.llm.client import LLMOutputError, LLMResult, OutputT, Usage

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


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMCall:
    system: str
    user: str
    output_type: type[BaseModel]
    model: str
    prompt_version: str
    max_tokens: int


class FakeLLMClient:
    """A scriptable LLMClient that records every call.

    Give it responses in order, or a `handler` that picks one per call. A response
    is an output object, a dict (validated against the call's output type, as the
    real client does with the tool input) or an exception to raise.
    """

    def __init__(
        self,
        *responses: object,
        handler: Callable[[LLMCall], object] | None = None,
        usage: tuple[int, int] = (120, 40),
        model: str | None = None,
    ) -> None:
        self.responses = list(responses)
        self.handler = handler
        self.usage = usage
        self.model = model
        self.calls: list[LLMCall] = []

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
        call = LLMCall(system, user, output_type, model, prompt_version, max_tokens)
        self.calls.append(call)
        if self.handler is not None:
            response = self.handler(call)
        elif self.responses:
            response = self.responses.pop(0)
        else:
            raise AssertionError("FakeLLMClient got a call it had no response for")
        if isinstance(response, BaseException):
            raise response
        try:
            output = (
                response
                if isinstance(response, output_type)
                else output_type.model_validate(response)
            )
        except ValidationError as exc:
            raise LLMOutputError("fake output didn't match the schema") from exc
        return LLMResult(output=output, usage=Usage(*self.usage), model=self.model or model)
