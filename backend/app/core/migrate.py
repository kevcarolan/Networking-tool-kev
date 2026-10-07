"""Database migrations (Alembic), applied when the app or the worker starts.

  * a new database: the tables are created from the models and marked as up to date;
  * a database from before migrations existed (tables, no version): any missing tables
    are created as before, it is marked as the baseline, then brought up to date;
  * otherwise: pending migrations are applied.

Before any migration runs, the database is copied next to it (app.db.before-<revision>),
so a failed migration, or going back to the previous release, can use the copy. The
installer puts it back by itself when a new release doesn't start.
A lock file stops the web app and the worker migrating at the same time.
"""

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
BASELINE = "0001_baseline"


def alembic_config(connection=None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


@contextmanager
def _lock(path: Path | None):
    """An exclusive lock on a file next to the database (Linux; no-op elsewhere)."""
    if path is None:
        yield
        return
    try:
        import fcntl
    except ImportError:  # Windows development
        yield
        return
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _copy_database(src: Path, dst: Path) -> None:
    """A consistent copy, including changes still in the write-ahead log (a plain file
    copy could miss them)."""
    dst.unlink(missing_ok=True)
    a, b = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()


def upgrade(engine, metadata) -> str:
    """Bring the database up to date. Returns what was done (for the log)."""
    db_file = Path(engine.url.database) if engine.url.database else None
    lock = db_file.with_name(db_file.name + ".migrate.lock") if db_file else None
    with _lock(lock):
        tables = set(inspect(engine).get_table_names())
        head = head_revision()
        if not tables - {"alembic_version"}:
            metadata.create_all(engine)
            with engine.begin() as conn:
                command.stamp(alembic_config(conn), "head")
            return f"new database created at {head}"
        if "alembic_version" not in tables or current_revision(engine) is None:
            metadata.create_all(engine)  # tables added since, as create_all always did
            with engine.begin() as conn:
                command.stamp(alembic_config(conn), BASELINE)
            log.info("Existing database marked as %s (from before migrations)", BASELINE)
        current = current_revision(engine)
        if current == head:
            return f"up to date at {head}"
        if db_file and db_file.exists():
            copy = db_file.with_name(f"{db_file.name}.before-{head}")
            _copy_database(db_file, copy)
            log.info("Database copied to %s before migrating", copy)
        log.info("Migrating the database from %s to %s", current, head)
        with engine.begin() as conn:
            command.upgrade(alembic_config(conn), "head")
        return f"migrated from {current} to {head}"
