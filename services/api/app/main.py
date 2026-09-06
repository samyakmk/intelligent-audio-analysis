from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
)
from .routes import auth, discovery, recordings
from .seed import seed_reference_data


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_environment()
    validate_runtime_settings(resolved)
    database = Database(resolved.database_url)
    blob_store = create_blob_store(resolved)
    speech_adapter = MockFixtureSpeechAdapter(resolved.fixture_root)
    llm_adapter = MockFixtureLLMAdapter(resolved.fixture_root)
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
            speech_adapter,
            llm_adapter,
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
            "provider_mode": "approved_fixture_only",
            "remote_provider_calls_allowed": False,
            "active_recordings": recording_count or 0,
        }

    return application


app = create_app()
