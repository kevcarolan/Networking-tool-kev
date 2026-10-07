"""Database engine and session handling (SQLite by default). The schema is kept up to
date by Alembic migrations (app/core/migrate.py, backend/migrations/)."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def init_engine(database_url: str):
    engine = create_engine(database_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    from app.core import migrate

    import_models()
    result = migrate.upgrade(engine, Base.metadata)
    logging.getLogger(__name__).info("Database: %s", result)
    SessionLocal.configure(bind=engine)
    return engine


def import_models() -> None:
    """Import every model module so its tables are registered on Base.metadata."""
    from app.core import models  # noqa: F401
    from app.tools.circuits import models as circuit_models  # noqa: F401
    from app.tools.config_backup import models as backup_models  # noqa: F401
    from app.tools.firmware_upgrade import models as firmware_models  # noqa: F401


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session
