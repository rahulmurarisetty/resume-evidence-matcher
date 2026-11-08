import sys
import types
from datetime import date
from typing import Any, ClassVar

import numpy as np
import pytest

from app.models import (
    FileType,
    MatchingMode,
    MatchMode,
    MatchStatus,
    Priority,
    RelatedEvidence,
    Requirement,
    ResumeDocument,
    Section,
    Span,
    SpanKind,
)
from app.services import semantic
from app.services.analysis import analyze
from app.services.jd_parser import parse_job_description
from app.services.matcher import (
    SEMANTIC_FAILED_WARNING,
    SEMANTIC_OFF_WARNING,
    build_report,
    index_evidence,
    match_requirement,
)
from app.services.semantic import (
    CrossEncoderReranker,
    SemanticMatcher,
    SentenceTransformerEncoder,
    load_models,
)
from app.services.skills import SkillCatalog
from tests.builders import build_pdf
from tests.fakes import BrokenEncoder, FakeEncoder, FakeReranker

TODAY = date(2026, 11, 8)
E, SU, SK = Section.EXPERIENCE, Section.SUMMARY, Section.SKILLS
H, B, L = SpanKind.HEADING, SpanKind.BULLET, SpanKind.LINE


def _resume(*spans: tuple[str, Section, SpanKind]) -> ResumeDocument:
    return ResumeDocument(
        file_type=FileType.PDF,
        page_count=1,
        spans=[
            Span(id=f"s{i}", text=text, kind=kind, section=section, page=1, order=i)
            for i, (text, section, kind) in enumerate(spans)
        ],
    )


RESUME = _resume(
    ("SUMMARY", SU, H),
    ("Engineer who enjoys streaming data and mentoring", SU, L),
    ("EXPERIENCE", E, H),
    ("Data Engineer, Example Corp | Jan 2021 - Present", E, L),
    ("Built event streaming pipelines that feed fraud alerts", E, B),
    ("Coached two junior engineers through their first on-call rotation", E, B),
    ("Wrote Python jobs that load claims data", E, B),
    ("SKILLS", SK, H),
    ("Python, SQL", SK, L),
)


def _requirement(text: str, skills: list[str] | None = None) -> Requirement:
    return Requirement(
        id="r0",
        text=text,
        priority=Priority.REQUIRED,
        skills=skills or [],
        match_mode=MatchMode.ANY if " or " in text else MatchMode.ALL,
    )


def _matcher(threshold: float = 0.5, top_k: int = 8) -> SemanticMatcher:
    return SemanticMatcher(FakeEncoder(), FakeReranker(), top_k=top_k, threshold=threshold)


def _report(catalog: SkillCatalog, jd: str, matcher: SemanticMatcher | None = None):  # type: ignore[no-untyped-def]
    job = parse_job_description(jd, catalog)
    return build_report(RESUME, job, catalog, semantic=matcher or _matcher(), today=TODAY)


# ---------------------------------------------------------------------------
# SemanticMatcher
# ---------------------------------------------------------------------------


def test_related_evidence_is_found_and_ranked() -> None:
    related = _matcher().find_related(RESUME, [_requirement("Mentor junior engineers")])["r0"]
    assert related[0].span_id == "s5"
    assert related[0].section is Section.EXPERIENCE
    assert related[0].score == 1.0
    assert [r.score for r in related] == sorted((r.score for r in related), reverse=True)
    assert all(r.span_id not in {"s0", "s2", "s7"} for r in related)  # never headings


def test_threshold_is_respected() -> None:
    requirement = [_requirement("Mentor junior engineers on call")]
    loose = _matcher(threshold=0.2).find_related(RESUME, requirement)["r0"]
    strict = _matcher(threshold=0.9).find_related(RESUME, requirement)["r0"]
    assert {r.span_id for r in strict} < {r.span_id for r in loose}
    assert all(r.score >= 0.9 for r in strict)
    assert _matcher(threshold=1.0).find_related(RESUME, [_requirement("Kubernetes")])["r0"] == []


def test_top_k_limits_candidates() -> None:
    reranker = FakeReranker()
    matcher = SemanticMatcher(FakeEncoder(), reranker, top_k=1, threshold=0.0)
    assert len(matcher.find_related(RESUME, [_requirement("Mentor engineers")])["r0"]) == 1
    with pytest.raises(ValueError):
        SemanticMatcher(FakeEncoder(), top_k=0)


def test_without_reranker_cosine_is_the_score() -> None:
    matcher = SemanticMatcher(FakeEncoder(), None, threshold=0.3)
    related = matcher.find_related(RESUME, [_requirement("Coached two junior engineers")])["r0"]
    assert related[0].span_id == "s5"
    assert 0.3 <= related[0].score <= 1.0
    assert round(related[0].score, 3) == related[0].score


def test_empty_inputs() -> None:
    assert _matcher().find_related(RESUME, []) == {}
    headings_only = _resume(("EXPERIENCE", E, H))
    assert _matcher().find_related(headings_only, [_requirement("Python")]) == {}


# ---------------------------------------------------------------------------
# ADJACENT and the rules around it
# ---------------------------------------------------------------------------


def test_adjacent_when_named_skill_is_missing(catalog: SkillCatalog) -> None:
    report = _report(catalog, "Requirements\n- Experience with Kafka streaming pipelines\n")
    match = report.matches[0]
    assert match.requirement.skills == ["Kafka"]
    assert match.status is MatchStatus.ADJACENT
    assert match.related_evidence[0].span_id == "s4"
    assert match.next_action.startswith("The resume doesn't name Kafka, but this line looks")
    assert '"Built event streaming pipelines that feed fraud alerts". Check' in match.next_action
    assert "only where it is true" in match.next_action
    assert report.coverage[Priority.REQUIRED].adjacent == 1
    # The named skill is still missing, and the report says so.
    assert report.missing_required_skills == ["Kafka"]


def test_adjacent_when_no_skill_is_named(catalog: SkillCatalog) -> None:
    report = _report(catalog, "Requirements\n- Mentor junior engineers\n")
    match = report.matches[0]
    assert match.status is MatchStatus.ADJACENT
    assert match.next_action.startswith("No exact match, but this line looks related:")
    assert "Coached two junior engineers" in match.next_action


def test_related_lines_outside_work_do_not_make_adjacent(catalog: SkillCatalog) -> None:
    resume = _resume(
        ("SUMMARY", SU, H),
        ("Engineer who enjoys mentoring junior engineers", SU, L),
        ("EXPERIENCE", E, H),
        ("Wrote Python jobs", E, B),
    )
    job = parse_job_description("Requirements\n- Mentor junior engineers\n", catalog)
    report = build_report(resume, job, catalog, semantic=_matcher(), today=TODAY)
    match = report.matches[0]
    assert match.related_evidence[0].section is Section.SUMMARY
    assert match.status is MatchStatus.NOT_ASSESSED
    assert "no closely related line was found by meaning" in match.next_action


def test_gap_stays_gap_when_nothing_is_related(catalog: SkillCatalog) -> None:
    report = _report(catalog, "Requirements\n- Experience with Terraform\n")
    assert report.matches[0].status is MatchStatus.GAP


def test_exact_evidence_is_never_downgraded(catalog: SkillCatalog) -> None:
    report = _report(
        catalog, "Requirements\n- Python jobs that load claims data\n", _matcher(threshold=0.2)
    )
    match = report.matches[0]
    assert match.status is MatchStatus.DIRECT
    exact = {e.span_id for s in match.skills for e in s.evidence}
    assert exact == {"s6", "s8"}
    # Related evidence adds lines; it never repeats exact evidence.
    assert match.related_evidence
    assert not exact & {r.span_id for r in match.related_evidence}


def test_partial_stays_partial(catalog: SkillCatalog) -> None:
    report = _report(catalog, "Requirements\n- SQL for streaming pipelines\n")
    assert report.matches[0].status is MatchStatus.PARTIAL


def test_years_only_requirement_is_never_adjacent(catalog: SkillCatalog) -> None:
    report = _report(
        catalog, "Requirements\n- 9+ years building streaming pipelines\n", _matcher(0.3)
    )
    match = report.matches[0]
    assert match.status is MatchStatus.GAP
    assert match.related_evidence  # shown, but the years decide the status


def test_long_quotes_are_shortened() -> None:
    long_text = "Built event streaming pipelines " + "with many careful steps " * 10
    related = RelatedEvidence(span_id="s1", text=long_text, section=E, page=1, score=0.9)
    requirement = _requirement("Streaming pipelines")
    match = match_requirement(requirement, {}, related=[related])
    assert match.status is MatchStatus.ADJACENT
    quote = match.next_action.split('"')[1]
    assert quote.endswith("...")
    assert len(quote) <= 163


def test_any_of_adjacent_counts_missing_skills(catalog: SkillCatalog) -> None:
    resume = RESUME
    requirement = Requirement(
        id="r0",
        text="Kafka or Kinesis streaming pipelines",
        priority=Priority.REQUIRED,
        skills=["Kafka", "Kinesis"],
        match_mode=MatchMode.ANY,
    )
    related = _matcher().find_related(resume, [requirement])["r0"]
    match = match_requirement(
        requirement, index_evidence(resume, requirement.skills, catalog), related=related
    )
    assert match.status is MatchStatus.ADJACENT
    assert "doesn't name Kafka or Kinesis" in match.next_action


# ---------------------------------------------------------------------------
# Off, failing, and end to end
# ---------------------------------------------------------------------------


def test_off_mode_leaves_related_evidence_empty(
    data_engineer_markup: str, data_engineer_jd: str
) -> None:
    _, report = analyze(build_pdf(data_engineer_markup), data_engineer_jd, today=TODAY)
    assert report.matching_mode is MatchingMode.EXACT
    assert report.pipeline_version == "0.4.0-exact"
    assert SEMANTIC_OFF_WARNING in report.warnings
    assert all(m.related_evidence == [] for m in report.matches)
    assert all(m.status is not MatchStatus.ADJACENT for m in report.matches)


def test_failing_model_falls_back_to_exact(
    data_engineer_markup: str, data_engineer_jd: str
) -> None:
    _, report = analyze(
        build_pdf(data_engineer_markup), data_engineer_jd, encoder=BrokenEncoder(), today=TODAY
    )
    assert report.matching_mode is MatchingMode.EXACT
    assert SEMANTIC_FAILED_WARNING in report.warnings
    assert report.coverage[Priority.REQUIRED].direct == 5


def test_sample_with_fakes(data_engineer_markup: str, data_engineer_jd: str) -> None:
    exact_doc, exact = analyze(build_pdf(data_engineer_markup), data_engineer_jd, today=TODAY)
    _, report = analyze(
        build_pdf(data_engineer_markup),
        data_engineer_jd,
        encoder=FakeEncoder(),
        reranker=FakeReranker(),
        today=TODAY,
    )
    assert report.matching_mode is MatchingMode.SEMANTIC
    assert report.pipeline_version == "0.4.0-semantic"
    assert SEMANTIC_OFF_WARNING not in report.warnings
    statuses = {m.requirement.text: m.status for m in report.matches}
    assert statuses["Mentor two junior engineers and review their code"] is MatchStatus.ADJACENT
    assert statuses["Partner with analysts to define metrics and data contracts"] is (
        MatchStatus.ADJACENT
    )
    assert report.coverage[Priority.CONTEXT].adjacent == 2
    # Nothing that had exact evidence changed.
    for before, after in zip(exact.matches, report.matches, strict=True):
        if before.status in (MatchStatus.DIRECT, MatchStatus.PARTIAL):
            assert after.status is before.status
            assert after.skills == before.skills
    assert report.coverage[Priority.REQUIRED] == exact.coverage[Priority.REQUIRED]
    span_ids = {s.id for s in exact_doc.spans}
    for match in report.matches:
        assert all(r.span_id in span_ids for r in match.related_evidence)


# ---------------------------------------------------------------------------
# The real model wrappers, driven by a stand-in sentence_transformers module
# ---------------------------------------------------------------------------


class _Identity:
    pass


class Sigmoid:
    pass


class _StubSentenceTransformer:
    loads: ClassVar[list[str]] = []

    def __init__(self, name: str) -> None:
        self.loads.append(name)

    def encode(self, texts: list[str], **kwargs: Any) -> Any:
        assert kwargs["normalize_embeddings"] is True
        return np.ones((len(texts), 3), dtype=np.float64) / np.sqrt(3)


class _StubCrossEncoder:
    """Recent sentence-transformers: raw logits and an identity activation_fn."""

    loads: ClassVar[list[str]] = []

    def __init__(self, name: str) -> None:
        self.loads.append(name)
        self.activation_fn = _Identity()

    def predict(self, pairs: list[tuple[str, str]], **kwargs: Any) -> Any:
        logits = [0.0, 50.0, -800.0]
        return np.array([logits[i % 3] for i in range(len(pairs))])


class _StubV3CrossEncoder(_StubCrossEncoder):
    """sentence-transformers 3 names the activation default_activation_function."""

    def __init__(self, name: str) -> None:
        self.loads.append(name)
        self.default_activation_function = Sigmoid()

    def predict(self, pairs: list[tuple[str, str]], **kwargs: Any) -> Any:
        return np.array([0.25, 0.75])


@pytest.fixture
def stub_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = _StubSentenceTransformer  # type: ignore[attr-defined]
    module.CrossEncoder = _StubCrossEncoder  # type: ignore[attr-defined]
    _StubSentenceTransformer.loads = []
    _StubCrossEncoder.loads = []
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return module


def test_encoder_loads_once_and_returns_float32(
    stub_sentence_transformers: types.ModuleType,
) -> None:
    encoder = SentenceTransformerEncoder()
    assert _StubSentenceTransformer.loads == []  # nothing loads until it's needed
    vectors = encoder.encode(["a", "b"])
    encoder.encode(["c"])
    assert vectors.dtype == np.float32
    assert vectors.shape == (2, 3)
    assert _StubSentenceTransformer.loads == ["sentence-transformers/all-MiniLM-L6-v2"]


def test_reranker_maps_logits_to_0_1(stub_sentence_transformers: types.ModuleType) -> None:
    reranker = CrossEncoderReranker()
    scores = reranker.score("query", ["a", "b", "c"])
    assert scores[0] == 0.5
    assert scores[1] == pytest.approx(1.0)
    assert scores[2] == pytest.approx(0.0)
    assert reranker.score("query", []) == []
    assert _StubCrossEncoder.loads == ["cross-encoder/ms-marco-MiniLM-L6-v2"]


def test_reranker_keeps_scores_that_are_already_probabilities(
    stub_sentence_transformers: types.ModuleType,
) -> None:
    stub_sentence_transformers.CrossEncoder = _StubV3CrossEncoder  # type: ignore[attr-defined]
    assert CrossEncoderReranker("my/model").score("q", ["a", "b"]) == [0.25, 0.75]


def test_load_models_warms_both(stub_sentence_transformers: types.ModuleType) -> None:
    encoder, reranker = load_models("enc/model", "rerank/model")
    assert _StubSentenceTransformer.loads == ["enc/model"]
    assert _StubCrossEncoder.loads == ["rerank/model"]
    matcher = SemanticMatcher(encoder, reranker, threshold=0.4)
    related = matcher.find_related(RESUME, [_requirement("anything")])["r0"]
    # Six candidate lines get logits 0, 50, -800, 0, 50, -800.
    assert [r.score for r in related] == [1.0, 1.0, 0.5, 0.5]


def test_availability_check(
    monkeypatch: pytest.MonkeyPatch, stub_sentence_transformers: types.ModuleType
) -> None:
    monkeypatch.setattr(semantic.importlib.util, "find_spec", lambda name: object())
    assert semantic.sentence_transformers_available()
    monkeypatch.setattr(semantic.importlib.util, "find_spec", lambda name: None)
    assert not semantic.sentence_transformers_available()
