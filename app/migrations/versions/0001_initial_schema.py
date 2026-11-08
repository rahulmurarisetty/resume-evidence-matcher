"""Initial schema: accounts, sessions, and analyses with everything stored with them.

On an empty database this creates every table. A SQLite file from v0.5 or earlier
(made with create_all, with no migration history) is upgraded in place: its tables
are set aside, the new ones are created, and their rows are copied over. Those
analyses had no owner, so they go to the local account that AUTH_MODE=disabled
uses, which is how v0.5 worked (one person, no login). Nobody can log in as that
account, and the analyses still expire when they always would have.

Before 1.0 the app shipped no Postgres driver, so a database from v0.5 or earlier
on any other backend is refused with a message instead of being guessed at.

Revision ID: 0001
Revises:
Create Date: 2026-11-08
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import context, op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_MESSAGE = (
    "This database has tables from v0.5 or earlier, which kept no migration history, "
    "and it isn't SQLite, the only database v0.5 shipped a driver for. Its analyses "
    "have no owner and expire within a day, so start from an empty database: drop its "
    "tables, then run the migrations again."
)
# The tables v0.5 and earlier made: analyses (from v0.1) and the rest (from v0.3).
LEGACY_CHILDREN = (
    "analysis_resumes",
    "suggestions",
    "suggestion_runs",
    "span_corrections",
    "gap_answers",
)
LEGACY_PREFIX = "_v05_"
# The account AUTH_MODE=disabled uses (app/storage/accounts.py). Written out here so
# this migration keeps working whatever later code does. Its email isn't an address
# and its password hash isn't a hash, so nobody can log in as it.
LOCAL_USER = {"id": "local", "email": "local", "password_hash": "!"}


def _timestamp(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False)


def _analysis_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["analysis_id"],
        ["analyses.id"],
        name=op.f(f"fk_{table}_analysis_id_analyses"),
        ondelete="CASCADE",
    )


def _legacy_tables() -> list[str]:
    """The v0.5 tables in this database, parent first. Empty for a new database and
    when writing SQL offline (`alembic upgrade head --sql`)."""
    if context.is_offline_mode():
        return []
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("analyses"):
        return []
    return ["analyses", *(t for t in LEGACY_CHILDREN if inspector.has_table(t))]


def _set_aside(table: str) -> None:
    """Rename a v0.5 table out of the way. Its indexes are dropped first, because
    the new tables use the same index names."""
    for index in sa.inspect(op.get_bind()).get_indexes(table):
        if index["name"]:
            op.drop_index(index["name"], table_name=table)
    op.rename_table(table, LEGACY_PREFIX + table)


def upgrade() -> None:
    legacy = _legacy_tables()
    if legacy and op.get_bind().dialect.name != "sqlite":
        raise RuntimeError(LEGACY_MESSAGE)
    # Children first, so no foreign key ever points at a table that is gone.
    for table in reversed(legacy):
        _set_aside(table)
    users = _create_tables()
    if legacy:
        _carry_over(users, legacy)


def _create_tables() -> sa.Table:
    users = op.create_table(
        "users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        _timestamp("created_at"),
        _timestamp("expires_at"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sessions")),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"])
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"])

    op.create_table(
        "analyses",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("owner_id", sa.String(length=32), nullable=False),
        _timestamp("created_at"),
        _timestamp("expires_at"),
        sa.Column("pipeline_version", sa.String(length=32), nullable=False),
        sa.Column("file_type", sa.String(length=8), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_analyses_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analyses")),
    )
    op.create_index(op.f("ix_analyses_expires_at"), "analyses", ["expires_at"])
    op.create_index(op.f("ix_analyses_owner_id"), "analyses", ["owner_id"])

    op.create_table(
        "analysis_resumes",
        sa.Column("analysis_id", sa.String(length=32), nullable=False),
        sa.Column("resume_json", sa.Text(), nullable=False),
        _analysis_fk("analysis_resumes"),
        sa.PrimaryKeyConstraint("analysis_id", name=op.f("pk_analysis_resumes")),
    )

    op.create_table(
        "suggestions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("analysis_id", sa.String(length=32), nullable=False),
        sa.Column("requirement_id", sa.String(length=16), nullable=False),
        sa.Column("span_id", sa.String(length=16), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _analysis_fk("suggestions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suggestions")),
    )
    op.create_index(op.f("ix_suggestions_analysis_id"), "suggestions", ["analysis_id"])

    op.create_table(
        "suggestion_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("analysis_id", sa.String(length=32), nullable=False),
        _timestamp("created_at"),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("requested", sa.Integer(), nullable=False),
        sa.Column("returned", sa.Integer(), nullable=False),
        sa.Column("rejected", sa.Integer(), nullable=False),
        sa.Column("kept", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        _analysis_fk("suggestion_runs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suggestion_runs")),
    )
    op.create_index(op.f("ix_suggestion_runs_analysis_id"), "suggestion_runs", ["analysis_id"])

    op.create_table(
        "span_corrections",
        sa.Column("analysis_id", sa.String(length=32), nullable=False),
        sa.Column("span_id", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        _timestamp("updated_at"),
        _analysis_fk("span_corrections"),
        sa.PrimaryKeyConstraint("analysis_id", "span_id", name=op.f("pk_span_corrections")),
    )

    op.create_table(
        "gap_answers",
        sa.Column("analysis_id", sa.String(length=32), nullable=False),
        sa.Column("requirement_id", sa.String(length=16), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        _timestamp("updated_at"),
        _analysis_fk("gap_answers"),
        sa.PrimaryKeyConstraint("analysis_id", "requirement_id", name=op.f("pk_gap_answers")),
    )
    return users


def _carry_over(users: sa.Table, legacy: list[str]) -> None:
    """Copy the v0.5 rows into the new tables, then drop the old ones. Rows with an
    empty required field (possible in v0.2 files, whose columns allowed it) are left
    out rather than invented."""
    bind = op.get_bind()
    old = LEGACY_PREFIX + "analyses"
    analysis_columns = [
        "created_at",
        "expires_at",
        "pipeline_version",
        "file_type",
        "file_sha256",
        "report_json",
    ]
    complete = " AND ".join(f"{c} IS NOT NULL" for c in ["id", *analysis_columns])
    if bind.execute(sa.text(f"SELECT COUNT(*) FROM {old} WHERE {complete}")).scalar():
        op.bulk_insert(users, [{**LOCAL_USER, "created_at": datetime.now(UTC)}])
        listed = ", ".join(analysis_columns)
        bind.execute(
            sa.text(
                f"INSERT INTO analyses (id, owner_id, {listed}) "
                f"SELECT id, :owner, {listed} FROM {old} WHERE {complete}"
            ),
            {"owner": LOCAL_USER["id"]},
        )
    for table in legacy[1:]:
        columns = [c["name"] for c in sa.inspect(bind).get_columns(table)]
        listed = ", ".join(columns)
        complete = " AND ".join(f"{c} IS NOT NULL" for c in columns)
        bind.execute(
            sa.text(
                f"INSERT INTO {table} ({listed}) SELECT {listed} FROM {LEGACY_PREFIX}{table} "
                f"WHERE {complete} AND analysis_id IN (SELECT id FROM analyses)"
            )
        )
    for table in reversed(legacy):
        op.drop_table(LEGACY_PREFIX + table)


def downgrade() -> None:
    for table in (
        "gap_answers",
        "span_corrections",
        "suggestion_runs",
        "suggestions",
        "analysis_resumes",
        "analyses",
        "sessions",
        "users",
    ):
        # Dropping a table drops its indexes with it.
        op.drop_table(table)
