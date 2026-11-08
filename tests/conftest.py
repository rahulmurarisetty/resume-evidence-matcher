from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.skills import SkillCatalog, get_catalog

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


@pytest.fixture(scope="session")
def catalog() -> SkillCatalog:
    return get_catalog()


@pytest.fixture(scope="session")
def data_engineer_markup() -> str:
    return (SAMPLES / "resumes" / "jordan_example_data_engineer.md").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def dotnet_markup() -> str:
    return (SAMPLES / "resumes" / "riley_sample_dotnet.md").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def data_engineer_jd() -> str:
    return (SAMPLES / "jobs" / "data_engineer.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def dotnet_jd() -> str:
    return (SAMPLES / "jobs" / "dotnet_fullstack.txt").read_text(encoding="utf-8")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        max_upload_mb=1,
        retention_hours=24,
        log_level="WARNING",
        # Tests never load real models. Matching by meaning is tested with fakes.
        semantic_matching="off",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
