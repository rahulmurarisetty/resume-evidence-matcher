"""Database setup. SQLite locally; any SQLAlchemy URL (Postgres in v1.0) in production."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, Engine, String, Text, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class AnalysisRecord(Base):
    """A stored analysis. The uploaded file itself is never stored, only its hash
    (to spot duplicate uploads) and the report built from it."""

    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    pipeline_version: Mapped[str] = mapped_column(String(32))
    file_type: Mapped[str] = mapped_column(String(8))
    file_sha256: Mapped[str] = mapped_column(String(64))
    report_json: Mapped[str] = mapped_column(Text)


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    connect_args: dict[str, object] = {}
    if url.get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)

    if url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    # v1.0 replaces this with Alembic migrations for Postgres.
    Base.metadata.create_all(engine)


class Database:
    def __init__(self, database_url: str) -> None:
        self.engine = make_engine(database_url)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Iterator[Session]:
        with self._sessions() as session:
            yield session
