"""Matching by meaning, run only with --semantic.

The real models need the ml extra and a one-time download from Hugging Face, so
this mode never runs in CI. When they can't be loaded the mode is skipped with a
message that says how to run it locally.

The pairs are scored at the app's default threshold and at a few others, so the
labels can be used to choose the threshold. Both models are wrapped in caches,
so each distinct line is encoded once however many thresholds are tried.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.services.semantic import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_RERANK_MODEL,
    DEFAULT_THRESHOLD,
    Encoder,
    Reranker,
    load_models,
    sentence_transformers_available,
)
from app.services.skills import SkillCatalog
from evals.dataset import Dataset
from evals.formats import Format
from evals.pairs import ItemOutcome, summarize
from evals.pipeline import Renderer, run_pairs, score_pairs

SWEEP_THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7)

HOW_TO_RUN = (
    'Install the ml extra (pip install -e ".[dev,ml]", with the CPU-only PyTorch first on '
    "Linux as the README shows), then run python -m evals.run --semantic. The first run "
    "downloads the two models from Hugging Face, about 180 MB."
)


def load_real_models() -> tuple[Encoder, Reranker] | str:
    """Both models, or the reason they can't be used here."""
    if not sentence_transformers_available():
        return "sentence-transformers isn't installed."
    try:
        encoder, reranker = load_models(DEFAULT_EMBEDDING_MODEL, DEFAULT_RERANK_MODEL)
    except Exception as exc:  # no network, no cache, or an incompatible install
        return f"the models couldn't be loaded ({type(exc).__name__})."
    return encoder, reranker


class CachingEncoder:
    def __init__(self, inner: Encoder) -> None:
        self.inner = inner
        self._cache: dict[str, NDArray[np.float32]] = {}

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            vectors = np.atleast_2d(np.asarray(self.inner.encode(missing), dtype=np.float32))
            for text, vector in zip(missing, vectors, strict=True):
                self._cache[text] = vector
        stacked: NDArray[np.float32] = np.stack([self._cache[t] for t in texts])
        return stacked


class CachingReranker:
    def __init__(self, inner: Reranker) -> None:
        self.inner = inner
        self._cache: dict[tuple[str, str], float] = {}

    def score(self, query: str, passages: list[str]) -> list[float]:
        missing = [p for p in dict.fromkeys(passages) if (query, p) not in self._cache]
        if missing:
            for passage, value in zip(missing, self.inner.score(query, missing), strict=True):
                self._cache[(query, passage)] = value
        return [self._cache[(query, p)] for p in passages]


_SWEEP_KEYS = (
    "status_accuracy",
    "false_proven_rate",
    "evidence_recall_at_3",
)


def run_semantic(
    dataset: Dataset,
    formats: Sequence[Format],
    renderer: Renderer,
    catalog: SkillCatalog,
    encoder: Encoder,
    reranker: Reranker | None,
    thresholds: Sequence[float] = SWEEP_THRESHOLDS,
) -> tuple[list[ItemOutcome], dict[str, Any]]:
    """Pair outcomes at the default threshold, and a summary per threshold."""
    cached_encoder = CachingEncoder(encoder)
    cached_reranker = CachingReranker(reranker) if reranker is not None else None
    default_outcomes: list[ItemOutcome] = []
    sweep: list[dict[str, Any]] = []
    fallbacks = 0
    for threshold in sorted({*thresholds, DEFAULT_THRESHOLD}):
        runs = run_pairs(
            dataset,
            formats,
            renderer,
            catalog,
            encoder=cached_encoder,
            reranker=cached_reranker,
            threshold=threshold,
        )
        fallbacks += sum(run.report.matching_mode.value != "semantic" for run in runs)
        outcomes = score_pairs(dataset, runs, "semantic")
        summary = summarize(outcomes)
        sweep.append(
            {
                "threshold": threshold,
                **{key: summary[key] for key in _SWEEP_KEYS},
                "adjacent_precision": summary["per_status"]["adjacent"]["precision"],
                "adjacent_recall": summary["per_status"]["adjacent"]["recall"],
            }
        )
        if threshold == DEFAULT_THRESHOLD:
            default_outcomes = outcomes
    models = {
        "embedding_model": _model_name(encoder),
        "rerank_model": _model_name(reranker) if reranker is not None else None,
    }
    return default_outcomes, {
        **models,
        "threshold_sweep": sweep,
        "reports_without_semantic": fallbacks,
    }


def _model_name(model: object) -> str:
    """The model's name, or its class name for a stand-in such as the test fakes."""
    name = getattr(model, "model_name", None)
    return name if isinstance(name, str) else type(model).__name__
