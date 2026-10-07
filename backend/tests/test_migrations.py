"""Database migrations: new databases, databases from before migrations, and a check that
the migrations bring an old database to exactly what the models describe."""

import shutil
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.core import migrate
from app.core.db import Base, import_models

BASELINE_SQL = Path(__file__).parent / "data" / "baseline_schema.sql"


def _engine(path: Path):
    return create_engine(f"sqlite:///{path}")


def _old_install(path: Path):
    """A database as installs created it before migrations existed."""
    engine = _engine(path)
    sql = "\n".join(ln for ln in BASELINE_SQL.read_text().splitlines() if not ln.startswith("--"))
    with engine.begin() as conn:
        for statement in filter(str.strip, sql.split(";\n")):
            conn.execute(text(statement))
    return engine


def test_new_database_is_created_and_marked_current(tmp_path):
    import_models()
    engine = _engine(tmp_path / "app.db")
    assert migrate.upgrade(engine, Base.metadata).startswith("new database")
    assert migrate.current_revision(engine) == migrate.head_revision()
    assert "devices" in inspect(engine).get_table_names()
    assert migrate.upgrade(engine, Base.metadata).startswith("up to date")


def test_old_install_is_marked_baseline_then_brought_up_to_date(tmp_path):
    import_models()
    engine = _old_install(tmp_path / "app.db")
    assert "alembic_version" not in inspect(engine).get_table_names()
    migrate.upgrade(engine, Base.metadata)
    assert migrate.current_revision(engine) == migrate.head_revision()


def test_migrations_match_the_models(tmp_path):
    """Fails when a model changed without a migration: run
    'alembic revision --autogenerate -m "..."' from backend/ and review the result."""
    import_models()
    engine = _old_install(tmp_path / "app.db")
    migrate.upgrade(engine, Base.metadata)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}),
                                Base.metadata)
    assert diff == [], diff


def test_a_pending_migration_is_applied_after_copying_the_database(tmp_path, monkeypatch):
    import_models()
    scripts = tmp_path / "migrations"
    shutil.copytree(migrate.MIGRATIONS_DIR, scripts)
    (scripts / "versions" / "0002_test.py").write_text('''
import sqlalchemy as sa
from alembic import op

revision = "0002_test"
down_revision = "0001_baseline"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("devices") as batch:
        batch.add_column(sa.Column("test_note", sa.String(50), nullable=True))


def downgrade():
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("test_note")
''')
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", scripts)
    db = tmp_path / "app.db"
    engine = _old_install(db)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO devices (name, address, platform, site, notes, enabled, "
                          "created_at, updated_at) VALUES ('sw1', '10.0.0.1', 'cisco_ios', 'HQ', '', 1, "
                          "'2026-01-01', '2026-01-01')"))
    assert migrate.upgrade(engine, Base.metadata) == "migrated from 0001_baseline to 0002_test"
    cols = {c["name"] for c in inspect(engine).get_columns("devices")}
    assert "test_note" in cols
    assert (tmp_path / "app.db.before-0002_test").exists()
    with engine.connect() as conn:  # the data survived the table copy
        assert conn.execute(text("SELECT name FROM devices")).scalar() == "sw1"


def test_the_app_starts_on_an_old_install(tmp_path, settings):
    from app.main import create_app
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    _old_install(settings.data_dir / "app.db").dispose()
    create_app(settings, start_scheduler=False)
    assert migrate.current_revision(_engine(settings.data_dir / "app.db")) == migrate.head_revision()


def test_lock_file_sits_next_to_the_database(tmp_path):
    import_models()
    engine = _engine(tmp_path / "app.db")
    migrate.upgrade(engine, Base.metadata)
    assert (tmp_path / "app.db.migrate.lock").exists()


def test_cli_db_status(tmp_path, monkeypatch, capsys):
    from app.cli import main
    monkeypatch.setenv("NETOPS_DATA_DIR", str(tmp_path))
    from app.core.config import get_settings
    get_settings.cache_clear()
    try:
        _old_install(tmp_path / "app.db").dispose()
        assert main(["db-status"]) == 0
        assert "none (from before migrations)" in capsys.readouterr().out
        import_models()
        migrate.upgrade(_engine(tmp_path / "app.db"), Base.metadata)
        main(["db-status"])
        assert "Up to date." in capsys.readouterr().out
    finally:
        get_settings.cache_clear()
