from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from starlette.concurrency import run_in_threadpool

from . import __version__
from .blobstore import create_blob_store
from .config import Settings, validate_runtime_settings
from .database import Database
from .domain import seed_demo_recordings
from .lifecycle import RetentionMaintenance
from .models import Recording
from .providers import (
    MockFixtureLLMAdapter,
    MockFixtureSpeechAdapter,
    MockHashEmbeddingAdapter,
    create_provider_adapters,
)
from .routes import auth, discovery, recordings
from .seed import seed_reference_data


def _attach_static_web(application: FastAPI, configured_root: Path | None) -> None:
    if configured_root is None:
        return
    root = configured_root.resolve()
    if not (root / "index.html").is_file():
        raise RuntimeError(f"WEB_DIST_ROOT does not contain index.html: {root}")

    @application.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    @application.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def static_web(full_path: str = "") -> FileResponse:
        # Unknown API and documentation paths must remain HTTP 404s instead of
        # falling through to the single-page application.
        if full_path in {"openapi.json", "docs", "redoc"} or full_path.startswith(
            ("v1/", "docs/", "redoc/")
        ):
            raise HTTPException(status_code=404, detail="Not found")
        requested = (root / full_path).resolve()
        if requested != root and root not in requested.parents:
            raise HTTPException(status_code=404, detail="Not found")
        candidates = [requested]
        if not requested.suffix:
            candidates.extend([Path(f"{requested}.html"), requested / "index.html"])
        for candidate in candidates:
            if candidate.is_file():
                immutable = full_path.startswith(("_expo/", "assets/"))
                return FileResponse(
                    candidate,
                    headers={
                        "Cache-Control": (
                            "public, max-age=31536000, immutable"
                            if immutable
                            else "no-cache"
                        ),
                        "X-Content-Type-Options": "nosniff",
                        "Referrer-Policy": "strict-origin-when-cross-origin",
                        "X-Frame-Options": "DENY",
                    },
                )
        if "." not in Path(full_path).name:
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
        raise HTTPException(status_code=404, detail="Not found")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_environment()
    validate_runtime_settings(resolved)
    database = Database(resolved.database_url)
    blob_store = create_blob_store(resolved)
    speech_adapter, llm_adapter = create_provider_adapters(resolved)
    # Demo seeding must remain deterministic and must never dispatch a paid
    # provider call simply because the runtime provider is enabled.
    seed_speech_adapter = MockFixtureSpeechAdapter(resolved.fixture_root)
    seed_llm_adapter = MockFixtureLLMAdapter(resolved.fixture_root)
    embedding_adapter = MockHashEmbeddingAdapter()
    retention_maintenance = RetentionMaintenance(
        database,
        blob_store,
        interval_seconds=resolved.sweeper_interval_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # SQLite is the zero-account compatibility path. PostgreSQL schema
        # ownership belongs exclusively to Alembic (Compose runs migrate first).
        if database.engine.dialect.name == "sqlite":
            database.create_all()
        with database.session_factory() as db:
            seed_reference_data(
                db,
                monthly_spend_limit_usd=resolved.workspace_monthly_cost_ceiling_usd,
            )
        seed_demo_recordings(
            database,
            blob_store,
            seed_speech_adapter,
            seed_llm_adapter,
            resolved,
        )
        if resolved.inline_worker:
            retention_maintenance.run_if_due(force=True)
        yield
        database.close()

    application = FastAPI(
        title="Pocket Demo API",
        version=__version__,
        description=(
            "Evidence-first Pocket architecture demo. Mock fixture provenance is "
            "explicit; arbitrary audio never receives invented AI artifacts."
        ),
        lifespan=lifespan,
    )
    application.state.settings = resolved
    application.state.database = database
    application.state.blob_store = blob_store
    application.state.speech_adapter = speech_adapter
    application.state.llm_adapter = llm_adapter
    application.state.embedding_adapter = embedding_adapter
    application.state.retention_maintenance = retention_maintenance
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "Range",
            "X-CSRF-Token",
            "X-Upload-Token",
        ],
        expose_headers=["ETag", "Content-Range", "Accept-Ranges", "X-CSRF-Token"],
    )

    @application.middleware("http")
    async def enforce_inline_retention(request, call_next):
        if resolved.inline_worker:
            await run_in_threadpool(retention_maintenance.run_if_due)
        return await call_next(request)

    application.include_router(auth.router)
    application.include_router(recordings.router)
    application.include_router(recordings.media_router)
    application.include_router(discovery.router)

    @application.get("/healthz", tags=["health"])
    @application.get("/v1/health", tags=["health"])
    def health() -> dict[str, object]:
        with database.session_factory() as db:
            db.execute(text("SELECT 1"))
            recording_count = db.scalar(
                select(func.count()).select_from(Recording).where(Recording.deleted_at.is_(None))
            )
        return {
            "status": "ok",
            "version": __version__,
            "database": "ready",
            "blob_store": resolved.blob_store_backend,
            "processing_mode": "inline" if resolved.inline_worker else "external_worker",
            "provider_mode": (
                "approved_fixture_only"
                if resolved.provider_mode in {"fixture", "mock"}
                else resolved.provider_mode
            ),
            "remote_provider_calls_allowed": resolved.allow_remote_provider_calls,
            "active_recordings": recording_count or 0,
        }

    @application.get("/v1/capabilities", tags=["health"])
    def capabilities() -> dict[str, object]:
        gemini_enabled = resolved.provider_mode == "gemini" and resolved.allow_remote_provider_calls
        maximum_seconds = resolved.max_duration_ms // 1000
        return {
            "provider_mode": resolved.provider_mode,
            "remote_processing": gemini_enabled,
            "data_policy": resolved.provider_data_policy,
            "allowed_languages": list(resolved.provider_allowed_languages),
            "max_audio_duration_seconds": maximum_seconds,
            "speech": {
                "model_alias": "speech.standard" if gemini_enabled else "speech.fixture",
                "max_duration_seconds": maximum_seconds,
                "diarization": True,
                "timestamps": True,
                "vocabulary_hints": True,
            },
            "intelligence": {
                "cheap_model_alias": "llm.cheap" if gemini_enabled else "llm.fixture",
                "strong_model_alias": "llm.strong" if gemini_enabled else None,
                "deep_available": gemini_enabled,
            },
            "ask": {
                "cheap_model_alias": "llm.cheap" if gemini_enabled else "llm.none",
                "strong_model_alias": "llm.strong" if gemini_enabled else None,
                "deep_available": gemini_enabled,
            },
            "features": {
                "transcript": True,
                "intelligence": True,
                "mind_map": True,
                "search": True,
                "ask": True,
                "tasks": True,
                "exports": True,
            },
        }

    _attach_static_web(application, resolved.web_dist_root)

    return application


app = create_app()
