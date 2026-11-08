import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services import accounts
from app.services.skills import SkillCatalog, get_catalog
from app.storage.db import make_engine
from app.storage.migrations import upgrade
from tests.support import TEST_DATABASE_URL, authenticate, make_settings, reset_postgres

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


@pytest.fixture(autouse=True)
def cheap_password_hashing() -> Iterator[None]:
    """argon2id with the real parameters takes about 0.1 s per hash. The tests use
    the smallest ones; test_accounts.py checks the real parameters."""
    accounts.set_hasher(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    yield
    accounts.set_hasher(accounts.default_hasher())


@pytest.fixture(scope="session")
def migrated_sqlite(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A SQLite file migrated once, copied for each test."""
    path = tmp_path_factory.mktemp("template") / "template.db"
    engine = make_engine(f"sqlite:///{path}")
    try:
        upgrade(engine)
    finally:
        engine.dispose()
    return path


@pytest.fixture
def database_url(tmp_path: Path, migrated_sqlite: Path) -> str:
    """A migrated, empty database for one test."""
    if TEST_DATABASE_URL is not None:
        reset_postgres(TEST_DATABASE_URL)
        engine = make_engine(TEST_DATABASE_URL)
        try:
            upgrade(engine)
        finally:
            engine.dispose()
        return TEST_DATABASE_URL
    path = tmp_path / "test.db"
    shutil.copyfile(migrated_sqlite, path)
    return f"sqlite:///{path}"


@pytest.fixture
def empty_database_url(tmp_path: Path) -> str:
    """A database with no tables at all, for the migration tests."""
    if TEST_DATABASE_URL is not None:
        reset_postgres(TEST_DATABASE_URL)
        return TEST_DATABASE_URL
    return f"sqlite:///{tmp_path / 'empty.db'}"


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
def settings(database_url: str) -> Settings:
    return make_settings(database_url)


@pytest.fixture
def anon_client(settings: Settings) -> Iterator[TestClient]:
    """A client with no session."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def client(anon_client: TestClient) -> TestClient:
    """A client logged in as person@example.com."""
    authenticate(anon_client)
    return anon_client
