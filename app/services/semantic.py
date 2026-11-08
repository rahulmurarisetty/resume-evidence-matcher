"""Matching by meaning.

Exact matching only finds a requirement's skills by name. This module finds resume
lines that are related to a requirement even when they share few of its words:
"Reviewed pull requests for two junior engineers" for "Mentor junior engineers".

It works in two steps. An embedding model (the encoder) turns every resume line
and requirement into a vector, and the closest lines by cosine similarity become
candidates. A cross-encoder (the reranker) then reads each requirement and
candidate together and scores how well they fit. Lines that score above a
threshold are returned as related evidence.

Related evidence is a suggestion for the person to confirm. It never replaces
exact evidence and is never counted as proof.

sentence-transformers (and PyTorch) are optional. They are imported only inside
the classes that use them, so the rest of the app runs without them.
"""

import importlib.util
import logging
import math
import threading
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from app.models import RelatedEvidence, Requirement, ResumeDocument, SpanKind

logger = logging.getLogger("app.semantic")

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L6-v2"
DEFAULT_TOP_K = 8
DEFAULT_THRESHOLD = 0.5


class Encoder(Protocol):
    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        """One unit-length vector per text, as a 2-D array."""
        ...


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]:
        """One relevance score from 0 to 1 per passage, in the same order."""
        ...


def sentence_transformers_available() -> bool:
    return importlib.util.find_spec("sentence_transformers") is not None


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


class _LazyModel:
    """Loads a sentence-transformers model on first use, once, and reuses it."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any = None
        self._lock = threading.Lock()

    def _create(self) -> Any:  # pragma: no cover - replaced by each subclass
        raise NotImplementedError

    def _get(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    logger.info("loading model", extra={"model": self.model_name})
                    self._model = self._create()
        return self._model

    def warm(self) -> None:
        """Load the model now (downloading it on first run) instead of on the first request."""
        self._get()


class SentenceTransformerEncoder(_LazyModel):
    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        super().__init__(model_name)

    def _create(self) -> Any:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self.model_name)

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        vectors = self._get().encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


class CrossEncoderReranker(_LazyModel):
    def __init__(self, model_name: str = DEFAULT_RERANK_MODEL) -> None:
        super().__init__(model_name)
        self._needs_sigmoid = True

    def _create(self) -> Any:
        from sentence_transformers import CrossEncoder

        model = CrossEncoder(self.model_name)
        # The MS MARCO cross-encoders return raw logits in sentence-transformers 4 and
        # later (their config sets an identity activation); version 3 applied a
        # sigmoid by default. Map both to 0..1 so the threshold means the same thing.
        activation = getattr(model, "activation_fn", None)
        if activation is None:
            activation = getattr(model, "default_activation_function", None)
        self._needs_sigmoid = type(activation).__name__ != "Sigmoid"
        return model

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        model = self._get()
        raw = model.predict(
            [(query, passage) for passage in passages],
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        values = [float(v) for v in np.asarray(raw, dtype=np.float64).reshape(-1)]
        if self._needs_sigmoid:
            values = [_sigmoid(v) for v in values]
        return [min(1.0, max(0.0, v)) for v in values]


def load_models(
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    rerank_model: str = DEFAULT_RERANK_MODEL,
) -> tuple[SentenceTransformerEncoder, CrossEncoderReranker]:
    """Build both models and load them now. The first run downloads them."""
    encoder = SentenceTransformerEncoder(embedding_model)
    reranker = CrossEncoderReranker(rerank_model)
    encoder.warm()
    reranker.warm()
    return encoder, reranker


def _unit_rows(matrix: NDArray[Any]) -> NDArray[np.float32]:
    rows = np.atleast_2d(np.asarray(matrix, dtype=np.float32))
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit: NDArray[np.float32] = rows / norms
    return unit


class SemanticMatcher:
    def __init__(
        self,
        encoder: Encoder,
        reranker: Reranker | None = None,
        top_k: int = DEFAULT_TOP_K,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        self.encoder = encoder
        self.reranker = reranker
        self.top_k = top_k
        self.threshold = threshold

    def find_related(
        self, resume: ResumeDocument, requirements: list[Requirement]
    ) -> dict[str, list[RelatedEvidence]]:
        """Related resume lines per requirement id, best first.

        Without a reranker, the cosine similarity is the score.
        """
        spans = [span for span in resume.spans if span.kind is not SpanKind.HEADING]
        if not spans or not requirements:
            return {}
        span_vectors = _unit_rows(self.encoder.encode([span.text for span in spans]))
        requirement_vectors = _unit_rows(self.encoder.encode([r.text for r in requirements]))
        similarity = requirement_vectors @ span_vectors.T
        k = min(self.top_k, len(spans))

        related: dict[str, list[RelatedEvidence]] = {}
        for row, requirement in enumerate(requirements):
            order = [int(i) for i in np.argsort(-similarity[row], kind="stable")[:k]]
            candidates = [spans[i] for i in order]
            if self.reranker is not None:
                scores = self.reranker.score(requirement.text, [s.text for s in candidates])
            else:
                scores = [float(similarity[row, i]) for i in order]
            kept = [
                (span, score)
                for span, score in zip(candidates, scores, strict=True)
                if score >= self.threshold
            ]
            kept.sort(key=lambda item: item[1], reverse=True)
            related[requirement.id] = [
                RelatedEvidence(
                    span_id=span.id,
                    text=span.text,
                    section=span.section,
                    page=span.page,
                    score=round(score, 3),
                )
                for span, score in kept
            ]
        return related
