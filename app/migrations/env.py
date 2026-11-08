"""Alembic environment.

The database comes from, in order: a connection the app passes in
(config.attributes["connection"]), the sqlalchemy.url option, or DATABASE_URL
through the app's settings. SQLite needs batch mode to change tables, so every
migration runs with render_as_batch.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.storage.db import Base, make_engine

config = context.config
target_metadata = Base.metadata

# Only the alembic command line has an ini file. The app configures its own logs.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    from app.config import Settings

    return Settings().database_url


def _configure(**options: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
        **options,  # type: ignore[arg-type]
    )


def run_migrations_offline() -> None:
    _configure(url=_database_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = make_engine(_database_url())
    try:
        with engine.begin() as conn:
            _run(conn)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
