"""Shared fixtures for the evaluation's tests."""

import json
from pathlib import Path

import pytest

TINY_RESUME = """# Sam Placeholder
## Experience
### Data Engineer, Example Corp | Mar 2022 - Present
- Built Python pipelines on Databricks.
## Education
### B.S. Computer Science, Example University, 2021
"""
TINY_JOB = """Data Engineer

Requirements
- Strong Python skills
- Experience with Kafka
- Bachelor's degree in Computer Science or a related field

Benefits
- 401(k) with a match
"""


@pytest.fixture
def tiny_dataset(tmp_path: Path) -> Path:
    """A one-resume, one-job set with no fact-check labels, written to a temporary
    folder in the same layout as evals/data."""
    root = tmp_path / "tiny_set"
    for folder in ("resumes", "jobs", "labels"):
        (root / folder).mkdir(parents=True)
    (root / "resumes" / "t01.md").write_text(TINY_RESUME, encoding="utf-8")
    (root / "jobs" / "j01.txt").write_text(TINY_JOB, encoding="utf-8")
    labels = {
        "resumes.json": {
            "t01": {
                "as_of": "2026-11-01",
                "roles": [
                    {
                        "title": "Data Engineer",
                        "employer": "Example Corp",
                        "start": "2022-03",
                        "end": None,
                    }
                ],
                "total_years": 4.7,
                "education": [
                    {
                        "degree": "B.S. Computer Science",
                        "school": "Example University",
                        "year": 2021,
                    }
                ],
            }
        },
        "jobs.json": {
            "j01": {
                "title": "Data Engineer",
                "min_years": None,
                "requirements": [
                    {"text": "Strong Python skills", "priority": "required"},
                    {"text": "Experience with Kafka", "priority": "required"},
                    {
                        "text": "Bachelor's degree in Computer Science or a related field",
                        "priority": "required",
                    },
                ],
            }
        },
        "pairs.json": [
            {
                "resume": "t01",
                "job": "j01",
                "fit": "strong",
                "requirements": [
                    {
                        "text": "Strong Python skills",
                        "status": "direct",
                        "evidence": ["Built Python pipelines on Databricks."],
                    },
                    {"text": "Experience with Kafka", "status": "gap"},
                    {
                        "text": "Bachelor's degree in Computer Science or a related field",
                        "status": "direct",
                        "evidence": ["B.S. Computer Science, Example University, 2021"],
                    },
                ],
            }
        ],
    }
    for name, value in labels.items():
        (root / "labels" / name).write_text(json.dumps(value), encoding="utf-8")
    return root
