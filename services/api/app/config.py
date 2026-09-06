from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


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
    if settings.provider_mode not in {"fixture", "mock"}:
        raise RuntimeError(
            f"PROVIDER_MODE={settings.provider_mode!r} is not implemented in this demo. "
            "Wire reviewed provider adapters before enabling paid calls."
        )
    if settings.allow_remote_provider_calls:
        raise RuntimeError(
            "ALLOW_REMOTE_PROVIDER_CALLS=true is unsupported until real provider adapters "
            "and policy smoke tests are implemented"
        )
