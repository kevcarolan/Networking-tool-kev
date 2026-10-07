"""Alembic environment. Migrations run on the app's own database (or a connection the
app hands over, see app/core/migrate.py). SQLite can't alter most things in place, so
changes run in 'batch' mode (copy the table, change it, swap it in)."""

from alembic import context
from sqlalchemy import create_engine

from app.core.db import Base, import_models

import_models()
config = context.config
target_metadata = Base.metadata


def run() -> None:
    connection = config.attributes.get("connection")
    if connection is None:  # run from the command line: use the configured database
        from app.core.config import get_settings
        engine = create_engine(get_settings().database_url)
        with engine.begin() as conn:
            _migrate(conn)
        return
    _migrate(connection)


def _migrate(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


run()
