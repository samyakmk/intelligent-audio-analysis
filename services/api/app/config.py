from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: list[str]) -> list[str]:
    value = os.environ.get(name)
    if not value:
        return default
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass(slots=True)
class Settings:
    """Runtime settings.

    Values are read from the process environment only.  The application never
    searches for or loads dotenv files.
    """

    database_url: str = "sqlite:///./data/pocket_demo.db"
    blob_root: Path = Path("./data/blobs")
    blob_store_backend: str = "filesystem"
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_key_prefix: str = "pocket-demo"
    token_signing_secret: str = "unsafe-local-demo-signing-secret-change-me"
    fixture_root: Path = Path(__file__).resolve().parents[3] / "fixtures"
    demo_mode: bool = True
    inline_worker: bool = True
    cookie_secure: bool = False
    cors_origins: list[str] = field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:8081",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8081",
        ]
    )
    session_ttl_seconds: int = 24 * 60 * 60
    media_grant_ttl_seconds: int = 60
    max_upload_bytes: int = 500 * 1024 * 1024
    max_duration_ms: int = 2 * 60 * 60 * 1000
    recording_cost_ceiling_usd: float = 2.00
    ask_cost_ceiling_usd: float = 0.10
    workspace_monthly_cost_ceiling_usd: float = 50.00
    worker_lease_seconds: int = 300
    workspace_storage_quota_bytes: int = 5 * 1024 * 1024 * 1024
    workspace_recording_quota: int = 200
    recording_retention_days: int = 30
    sweeper_interval_seconds: float = 60.0
    provider_mode: str = "fixture"
    allow_remote_provider_calls: bool = False
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_speech_model: str = "gemini-3.5-transcribe"
    llm_cheap_model: str = "gemini-3.5-flash-lite"
    llm_strong_model: str = "gemini-3.8-flash"
    max_cheap_repair_attempts: int = 1
    max_strong_repair_attempts: int = 1
    max_strong_context_tokens: int = 131_072
    gemini_request_timeout_seconds: float = 300.0
    gemini_upload_timeout_seconds: float = 600.0
    gemini_max_http_retries: int = 2
    gemini_retry_backoff_seconds: float = 0.25
    provider_data_policy: str = "synthetic-approved-only"
    provider_allowed_languages: list[str] = field(default_factory=lambda: ["en"])
    gemini_cheap_input_usd_per_million: float = 0.30
    gemini_cheap_output_usd_per_million: float = 2.50
    gemini_strong_input_usd_per_million: float = 0.75
    gemini_strong_output_usd_per_million: float = 3.75
    gemini_speech_input_usd_per_million: float = 2.00
    gemini_speech_output_usd_per_million: float = 12.00
    gemini_price_catalog_version: str = "google-gemini-standard-2026-09-07"

    @classmethod
    def from_environment(cls) -> Settings:
        # Deliberately use os.environ directly; do not add dotenv loading here.
        return cls(
            database_url=os.environ.get("DATABASE_URL", "sqlite:///./data/pocket_demo.db"),
            blob_root=Path(os.environ.get("BLOB_ROOT", "./data/blobs")),
            blob_store_backend=os.environ.get("BLOB_STORE_BACKEND", "filesystem").strip().lower(),
            s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
            s3_bucket=os.environ.get("S3_BUCKET"),
            s3_region=os.environ.get("S3_REGION", "us-east-1"),
            s3_access_key_id=os.environ.get("S3_ACCESS_KEY_ID"),
            s3_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY"),
            s3_key_prefix=os.environ.get("S3_KEY_PREFIX", "pocket-demo").strip("/"),
            token_signing_secret=os.environ.get(
                "TOKEN_SIGNING_SECRET",
                os.environ.get("SESSION_SECRET", "unsafe-local-demo-signing-secret-change-me"),
            ),
            fixture_root=Path(
                os.environ.get(
                    "FIXTURE_ROOT", str(Path(__file__).resolve().parents[3] / "fixtures")
                )
            ),
            demo_mode=_bool_env("DEMO_MODE", True),
            inline_worker=_bool_env("INLINE_WORKER", True),
            cookie_secure=_bool_env("COOKIE_SECURE", False),
            cors_origins=_csv_env(
                "CORS_ORIGINS",
                [
                    "http://localhost:3000",
                    "http://localhost:8081",
                    "http://127.0.0.1:3000",
                    "http://127.0.0.1:8081",
                ],
            ),
            session_ttl_seconds=int(os.environ.get("SESSION_TTL_SECONDS", 86400)),
            media_grant_ttl_seconds=int(os.environ.get("MEDIA_GRANT_TTL_SECONDS", 60)),
            max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", 500 * 1024 * 1024)),
            max_duration_ms=1000
            * int(
                os.environ.get(
                    "MAX_AUDIO_DURATION_SECONDS",
                    str(int(os.environ.get("MAX_DURATION_MS", 2 * 60 * 60 * 1000)) // 1000),
                )
            ),
            recording_cost_ceiling_usd=float(
                os.environ.get(
                    "MAX_AI_SPEND_PER_RECORDING_USD",
                    os.environ.get("RECORDING_COST_CEILING_USD", "2.00"),
                )
            ),
            ask_cost_ceiling_usd=float(
                os.environ.get(
                    "MAX_AI_SPEND_PER_ASK_USD",
                    os.environ.get("ASK_COST_CEILING_USD", "0.10"),
                )
            ),
            workspace_monthly_cost_ceiling_usd=float(
                os.environ.get("MAX_AI_SPEND_PER_WORKSPACE_MONTH_USD", "50.00")
            ),
            worker_lease_seconds=int(os.environ.get("WORKER_LEASE_SECONDS", "300")),
            workspace_storage_quota_bytes=int(
                os.environ.get(
                    "WORKSPACE_STORAGE_QUOTA_BYTES",
                    os.environ.get("WORKSPACE_STORAGE_LIMIT_BYTES", str(5 * 1024 * 1024 * 1024)),
                )
            ),
            workspace_recording_quota=int(
                os.environ.get(
                    "WORKSPACE_RECORDING_QUOTA",
                    os.environ.get("MAX_RETAINED_RECORDINGS", "200"),
                )
            ),
            recording_retention_days=int(
                os.environ.get("RECORDING_RETENTION_DAYS", os.environ.get("RETENTION_DAYS", "30"))
            ),
            sweeper_interval_seconds=float(os.environ.get("SWEEPER_INTERVAL_SECONDS", "60")),
            provider_mode=os.environ.get("PROVIDER_MODE", "fixture").strip().lower(),
            allow_remote_provider_calls=_bool_env("ALLOW_REMOTE_PROVIDER_CALLS", False),
            gemini_api_key=os.environ.get("GEMINI_API_KEY"),
            gemini_base_url=os.environ.get(
                "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
            ).rstrip("/"),
            gemini_speech_model=os.environ.get(
                "GEMINI_SPEECH_MODEL",
                "gemini-3.5-transcribe",
            ).strip(),
            llm_cheap_model=os.environ.get("LLM_CHEAP_MODEL", "gemini-3.5-flash-lite").strip(),
            llm_strong_model=os.environ.get("LLM_STRONG_MODEL", "gemini-3.8-flash").strip(),
            max_cheap_repair_attempts=int(os.environ.get("MAX_CHEAP_REPAIR_ATTEMPTS", "1")),
            max_strong_repair_attempts=int(os.environ.get("MAX_STRONG_REPAIR_ATTEMPTS", "1")),
            max_strong_context_tokens=int(os.environ.get("MAX_STRONG_CONTEXT_TOKENS", "131072")),
            gemini_request_timeout_seconds=float(
                os.environ.get("GEMINI_REQUEST_TIMEOUT_SECONDS", "300")
            ),
            gemini_upload_timeout_seconds=float(
                os.environ.get("GEMINI_UPLOAD_TIMEOUT_SECONDS", "600")
            ),
            gemini_max_http_retries=int(os.environ.get("GEMINI_MAX_HTTP_RETRIES", "2")),
            gemini_retry_backoff_seconds=float(
                os.environ.get("GEMINI_RETRY_BACKOFF_SECONDS", "0.25")
            ),
            provider_data_policy=os.environ.get(
                "PROVIDER_DATA_POLICY", "synthetic-approved-only"
            ).strip(),
            provider_allowed_languages=_csv_env("PROVIDER_ALLOWED_LANGUAGES", ["en"]),
            gemini_cheap_input_usd_per_million=float(
                os.environ.get("GEMINI_CHEAP_INPUT_USD_PER_MILLION", "0.30")
            ),
            gemini_cheap_output_usd_per_million=float(
                os.environ.get("GEMINI_CHEAP_OUTPUT_USD_PER_MILLION", "2.50")
            ),
            gemini_strong_input_usd_per_million=float(
                os.environ.get("GEMINI_STRONG_INPUT_USD_PER_MILLION", "0.75")
            ),
            gemini_strong_output_usd_per_million=float(
                os.environ.get("GEMINI_STRONG_OUTPUT_USD_PER_MILLION", "3.75")
            ),
            gemini_speech_input_usd_per_million=float(
                os.environ.get("GEMINI_SPEECH_INPUT_USD_PER_MILLION", "2.00")
            ),
            gemini_speech_output_usd_per_million=float(
                os.environ.get("GEMINI_SPEECH_OUTPUT_USD_PER_MILLION", "12.00")
            ),
            gemini_price_catalog_version=os.environ.get(
                "GEMINI_PRICE_CATALOG_VERSION", "google-gemini-standard-2026-09-07"
            ).strip(),
        )


def validate_runtime_settings(settings: Settings) -> None:
    """Fail closed when configuration suggests unsupported paid-provider use."""

    if (
        min(
            settings.recording_cost_ceiling_usd,
            settings.ask_cost_ceiling_usd,
            settings.workspace_monthly_cost_ceiling_usd,
        )
        < 0
    ):
        raise RuntimeError("AI spend ceilings cannot be negative")
    if not settings.demo_mode and (
        settings.token_signing_secret == "unsafe-local-demo-signing-secret-change-me"
        or len(settings.token_signing_secret) < 32
    ):
        raise RuntimeError(
            "SESSION_SECRET or TOKEN_SIGNING_SECRET must be at least 32 characters "
            "when DEMO_MODE is disabled"
        )
    if settings.provider_mode not in {"fixture", "mock", "gemini"}:
        raise RuntimeError(
            f"PROVIDER_MODE={settings.provider_mode!r} is not implemented in this demo. "
            "Wire reviewed provider adapters before enabling paid calls."
        )
    if settings.provider_mode != "gemini" and settings.allow_remote_provider_calls:
        raise RuntimeError(
            "ALLOW_REMOTE_PROVIDER_CALLS=true is valid only with PROVIDER_MODE=gemini"
        )
    if settings.provider_mode != "gemini":
        return
    if not settings.allow_remote_provider_calls:
        raise RuntimeError(
            "PROVIDER_MODE=gemini requires the explicit ALLOW_REMOTE_PROVIDER_CALLS=true gate"
        )
    normalized_key = (settings.gemini_api_key or "").strip().casefold()
    if (
        not normalized_key
        or normalized_key.startswith("<")
        or "replace-me" in normalized_key
        or len(normalized_key) < 20
    ):
        raise RuntimeError("GEMINI_API_KEY is required for PROVIDER_MODE=gemini")
    parsed = urlparse(settings.gemini_base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "generativelanguage.googleapis.com"
        or parsed.path.rstrip("/") not in {"/v1", "/v1beta"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "GEMINI_BASE_URL must be the official HTTPS generativelanguage.googleapis.com "
            "v1 or v1beta endpoint"
        )
    expected_models = {
        "gemini-3.5-transcribe",
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
    }
    configured_models = {
        settings.gemini_speech_model,
        settings.llm_cheap_model,
        settings.llm_strong_model,
    }
    if not configured_models.issubset(expected_models):
        raise RuntimeError(
            "Gemini model IDs must use the pinned, priced demo registry: "
            + ", ".join(sorted(expected_models))
        )
    if settings.llm_cheap_model == settings.llm_strong_model:
        raise RuntimeError("LLM cheap and strong routes must use different pinned models")
    if settings.llm_cheap_model != "gemini-3.5-flash-lite":
        raise RuntimeError("LLM_CHEAP_MODEL must use the pinned gemini-3.5-flash-lite route")
    if settings.llm_strong_model != "gemini-3.8-flash":
        raise RuntimeError("LLM_STRONG_MODEL must use the pinned gemini-3.8-flash route")
    if settings.gemini_speech_model not in {
        settings.llm_cheap_model,
        "gemini-3.5-transcribe",
    }:
        raise RuntimeError(
            "GEMINI_SPEECH_MODEL must be the configured cheap model or gemini-3.5-transcribe"
        )
    if settings.provider_data_policy != "synthetic-approved-only":
        raise RuntimeError(
            "The local Gemini demo currently permits only PROVIDER_DATA_POLICY="
            "synthetic-approved-only"
        )
    allowed_languages = {item.casefold() for item in settings.provider_allowed_languages}
    if not allowed_languages or not allowed_languages.issubset({"en", "en-us", "en-gb"}):
        raise RuntimeError("The evaluated Gemini demo lane currently supports English only")
    bounded_values = {
        "MAX_CHEAP_REPAIR_ATTEMPTS": (settings.max_cheap_repair_attempts, 0, 3),
        "MAX_STRONG_REPAIR_ATTEMPTS": (settings.max_strong_repair_attempts, 0, 1),
        "GEMINI_MAX_HTTP_RETRIES": (settings.gemini_max_http_retries, 0, 5),
    }
    for name, (value, minimum, maximum) in bounded_values.items():
        if not minimum <= value <= maximum:
            raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    if settings.max_strong_context_tokens < 1_000:
        raise RuntimeError("MAX_STRONG_CONTEXT_TOKENS must be at least 1000")
    if (
        min(
            settings.gemini_request_timeout_seconds,
            settings.gemini_upload_timeout_seconds,
        )
        <= 0
    ):
        raise RuntimeError("Gemini request timeouts must be positive")
    if settings.gemini_retry_backoff_seconds < 0:
        raise RuntimeError("GEMINI_RETRY_BACKOFF_SECONDS cannot be negative")
    if (
        min(
            settings.gemini_cheap_input_usd_per_million,
            settings.gemini_cheap_output_usd_per_million,
            settings.gemini_strong_input_usd_per_million,
            settings.gemini_strong_output_usd_per_million,
            settings.gemini_speech_input_usd_per_million,
            settings.gemini_speech_output_usd_per_million,
        )
        <= 0
    ):
        raise RuntimeError("Gemini price-catalog rates must be positive")
    if settings.gemini_price_catalog_version != "google-gemini-standard-2026-09-07":
        raise RuntimeError(
            "GEMINI_PRICE_CATALOG_VERSION must match the reviewed, pinned demo catalog"
        )
