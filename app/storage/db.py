"""Database setup. SQLite locally; any SQLAlchemy URL (Postgres in v1.0) in production.

v0.3 only adds tables. `create_all` creates missing tables and leaves existing
ones alone, so a v0.2 database file starts without changes: its old analyses
simply have no stored resume lines, and the endpoints that need them say so.
Alembic migrations replace this in v1.0.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

_ANALYSIS_FK = "analyses.id"


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


class ResumeRecord(Base):
    """The lines the app read from the resume (added in v0.3, for export). They are
    the same personal data the report quotes, and expire with the analysis."""

    __tablename__ = "analysis_resumes"

    analysis_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(_ANALYSIS_FK, ondelete="CASCADE"), primary_key=True
    )
    resume_json: Mapped[str] = mapped_column(Text)


class SuggestionRecord(Base):
    """A rewrite that passed the fact checker, with the person's decision."""

    __tablename__ = "suggestions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(_ANALYSIS_FK, ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(String(16))
    span_id: Mapped[str] = mapped_column(String(16))
    source_text: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    prompt_version: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    # Order within the request that made it; suggestions made together share created_at.
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SuggestionRunRecord(Base):
    """One request for suggestions: what was asked of Claude and what came back.
    Counts only, never text. The per-analysis cap is the sum of `requested`."""

    __tablename__ = "suggestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(_ANALYSIS_FK, ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    calls: Mapped[int] = mapped_column(Integer)
    requested: Mapped[int] = mapped_column(Integer)
    returned: Mapped[int] = mapped_column(Integer)
    rejected: Mapped[int] = mapped_column(Integer)
    kept: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)


class CorrectionRecord(Base):
    """The person's fix for a line the app read wrongly."""

    __tablename__ = "span_corrections"

    analysis_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(_ANALYSIS_FK, ondelete="CASCADE"), primary_key=True
    )
    span_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GapAnswerRecord(Base):
    """The person's answer to a gap question. Never inserted into the resume."""

    __tablename__ = "gap_answers"

    analysis_id: Mapped[str] = mapped_column(
        String(32), ForeignKey(_ANALYSIS_FK, ondelete="CASCADE"), primary_key=True
    )
    requirement_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    answer: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Everything stored with an analysis, deleted with it.
CHILD_TABLES: tuple[type[Base], ...] = (
    ResumeRecord,
    SuggestionRecord,
    SuggestionRunRecord,
    CorrectionRecord,
    GapAnswerRecord,
)


def analysis_column(table: type[Base]) -> ColumnElement[str]:
    """The column that links a table's rows to their analysis."""
    column: ColumnElement[str] = (
        table.__table__.c.id if table is AnalysisRecord else table.__table__.c.analysis_id
    )
    return column


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
            # SQLite ignores foreign keys unless asked. The repository also deletes
            # child rows itself, so this is a second line of defense.
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    # Creates missing tables only. v1.0 replaces this with Alembic migrations.
    Base.metadata.create_all(engine)


class Database:
    def __init__(self, database_url: str) -> None:
        self.engine = make_engine(database_url)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Iterator[Session]:
        with self._sessions() as session:
            yield session
