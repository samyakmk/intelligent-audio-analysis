#!/usr/bin/env python3
"""Invoke Compose in safe-default or explicit-config mode.

Safe-default mode sanitizes ambient configuration before interpolation and forces
fixture-only local values. Public behavior comes from config/pocket.json. Explicit
mode accepts a user-nominated secret-only env path; there is no implicit `.env` fallback.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from configuration import (
    PRIVATE_ENV_KEYS,
    load_private_environment,
    load_public_configuration,
    validate_private_environment,
)


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "compose.yaml"
DEFAULT_CONFIG_FILE = ROOT / "config" / "pocket.json"

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
    "POSTGRES_PASSWORD": "pocket-local-only",
    "COMPOSE_DATABASE_URL": "postgresql+psycopg://pocket:pocket-local-only@postgres:5432/pocket",
    "MINIO_ROOT_USER": "pocket-local",
    "MINIO_ROOT_PASSWORD": "pocket-local-only",
    "SESSION_SECRET": "local-demo-session-secret-change-before-sharing",
    "CSRF_SECRET": "local-demo-csrf-secret-change-before-sharing",
    "TOKEN_SIGNING_SECRET": "local-demo-capability-secret-change-before-sharing",
    "PRICE_CATALOG_PATH": "/dev/null",
    "EXPO_NO_DOTENV": "1",
}


def usage() -> str:
    return (
        "usage: scripts/compose.py [--config-file path] [--env-file /explicit/path] "
        "<compose arguments...>"
    )


def main() -> int:
    arguments = sys.argv[1:]
    configured_env: str | None = None
    config_file = str(DEFAULT_CONFIG_FILE)
    while arguments[:1] in (["--config-file"], ["--env-file"]):
        if len(arguments) < 3:
            raise SystemExit(usage())
        flag, value = arguments[:2]
        arguments = arguments[2:]
        if flag == "--config-file":
            config_file = value
        else:
            configured_env = value
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
    environment.update(load_public_configuration(config_file))
    for private_key in PRIVATE_ENV_KEYS:
        environment.pop(private_key, None)

    if configured_env is None:
        environment.update(SAFE_COMPOSE_VALUES)
    else:
        if configured_env in {"", ".env"}:
            raise SystemExit("pass an explicit env path; bare `.env` is not accepted")
        private_path = str(Path(configured_env).expanduser().resolve())
        private_values = load_private_environment(private_path)
        validate_private_environment(private_values)
        environment.update(private_values)
        environment["EXPO_NO_DOTENV"] = "1"

    command = [
        docker,
        "compose",
        "--project-directory",
        str(ROOT),
        "--env-file",
        os.devnull,
        "--file",
        str(COMPOSE_FILE),
        *arguments,
    ]
    os.execve(docker, command, environment)
    return 127


if __name__ == "__main__":
    sys.exit(main())
