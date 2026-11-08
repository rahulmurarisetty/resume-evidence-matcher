"""Running and checking the Alembic migrations from the app.

At startup the app either upgrades the database (DB_AUTO_MIGRATE, the default
locally) or checks that it is already at the newest revision and refuses to
start when it isn't (the default in production, where migrations run once as a
separate step).

    python -m app.storage.migrations    # print the revision; exit 1 if migrations are pending
"""

import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

from app.errors import StartupError

logger = logging.getLogger("app.storage")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


@dataclass(frozen=True)
class SchemaStatus:
    current: str | None
    head: str
    # Tables made by v0.5 or earlier, which kept no migration history.
    legacy: bool
    dialect: str

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head

    @property
    def legacy_upgradable(self) -> bool:
        """v0.5 only shipped a SQLite driver, and only its SQLite files are upgraded
        in place. See app/migrations/versions/0001_initial_schema.py."""
        return self.legacy and self.dialect == "sqlite"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert head is not None, "app/migrations/versions has no revisions"
    return head


def schema_status(engine: Engine) -> SchemaStatus:
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
        legacy = current is None and inspect(connection).has_table("analyses")
    return SchemaStatus(
        current=current, head=head_revision(), legacy=legacy, dialect=engine.dialect.name
    )


def _legacy_error() -> StartupError:
    return StartupError(
        "The database has tables from v0.5 or earlier, which kept no migration history, "
        "and it isn't SQLite, the only database v0.5 shipped a driver for. Its analyses "
        "have no owner and expire within a day, so start from an empty database: drop its "
        "tables, then start again."
    )


def upgrade(engine: Engine) -> None:
    """Bring the database to the newest revision (`alembic upgrade head`). A SQLite
    file from v0.5 or earlier is upgraded in place, its analyses kept for the local
    account."""
    status = schema_status(engine)
    if status.legacy and not status.legacy_upgradable:
        raise _legacy_error()
    if status.up_to_date:
        return
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    before = "v0.5 tables" if status.legacy else status.current or "empty"
    logger.info("database migrated", extra={"revision": status.head, "from_revision": before})


def ensure_current(engine: Engine) -> None:
    """Refuse to start unless the database is at the newest revision."""
    status = schema_status(engine)
    if status.legacy and not status.legacy_upgradable:
        raise _legacy_error()
    if not status.up_to_date:
        if status.legacy:
            where = "has tables from v0.5 or earlier"
        else:
            where = f"is at {status.current or 'no revision (empty)'}"
        raise StartupError(
            f"Database migrations are pending: the database {where} and this version "
            f"needs {status.head}. Run `alembic upgrade head` with the same DATABASE_URL "
            "(in the container: start it once with RUN_MIGRATIONS=true), then start the "
            "app again."
        )


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    """Print where the database stands. Exit 0 when it is up to date, 1 when not."""
    from app.config import Settings
    from app.storage.db import make_engine

    del argv  # no options yet
    out = out or sys.stdout
    engine = make_engine(Settings().database_url)
    try:
        status = schema_status(engine)
    finally:
        engine.dispose()
    if status.up_to_date:
        print(f"The database is at revision {status.head}, the newest.", file=out)
        return 0
    found = "tables from v0.5 or earlier" if status.legacy else status.current or "no revision"
    print(
        f"Migrations are pending: the database has {found} and this version needs "
        f"{status.head}. Run `alembic upgrade head`.",
        file=out,
    )
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
