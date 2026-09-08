from __future__ import annotations

import io
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app import main as main_module
from app.config import Settings
from app.models import Base

API_ROOT = Path(__file__).resolve().parents[1]
HEAD_REVISION = "d9a2f18b6c41"


def _config() -> Config:
    return Config(str(API_ROOT / "alembic.ini"))


def test_fresh_sqlite_upgrade_matches_current_metadata(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    config = _config()

    command.upgrade(config, "head")
    # A second invocation is intentionally a no-op, proving redrivable deploys.
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        assert "budget_reservation" in inspector.get_table_names()
        assert set(inspector.get_table_names()) == {*Base.metadata.tables, "alembic_version"}
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={"compare_type": True, "compare_server_default": True},
            )
            assert compare_metadata(context, Base.metadata) == []
            assert (
                connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                == HEAD_REVISION
            )
    finally:
        engine.dispose()


def test_approval_migration_backfills_only_checked_in_fixture_rows(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "approval-backfill.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    config = _config()
    command.upgrade(config, "c14c172f08b5")

    engine = create_engine(f"sqlite:///{database_path}")
    insert_sql = """
        INSERT INTO recording (
            id, workspace_id, created_by, display_name, original_filename,
            content_type, requested_language, requested_mode, vocabulary_hints,
            tags, summary_style, source_kind, status, stage, original_ready,
            transcript_ready, intelligence_ready, indexed_ready,
            deletion_generation, transcript_version, intelligence_version,
            etag_version, cancel_requested, created_at, updated_at,
            retention_expires_at
        ) VALUES (
            ?, 'test-workspace', 'test-account', ?, ?, 'audio/wav', 'en', 'standard',
            '[]', '[]', 'standard', ?, 'READY', 'ready', 1, 1, 1, 1,
            0, 1, 1, 1, 0, '2026-09-07 00:00:00', '2026-09-07 00:00:00',
            '2026-10-07 00:00:00'
        )
    """
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                insert_sql,
                ("fixture-row", "Fixture", "fixture.wav", "approved_fixture"),
            )
            connection.exec_driver_sql(
                insert_sql,
                ("upload-row", "Upload", "upload.wav", "upload"),
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.connect() as connection:
            rows = dict(
                connection.exec_driver_sql(
                    "SELECT id, provider_data_approved FROM recording ORDER BY id"
                ).all()
            )
            assert rows == {"fixture-row": 1, "upload-row": 0}
            assert "_alembic_tmp_recording" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()


def test_postgresql_offline_sql_includes_pgvector_and_budget_table(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://migration_user:placeholder@db.invalid/pocket",
    )
    config = _config()
    output = io.StringIO()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)

    sql = output.getvalue().casefold()
    assert "create extension if not exists vector" in sql
    assert "create table budget_reservation" in sql
    assert "create table evidence_unit" in sql


def test_single_baseline_head_and_no_dotenv_loader() -> None:
    config = _config()
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [HEAD_REVISION]
    env_source = (API_ROOT / "alembic" / "env.py").read_text(encoding="utf-8").casefold()
    assert "dotenv" not in env_source


def test_postgresql_app_startup_leaves_schema_ownership_to_alembic(
    tmp_path: Path, monkeypatch
) -> None:
    calls = {"create_all": 0, "closed": 0}

    class StubDatabase:
        def __init__(self, _url: str) -> None:
            self.engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        @contextmanager
        def session_factory(self):
            yield object()

        def create_all(self) -> None:
            calls["create_all"] += 1

        def close(self) -> None:
            calls["closed"] += 1

    monkeypatch.setattr(main_module, "Database", StubDatabase)
    monkeypatch.setattr(main_module, "seed_reference_data", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_module, "seed_demo_recordings", lambda *_args, **_kwargs: None)
    settings = Settings(
        database_url="postgresql+psycopg://placeholder.invalid/pocket",
        blob_root=tmp_path / "blobs",
        fixture_root=API_ROOT.parents[1] / "fixtures",
        inline_worker=False,
        cookie_secure=False,
        token_signing_secret="test-only-signing-secret-at-least-32-characters",
    )
    with TestClient(main_module.create_app(settings)):
        pass

    assert calls == {"create_all": 0, "closed": 1}
