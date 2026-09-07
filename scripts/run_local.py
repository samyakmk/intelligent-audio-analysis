#!/usr/bin/env python3
"""Run the local FastAPI + Expo web profile.

The safe default never loads dotenv.  An operator can explicitly nominate an
absolute secret-file path for a configured local run. Public behavior comes from
config/pocket.json; secrets are parsed as data (never sourced as shell code), and
server-only values are not passed to the Expo process.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from configuration import (  # noqa: E402
    PRIVATE_ENV_KEYS,
    load_private_environment,
    load_public_configuration,
    validate_private_environment,
)


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services" / "api"
CLIENT_DIR = ROOT / "apps" / "client"
LOCAL_DIR = ROOT / ".local"
# Kept as a compatibility export for launcher tests and downstream tooling.
GEMINI_LOCAL_ENV_KEYS = PRIVATE_ENV_KEYS
LOCAL_API_PRIVATE_KEYS = {
    "CSRF_SECRET",
    "GEMINI_API_KEY",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "SENTRY_DSN",
    "SESSION_SECRET",
    "TOKEN_SIGNING_SECRET",
}
BASE_PROCESS_KEYS = {
    "ALL_PROXY",
    "CI",
    "CURL_CA_BUNDLE",
    "FORCE_COLOR",
    "HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "LANG",
    "LOGNAME",
    "NO_COLOR",
    "NO_PROXY",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SHELL",
    "SSL_CERT_FILE",
    "TEMP",
    "TERM",
    "TMP",
    "TMPDIR",
    "USER",
}
BASELINE_REVISION = "c14c172f08b5"
HEAD_REVISION = "d9a2f18b6c41"
LEGACY_SCHEMA_MARKERS = {
    "budget_reservation",
    "domain_event",
    "recording",
    "workspace",
}
BASELINE_RECORDING_COLUMN_MARKERS = {
    "id",
    "workspace_id",
    "created_by",
    "requested_mode",
    "source_kind",
    "intelligence_version",
    "retention_expires_at",
}


load_explicit_environment = load_private_environment


def command_or_fail(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise SystemExit(f"required executable is missing: {name}")
    return resolved


def unversioned_sqlite_revision(database_path: Path) -> str | None:
    """Return the only safe revision to stamp for a recognized unversioned DB."""

    if not database_path.is_file():
        return None
    with sqlite3.connect(database_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        revision = (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if "alembic_version" in tables
            else None
        )
        recording_columns = (
            {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(recording)")
            }
            if "recording" in tables
            else set()
        )
    if not tables or revision is not None:
        return None
    if "_alembic_tmp_recording" in tables:
        raise SystemExit(
            "local SQLite contains an unfinished Alembic recording table; restore or inspect "
            "the database before retrying"
        )
    if not LEGACY_SCHEMA_MARKERS.issubset(tables):
        raise SystemExit(
            "local SQLite has tables but is not a recognized pre-Alembic Pocket schema"
        )
    if not BASELINE_RECORDING_COLUMN_MARKERS.issubset(recording_columns):
        raise SystemExit(
            "local SQLite recording table is not a recognized Pocket baseline schema"
        )
    if "provider_data_approved" in recording_columns:
        return HEAD_REVISION
    return BASELINE_REVISION


def legacy_sqlite_needs_stamp(database_path: Path) -> bool:
    """Compatibility predicate for callers that only need stamp/no-stamp."""

    return unversioned_sqlite_revision(database_path) is not None


def terminate(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 8
    for process in processes:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            process.kill()
    for process in processes:
        if process.poll() is None:
            process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Pocket API and universal web client")
    parser.add_argument(
        "--env-file",
        help="absolute path to an explicitly selected secret-only environment file",
    )
    parser.add_argument(
        "--config-file",
        default=str(ROOT / "config" / "pocket.json"),
        help="public JSON configuration path",
    )
    parser.add_argument(
        "--provider-mode",
        choices=("fixture", "gemini"),
        default="fixture",
        help="provider route to activate; defaults to the zero-account fixture route",
    )
    args = parser.parse_args()
    venv_python = API_DIR / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.is_file() else command_or_fail("python3.12")
    npm = command_or_fail("npm")

    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    blob_root = LOCAL_DIR / "blobs"
    blob_root.mkdir(parents=True, exist_ok=True)

    environment = {
        key: value
        for key, value in os.environ.items()
        if key in BASE_PROCESS_KEYS
        or key.startswith("LC_")
        or key.startswith("npm_config_")
    }
    assert not set(environment) & PRIVATE_ENV_KEYS
    environment.update(load_public_configuration(args.config_file))
    local_defaults = {
        "APP_ENV": "development",
        "DEMO_MODE": "true",
        "DATABASE_URL": f"sqlite:///{LOCAL_DIR / 'pocket_demo.db'}",
        "BLOB_ROOT": str(blob_root),
        "FIXTURE_ROOT": str(ROOT / "fixtures"),
        "INLINE_WORKER": "true",
        "COOKIE_SECURE": "false",
        "CORS_ORIGINS": "http://localhost:8081,http://127.0.0.1:8081",
        "SESSION_SECRET": "local-demo-session-secret-not-for-shared-deployments",
        "CSRF_SECRET": "local-demo-csrf-secret-not-for-shared-deployments",
        "TOKEN_SIGNING_SECRET": "local-demo-capability-secret-not-for-shared-deployments",
        "WORKER_LEASE_SECONDS": "1800",
        "LOG_CONTENT_POLICY": "metadata-only",
        "EXPO_NO_DOTENV": "1",
        "EXPO_PUBLIC_API_URL": "http://localhost:8000",
        "EXPO_PUBLIC_DEMO_MODE": "true",
    }
    if args.provider_mode == "fixture":
        if args.env_file:
            raise SystemExit("--env-file is accepted only with --provider-mode gemini")
        environment.update(local_defaults)
        environment.update(
            {
                "PROVIDER_MODE": "fixture",
                "ALLOW_REMOTE_PROVIDER_CALLS": "false",
            }
        )
    else:
        if not args.env_file:
            raise SystemExit("Gemini mode requires --env-file with an absolute private path")
        selected = load_explicit_environment(args.env_file)
        validate_private_environment(selected)
        configured = {
            key: value for key, value in selected.items() if key in LOCAL_API_PRIVATE_KEYS
        }
        environment.update(local_defaults)
        environment.update(configured)
        environment["PROVIDER_MODE"] = "gemini"
        environment["ALLOW_REMOTE_PROVIDER_CALLS"] = "true"
        environment["EXPO_NO_DOTENV"] = "1"

    # The Expo process receives only normal process settings and explicitly public
    # values. Server/provider credentials from the invoking shell stay API-only.
    client_process_keys = BASE_PROCESS_KEYS - {
        "ALL_PROXY",
        "CURL_CA_BUNDLE",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
    }
    client_environment = {
        key: value
        for key, value in environment.items()
        if key in client_process_keys
        or key.startswith("LC_")
        or key.startswith("npm_config_")
        or key.startswith("EXPO_PUBLIC_")
        or key == "EXPO_NO_DOTENV"
    }

    processes: list[subprocess.Popen[bytes]] = []
    shutting_down = False

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal shutting_down
        shutting_down = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        stamp_revision = unversioned_sqlite_revision(LOCAL_DIR / "pocket_demo.db")
        if stamp_revision is not None:
            subprocess.run(
                [python, "-m", "alembic", "stamp", stamp_revision],
                cwd=API_DIR,
                env=environment,
                check=True,
            )
        subprocess.run(
            [python, "-m", "alembic", "upgrade", "head"],
            cwd=API_DIR,
            env=environment,
            check=True,
        )
        processes.append(
            subprocess.Popen(
                [
                    python,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                    "--no-access-log",
                ],
                cwd=API_DIR,
                env=environment,
            )
        )
        processes.append(
            subprocess.Popen(
                [npm, "--prefix", str(CLIENT_DIR), "run", "web"],
                cwd=ROOT,
                env=client_environment,
            )
        )
        print("Pocket Demo starting: web http://localhost:8081, API http://localhost:8000")
        if args.provider_mode == "fixture":
            print("Fixture mode is active; no remote provider calls are allowed.")
        else:
            print("Gemini mode is active; only the API process received private settings.")

        while not shutting_down:
            for process in processes:
                result = process.poll()
                if result is not None:
                    return result if result != 0 else 1
            time.sleep(0.2)
        return 0
    finally:
        terminate(processes)


if __name__ == "__main__":
    sys.exit(main())
