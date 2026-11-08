from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.skills import SkillCatalog, get_catalog

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"


@pytest.fixture(autouse=True)
def no_real_claude(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may call the real Anthropic API. A key in the developer's environment
    is removed, so LLM_ENABLED=auto stays off, and any SDK client that is built
    anyway points at a closed local port."""
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "LLM_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9")


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
        # Tests never call Claude. The LLM features are tested with a fake client.
        llm_enabled="off",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
