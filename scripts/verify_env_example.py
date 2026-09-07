#!/usr/bin/env python3
"""Validate the public configuration inventory without opening any real env file."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"

REQUIRED_KEYS = {
    "APP_ENV",
    "DEMO_MODE",
    "PROVIDER_MODE",
    "API_PUBLIC_URL",
    "WEB_PUBLIC_URL",
    "CORS_ORIGINS",
    "DATABASE_URL",
    "COMPOSE_DATABASE_URL",
    "POSTGRES_PASSWORD",
    "BLOB_STORE_BACKEND",
    "BLOB_ROOT",
    "S3_ENDPOINT_URL",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "S3_KEY_PREFIX",
    "SESSION_SECRET",
    "CSRF_SECRET",
    "TOKEN_SIGNING_SECRET",
    "GEMINI_API_KEY",
    "GEMINI_BASE_URL",
    "GEMINI_SPEECH_MODEL",
    "ASSEMBLYAI_API_KEY",
    "SPEECH_STANDARD_MODEL",
    "SPEECH_STRONG_MODEL",
    "OPENAI_API_KEY",
    "LLM_CHEAP_MODEL",
    "LLM_STRONG_MODEL",
    "GEMINI_PRICE_CATALOG_VERSION",
    "EMBEDDING_MODEL",
    "PROVIDER_DATA_POLICY",
    "ALLOW_REMOTE_PROVIDER_CALLS",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
    "PROCESSING_CONCURRENCY",
    "MAX_UPLOAD_BYTES",
    "MAX_AUDIO_DURATION_SECONDS",
    "MAX_AI_SPEND_PER_RECORDING_USD",
    "MAX_AI_SPEND_PER_ASK_USD",
    "MAX_AI_SPEND_PER_WORKSPACE_MONTH_USD",
    "WORKSPACE_STORAGE_QUOTA_BYTES",
    "WORKSPACE_RECORDING_QUOTA",
    "RECORDING_RETENTION_DAYS",
    "PRICE_CATALOG_PATH",
    "PRICE_CATALOG_VERSION",
    "LOG_CONTENT_POLICY",
    "OTEL_ENABLED",
    "FAILURE_INJECTION_ENABLED",
    "EXPO_PUBLIC_API_URL",
    "EXPO_PUBLIC_DEMO_MODE",
    "EXPO_APP_NAME",
    "EXPO_APP_SLUG",
    "EXPO_APP_SCHEME",
    "IOS_BUNDLE_IDENTIFIER",
    "ANDROID_PACKAGE_NAME",
    "EAS_PROJECT_ID",
}

SERVER_ONLY_NAME_FRAGMENTS = {
    "api_key",
    "secret",
    "password",
    "token",
    "database_url",
    "access_key",
    "private_key",
}

PLACEHOLDER_SECRET_KEYS = {
    "POSTGRES_PASSWORD",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "SESSION_SECRET",
    "CSRF_SECRET",
    "TOKEN_SIGNING_SECRET",
    "PROVIDER_CALLBACK_SECRET",
    "GEMINI_API_KEY",
    "ASSEMBLYAI_API_KEY",
    "OPENAI_API_KEY",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "SENTRY_DSN",
}


def parse_example() -> dict[str, str]:
    values: dict[str, str] = {}
    assignment = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
    for line_number, raw_line in enumerate(
        EXAMPLE.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = assignment.fullmatch(line)
        if not match:
            raise SystemExit(f"invalid .env.example line {line_number}: {raw_line!r}")
        key, value = match.groups()
        if key in values:
            raise SystemExit(f"duplicate .env.example key: {key}")
        values[key] = value
    return values


def main() -> int:
    values = parse_example()
    missing = sorted(REQUIRED_KEYS - values.keys())
    if missing:
        raise SystemExit(f".env.example is missing required keys: {', '.join(missing)}")

    for key in sorted(PLACEHOLDER_SECRET_KEYS):
        value = values.get(key, "")
        if value and "replace-me" not in value:
            raise SystemExit(f"{key} must remain an obvious non-secret placeholder")

    for key in values:
        if not key.startswith("EXPO_PUBLIC_"):
            continue
        normalized = key.removeprefix("EXPO_PUBLIC_").lower()
        forbidden = sorted(
            fragment for fragment in SERVER_ONLY_NAME_FRAGMENTS if fragment in normalized
        )
        if forbidden:
            raise SystemExit(
                f"client-exposed key {key} looks secret/server-only ({', '.join(forbidden)})"
            )

    if values["ALLOW_REMOTE_PROVIDER_CALLS"].lower() != "false":
        raise SystemExit("remote provider calls must be disabled in .env.example")
    if values["PROVIDER_MODE"] != "fixture":
        raise SystemExit(".env.example must default to fixture provider mode")
    if values["LOG_CONTENT_POLICY"] != "metadata-only":
        raise SystemExit(".env.example logs must default to metadata-only")

    print(f"environment inventory verification passed: {len(values)} declared values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
