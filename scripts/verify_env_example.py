#!/usr/bin/env python3
"""Validate the public config and placeholder-only private secret template."""

from __future__ import annotations

from pathlib import Path

from configuration import (
    PRIVATE_ENV_KEYS,
    load_private_environment,
    load_public_configuration,
    validate_private_environment,
)


ROOT = Path(__file__).resolve().parents[1]
SECRET_EXAMPLE = ROOT / ".env.example"
PUBLIC_CONFIG = ROOT / "config" / "intelligent-audio-analysis.json"

REQUIRED_PUBLIC_KEYS = {
    "ALLOW_REMOTE_PROVIDER_CALLS",
    "APP_ENV",
    "BLOB_STORE_BACKEND",
    "BLOB_ROOT",
    "COOKIE_SECURE",
    "CORS_ORIGINS",
    "DEMO_MODE",
    "EXPO_APP_NAME",
    "EXPO_APP_SCHEME",
    "EXPO_APP_SLUG",
    "EXPO_PUBLIC_API_URL",
    "EXPO_PUBLIC_DEMO_MODE",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
    "GEMINI_BASE_URL",
    "GEMINI_PRICE_CATALOG_VERSION",
    "GEMINI_SPEECH_MODEL",
    "LLM_CHEAP_MODEL",
    "LLM_STRONG_MODEL",
    "LOG_CONTENT_POLICY",
    "MAX_AI_SPEND_PER_ASK_USD",
    "MAX_AI_SPEND_PER_RECORDING_USD",
    "MAX_AI_SPEND_PER_WORKSPACE_MONTH_USD",
    "MAX_AUDIO_DURATION_SECONDS",
    "MAX_UPLOAD_BYTES",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "PROVIDER_ALLOWED_LANGUAGES",
    "PROVIDER_DATA_POLICY",
    "PROVIDER_MODE",
    "RECORDING_RETENTION_DAYS",
    "S3_BUCKET",
    "S3_ENDPOINT_URL",
    "S3_KEY_PREFIX",
    "SWEEPER_INTERVAL_SECONDS",
    "WORKER_LEASE_SECONDS",
    "WORKSPACE_RECORDING_QUOTA",
    "WORKSPACE_STORAGE_QUOTA_BYTES",
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


def main() -> int:
    private_values = load_private_environment(str(SECRET_EXAMPLE.resolve()))
    validate_private_environment(private_values)
    missing_private = sorted(PRIVATE_ENV_KEYS - private_values.keys())
    if missing_private:
        raise SystemExit(
            ".env.example is missing secret placeholders: " + ", ".join(missing_private)
        )
    for key, value in private_values.items():
        if value and "replace-me" not in value:
            raise SystemExit(f"{key} must remain empty or an obvious replace-me placeholder")

    public_values = load_public_configuration(PUBLIC_CONFIG)
    missing_public = sorted(REQUIRED_PUBLIC_KEYS - public_values.keys())
    if missing_public:
        raise SystemExit(
            "config/intelligent-audio-analysis.json is missing required settings: "
            + ", ".join(missing_public)
        )
    overlap = sorted(set(private_values) & set(public_values))
    if overlap:
        raise SystemExit("private/public configuration overlap: " + ", ".join(overlap))

    for key in public_values:
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

    if public_values["PROVIDER_MODE"] != "gemini":
        raise SystemExit("public config must describe the configured Gemini demo route")
    if public_values["ALLOW_REMOTE_PROVIDER_CALLS"] != "true":
        raise SystemExit("public config must explicitly declare the Gemini remote-call gate")
    if public_values["LOG_CONTENT_POLICY"] != "metadata-only":
        raise SystemExit("public config logs must remain metadata-only")

    print(
        "configuration split verification passed: "
        f"{len(private_values)} secret placeholders, {len(public_values)} public settings"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
