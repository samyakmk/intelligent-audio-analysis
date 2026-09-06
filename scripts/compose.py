#!/usr/bin/env python3
"""Invoke Compose in safe-default or explicit-config mode.

Safe-default mode sanitizes ambient configuration before interpolation and forces
fixture-only local values. Explicit-config mode accepts a user-nominated env path;
there is intentionally no implicit `.env` fallback.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "compose.yaml"

PROCESS_KEYS = {
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "TERM",
    "CI",
    "NO_COLOR",
    "FORCE_COLOR",
}

DOCKER_KEYS = {
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
    "DOCKER_CONFIG",
    "DOCKER_DEFAULT_PLATFORM",
    "DOCKER_BUILDKIT",
    "BUILDKIT_PROGRESS",
}

SAFE_COMPOSE_VALUES = {
    "APP_ENV": "development",
    "DEMO_MODE": "true",
    "PROVIDER_MODE": "fixture",
    "ALLOW_REMOTE_PROVIDER_CALLS": "false",
    "POSTGRES_USER": "pocket",
    "POSTGRES_PASSWORD": "pocket-local-only",
    "POSTGRES_DB": "pocket",
    "POSTGRES_PORT": "5432",
    "COMPOSE_DATABASE_URL": "postgresql+psycopg://pocket:pocket-local-only@postgres:5432/pocket",
    "MINIO_ROOT_USER": "pocket-local",
    "MINIO_ROOT_PASSWORD": "pocket-local-only",
    "MINIO_API_PORT": "9000",
    "MINIO_CONSOLE_PORT": "9001",
    "S3_BUCKET": "pocket-demo",
    "API_PORT": "8000",
    "WEB_PORT": "8081",
    "CORS_ORIGINS": "http://localhost:8081,http://127.0.0.1:8081",
    "SESSION_SECRET": "local-demo-session-secret-change-before-sharing",
    "CSRF_SECRET": "local-demo-csrf-secret-change-before-sharing",
    "TOKEN_SIGNING_SECRET": "local-demo-capability-secret-change-before-sharing",
    "COOKIE_SECURE": "false",
    "LOG_LEVEL": "INFO",
    "LOG_FORMAT": "json",
    "PRICE_CATALOG_PATH": "/dev/null",
    "FAILURE_INJECTION_ENABLED": "false",
    "EXPO_PUBLIC_API_URL": "http://localhost:8000",
    "EXPO_NO_DOTENV": "1",
}


def usage() -> str:
    return (
        "usage: scripts/compose.py [--env-file /explicit/path] "
        "<compose arguments...>"
    )


def main() -> int:
    arguments = sys.argv[1:]
    configured_env: str | None = None
    if arguments[:1] == ["--env-file"]:
        if len(arguments) < 3:
            raise SystemExit(usage())
        configured_env = arguments[1]
        arguments = arguments[2:]
    if not arguments:
        raise SystemExit(usage())

    docker = shutil.which("docker")
    if docker is None:
        raise SystemExit("Docker CLI is required for Compose commands")

    environment = {
        key: value
        for key, value in os.environ.items()
        if key in PROCESS_KEYS
        or key in DOCKER_KEYS
        or key.startswith("LC_")
        or key.startswith("XDG_")
    }

    if configured_env is None:
        environment.update(SAFE_COMPOSE_VALUES)
        env_file = os.devnull
    else:
        if configured_env in {"", ".env"}:
            raise SystemExit("pass an explicit env path; bare `.env` is not accepted")
        env_file = str(Path(configured_env).expanduser().resolve())
        environment["EXPO_NO_DOTENV"] = "1"

    command = [
        docker,
        "compose",
        "--project-directory",
        str(ROOT),
        "--env-file",
        env_file,
        "--file",
        str(COMPOSE_FILE),
        *arguments,
    ]
    os.execve(docker, command, environment)
    return 127


if __name__ == "__main__":
    sys.exit(main())
