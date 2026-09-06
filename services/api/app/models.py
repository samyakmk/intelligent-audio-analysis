from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspace"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    monthly_spend_limit_usd: Mapped[float] = mapped_column(Float, default=50.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Principal(Base):
    __tablename__ = "principal"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Membership(Base):
    __tablename__ = "membership"
    principal_id: Mapped[str] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), primary_key=True
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), default="member")


class DemoSession(Base):
    __tablename__ = "demo_session"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128))
    principal_id: Mapped[str] = mapped_column(ForeignKey("principal.id"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recording(Base):
    __tablename__ = "recording"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("principal.id"))
    display_name: Mapped[str] = mapped_column(String(240))
    original_filename: Mapped[str] = mapped_column(String(240))
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    requested_language: Mapped[str] = mapped_column(String(32), default="en")
    requested_mode: Mapped[str] = mapped_column(String(16), default="standard")
    vocabulary_hints: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    folder: Mapped[str | None] = mapped_column(String(160), nullable=True)
    summary_style: Mapped[str] = mapped_column(String(32), default="standard")
    source_kind: Mapped[str] = mapped_column(String(32), default="upload")
    status: Mapped[str] = mapped_column(String(32), default="UPLOADING", index=True)
    stage: Mapped[str] = mapped_column(String(48), default="uploading")
    error_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    original_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    transcript_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    intelligence_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    indexed_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    deletion_generation: Mapped[int] = mapped_column(Integer, default=0)
    transcript_version: Mapped[int] = mapped_column(Integer, default=0)
    intelligence_version: Mapped[int] = mapped_column(Integer, default=0)
    etag_version: Mapped[int] = mapped_column(Integer, default=1)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: utcnow() + timedelta(days=30)
    )


class UploadSession(Base):
    __tablename__ = "upload_session"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), unique=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    deletion_generation: Mapped[int] = mapped_column(Integer)
    quarantine_key: Mapped[str] = mapped_column(String(512), unique=True)
    upload_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expected_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actual_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MediaObject(Base):
    __tablename__ = "media_object"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    deletion_generation: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    blob_key: Mapped[str] = mapped_column(String(512), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("recording_id", "kind", name="uq_media_kind"),)


class ProcessingRun(Base):
    __tablename__ = "processing_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    deletion_generation: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    failure_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StageRun(Base):
    __tablename__ = "stage_run"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    processing_run_id: Mapped[str] = mapped_column(ForeignKey("processing_run.id"), index=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    stage: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("processing_run_id", "stage", name="uq_run_stage"),)


class OutboxEvent(Base):
    __tablename__ = "outbox_event"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_key: Mapped[str] = mapped_column(String(180), unique=True)
    event_type: Mapped[str] = mapped_column(String(96))
    recording_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    deletion_generation: Mapped[int] = mapped_column(Integer)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TranscriptVersion(Base):
    __tablename__ = "transcript_version"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(96))
    model: Mapped[str] = mapped_column(String(128))
    pipeline_version: Mapped[str] = mapped_column(String(64), default="mock-pipeline.v1")
    schema_version: Mapped[str] = mapped_column(String(64), default="CanonicalTranscript.v1")
    prompt_version: Mapped[str] = mapped_column(String(64), default="none")
    policy_version: Mapped[str] = mapped_column(String(64), default="demo-policy.v1")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("recording_id", "version", name="uq_transcript_version"),)


class TimelineInterval(Base):
    __tablename__ = "timeline_interval"
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    transcript_id: Mapped[str] = mapped_column(
        ForeignKey("transcript_version.id", ondelete="CASCADE"), index=True
    )
    recording_id: Mapped[str] = mapped_column(String(36), index=True)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16))


class TranscriptSegment(Base):
    __tablename__ = "transcript_segment"
    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    transcript_id: Mapped[str] = mapped_column(
        ForeignKey("transcript_version.id", ondelete="CASCADE"), index=True
    )
    recording_id: Mapped[str] = mapped_column(String(36), index=True)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    language_bcp47: Mapped[str] = mapped_column(String(32), default="en-US")
    speaker_cluster_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    speaker_display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    overlap_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


class IntelligenceVersion(Base):
    __tablename__ = "intelligence_version"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    transcript_version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    provenance: Mapped[dict] = mapped_column(JSON)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("recording_id", "version", name="uq_intelligence_version"),)


class EvidenceUnit(Base):
    __tablename__ = "evidence_unit"
    id: Mapped[str] = mapped_column(String(220), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    transcript_version: Mapped[int] = mapped_column(Integer)
    deletion_generation: Mapped[int] = mapped_column(Integer)
    speaker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    text_normalized: Mapped[str] = mapped_column(Text)
    citation: Mapped[dict] = mapped_column(JSON)


class ActionItem(Base):
    __tablename__ = "action_item"
    id: Mapped[str] = mapped_column(String(220), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    intelligence_version: Mapped[int] = mapped_column(Integer)
    task: Mapped[str] = mapped_column(Text)
    owner_text: Mapped[str | None] = mapped_column(String(160), nullable=True)
    due_text: Mapped[str | None] = mapped_column(String(160), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    ambiguities: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AskSession(Base):
    __tablename__ = "ask_session"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principal.id"))
    scope_type: Mapped[str] = mapped_column(String(32), default="library")
    recording_ids: Mapped[list] = mapped_column(JSON, default=list)
    selection_segment_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AskMessage(Base):
    __tablename__ = "ask_message"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ask_session_id: Mapped[str] = mapped_column(
        ForeignKey("ask_session.id", ondelete="CASCADE"), index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recap(Base):
    __tablename__ = "recap"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    principal_id: Mapped[str] = mapped_column(ForeignKey("principal.id"))
    kind: Mapped[str] = mapped_column(String(32))
    project: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    input_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CostEvent(Base):
    __tablename__ = "cost_event"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(160), unique=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    recording_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ask_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    stage: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(96))
    model_alias: Mapped[str] = mapped_column(String(96))
    resolved_model: Mapped[str] = mapped_column(String(128))
    price_catalog_version: Mapped[str] = mapped_column(String(64))
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    reconciled_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    cache_reuse: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BudgetReservation(Base):
    """Durable admission fence created before a potentially billable call."""

    __tablename__ = "budget_reservation"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspace.id"), index=True)
    recording_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ask_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(64))
    reserved_usd: Mapped[float] = mapped_column(Float)
    committed_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="reserved", index=True)
    release_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MediaGrant(Base):
    __tablename__ = "media_grant"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    recording_id: Mapped[str] = mapped_column(ForeignKey("recording.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    deletion_generation: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DomainEvent(Base):
    __tablename__ = "domain_event"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), unique=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    recording_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(96))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    operation: Mapped[str] = mapped_column(String(96))
    key: Mapped[str] = mapped_column(String(180))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSON)
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("workspace_id", "operation", "key", name="uq_idempotency"),)
