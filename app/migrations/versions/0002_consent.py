"""Consent: when the person agreed to the analysis, which consent text they saw, and
whether Claude may see their resume and job text.

Analyses made before this revision get no consent time or version and no consent
for Claude, so suggestions stay off for them. They expire within RETENTION_HOURS.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain ADD COLUMN works on SQLite and Postgres without rebuilding the table.
    op.add_column("analyses", sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("analyses", sa.Column("consent_version", sa.String(length=32), nullable=True))
    op.add_column(
        "analyses",
        sa.Column("llm_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    # Plain DROP COLUMN, never batch mode: on SQLite batch mode rebuilds the table,
    # and dropping the old analyses table would cascade to every row stored with it.
    # SQLite has DROP COLUMN since 3.35; an older SQLite stops here with an error and
    # loses nothing.
    for column in ("llm_consent", "consent_version", "consent_at"):
        op.drop_column("analyses", column)
