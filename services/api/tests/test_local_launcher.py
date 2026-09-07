from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.models import Base

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "pocket_run_local", ROOT / "scripts" / "run_local.py"
)
assert SPEC is not None and SPEC.loader is not None
RUN_LOCAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN_LOCAL)


def test_explicit_environment_parser_treats_values_as_data(tmp_path: Path) -> None:
    config = tmp_path / "operator-settings"
    config.write_text(
        """
# This is synthetic configuration, not a real environment file.
export GEMINI_API_KEY='dummy-key-for-parser-test'
GEMINI_BASE_URL=https://example.invalid/v1beta
LITERAL=$(must-not-execute)
""".strip(),
        encoding="utf-8",
    )

    assert RUN_LOCAL.load_explicit_environment(str(config)) == {
        "GEMINI_API_KEY": "dummy-key-for-parser-test",
        "GEMINI_BASE_URL": "https://example.invalid/v1beta",
        "LITERAL": "$(must-not-execute)",
    }


def test_explicit_environment_parser_requires_absolute_path() -> None:
    with pytest.raises(SystemExit, match="absolute path"):
        RUN_LOCAL.load_explicit_environment("operator-settings")


def test_explicit_environment_parser_rejects_duplicates(tmp_path: Path) -> None:
    config = tmp_path / "operator-settings"
    config.write_text("MODE=one\nMODE=two\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="duplicate environment key"):
        RUN_LOCAL.load_explicit_environment(str(config))


def test_missing_local_database_requires_no_stamp(tmp_path: Path) -> None:
    missing = tmp_path / "not-created.db"
    assert RUN_LOCAL.unversioned_sqlite_revision(missing) is None
    assert RUN_LOCAL.legacy_sqlite_needs_stamp(missing) is False


def test_gemini_local_allowlist_contains_required_private_contract_only() -> None:
    assert {
        "GEMINI_API_KEY",
        "GEMINI_BASE_URL",
        "LLM_CHEAP_MODEL",
        "LLM_STRONG_MODEL",
        "MAX_AI_SPEND_PER_RECORDING_USD",
        "MAX_AI_SPEND_PER_ASK_USD",
        "MAX_AI_SPEND_PER_WORKSPACE_MONTH_USD",
        "MAX_CHEAP_REPAIR_ATTEMPTS",
        "MAX_STRONG_REPAIR_ATTEMPTS",
        "MAX_STRONG_CONTEXT_TOKENS",
        "PROVIDER_DATA_POLICY",
        "PROVIDER_ALLOWED_LANGUAGES",
    }.issubset(RUN_LOCAL.GEMINI_LOCAL_ENV_KEYS)
    assert "DATABASE_URL" not in RUN_LOCAL.GEMINI_LOCAL_ENV_KEYS
    assert "EXPO_PUBLIC_GEMINI_API_KEY" not in RUN_LOCAL.GEMINI_LOCAL_ENV_KEYS


def test_legacy_sqlite_stamp_detection_is_narrow(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        for table in RUN_LOCAL.LEGACY_SCHEMA_MARKERS:
            if table == "recording":
                connection.execute(
                    "CREATE TABLE recording ("
                    "id TEXT, workspace_id TEXT, created_by TEXT, requested_mode TEXT, "
                    "source_kind TEXT, intelligence_version INTEGER, "
                    "retention_expires_at DATETIME)"
                )
            else:
                connection.execute(f"CREATE TABLE {table} (id TEXT)")
    assert RUN_LOCAL.legacy_sqlite_needs_stamp(database) is True
    assert RUN_LOCAL.unversioned_sqlite_revision(database) == RUN_LOCAL.BASELINE_REVISION

    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
    assert RUN_LOCAL.legacy_sqlite_needs_stamp(database) is True

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (RUN_LOCAL.BASELINE_REVISION,),
        )
    assert RUN_LOCAL.legacy_sqlite_needs_stamp(database) is False


def test_current_unversioned_sqlite_is_stamped_at_head(tmp_path: Path) -> None:
    database = tmp_path / "current-unversioned.db"
    engine = create_engine(f"sqlite:///{database}")
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()

    assert RUN_LOCAL.unversioned_sqlite_revision(database) == RUN_LOCAL.HEAD_REVISION


def test_unfinished_sqlite_batch_migration_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "unfinished.db"
    with sqlite3.connect(database) as connection:
        for table in RUN_LOCAL.LEGACY_SCHEMA_MARKERS:
            if table == "recording":
                connection.execute(
                    "CREATE TABLE recording ("
                    "id TEXT, workspace_id TEXT, created_by TEXT, requested_mode TEXT, "
                    "source_kind TEXT, intelligence_version INTEGER, "
                    "retention_expires_at DATETIME)"
                )
            else:
                connection.execute(f"CREATE TABLE {table} (id TEXT)")
        connection.execute("CREATE TABLE _alembic_tmp_recording (id TEXT)")

    with pytest.raises(SystemExit, match="unfinished Alembic"):
        RUN_LOCAL.unversioned_sqlite_revision(database)


def test_unknown_unversioned_sqlite_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "unknown.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unrelated (id TEXT)")

    with pytest.raises(SystemExit, match="not a recognized"):
        RUN_LOCAL.legacy_sqlite_needs_stamp(database)
