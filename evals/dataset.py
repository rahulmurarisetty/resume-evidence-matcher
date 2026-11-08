"""Load the labeled evaluation set in evals/data/ into typed records."""

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class GoldRole:
    title: str
    employer: str
    start: str | None  # YYYY-MM
    end: str | None  # YYYY-MM, None for a current role


@dataclass(frozen=True)
class GoldEducation:
    degree: str
    school: str
    year: int | None


@dataclass(frozen=True)
class GoldResume:
    name: str
    markup: str
    as_of: date
    roles: tuple[GoldRole, ...]
    total_years: float
    education: tuple[GoldEducation, ...]


@dataclass(frozen=True)
class GoldRequirement:
    text: str
    priority: str  # required, preferred or context


@dataclass(frozen=True)
class GoldJob:
    name: str
    text: str
    title: str
    min_years: int | None
    requirements: tuple[GoldRequirement, ...]


@dataclass(frozen=True)
class GoldPairItem:
    text: str
    status: str  # direct, partial, adjacent, gap or needs_check
    evidence: tuple[str, ...]
    note: str | None


@dataclass(frozen=True)
class GoldPair:
    resume: str
    job: str
    fit: str  # strong, mixed or wrong
    items: tuple[GoldPairItem, ...]

    @property
    def key(self) -> str:
        return f"{self.resume} x {self.job}"


@dataclass(frozen=True)
class FactCase:
    id: str
    source: str
    rewrite: str
    label: str  # adds_fact or faithful
    added: tuple[str, ...]
    category: str


@dataclass(frozen=True)
class Dataset:
    resumes: dict[str, GoldResume]
    jobs: dict[str, GoldJob]
    pairs: tuple[GoldPair, ...]
    factcheck_dev: tuple[FactCase, ...]
    factcheck_holdout: tuple[FactCase, ...]

    @property
    def as_of(self) -> date:
        """The labels' "today". Every resume in the set uses the same date."""
        dates = sorted({resume.as_of for resume in self.resumes.values()})
        if len(dates) != 1:
            raise ValueError(f"expected one as_of date in the labels, found {dates}")
        return dates[0]

    def limited(self, pair_count: int) -> "Dataset":
        """The first `pair_count` pairs and only the resumes and jobs they use. Used by
        the smoke test to keep it fast."""
        pairs = self.pairs[:pair_count]
        resume_names = {pair.resume for pair in pairs}
        job_names = {pair.job for pair in pairs}
        return replace(
            self,
            pairs=pairs,
            resumes={k: v for k, v in self.resumes.items() if k in resume_names},
            jobs={k: v for k, v in self.jobs.items() if k in job_names},
        )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resumes(data_dir: Path) -> dict[str, GoldResume]:
    labels = _read_json(data_dir / "labels" / "resumes.json")
    resumes: dict[str, GoldResume] = {}
    for name, label in labels.items():
        resumes[name] = GoldResume(
            name=name,
            markup=(data_dir / "resumes" / f"{name}.md").read_text(encoding="utf-8"),
            as_of=date.fromisoformat(label["as_of"]),
            roles=tuple(
                GoldRole(r["title"], r["employer"], r["start"], r["end"]) for r in label["roles"]
            ),
            total_years=float(label["total_years"]),
            education=tuple(
                GoldEducation(e["degree"], e["school"], e.get("year")) for e in label["education"]
            ),
        )
    return resumes


def _jobs(data_dir: Path) -> dict[str, GoldJob]:
    labels = _read_json(data_dir / "labels" / "jobs.json")
    return {
        name: GoldJob(
            name=name,
            text=(data_dir / "jobs" / f"{name}.txt").read_text(encoding="utf-8"),
            title=label["title"],
            min_years=label.get("min_years"),
            requirements=tuple(
                GoldRequirement(r["text"], r["priority"]) for r in label["requirements"]
            ),
        )
        for name, label in labels.items()
    }


def _pairs(data_dir: Path) -> tuple[GoldPair, ...]:
    labels = _read_json(data_dir / "labels" / "pairs.json")
    return tuple(
        GoldPair(
            resume=pair["resume"],
            job=pair["job"],
            fit=pair["fit"],
            items=tuple(
                GoldPairItem(
                    text=item["text"],
                    status=item["status"],
                    evidence=tuple(item.get("evidence", [])),
                    note=item.get("note"),
                )
                for item in pair["requirements"]
            ),
        )
        for pair in labels
    )


def _fact_cases(path: Path) -> tuple[FactCase, ...]:
    return tuple(
        FactCase(
            id=case["id"],
            source=case["source"],
            rewrite=case["rewrite"],
            label=case["label"],
            added=tuple(case.get("added", [])),
            category=case["category"],
        )
        for case in _read_json(path)
    )


def load_dataset(data_dir: Path = DATA_DIR) -> Dataset:
    dataset = Dataset(
        resumes=_resumes(data_dir),
        jobs=_jobs(data_dir),
        pairs=_pairs(data_dir),
        factcheck_dev=_fact_cases(data_dir / "labels" / "factcheck.json"),
        factcheck_holdout=_fact_cases(data_dir / "labels" / "factcheck_holdout.json"),
    )
    _check(dataset)
    return dataset


def _check(dataset: Dataset) -> None:
    """Fail early on labels that don't fit together, so a metric never quietly
    skips an item."""
    for pair in dataset.pairs:
        if pair.resume not in dataset.resumes or pair.job not in dataset.jobs:
            raise ValueError(f"pair {pair.key} names a resume or job that has no labels")
        texts = {r.text for r in dataset.jobs[pair.job].requirements}
        for item in pair.items:
            if item.text not in texts:
                raise ValueError(f"pair {pair.key}: {item.text!r} isn't a requirement of the job")
