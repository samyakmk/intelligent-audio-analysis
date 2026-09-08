from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.models import Base

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "intelligent_audio_analysis_run_local", ROOT / "scripts" / "run_local.py"
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


def test_auto_mode_uses_fixture_without_env_file(tmp_path: Path) -> None:
    mode, values, selected_path = RUN_LOCAL.load_provider_environment(
        "auto", None, default_env_file=tmp_path / ".env"
    )

    assert mode == "fixture"
    assert values == {}
    assert selected_path is None


@pytest.mark.parametrize("value", ["", "replace-me-gemini-api-key", "<gemini-key>"])
def test_auto_mode_uses_fixture_for_unconfigured_key(tmp_path: Path, value: str) -> None:
    private = tmp_path / ".env"
    private.write_text(f"GEMINI_API_KEY={value}\n", encoding="utf-8")

    mode, values, selected_path = RUN_LOCAL.load_provider_environment(
        "auto", None, default_env_file=private
    )

    assert mode == "fixture"
    assert values == {}
    assert selected_path == private


def test_auto_mode_enables_gemini_and_keeps_only_local_api_secrets(tmp_path: Path) -> None:
    private = tmp_path / ".env"
    private.write_text(
        "GEMINI_API_KEY=dummy-gemini-key-for-launcher-tests\n"
        "SESSION_SECRET=dummy-session-secret-for-launcher-tests\n"
        "POSTGRES_PASSWORD=must-not-reach-lightweight-api\n",
        encoding="utf-8",
    )

    mode, values, selected_path = RUN_LOCAL.load_provider_environment(
        "auto", None, default_env_file=private
    )

    assert mode == "gemini"
    assert values == {
        "GEMINI_API_KEY": "dummy-gemini-key-for-launcher-tests",
        "SESSION_SECRET": "dummy-session-secret-for-launcher-tests",
    }
    assert selected_path == private


def test_explicit_fixture_mode_never_loads_env_file(tmp_path: Path) -> None:
    private = tmp_path / ".env"
    private.write_text("GEMINI_API_KEY=dummy-key-for-tests-only\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="cannot be combined"):
        RUN_LOCAL.load_provider_environment("fixture", str(private))


def test_forced_gemini_mode_requires_an_env_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="does not exist"):
        RUN_LOCAL.load_provider_environment(
            "gemini", None, default_env_file=tmp_path / ".env"
        )


def test_explicit_environment_parser_rejects_duplicates(tmp_path: Path) -> None:
    config = tmp_path / "operator-settings"
    config.write_text("MODE=one\nMODE=two\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="duplicate environment key"):
        RUN_LOCAL.load_explicit_environment(str(config))


def test_missing_local_database_requires_no_stamp(tmp_path: Path) -> None:
    missing = tmp_path / "not-created.db"
    assert RUN_LOCAL.unversioned_sqlite_revision(missing) is None
    assert RUN_LOCAL.legacy_sqlite_needs_stamp(missing) is False


def test_gemini_local_allowlist_contains_secrets_only() -> None:
    assert {
        "GEMINI_API_KEY",
        "SESSION_SECRET",
        "CSRF_SECRET",
        "TOKEN_SIGNING_SECRET",
    }.issubset(RUN_LOCAL.GEMINI_LOCAL_ENV_KEYS)
    assert "DATABASE_URL" in RUN_LOCAL.GEMINI_LOCAL_ENV_KEYS
    assert "LLM_CHEAP_MODEL" not in RUN_LOCAL.GEMINI_LOCAL_ENV_KEYS
    assert "MAX_AI_SPEND_PER_RECORDING_USD" not in RUN_LOCAL.GEMINI_LOCAL_ENV_KEYS
    assert "PROVIDER_DATA_POLICY" not in RUN_LOCAL.GEMINI_LOCAL_ENV_KEYS
    assert "EXPO_PUBLIC_GEMINI_API_KEY" not in RUN_LOCAL.GEMINI_LOCAL_ENV_KEYS


def test_private_environment_rejects_public_configuration(tmp_path: Path) -> None:
    private = tmp_path / "secrets.env"
    private.write_text(
        "GEMINI_API_KEY=dummy-secret\nLLM_CHEAP_MODEL=public-model\n",
        encoding="utf-8",
    )

    values = RUN_LOCAL.load_explicit_environment(str(private))
    with pytest.raises(
        SystemExit,
        match="move these keys to config/intelligent-audio-analysis.json",
    ):
        RUN_LOCAL.validate_private_environment(values)


def test_public_configuration_is_typed_flattened_and_secret_free(tmp_path: Path) -> None:
    public = tmp_path / "intelligent-audio-analysis.json"
    public.write_text(
        json.dumps(
            {
                "models": {
                    "LLM_CHEAP_MODEL": "gemini-test",
                    "MAX_CHEAP_REPAIR_ATTEMPTS": 1,
                    "ALLOW_REMOTE_PROVIDER_CALLS": True,
                    "PROVIDER_ALLOWED_LANGUAGES": ["en", "en-US"],
                }
            }
        ),
        encoding="utf-8",
    )

    assert RUN_LOCAL.load_public_configuration(public) == {
        "LLM_CHEAP_MODEL": "gemini-test",
        "MAX_CHEAP_REPAIR_ATTEMPTS": "1",
        "ALLOW_REMOTE_PROVIDER_CALLS": "true",
        "PROVIDER_ALLOWED_LANGUAGES": "en,en-US",
    }

    public.write_text(
        json.dumps({"unsafe": {"GEMINI_API_KEY": "must-not-be-public"}}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="must be kept in the private .env"):
        RUN_LOCAL.load_public_configuration(public)


def test_checked_in_public_config_owns_gemini_models_budgets_and_policy() -> None:
    public = RUN_LOCAL.load_public_configuration(
        ROOT / "config" / "intelligent-audio-analysis.json"
    )

    assert not set(public) & RUN_LOCAL.GEMINI_LOCAL_ENV_KEYS
    assert public["GEMINI_SPEECH_MODEL"] == "gemini-3.5-transcribe"
    assert public["LLM_CHEAP_MODEL"] == "gemini-3.5-flash-lite"
    assert public["LLM_STRONG_MODEL"] == "gemini-3.8-flash"
    assert public["MAX_AI_SPEND_PER_RECORDING_USD"] == "2.0"
    assert public["MAX_AI_SPEND_PER_ASK_USD"] == "0.1"
    assert public["MAX_AI_SPEND_PER_WORKSPACE_MONTH_USD"] == "20.0"
    assert public["PROVIDER_DATA_POLICY"] == "synthetic-approved-only"
    assert public["PROVIDER_ALLOWED_LANGUAGES"] == "en"


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
