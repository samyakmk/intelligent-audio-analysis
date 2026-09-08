"""Strict loaders for checked-in public config and secret-only environment files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# These are the only values permitted in a private dotenv-style file. Values that
# describe behavior belong in config/pocket.json so they remain reviewable.
PRIVATE_ENV_KEYS = frozenset(
    {
        "ASSEMBLYAI_API_KEY",
        "COMPOSE_DATABASE_URL",
        "CSRF_SECRET",
        "DATABASE_URL",
        "GEMINI_API_KEY",
        "MINIO_ROOT_PASSWORD",
        "MINIO_ROOT_USER",
        "OPENAI_API_KEY",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "POSTGRES_PASSWORD",
        "PROVIDER_CALLBACK_SECRET",
        "S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY",
        "SENTRY_DSN",
        "SESSION_SECRET",
        "TOKEN_SIGNING_SECRET",
    }
)
PRIVATE_NAME_PATTERN = re.compile(
    r"(^|_)(API_KEY|SECRET|PASSWORD|PRIVATE_KEY|ACCESS_KEY|AUTH_TOKEN)(_|$)"
)


def load_private_environment(path_value: str) -> dict[str, str]:
    """Parse an absolute dotenv path as data, never as shell code."""

    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise SystemExit("--env-file must be an absolute path")
    if not path.is_file():
        raise SystemExit("the explicitly selected environment file does not exist")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise SystemExit(f"invalid environment assignment on line {line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not ENV_ASSIGNMENT.fullmatch(key):
            raise SystemExit(f"invalid environment key on line {line_number}")
        if key in values:
            raise SystemExit(f"duplicate environment key on line {line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def validate_private_environment(values: dict[str, str]) -> None:
    public_keys = sorted(set(values) - PRIVATE_ENV_KEYS)
    if public_keys:
        raise SystemExit(
            "private environment file contains public configuration; move these keys to "
            f"config/pocket.json: {', '.join(public_keys)}"
        )


def _environment_value(value: Any, *, key: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)) and not isinstance(value, complex):
        return str(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ",".join(value)
    raise SystemExit(
        f"public configuration value {key} must be a string, number, boolean, or string list"
    )


def load_public_configuration(path_value: str | Path) -> dict[str, str]:
    """Load the sectioned public JSON file into normalized process settings."""

    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"public configuration file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"public configuration file is invalid JSON: {path}") from exc
    if not isinstance(payload, dict) or not payload:
        raise SystemExit("public configuration must contain named object sections")

    result: dict[str, str] = {}
    for section_name, section in payload.items():
        if not isinstance(section_name, str) or not isinstance(section, dict):
            raise SystemExit("public configuration must contain named object sections")
        for key, value in section.items():
            if not isinstance(key, str) or not ENV_ASSIGNMENT.fullmatch(key) or key.upper() != key:
                raise SystemExit(f"invalid public configuration key in {section_name}")
            looks_private = bool(PRIVATE_NAME_PATTERN.search(key)) or key in {
                "DATABASE_URL",
                "COMPOSE_DATABASE_URL",
                "SENTRY_DSN",
            }
            if key in PRIVATE_ENV_KEYS or looks_private:
                raise SystemExit(
                    f"secret {key} must be kept in the private .env, not public config"
                )
            if key in result:
                raise SystemExit(f"duplicate public configuration key: {key}")
            result[key] = _environment_value(value, key=key)
    return result
