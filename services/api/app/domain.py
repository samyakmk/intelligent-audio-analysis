from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import uuid
import wave
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from .blobstore import BlobStore
from .config import Settings
from .database import Database
from .demo_fixture import FIXTURE_DURATION_MS, FIXTURE_SHA256, load_fixture_wav
from .models import (
    ActionItem,
    AskMessage,
    BudgetReservation,
    CostEvent,
    DomainEvent,
    EvidenceUnit,
    IdempotencyRecord,
    IntelligenceVersion,
    MediaObject,
    OutboxEvent,
    ProcessingRun,
    Recap,
    Recording,
    StageRun,
    TimelineInterval,
    TranscriptSegment,
    TranscriptVersion,
    UploadSession,
    Workspace,
    utcnow,
)
from .providers import (
    AskRequest,
    LLMAdapter,
    ProviderBilledFailure,
    ProviderDataPolicyDenied,
    ProviderUnavailable,
    SpeechAdapter,
    SpeechRequest,
    SpeechUnconfigured,
)


class ValidationFailure(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class StaleGeneration(RuntimeError):
    pass


class BudgetExceeded(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BudgetReservationUnavailable(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def retry_sealed_quarantine_cleanup(
    database: Database, blob_store: BlobStore, *, limit: int = 50
) -> int:
    """Remove copy-first quarantine objects whose post-commit cleanup failed."""

    completed = 0
    with database.session_factory() as db:
        uploads = db.scalars(
            select(UploadSession)
            .where(UploadSession.status == "sealed_cleanup_pending")
            .limit(limit)
            .with_for_update(skip_locked=database.engine.dialect.name == "postgresql")
        ).all()
        for upload in uploads:
            try:
                blob_store.delete(upload.quarantine_key)
            except Exception:
                continue
            upload.status = "sealed"
            completed += 1
        db.commit()
    return completed


@dataclass(frozen=True, slots=True)
class AudioProbe:
    detected_format: str
    content_type: str
    duration_ms: int | None


MAGIC_TYPES = {
    "wav": "audio/wav",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "aac": "audio/aac",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "webm": "audio/webm",
}


def detect_audio_format(data: bytes) -> str | None:
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"fLaC"):
        return "flac"
    if data.startswith(b"OggS"):
        return "ogg"
    # ADTS AAC uses the same 12-bit sync prefix as MPEG audio, but its layer
    # bits are zero.  Detect it before the broader MP3 sync check.
    if len(data) >= 2 and data[0] == 0xFF and data[1] & 0xF6 == 0xF0:
        return "aac"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "m4a"
    if data.startswith(bytes.fromhex("1a45dfa3")):
        return "webm"
    return None


def validate_audio(data: bytes, settings: Settings) -> AudioProbe:
    if not data:
        raise ValidationFailure("empty_media", "The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise ValidationFailure(
            "media_too_large", f"Audio exceeds the {settings.max_upload_bytes}-byte limit."
        )
    detected = detect_audio_format(data)
    if detected is None:
        raise ValidationFailure(
            "unsupported_media", "File content is not a supported audio container."
        )
    duration_ms: int | None
    if detected == "wav":
        duration_ms = _probe_wav(data)
    else:
        duration_ms = _probe_ffmpeg(data, detected)
    if duration_ms is not None and duration_ms > settings.max_duration_ms:
        raise ValidationFailure(
            "media_too_long", f"Audio exceeds the {settings.max_duration_ms // 1000}-second limit."
        )
    return AudioProbe(detected, MAGIC_TYPES[detected], duration_ms)


def _probe_wav(data: bytes) -> int:
    try:
        if len(data) < 12 or int.from_bytes(data[4:8], "little") + 8 != len(data):
            raise ValidationFailure(
                "corrupt_media", "WAV RIFF length does not match the uploaded byte count."
            )
        with wave.open(io.BytesIO(data), "rb") as stream:
            channels = stream.getnchannels()
            sample_width = stream.getsampwidth()
            rate = stream.getframerate()
            frame_count = stream.getnframes()
            if channels < 1 or channels > 8 or sample_width not in {1, 2, 3, 4} or rate <= 0:
                raise ValidationFailure("corrupt_media", "WAV parameters are invalid.")
            decoded = stream.readframes(frame_count)
            expected = channels * sample_width * frame_count
            if frame_count <= 0 or len(decoded) != expected:
                raise ValidationFailure(
                    "partial_media", "WAV payload is truncated or has no decodable frames."
                )
            return max(1, round(frame_count * 1000 / rate))
    except ValidationFailure:
        raise
    except (wave.Error, EOFError, OSError) as exc:
        raise ValidationFailure("corrupt_media", "WAV could not be decoded.") from exc


def _probe_ffmpeg(data: bytes, suffix: str) -> int | None:
    executable = shutil.which("ffprobe")
    if executable is None:
        # Magic validation is still real, but duration/decoding cannot be claimed.
        # Fail closed rather than accepting an unbounded or corrupt input.
        raise ValidationFailure(
            "decoder_unavailable",
            "ffprobe is required to validate this audio container; WAV works without it.",
        )
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as handle:
            handle.write(data)
            path = Path(handle.name)
        result = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise ValidationFailure("corrupt_media", "Audio container could not be decoded.")
        duration = float(result.stdout.strip())
        if duration <= 0:
            raise ValidationFailure("corrupt_media", "Audio has no positive duration.")
        return round(duration * 1000)
    except (ValueError, subprocess.TimeoutExpired) as exc:
        raise ValidationFailure("corrupt_media", "Audio probe failed safely.") from exc
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def recording_payload(recording: Recording) -> dict[str, Any]:
    state = recording.status.casefold()
    issue = None
    if recording.error_code:
        issue = {
            "code": recording.error_code,
            "message": recording.error_detail or recording.error_code,
            "retryable": recording.status in {"FAILED_RETRYABLE", "PARTIAL"},
            "action": "Configure a speech provider or use the approved demo fixture."
            if recording.error_code == "speech_unconfigured"
            else None,
        }
    return {
        "id": recording.id,
        "title": recording.display_name,
        "filename": recording.original_filename,
        "display_name": recording.display_name,
        "original_filename": recording.original_filename,
        "content_type": recording.content_type,
        "language": recording.requested_language,
        "mode": recording.requested_mode,
        "provider_data_approved": recording.provider_data_approved,
        "tags": recording.tags or [],
        "folder": recording.folder,
        "summary_style": recording.summary_style,
        "source_kind": recording.source_kind,
        "status": recording.status,
        "state": state,
        "stage": recording.stage,
        "error": (
            {"code": recording.error_code, "message": recording.error_detail}
            if recording.error_code
            else None
        ),
        "issues": [issue] if issue else [],
        "readiness": {
            "original_ready": recording.original_ready,
            "transcript_ready": recording.transcript_ready,
            "intelligence_ready": recording.intelligence_ready,
            "indexed_ready": recording.indexed_ready,
        },
        "sha256": recording.sha256,
        "size_bytes": recording.size_bytes or 0,
        "duration_ms": recording.duration_ms,
        "transcript_version": recording.transcript_version,
        "intelligence_version": recording.intelligence_version,
        "version": recording.etag_version,
        "created_at": recording.created_at,
        "updated_at": recording.updated_at,
        "expires_at": recording.retention_expires_at,
        "is_fixture": recording.source_kind == "approved_fixture",
        "fixture_label": "Scripted functional mock"
        if recording.source_kind == "approved_fixture"
        else None,
    }


def recording_detail_payload(db: Session, recording: Recording) -> dict[str, Any]:
    payload = recording_payload(recording)
    runs = db.scalars(
        select(StageRun).where(StageRun.recording_id == recording.id).order_by(StageRun.created_at)
    ).all()
    latest_by_stage: dict[str, StageRun] = {}
    for item in runs:
        latest_by_stage[item.stage] = item
    status_map = {
        "running": "active",
        "complete": "complete",
        "failed": "failed",
        "unavailable": "failed",
        "pending": "pending",
    }
    payload["stages"] = [
        {
            "stage": stage,
            "status": status_map.get(item.status, "pending"),
            "message": item.detail.get("message") or item.detail.get("code"),
            "started_at": item.created_at,
            "completed_at": item.created_at if item.status == "complete" else None,
        }
        for stage, item in latest_by_stage.items()
    ]
    return payload


def seed_demo_recordings(
    database: Database,
    blob_store: BlobStore,
    speech: SpeechAdapter,
    llm: LLMAdapter,
    settings: Settings,
) -> None:
    if not settings.demo_mode:
        return
    fixture_bytes = load_fixture_wav(settings.fixture_root)
    probe = validate_audio(fixture_bytes, settings)
    seeds = (("demo-recording-test", "test-workspace", "test-account"),)
    run_ids: list[str] = []
    with database.session_factory() as db:
        for recording_id, workspace_id, principal_id in seeds:
            if db.get(Recording, recording_id) is not None:
                continue
            blob_key = f"original/{workspace_id}/{recording_id}/g0/audio"
            if not blob_store.exists(blob_key):
                blob_store.put(blob_key, fixture_bytes, immutable=True)
            elif hashlib.sha256(blob_store.get(blob_key)).hexdigest() != FIXTURE_SHA256:
                raise RuntimeError("Existing seeded original does not match canonical fixture")
            recording = Recording(
                id=recording_id,
                workspace_id=workspace_id,
                created_by=principal_id,
                display_name="Pocket scripted architecture demo",
                original_filename="pocket-demo-fixture.wav",
                content_type=probe.content_type,
                requested_language="en",
                provider_data_approved=True,
                source_kind="approved_fixture",
                status="SEALED",
                stage="sealed",
                size_bytes=len(fixture_bytes),
                duration_ms=probe.duration_ms or FIXTURE_DURATION_MS,
                sha256=FIXTURE_SHA256,
                original_ready=True,
                retention_expires_at=utcnow() + timedelta(days=settings.recording_retention_days),
            )
            db.add(recording)
            db.flush()
            db.add(
                MediaObject(
                    id=str(uuid.uuid4()),
                    recording_id=recording.id,
                    workspace_id=workspace_id,
                    deletion_generation=0,
                    kind="original",
                    blob_key=blob_key,
                    sha256=FIXTURE_SHA256,
                    size_bytes=len(fixture_bytes),
                    content_type=probe.content_type,
                )
            )
            run = create_processing_run(db, recording)
            run_ids.append(run.id)
            db.add(
                OutboxEvent(
                    id=str(uuid.uuid4()),
                    event_key=f"recording.sealed:{recording.id}:g0",
                    event_type="recording.sealed.v1",
                    recording_id=recording.id,
                    workspace_id=workspace_id,
                    deletion_generation=0,
                )
            )
            emit_event(db, recording, "recording.sealed", {})
        db.commit()
    if settings.inline_worker:
        for run_id in run_ids:
            process_run(database, blob_store, speech, llm, settings, run_id)


def require_recording(
    db: Session,
    recording_id: str,
    workspace_id: str,
    *,
    include_deleted: bool = False,
    lock: bool = False,
) -> Recording:
    query = select(Recording).where(
        Recording.id == recording_id, Recording.workspace_id == workspace_id
    )
    if not include_deleted:
        query = query.where(Recording.deleted_at.is_(None))
    if lock:
        query = query.with_for_update()
    recording = db.scalar(query)
    if recording is None:
        # Deliberately avoid exposing whether another workspace owns the ID.
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


def emit_event(
    db: Session,
    recording: Recording,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    db.add(
        DomainEvent(
            id=str(uuid.uuid4()),
            workspace_id=recording.workspace_id,
            recording_id=recording.id,
            event_type=event_type,
            payload=payload or {},
        )
    )


def set_stage(
    db: Session,
    recording: Recording,
    run: ProcessingRun,
    stage: str,
    status: str,
    detail: dict[str, Any] | None = None,
) -> None:
    recording.stage = stage
    existing = db.scalar(
        select(StageRun).where(StageRun.processing_run_id == run.id, StageRun.stage == stage)
    )
    if existing is None:
        db.add(
            StageRun(
                id=str(uuid.uuid4()),
                processing_run_id=run.id,
                recording_id=recording.id,
                stage=stage,
                status=status,
                detail=detail or {},
            )
        )
    else:
        existing.status = status
        existing.detail = detail or {}
    emit_event(db, recording, "stage.updated", {"stage": stage, "status": status})


def assert_publishable(recording: Recording, generation: int) -> None:
    if recording.deleted_at is not None or recording.deletion_generation != generation:
        raise StaleGeneration("Recording was deleted or replaced while work was running")
    if recording.cancel_requested:
        raise StaleGeneration("Recording processing was cancelled")


def create_processing_run(db: Session, recording: Recording) -> ProcessingRun:
    attempt = (
        db.scalar(
            select(func.max(ProcessingRun.attempt)).where(
                ProcessingRun.recording_id == recording.id
            )
        )
        or 0
    ) + 1
    run = ProcessingRun(
        id=str(uuid.uuid4()),
        recording_id=recording.id,
        workspace_id=recording.workspace_id,
        deletion_generation=recording.deletion_generation,
        status="queued",
        attempt=attempt,
    )
    db.add(run)
    emit_event(db, recording, "processing.queued", {"run_id": run.id, "attempt": attempt})
    return run


def claim_next_run(database: Database, lease_owner: str, *, lease_seconds: int = 300) -> str | None:
    """Atomically claim one runnable job.

    PostgreSQL workers serialize candidates with SKIP LOCKED. SQLite uses a
    conditional UPDATE fence, which is sufficient for the local demo.
    """

    now = utcnow()
    expires = now + timedelta(seconds=lease_seconds)
    with database.session_factory() as db:
        runnable = or_(
            ProcessingRun.status == "queued",
            and_(
                ProcessingRun.status.in_(["claimed", "processing"]),
                ProcessingRun.lease_expires_at.is_not(None),
                ProcessingRun.lease_expires_at < now,
            ),
        )
        statement = (
            select(ProcessingRun.id).where(runnable).order_by(ProcessingRun.created_at).limit(1)
        )
        if database.engine.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        candidate = db.scalar(statement)
        if candidate is None:
            return None
        claimed = db.execute(
            update(ProcessingRun)
            .where(ProcessingRun.id == candidate, runnable)
            .values(
                status="claimed",
                lease_owner=lease_owner,
                lease_expires_at=expires,
            )
        )
        if claimed.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        return candidate


def _claim_specific_run(
    database: Database, run_id: str, lease_owner: str, *, lease_seconds: int = 300
) -> bool:
    with database.session_factory() as db:
        result = db.execute(
            update(ProcessingRun)
            .where(
                ProcessingRun.id == run_id,
                ProcessingRun.status == "queued",
            )
            .values(
                status="claimed",
                lease_owner=lease_owner,
                lease_expires_at=utcnow() + timedelta(seconds=lease_seconds),
            )
        )
        db.commit()
        return result.rowcount == 1


def _refresh_publishable(
    db: Session,
    recording_id: str,
    generation: int,
    run_id: str,
    lease_owner: str,
    lease_seconds: int,
    *,
    lock_for_publication: bool = True,
) -> Recording:
    db.expire_all()
    recording_query = select(Recording).where(Recording.id == recording_id)
    run_query = select(ProcessingRun).where(ProcessingRun.id == run_id)
    if lock_for_publication:
        recording_query = recording_query.with_for_update()
        run_query = run_query.with_for_update()
    recording = db.scalar(recording_query)
    if recording is None:
        raise StaleGeneration("Recording no longer exists")
    assert_publishable(recording, generation)
    run = db.scalar(run_query)
    if (
        run is None
        or run.lease_owner != lease_owner
        or run.status
        not in {
            "claimed",
            "processing",
        }
    ):
        raise StaleGeneration("Worker no longer owns the processing lease")
    expires = run.lease_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires is not None and expires <= utcnow():
        raise StaleGeneration("Processing lease expired before publication")
    run.lease_expires_at = utcnow() + timedelta(seconds=lease_seconds)
    db.flush()
    return recording


def process_run(
    database: Database,
    blob_store: BlobStore,
    speech: SpeechAdapter,
    llm: LLMAdapter,
    settings: Settings,
    run_id: str,
    lease_owner: str | None = None,
) -> None:
    owner = lease_owner or f"inline:{uuid.uuid4()}"
    dispatched_attempts: set[str] = set()
    if lease_owner is None and not _claim_specific_run(
        database, run_id, owner, lease_seconds=settings.worker_lease_seconds
    ):
        return
    db = database.session_factory()
    try:
        run = db.get(ProcessingRun, run_id)
        if run is None or run.status != "claimed" or run.lease_owner != owner:
            return
        recording = db.get(Recording, run.recording_id)
        if recording is None:
            return
        try:
            assert_publishable(recording, run.deletion_generation)
            if (
                settings.provider_mode == "gemini"
                and settings.allow_remote_provider_calls
                and not recording.provider_data_approved
            ):
                raise SpeechUnconfigured(
                    "Remote provider processing requires persisted data-policy approval."
                )
            run.status = "processing"
            run.started_at = utcnow()
            recording.status = "PROCESSING"
            recording.error_code = None
            recording.error_detail = None
            if recording.transcript_ready:
                transcript = db.scalar(
                    select(TranscriptVersion).where(
                        TranscriptVersion.recording_id == recording.id,
                        TranscriptVersion.is_current.is_(True),
                    )
                )
                if transcript is None:
                    raise RuntimeError("transcript readiness pointer is inconsistent")
                set_stage(
                    db,
                    recording,
                    run,
                    "transcribing",
                    "complete",
                    {"reused_transcript_version": transcript.version},
                )
            else:
                set_stage(db, recording, run, "transcribing", "running")
                db.commit()
                recording = _refresh_publishable(
                    db,
                    recording.id,
                    run.deletion_generation,
                    run.id,
                    owner,
                    settings.worker_lease_seconds,
                    lock_for_publication=False,
                )
                media = db.scalar(
                    select(MediaObject).where(
                        MediaObject.recording_id == recording.id,
                        MediaObject.kind == "original",
                    )
                )
                if media is None:
                    raise RuntimeError("sealed recording is missing immutable original")
                speech_attempt_id = f"speech:{run.id}"
                audio_bytes = blob_store.get(media.blob_key)
                speech_request = SpeechRequest(
                    recording_id=recording.id,
                    audio_sha256=media.sha256,
                    audio_reference=media.id,
                    original_time_offset_ms=0,
                    language=recording.requested_language,
                    vocabulary_hints=tuple(recording.vocabulary_hints or []),
                    require_diarization=True,
                    require_timestamps=True,
                    budget_usd=settings.recording_cost_ceiling_usd,
                    request_id=speech_attempt_id,
                    audio_bytes=audio_bytes,
                    content_type=media.content_type,
                    duration_ms=recording.duration_ms,
                )
                estimate_speech = getattr(speech, "estimate_transcription_reservation", None)
                speech_reservation = (
                    estimate_speech(speech_request) if callable(estimate_speech) else 0.0
                )
                reserve_budget(
                    db,
                    attempt_id=speech_attempt_id,
                    workspace_id=recording.workspace_id,
                    recording_id=recording.id,
                    stage="speech",
                    amount_usd=speech_reservation,
                    per_request_cap_usd=settings.recording_cost_ceiling_usd,
                    recording_cap_usd=settings.recording_cost_ceiling_usd,
                )
                mark_budget_dispatched(db, attempt_id=speech_attempt_id)
                db.commit()  # Lease heartbeat; do not hold row locks across provider work.
                dispatched_attempts.add(speech_attempt_id)
                result = speech.transcribe(speech_request)
                result.provenance["provider_data_approved"] = recording.provider_data_approved
                recording = _refresh_publishable(
                    db,
                    recording.id,
                    run.deletion_generation,
                    run.id,
                    owner,
                    settings.worker_lease_seconds,
                )
                run = db.get(ProcessingRun, run_id)
                transcript = _publish_transcript(db, recording, run, result)
                _cost_once(
                    db,
                    attempt_id=speech_attempt_id,
                    workspace_id=recording.workspace_id,
                    recording_id=recording.id,
                    stage="speech",
                    provider=result.provider,
                    model_alias=result.model_alias,
                    resolved_model=result.resolved_model,
                    usage=result.usage,
                    estimated=_provider_actual_cost(result.provenance, result.usage),
                    provenance=result.provenance,
                )
                commit_budget(
                    db,
                    attempt_id=speech_attempt_id,
                    actual_usd=_provider_actual_cost(result.provenance, result.usage),
                )
                recording.transcript_ready = True
                recording.transcript_version = transcript.version
                set_stage(db, recording, run, "transcribing", "complete")
                emit_event(
                    db,
                    recording,
                    "transcript.finalized",
                    {"version": transcript.version},
                )
            if recording.intelligence_ready:
                intelligence = db.scalar(
                    select(IntelligenceVersion).where(
                        IntelligenceVersion.recording_id == recording.id,
                        IntelligenceVersion.is_current.is_(True),
                        IntelligenceVersion.transcript_version == transcript.version,
                    )
                )
                if intelligence is None:
                    raise RuntimeError("intelligence readiness pointer is inconsistent")
                set_stage(
                    db,
                    recording,
                    run,
                    "extracting_intelligence",
                    "complete",
                    {"reused_intelligence_version": intelligence.version},
                )
            else:
                set_stage(db, recording, run, "extracting_intelligence", "running")
                db.commit()

                recording = _refresh_publishable(
                    db,
                    recording.id,
                    run.deletion_generation,
                    run.id,
                    owner,
                    settings.worker_lease_seconds,
                    lock_for_publication=False,
                )
                run = db.get(ProcessingRun, run_id)
                segment_rows = db.scalars(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.transcript_id == transcript.id)
                    .order_by(TranscriptSegment.start_ms, TranscriptSegment.id)
                ).all()
                segment_values = [
                    _segment_payload(item, transcript.version) for item in segment_rows
                ]
                intelligence_source_id = transcript.id
                intelligence_source_version = transcript.version
                intelligence_attempt_id = f"intelligence:{run.id}"
                estimate_intelligence = getattr(
                    llm, "estimate_intelligence_reservation", None
                )
                intelligence_budget = (
                    estimate_intelligence(
                        recording_id=recording.id,
                        transcript_version=transcript.version,
                        segments=segment_values,
                        budget_usd=settings.recording_cost_ceiling_usd,
                        deep=recording.requested_mode == "deep",
                    )
                    if callable(estimate_intelligence)
                    else 0.0
                )
                reserve_budget(
                    db,
                    attempt_id=intelligence_attempt_id,
                    workspace_id=recording.workspace_id,
                    recording_id=recording.id,
                    stage="intelligence",
                    amount_usd=intelligence_budget,
                    per_request_cap_usd=settings.recording_cost_ceiling_usd,
                    recording_cap_usd=settings.recording_cost_ceiling_usd,
                )
                mark_budget_dispatched(db, attempt_id=intelligence_attempt_id)
                db.commit()  # Lease heartbeat; do not hold row locks across provider work.
                dispatched_attempts.add(intelligence_attempt_id)
                intelligence_payload, provenance = llm.extract_intelligence(
                    recording_id=recording.id,
                    transcript_version=transcript.version,
                    segments=segment_values,
                    request_id=intelligence_attempt_id,
                    budget_usd=intelligence_budget,
                    deep=recording.requested_mode == "deep",
                )
                recording = _refresh_publishable(
                    db,
                    recording.id,
                    run.deletion_generation,
                    run.id,
                    owner,
                    settings.worker_lease_seconds,
                )
                current_transcript = db.scalar(
                    select(TranscriptVersion).where(
                        TranscriptVersion.recording_id == recording.id,
                        TranscriptVersion.is_current.is_(True),
                    )
                )
                if (
                    current_transcript is None
                    or current_transcript.id != intelligence_source_id
                    or current_transcript.version != intelligence_source_version
                    or recording.transcript_version != intelligence_source_version
                ):
                    raise StaleGeneration(
                        "Transcript changed while intelligence extraction was running"
                    )
                transcript = current_transcript
                run = db.get(ProcessingRun, run_id)
                intelligence = _publish_intelligence(
                    db, recording, transcript.version, intelligence_payload, provenance
                )
                _cost_once(
                    db,
                    attempt_id=intelligence_attempt_id,
                    workspace_id=recording.workspace_id,
                    recording_id=recording.id,
                    stage="intelligence",
                    provider=provenance["provider"],
                    model_alias=provenance["model_alias"],
                    resolved_model=provenance["resolved_model"],
                    usage=provenance["usage"],
                    estimated=_provider_actual_cost(provenance, provenance.get("usage", {})),
                    provenance=provenance,
                )
                commit_budget(
                    db,
                    attempt_id=intelligence_attempt_id,
                    actual_usd=_provider_actual_cost(provenance, provenance.get("usage", {})),
                )
                recording.intelligence_ready = True
                recording.intelligence_version = intelligence.version
                set_stage(db, recording, run, "extracting_intelligence", "complete")
                emit_event(
                    db,
                    recording,
                    "intelligence.finalized",
                    {"version": intelligence.version},
                )
            set_stage(db, recording, run, "indexing", "running")
            db.flush()
            recording = _refresh_publishable(
                db,
                recording.id,
                run.deletion_generation,
                run.id,
                owner,
                settings.worker_lease_seconds,
            )
            run = db.get(ProcessingRun, run_id)
            _rebuild_evidence(db, recording, transcript)
            invalidate_dependent_views(db, recording)
            recording.indexed_ready = True
            recording.status = "READY"
            recording.stage = "ready"
            run.status = "complete"
            run.completed_at = utcnow()
            run.lease_owner = None
            run.lease_expires_at = None
            set_stage(db, recording, run, "indexing", "complete")
            emit_event(db, recording, "evidence.indexed", {"version": transcript.version})
            emit_event(db, recording, "recording.ready", {})
            db.commit()
        except SpeechUnconfigured as exc:
            db.rollback()
            db.expire_all()
            recording = db.get(Recording, run.recording_id)
            run = db.get(ProcessingRun, run_id)
            settle_run_reservations(
                db,
                run_id,
                dispatched_attempts=set(),
                reason="speech_provider_unconfigured",
            )
            if (
                recording is None
                or run is None
                or run.lease_owner != owner
                or recording.deleted_at is not None
                or recording.cancel_requested
                or recording.deletion_generation != run.deletion_generation
            ):
                db.commit()
                return
            run.status = "partial"
            run.failure_code = "speech_unconfigured"
            run.completed_at = utcnow()
            run.lease_owner = None
            run.lease_expires_at = None
            recording.status = "PARTIAL"
            recording.stage = "partial"
            recording.error_code = "speech_unconfigured"
            recording.error_detail = str(exc)
            set_stage(
                db,
                recording,
                run,
                "transcribing",
                "unavailable",
                {"code": "speech_unconfigured"},
            )
            emit_event(
                db,
                recording,
                "recording.partial",
                {"reason": "speech_unconfigured"},
            )
            db.commit()
        except StaleGeneration:
            db.rollback()
            settle_run_reservations(
                db,
                run_id,
                dispatched_attempts=dispatched_attempts,
                reason="stale_generation",
            )
            cancelled = db.execute(
                update(ProcessingRun)
                .where(
                    ProcessingRun.id == run_id,
                    ProcessingRun.lease_owner == owner,
                    ProcessingRun.status.in_(["claimed", "processing"]),
                )
                .values(
                    status="cancelled",
                    completed_at=utcnow(),
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )
            if cancelled.rowcount == 1:
                recording = db.scalar(
                    select(Recording).where(Recording.id == run.recording_id).with_for_update()
                )
                if (
                    recording is not None
                    and recording.deleted_at is None
                    and not recording.cancel_requested
                    and recording.status == "PROCESSING"
                ):
                    recording.status = (
                        "PARTIAL" if recording.transcript_ready else "FAILED_RETRYABLE"
                    )
                    recording.stage = "partial" if recording.transcript_ready else "failed"
                    recording.error_code = "stale_processing_lease"
                    recording.error_detail = (
                        "Processing lost its publication lease and can be retried."
                    )
                    emit_event(db, recording, "processing.retryable", {})
            db.commit()
        except ProviderUnavailable as exc:
            db.rollback()
            db.expire_all()
            recording = db.get(Recording, run.recording_id)
            run = db.get(ProcessingRun, run_id)
            if isinstance(exc, ProviderBilledFailure) and recording is not None:
                _ledger_billed_failure(
                    db,
                    exc,
                    workspace_id=recording.workspace_id,
                    recording_id=recording.id,
                    stage=("speech" if exc.attempt_id.startswith("speech:") else "intelligence"),
                )
            settle_run_reservations(
                db,
                run_id,
                dispatched_attempts=dispatched_attempts,
                reason="provider_unavailable",
            )
            if (
                recording is not None
                and run is not None
                and run.lease_owner == owner
                and recording.deleted_at is None
                and not recording.cancel_requested
                and recording.deletion_generation == run.deletion_generation
            ):
                run.status = "failed_retryable"
                run.failure_code = "provider_unavailable"
                run.completed_at = utcnow()
                run.lease_owner = None
                run.lease_expires_at = None
                recording.status = "PARTIAL" if recording.transcript_ready else "FAILED_RETRYABLE"
                recording.stage = "partial" if recording.transcript_ready else "failed"
                recording.error_code = "provider_unavailable"
                recording.error_detail = str(exc)
                failed_stage = (
                    "extracting_intelligence" if recording.transcript_ready else "transcribing"
                )
                set_stage(
                    db,
                    recording,
                    run,
                    failed_stage,
                    "failed",
                    {"code": "provider_unavailable", "message": str(exc)},
                )
                recording.stage = "partial" if recording.transcript_ready else "failed"
                emit_event(db, recording, "processing.retryable", {})
            db.commit()
        except Exception:
            db.rollback()
            db.expire_all()
            recording = db.get(Recording, run.recording_id)
            run = db.get(ProcessingRun, run_id)
            settle_run_reservations(
                db,
                run_id,
                dispatched_attempts=dispatched_attempts,
                reason="provider_or_processing_exception",
            )
            if (
                recording is not None
                and run is not None
                and run.lease_owner == owner
                and recording.deleted_at is None
                and not recording.cancel_requested
                and recording.deletion_generation == run.deletion_generation
            ):
                run.status = "failed_retryable"
                run.failure_code = "internal_processing_error"
                run.completed_at = utcnow()
                run.lease_owner = None
                run.lease_expires_at = None
                recording.status = "PARTIAL" if recording.transcript_ready else "FAILED_RETRYABLE"
                recording.stage = "partial" if recording.transcript_ready else "failed"
                recording.error_code = "internal_processing_error"
                recording.error_detail = "Mock processing failed and can be retried."
                failed_stage = (
                    "extracting_intelligence" if recording.transcript_ready else "transcribing"
                )
                set_stage(
                    db,
                    recording,
                    run,
                    failed_stage,
                    "failed",
                    {
                        "code": "internal_processing_error",
                        "message": "Processing failed and can be retried.",
                    },
                )
                recording.stage = "partial" if recording.transcript_ready else "failed"
                emit_event(db, recording, "processing.retryable", {})
            db.commit()
            # Keep content and provider payloads out of logs; caller can inspect persisted state.
    finally:
        db.close()


def _publish_transcript(
    db: Session, recording: Recording, run: ProcessingRun, result: Any
) -> TranscriptVersion:
    version = recording.transcript_version + 1
    transcript = TranscriptVersion(
        id=str(uuid.uuid4()),
        recording_id=recording.id,
        workspace_id=recording.workspace_id,
        version=version,
        source=(
            "approved_fixture_sidecar"
            if result.provenance.get("mock") is True
            else str(result.provenance.get("source") or "provider_transcription")
        ),
        provider=result.provider,
        model=result.resolved_model,
        pipeline_version=str(
            result.provenance.get("pipeline_version") or "provider-speech-pipeline.v1"
        ),
        schema_version=str(result.provenance.get("schema_version") or "CanonicalTranscript.v1"),
        prompt_version=str(result.provenance.get("prompt_version") or "unknown"),
        policy_version=str(result.provenance.get("policy_version") or "demo-policy.v1"),
    )
    db.execute(
        update(TranscriptVersion)
        .where(TranscriptVersion.recording_id == recording.id)
        .values(is_current=False)
    )
    db.add(transcript)
    db.flush()
    _validate_timeline(result.timeline, recording.duration_ms)
    speech_intervals = [item for item in result.timeline if item["state"] == "speech"]
    segment_ids: set[str] = set()
    for item in result.timeline:
        db.add(
            TimelineInterval(
                id=f"{transcript.id}:{item['id']}",
                transcript_id=transcript.id,
                recording_id=recording.id,
                start_ms=item["start_ms"],
                end_ms=item["end_ms"],
                state=item["state"],
            )
        )
    for item in result.segments:
        segment_id = item.get("id")
        if not isinstance(segment_id, str) or not segment_id.strip():
            raise ValueError("transcript segment ID is required")
        if segment_id in segment_ids:
            raise ValueError("duplicate transcript segment ID")
        segment_ids.add(segment_id)
        if not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ValueError("transcript segment text cannot be blank")
        confidence = item.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, int | float) or not 0 <= confidence <= 1
        ):
            raise ValueError("transcript confidence must be between zero and one")
        if item["start_ms"] < 0 or item["end_ms"] <= item["start_ms"]:
            raise ValueError("invalid transcript timestamp")
        if recording.duration_ms and item["end_ms"] > recording.duration_ms:
            raise ValueError("transcript timestamp exceeds media duration")
        if not any(
            item["start_ms"] >= interval["start_ms"] and item["end_ms"] <= interval["end_ms"]
            for interval in speech_intervals
        ):
            raise ValueError("transcript text must lie wholly within a speech interval")
        db.add(
            TranscriptSegment(
                id=f"{transcript.id}:{segment_id}",
                transcript_id=transcript.id,
                recording_id=recording.id,
                start_ms=item["start_ms"],
                end_ms=item["end_ms"],
                language_bcp47=item.get("language_bcp47", "en-US"),
                speaker_cluster_id=item.get("speaker_cluster_id"),
                text=item["text"],
                confidence=item.get("confidence"),
            )
        )
    return transcript


def _validate_timeline(timeline: list[dict[str, Any]], duration_ms: int | None) -> None:
    if not timeline:
        raise ValueError("timeline is empty")
    expected_start = 0
    for item in timeline:
        if item["state"] not in {"speech", "silence", "unreadable"}:
            raise ValueError("invalid timeline state")
        if item["start_ms"] != expected_start or item["end_ms"] <= item["start_ms"]:
            raise ValueError("timeline must be ordered, gap-free, and non-overlapping")
        expected_start = item["end_ms"]
    if duration_ms is not None and expected_start != duration_ms:
        raise ValueError("timeline does not account for the complete media duration")


def _publish_intelligence(
    db: Session,
    recording: Recording,
    transcript_version: int,
    payload: dict[str, Any],
    provenance: dict[str, Any],
) -> IntelligenceVersion:
    _validate_intelligence_citations(db, recording, transcript_version, payload)
    # Extraction versions are immutable, while task completion is mutable user
    # state.  Reprojection must not turn a completed task back into an open one.
    existing_task_state = {
        item.task.strip().casefold(): (item.status, item.version)
        for item in db.scalars(
            select(ActionItem).where(ActionItem.recording_id == recording.id)
        ).all()
    }
    version = recording.intelligence_version + 1
    db.execute(
        update(IntelligenceVersion)
        .where(IntelligenceVersion.recording_id == recording.id)
        .values(is_current=False)
    )
    item = IntelligenceVersion(
        id=str(uuid.uuid4()),
        recording_id=recording.id,
        workspace_id=recording.workspace_id,
        version=version,
        transcript_version=transcript_version,
        payload=payload,
        provenance=provenance,
    )
    db.add(item)
    db.flush()
    db.execute(delete(ActionItem).where(ActionItem.recording_id == recording.id))
    for action in payload.get("actions", []):
        prior_status, prior_version = existing_task_state.get(
            action["task"].strip().casefold(),
            (action.get("status", "open"), 1),
        )
        db.add(
            ActionItem(
                id=f"{recording.id}:v{version}:{action.get('id', uuid.uuid4())}",
                workspace_id=recording.workspace_id,
                recording_id=recording.id,
                intelligence_version=version,
                task=action["task"],
                owner_text=action.get("owner_text"),
                due_text=action.get("due_text"),
                due_at=_parse_optional_datetime(action.get("due_at")),
                status=prior_status,
                ambiguities=action.get("ambiguities", []),
                evidence=action.get("evidence", []),
                version=prior_version,
            )
        )
    return item


def _parse_optional_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _walk_citations(value: Any):
    if isinstance(value, dict):
        if {"segment_id", "start_ms", "end_ms"}.issubset(value):
            yield value
        for nested in value.values():
            yield from _walk_citations(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_citations(nested)


def _validate_intelligence_citations(
    db: Session, recording: Recording, transcript_version: int, payload: dict[str, Any]
) -> None:
    transcript = db.scalar(
        select(TranscriptVersion).where(
            TranscriptVersion.recording_id == recording.id,
            TranscriptVersion.version == transcript_version,
        )
    )
    if transcript is None:
        raise ValueError("intelligence references a missing transcript")
    segments = db.scalars(
        select(TranscriptSegment).where(TranscriptSegment.transcript_id == transcript.id)
    ).all()
    index = {item.id.split(":", 1)[1]: item for item in segments}
    if not isinstance(payload, dict):
        raise ValueError("intelligence payload must be an object")
    required_evidence_items: list[dict[str, Any]] = []
    title = payload.get("title")
    summary = payload.get("summary")
    if not isinstance(title, dict) or not isinstance(title.get("text"), str) or not title["text"]:
        raise ValueError("intelligence title.text is required")
    if (
        not isinstance(summary, dict)
        or not isinstance(summary.get("short"), str)
        or not isinstance(summary.get("detailed"), str)
    ):
        raise ValueError("intelligence summary short/detailed text is required")
    required_evidence_items.extend((title, summary))
    field_by_group = {
        "facts": "claim",
        "decisions": "decision",
        "actions": "task",
        "topics": "label",
        "participants": "speaker_cluster_id",
        "open_questions": "question",
    }
    for key, text_field in field_by_group.items():
        values = payload.get(key, [])
        if not isinstance(values, list):
            raise ValueError(f"intelligence {key} must be a list")
        for item in values:
            if not isinstance(item, dict):
                raise ValueError(f"every intelligence {key} item must be an object")
            if not isinstance(item.get(text_field), str) or not item[text_field].strip():
                raise ValueError(f"intelligence {key}.{text_field} is required")
            required_evidence_items.append(item)
    warnings = payload.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
        raise ValueError("intelligence warnings must be a list of strings")
    for item in required_evidence_items:
        confidence = item.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, int | float) or not 0 <= confidence <= 1
        ):
            raise ValueError("intelligence confidence must be between zero and one")
        unresolved = item.get("status") == "unresolved"
        evidence = item.get("evidence")
        if not isinstance(evidence, list):
            raise ValueError("material intelligence evidence must be a list")
        if not evidence and not unresolved:
            raise ValueError("material intelligence item lacks evidence or unresolved state")
        for citation in evidence:
            if not isinstance(citation, dict) or not {
                "recording_id",
                "transcript_version",
                "segment_id",
                "start_ms",
                "end_ms",
                "quote",
            }.issubset(citation):
                raise ValueError("evidence citation is incomplete")
            _validate_citation(citation, recording, transcript_version, index)


def _validate_citation(
    citation: dict[str, Any],
    recording: Recording,
    transcript_version: int,
    index: dict[str, TranscriptSegment],
) -> None:
    if not isinstance(citation.get("start_ms"), int) or not isinstance(citation.get("end_ms"), int):
        raise ValueError("citation timestamps must be integers")
    if not isinstance(citation.get("quote"), str) or not citation["quote"].strip():
        raise ValueError("citation quote is required")
    if citation.get("recording_id") != recording.id:
        raise ValueError("citation recording mismatch")
    if citation.get("transcript_version") != transcript_version:
        raise ValueError("citation transcript mismatch")
    source = index.get(citation["segment_id"])
    if source is None:
        raise ValueError("citation segment does not exist")
    if (
        citation["start_ms"] < source.start_ms
        or citation["end_ms"] > source.end_ms
        or citation["start_ms"] < 0
        or citation["end_ms"] <= citation["start_ms"]
    ):
        raise ValueError("citation is outside its source segment")
    if citation["quote"].casefold() not in source.text.casefold():
        raise ValueError("citation quote is not supported by source text")


def _rebuild_evidence(db: Session, recording: Recording, transcript: TranscriptVersion) -> None:
    db.execute(delete(EvidenceUnit).where(EvidenceUnit.recording_id == recording.id))
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcript_id == transcript.id)
        .order_by(TranscriptSegment.start_ms)
    ).all()
    for segment in segments:
        public_id = segment.id.split(":", 1)[1]
        citation = {
            "recording_id": recording.id,
            "transcript_version": transcript.version,
            "segment_id": public_id,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "speaker_id": segment.speaker_cluster_id,
            "quote": segment.text,
        }
        db.add(
            EvidenceUnit(
                id=f"{recording.id}:v{transcript.version}:{public_id}",
                workspace_id=recording.workspace_id,
                recording_id=recording.id,
                transcript_version=transcript.version,
                deletion_generation=recording.deletion_generation,
                speaker_id=segment.speaker_cluster_id,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=segment.text,
                text_normalized=normalize_text(segment.text),
                citation=citation,
            )
        )


def _utc_month_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or utcnow()
    start = datetime(current.year, current.month, 1, tzinfo=UTC)
    end = (
        datetime(current.year + 1, 1, 1, tzinfo=UTC)
        if current.month == 12
        else datetime(current.year, current.month + 1, 1, tzinfo=UTC)
    )
    return start, end


def reserve_budget(
    db: Session,
    *,
    attempt_id: str,
    workspace_id: str,
    stage: str,
    amount_usd: float,
    per_request_cap_usd: float,
    recording_id: str | None = None,
    ask_session_id: str | None = None,
    recording_cap_usd: float | None = None,
) -> BudgetReservation:
    """Atomically admit one provider attempt and reserve its worst-case spend.

    The caller must commit this reservation before dispatching the external
    request. Repeating the same attempt and parameters returns the same row.
    """

    if not attempt_id or len(attempt_id) > 160:
        raise ValueError("attempt_id must be 1-160 characters")
    if (
        amount_usd < 0
        or per_request_cap_usd < 0
        or (recording_cap_usd is not None and recording_cap_usd < 0)
    ):
        raise ValueError("budget amounts cannot be negative")

    existing = db.scalar(
        select(BudgetReservation)
        .where(BudgetReservation.attempt_id == attempt_id)
        .with_for_update()
    )
    if existing is not None:
        existing = _validate_reservation_replay(
            existing,
            workspace_id=workspace_id,
            stage=stage,
            amount_usd=amount_usd,
            recording_id=recording_id,
            ask_session_id=ask_session_id,
        )
        return _readmit_safe_reservation_replay(db, existing)
    if amount_usd > per_request_cap_usd + 1e-9:
        raise BudgetExceeded(
            "request_budget_exceeded",
            "Provider attempt exceeds its per-request spend ceiling.",
        )

    workspace = db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    if workspace is None:
        raise ValueError("workspace does not exist")
    # Recheck under the workspace lock so concurrent retries cannot create a
    # duplicate reservation on PostgreSQL.
    existing = db.scalar(
        select(BudgetReservation)
        .where(BudgetReservation.attempt_id == attempt_id)
        .with_for_update()
    )
    if existing is not None:
        existing = _validate_reservation_replay(
            existing,
            workspace_id=workspace_id,
            stage=stage,
            amount_usd=amount_usd,
            recording_id=recording_id,
            ask_session_id=ask_session_id,
        )
        return _readmit_safe_reservation_replay(db, existing)

    month_start, month_end = _utc_month_bounds()
    incurred = float(
        db.scalar(
            select(func.coalesce(func.sum(CostEvent.estimated_cost_usd), 0)).where(
                CostEvent.workspace_id == workspace_id,
                CostEvent.created_at >= month_start,
                CostEvent.created_at < month_end,
            )
        )
        or 0
    )
    reservation_rows = db.scalars(
        select(BudgetReservation).where(
            BudgetReservation.workspace_id == workspace_id,
            BudgetReservation.status.in_(
                [
                    "reserved",
                    "dispatching",
                    "committed",
                    "reconciliation_pending",
                ]
            ),
            BudgetReservation.created_at >= month_start,
            BudgetReservation.created_at < month_end,
        )
    ).all()
    ledger_attempts = set(
        db.scalars(
            select(CostEvent.attempt_id).where(
                CostEvent.workspace_id == workspace_id,
                CostEvent.created_at >= month_start,
                CostEvent.created_at < month_end,
            )
        ).all()
    )
    outstanding = sum(
        (float(item.committed_usd or 0) if item.status == "committed" else item.reserved_usd)
        for item in reservation_rows
        if item.attempt_id not in ledger_attempts
    )
    if incurred + outstanding + amount_usd > workspace.monthly_spend_limit_usd + 1e-9:
        raise BudgetExceeded(
            "workspace_monthly_budget_exceeded",
            "Provider attempt would exceed the workspace monthly spend ceiling.",
        )

    if recording_id is not None and recording_cap_usd is not None:
        recording_incurred = float(
            db.scalar(
                select(func.coalesce(func.sum(CostEvent.estimated_cost_usd), 0)).where(
                    CostEvent.recording_id == recording_id
                )
            )
            or 0
        )
        recording_ledger_attempts = set(
            db.scalars(
                select(CostEvent.attempt_id).where(CostEvent.recording_id == recording_id)
            ).all()
        )
        recording_reservations = db.scalars(
            select(BudgetReservation).where(
                BudgetReservation.recording_id == recording_id,
                BudgetReservation.status.in_(
                    [
                        "reserved",
                        "dispatching",
                        "committed",
                        "reconciliation_pending",
                    ]
                ),
            )
        ).all()
        recording_outstanding = sum(
            (float(item.committed_usd or 0) if item.status == "committed" else item.reserved_usd)
            for item in recording_reservations
            if item.attempt_id not in recording_ledger_attempts
        )
        if recording_incurred + recording_outstanding + amount_usd > recording_cap_usd + 1e-9:
            raise BudgetExceeded(
                "recording_budget_exceeded",
                "Provider attempt would exceed the recording spend ceiling.",
            )

    reservation = BudgetReservation(
        id=str(uuid.uuid4()),
        attempt_id=attempt_id,
        workspace_id=workspace_id,
        recording_id=recording_id,
        ask_session_id=ask_session_id,
        stage=stage,
        reserved_usd=amount_usd,
        status="reserved",
    )
    db.add(reservation)
    db.flush()
    return reservation


def _validate_reservation_replay(
    reservation: BudgetReservation,
    *,
    workspace_id: str,
    stage: str,
    amount_usd: float,
    recording_id: str | None,
    ask_session_id: str | None,
) -> BudgetReservation:
    expected = (
        workspace_id,
        stage,
        round(amount_usd, 9),
        recording_id,
        ask_session_id,
    )
    actual = (
        reservation.workspace_id,
        reservation.stage,
        round(reservation.reserved_usd, 9),
        reservation.recording_id,
        reservation.ask_session_id,
    )
    if actual != expected:
        raise ValueError("attempt_id was already reserved with different parameters")
    return reservation


def _readmit_safe_reservation_replay(
    db: Session, reservation: BudgetReservation
) -> BudgetReservation:
    """Return only attempts that are safe for the caller to dispatch again.

    A released zero-dollar fixture attempt can be re-armed after a failed HTTP
    request because it can never conceal provider spend. Non-zero released
    attempts require a fresh identity, while reconciliation-pending attempts
    remain a hard fence until an explicit reconciler settles them.
    """

    if reservation.status == "reconciliation_pending":
        raise BudgetReservationUnavailable(
            "budget_reconciliation_pending",
            "The prior provider outcome is ambiguous and must be reconciled before retrying.",
        )
    if reservation.status == "dispatching":
        raise BudgetReservationUnavailable(
            "budget_dispatch_outcome_unknown",
            "The prior provider call may already have been dispatched and cannot be replayed.",
        )
    if reservation.status == "released":
        if reservation.reserved_usd > 0:
            raise BudgetReservationUnavailable(
                "budget_attempt_requires_new_identity",
                "A released non-zero provider attempt cannot be dispatched with the same identity.",
            )
        reservation.status = "reserved"
        reservation.committed_usd = None
        reservation.release_reason = None
        db.flush()
    return reservation


def mark_budget_dispatched(db: Session, *, attempt_id: str) -> BudgetReservation:
    """Persist a non-replayable fence immediately before provider dispatch.

    If a process exits after this transaction commits, recovery treats the
    provider outcome as ambiguous instead of repeating a potentially billable
    call with the same business attempt identity.
    """

    reservation = db.scalar(
        select(BudgetReservation)
        .where(BudgetReservation.attempt_id == attempt_id)
        .with_for_update()
    )
    if reservation is None:
        raise ValueError("budget reservation does not exist")
    if reservation.status != "reserved":
        raise BudgetReservationUnavailable(
            "budget_dispatch_not_admitted",
            "The provider attempt is not in an admissible pre-dispatch state.",
        )
    reservation.status = "dispatching"
    reservation.release_reason = None
    db.flush()
    return reservation


def commit_budget(db: Session, *, attempt_id: str, actual_usd: float) -> BudgetReservation:
    if actual_usd < 0:
        raise ValueError("actual spend cannot be negative")
    reservation = db.scalar(
        select(BudgetReservation)
        .where(BudgetReservation.attempt_id == attempt_id)
        .with_for_update()
    )
    if reservation is None:
        raise ValueError("budget reservation does not exist")
    if actual_usd > reservation.reserved_usd + 1e-9:
        raise BudgetExceeded(
            "reservation_underestimated",
            "Actual provider spend exceeds the durable reservation.",
        )
    if reservation.status == "committed":
        if abs(float(reservation.committed_usd or 0) - actual_usd) > 1e-9:
            raise ValueError("budget reservation was committed with a different amount")
        return reservation
    if reservation.status not in {"reserved", "dispatching"}:
        raise ValueError(f"{reservation.status} budget reservation cannot be committed")
    reservation.status = "committed"
    reservation.committed_usd = actual_usd
    reservation.release_reason = None
    db.flush()
    return reservation


def release_budget(
    db: Session, *, attempt_id: str, reason: str = "provider_not_billed"
) -> BudgetReservation:
    reservation = db.scalar(
        select(BudgetReservation)
        .where(BudgetReservation.attempt_id == attempt_id)
        .with_for_update()
    )
    if reservation is None:
        raise ValueError("budget reservation does not exist")
    if reservation.status == "released":
        return reservation
    if reservation.status == "committed":
        raise ValueError("committed budget reservation cannot be released")
    reservation.status = "released"
    reservation.release_reason = reason[:160]
    db.flush()
    return reservation


def _release_if_reserved(db: Session, attempt_id: str, *, reason: str) -> None:
    reservation = db.scalar(
        select(BudgetReservation).where(BudgetReservation.attempt_id == attempt_id)
    )
    if reservation is not None and reservation.status == "reserved":
        release_budget(db, attempt_id=attempt_id, reason=reason)


def settle_run_reservations(
    db: Session,
    run_id: str,
    *,
    dispatched_attempts: set[str],
    reason: str,
) -> None:
    """Resolve every unfinished reservation owned by a processing run.

    Zero-cost fixture calls and attempts that never reached an adapter are
    safely released. A non-zero attempt that may have reached a provider stays
    charged against admission as an explicit reconciliation item.
    """

    for attempt_id in (f"speech:{run_id}", f"intelligence:{run_id}"):
        settle_interrupted_budget(
            db,
            attempt_id=attempt_id,
            provider_dispatched=attempt_id in dispatched_attempts,
            reason=reason,
        )


def settle_interrupted_budget(
    db: Session,
    *,
    attempt_id: str,
    provider_dispatched: bool,
    reason: str,
) -> None:
    reservation = db.scalar(
        select(BudgetReservation)
        .where(BudgetReservation.attempt_id == attempt_id)
        .with_for_update()
    )
    if reservation is None or reservation.status not in {"reserved", "dispatching"}:
        return
    durably_dispatched = reservation.status == "dispatching"
    if not (provider_dispatched or durably_dispatched) or reservation.reserved_usd <= 0:
        release_budget(db, attempt_id=attempt_id, reason=reason)
    else:
        reservation.status = "reconciliation_pending"
        reservation.release_reason = f"ambiguous_provider_outcome:{reason}"[:160]
        db.flush()


def _cost_once(
    db: Session,
    *,
    attempt_id: str,
    workspace_id: str,
    recording_id: str | None,
    stage: str,
    provider: str,
    model_alias: str,
    resolved_model: str,
    usage: dict[str, Any],
    estimated: float,
    provenance: dict[str, Any],
    ask_session_id: str | None = None,
) -> None:
    if db.scalar(select(CostEvent).where(CostEvent.attempt_id == attempt_id)) is not None:
        return
    db.add(
        CostEvent(
            id=str(uuid.uuid4()),
            attempt_id=attempt_id,
            workspace_id=workspace_id,
            recording_id=recording_id,
            ask_session_id=ask_session_id,
            stage=stage,
            provider=provider,
            model_alias=model_alias,
            resolved_model=resolved_model,
            price_catalog_version=str(
                provenance.get("price_catalog_version") or "mock-zero-cost.v1"
            ),
            usage=usage,
            estimated_cost_usd=estimated,
            reconciled_cost_usd=estimated if provenance.get("mock") is True else None,
            cache_reuse=False,
            provenance={
                **provenance,
                "usage_metered": provenance.get("mock") is not True,
                "invoice_reconciled": provenance.get("mock") is True,
            },
        )
    )


def _provider_actual_cost(provenance: dict[str, Any], usage: dict[str, Any] | None = None) -> float:
    value = provenance.get("estimated_cost_usd")
    if value is None and usage is not None:
        value = usage.get("estimated_cost_usd")
    if value is None and provenance.get("mock") is True:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ProviderUnavailable("Provider response omitted trustworthy cost attribution")
    return float(value)


def _ledger_billed_failure(
    db: Session,
    failure: ProviderBilledFailure,
    *,
    workspace_id: str,
    recording_id: str | None,
    stage: str,
    ask_session_id: str | None = None,
) -> None:
    _cost_once(
        db,
        attempt_id=failure.attempt_id,
        workspace_id=workspace_id,
        recording_id=recording_id,
        ask_session_id=ask_session_id,
        stage=stage,
        provider=failure.provider,
        model_alias=failure.model_alias,
        resolved_model=failure.resolved_model,
        usage=failure.usage,
        estimated=failure.estimated_cost_usd,
        provenance=failure.provenance,
    )
    commit_budget(
        db,
        attempt_id=failure.attempt_id,
        actual_usd=failure.estimated_cost_usd,
    )


def _segment_payload(segment: TranscriptSegment, version: int) -> dict[str, Any]:
    return {
        "id": segment.id.split(":", 1)[1],
        "start_ms": segment.start_ms,
        "end_ms": segment.end_ms,
        "language_bcp47": segment.language_bcp47,
        "speaker_cluster_id": segment.speaker_cluster_id,
        "speaker_display_name": segment.speaker_display_name,
        "speaker_name": segment.speaker_display_name,
        "overlap_group_id": segment.overlap_group_id,
        "text": segment.text,
        "confidence": segment.confidence,
        "transcript_version": version,
    }


def transcript_payload(db: Session, recording: Recording) -> dict[str, Any]:
    transcript = db.scalar(
        select(TranscriptVersion).where(
            TranscriptVersion.recording_id == recording.id,
            TranscriptVersion.is_current.is_(True),
        )
    )
    if transcript is None:
        return {
            "recording_id": recording.id,
            "ready": False,
            "error": (
                {"code": recording.error_code, "message": recording.error_detail}
                if recording.error_code
                else None
            ),
        }
    timeline = db.scalars(
        select(TimelineInterval)
        .where(TimelineInterval.transcript_id == transcript.id)
        .order_by(TimelineInterval.start_ms)
    ).all()
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcript_id == transcript.id)
        .order_by(TranscriptSegment.start_ms, TranscriptSegment.id)
    ).all()
    return {
        "recording_id": recording.id,
        "ready": True,
        "version": transcript.version,
        "language": recording.requested_language,
        "duration_ms": recording.duration_ms or 0,
        "intervals": [
            {
                "id": item.id.split(":", 1)[1],
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "state": item.state,
            }
            for item in timeline
        ],
        "segments": [_segment_payload(item, transcript.version) for item in segments],
        "speakers": _speaker_payload(segments),
        "provenance": {
            "source": transcript.source,
            "provider": transcript.provider,
            "model": transcript.model,
            "pipeline_version": transcript.pipeline_version,
            "prompt_version": transcript.prompt_version,
            "schema_version": transcript.schema_version,
            "policy_version": transcript.policy_version,
            "mock": transcript.provider.startswith("mock."),
        },
    }


def intelligence_payload(db: Session, recording: Recording) -> dict[str, Any]:
    intelligence = db.scalar(
        select(IntelligenceVersion).where(
            IntelligenceVersion.recording_id == recording.id,
            IntelligenceVersion.is_current.is_(True),
        )
    )
    if intelligence is None:
        return {
            "recording_id": recording.id,
            "ready": False,
            "error": (
                {"code": recording.error_code, "message": recording.error_detail}
                if recording.error_code
                else None
            ),
        }
    payload = json.loads(json.dumps(intelligence.payload))
    task_state = {
        item.task.strip().casefold(): item
        for item in db.scalars(
            select(ActionItem).where(ActionItem.recording_id == recording.id)
        ).all()
    }
    for action in payload.get("actions", []):
        task = task_state.get(str(action.get("task", "")).strip().casefold())
        if task is not None:
            action["status"] = task.status
            action["task_version"] = task.version
    return {
        "recording_id": recording.id,
        "ready": True,
        "version": intelligence.version,
        "transcript_version": intelligence.transcript_version,
        **payload,
        "summary_style": recording.summary_style,
        "provenance": intelligence.provenance,
    }


def _speaker_payload(segments: list[TranscriptSegment]) -> list[dict[str, Any]]:
    speakers: dict[str, dict[str, Any]] = {}
    for item in segments:
        if not item.speaker_cluster_id:
            continue
        current = speakers.setdefault(
            item.speaker_cluster_id,
            {
                "id": item.speaker_cluster_id,
                "label": item.speaker_cluster_id.replace("speaker-", "Speaker ").title(),
                "display_name": item.speaker_display_name,
                "segment_count": 0,
            },
        )
        current["segment_count"] += 1
        if item.speaker_display_name:
            current["display_name"] = item.speaker_display_name
    return list(speakers.values())


def clone_transcript_with_edit(
    db: Session,
    recording: Recording,
    *,
    expected_version: int,
    segment_id: str | None = None,
    replacement_text: str | None = None,
    speaker_id: str | None = None,
    display_name: str | None = None,
    merge_into: str | None = None,
) -> TranscriptVersion:
    current = db.scalar(
        select(TranscriptVersion).where(
            TranscriptVersion.recording_id == recording.id,
            TranscriptVersion.is_current.is_(True),
        )
    )
    if current is None or current.version != expected_version:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="Transcript version changed; refresh first")
    prior_intelligence = db.scalar(
        select(IntelligenceVersion).where(
            IntelligenceVersion.recording_id == recording.id,
            IntelligenceVersion.is_current.is_(True),
        )
    )
    timeline = db.scalars(
        select(TimelineInterval)
        .where(TimelineInterval.transcript_id == current.id)
        .order_by(TimelineInterval.start_ms)
    ).all()
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcript_id == current.id)
        .order_by(TranscriptSegment.start_ms, TranscriptSegment.id)
    ).all()
    public_ids = {item.id.split(":", 1)[1] for item in segments}
    if segment_id is not None and segment_id not in public_ids:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Transcript segment not found")
    if speaker_id is not None and speaker_id not in {item.speaker_cluster_id for item in segments}:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Speaker not found")
    new_version = current.version + 1
    current.is_current = False
    clone = TranscriptVersion(
        id=str(uuid.uuid4()),
        recording_id=recording.id,
        workspace_id=recording.workspace_id,
        version=new_version,
        source="manual_correction" if segment_id else "manual_speaker_edit",
        provider=current.provider,
        model=current.model,
        pipeline_version=current.pipeline_version,
        schema_version=current.schema_version,
        prompt_version="none",
        policy_version=current.policy_version,
    )
    db.add(clone)
    db.flush()
    for item in timeline:
        public_id = item.id.split(":", 1)[1]
        db.add(
            TimelineInterval(
                id=f"{clone.id}:{public_id}",
                transcript_id=clone.id,
                recording_id=recording.id,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                state=item.state,
            )
        )
    for item in segments:
        public_id = item.id.split(":", 1)[1]
        new_speaker = item.speaker_cluster_id
        new_display = item.speaker_display_name
        if segment_id == public_id:
            text = replacement_text
        else:
            text = item.text
        if speaker_id == item.speaker_cluster_id:
            if merge_into:
                new_speaker = merge_into
                new_display = None
            else:
                new_display = display_name
        db.add(
            TranscriptSegment(
                id=f"{clone.id}:{public_id}",
                transcript_id=clone.id,
                recording_id=recording.id,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                language_bcp47=item.language_bcp47,
                speaker_cluster_id=new_speaker,
                speaker_display_name=new_display,
                overlap_group_id=item.overlap_group_id,
                text=text,
                confidence=item.confidence,
            )
        )
    recording.transcript_version = new_version
    recording.etag_version += 1
    db.flush()
    if prior_intelligence is None:
        _publish_safe_extractive_intelligence(db, recording, clone)
    else:
        _publish_revalidated_intelligence(
            db,
            recording,
            clone,
            prior_intelligence,
            edited_segment_id=segment_id,
            edited_speaker_id=speaker_id,
            merged_into=merge_into,
            speaker_display_name=display_name,
        )
    _rebuild_evidence(db, recording, clone)
    recording.transcript_ready = True
    recording.intelligence_ready = True
    recording.indexed_ready = True
    recording.status = "READY"
    recording.stage = "ready"
    invalidate_dependent_views(db, recording)
    emit_event(db, recording, "artifact.invalidated", {"from_transcript_version": expected_version})
    emit_event(db, recording, "transcript.finalized", {"version": new_version, "manual": True})
    emit_event(db, recording, "intelligence.finalized", {"version": recording.intelligence_version})
    emit_event(db, recording, "evidence.indexed", {"version": new_version})
    return clone


def invalidate_dependent_views(db: Session, recording: Recording) -> None:
    """Invalidate workspace views whose persisted citations may now be stale."""

    # A recording can change a positive answer, a count, or a prior abstention.
    # Without a full dependency table the safe demo policy is workspace-wide.
    db.execute(delete(AskMessage).where(AskMessage.workspace_id == recording.workspace_id))
    # Recaps are cheap deterministic projections; invalidate them conservatively.
    db.execute(delete(Recap).where(Recap.workspace_id == recording.workspace_id))
    idempotency_rows = db.scalars(
        select(IdempotencyRecord).where(IdempotencyRecord.workspace_id == recording.workspace_id)
    ).all()
    for item in idempotency_rows:
        # Durable command idempotency (upload/complete/retry/mutations) must
        # survive projection invalidation.  Only cached derived views are
        # invalidated workspace-wide.
        if item.operation.startswith(("ask-message:", "recap:")):
            db.delete(item)


def _publish_revalidated_intelligence(
    db: Session,
    recording: Recording,
    transcript: TranscriptVersion,
    prior: IntelligenceVersion,
    *,
    edited_segment_id: str | None,
    edited_speaker_id: str | None,
    merged_into: str | None,
    speaker_display_name: str | None,
) -> IntelligenceVersion:
    """Rebase grounded projections without inventing replacement claims.

    Speaker-only changes preserve every material item and update its citation
    metadata.  A text correction retains only items whose evidence did not use
    the edited segment; affected material is removed and disclosed for later
    review.  The title/summary are rebuilt extractively when their source text
    changed.
    """

    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcript_id == transcript.id)
        .order_by(TranscriptSegment.start_ms)
    ).all()
    segment_index = {item.id.split(":", 1)[1]: item for item in segments}
    payload = json.loads(json.dumps(prior.payload))

    def rebase(citation: dict[str, Any]) -> None:
        segment = segment_index.get(str(citation.get("segment_id", "")))
        if segment is None:
            return
        citation.update(
            {
                "recording_id": recording.id,
                "transcript_version": transcript.version,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "speaker_id": segment.speaker_cluster_id,
                "quote": segment.text,
            }
        )

    removed = 0
    for key in ("facts", "decisions", "actions", "topics", "participants", "open_questions"):
        retained = []
        for item in payload.get(key, []):
            evidence = item.get("evidence", []) if isinstance(item, dict) else []
            if edited_segment_id and any(
                citation.get("segment_id") == edited_segment_id for citation in evidence
            ):
                removed += 1
                continue
            for citation in evidence:
                rebase(citation)
            retained.append(item)
        payload[key] = retained

    if edited_segment_id:
        citations = []
        for segment in segments[:4]:
            citations.append(
                {
                    "recording_id": recording.id,
                    "transcript_version": transcript.version,
                    "segment_id": segment.id.split(":", 1)[1],
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "speaker_id": segment.speaker_cluster_id,
                    "quote": segment.text,
                }
            )
        first = segments[0].text if segments else "Untitled recording"
        combined = " ".join(item.text for item in segments[:4])
        payload["title"] = {
            "text": first[:100],
            "evidence": citations[:1],
            "confidence": 1.0,
        }
        payload["summary"] = {
            "short": combined[:500],
            "detailed": combined[:2000],
            "evidence": citations,
        }
    else:
        for citation in _walk_citations(payload):
            rebase(citation)

    if edited_speaker_id:
        replacement = merged_into or edited_speaker_id
        for key in ("facts", "decisions", "actions", "topics", "open_questions"):
            for item in payload.get(key, []):
                if isinstance(item.get("participants"), list):
                    item["participants"] = list(
                        dict.fromkeys(
                            replacement if value == edited_speaker_id else value
                            for value in item["participants"]
                        )
                    )
        merged_participants: dict[str, dict[str, Any]] = {}
        for participant in payload.get("participants", []):
            cluster_id = participant.get("speaker_cluster_id")
            if cluster_id == edited_speaker_id:
                cluster_id = replacement
            if not cluster_id:
                continue
            participant["speaker_cluster_id"] = cluster_id
            live_names = {
                item.speaker_display_name
                for item in segments
                if item.speaker_cluster_id == cluster_id and item.speaker_display_name
            }
            if live_names:
                participant["display_name"] = sorted(live_names)[0]
            elif cluster_id == edited_speaker_id and speaker_display_name:
                participant["display_name"] = speaker_display_name
            current = merged_participants.get(cluster_id)
            if current is None:
                merged_participants[cluster_id] = participant
                continue
            current["evidence"] = list(
                {
                    citation["segment_id"]: citation
                    for citation in [
                        *(current.get("evidence") or []),
                        *(participant.get("evidence") or []),
                    ]
                }.values()
            )
            current["confidence"] = max(
                float(current.get("confidence", 0)),
                float(participant.get("confidence", 0)),
            )
            current["display_name"] = current.get("display_name") or participant.get("display_name")
        payload["participants"] = list(merged_participants.values())

    warnings = list(payload.get("warnings", []))
    if removed:
        warnings.append(
            f"{removed} intelligence item(s) whose evidence changed were removed for review."
        )
    warnings.append("Grounded projections were deterministically revalidated after a manual edit.")
    payload["warnings"] = list(dict.fromkeys(warnings))
    provenance = {
        **(prior.provenance or {}),
        "mock": True,
        "source": "deterministic_manual_edit_revalidation",
        "llm_called": False,
        "based_on_intelligence_version": prior.version,
    }
    intelligence = _publish_intelligence(db, recording, transcript.version, payload, provenance)
    recording.intelligence_version = intelligence.version
    return intelligence


def _safe_extractive_intelligence_values(
    db: Session, recording: Recording, transcript: TranscriptVersion
) -> tuple[dict[str, Any], dict[str, Any]]:
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcript_id == transcript.id)
        .order_by(TranscriptSegment.start_ms)
    ).all()
    citations = []
    for item in segments[:4]:
        citations.append(
            {
                "recording_id": recording.id,
                "transcript_version": transcript.version,
                "segment_id": item.id.split(":", 1)[1],
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "speaker_id": item.speaker_cluster_id,
                "quote": item.text,
            }
        )
    first = segments[0].text if segments else "Untitled recording"
    combined = " ".join(item.text for item in segments[:4])
    payload = {
        "title": {"text": first[:100], "evidence": citations[:1], "confidence": 1.0},
        "summary": {"short": combined[:500], "detailed": combined[:2000], "evidence": citations},
        "facts": [],
        "decisions": [],
        "actions": [],
        "topics": [],
        "participants": [],
        "open_questions": [],
        "warnings": [
            "Only an extractive summary was rebuilt after the manual edit; no LLM was configured."
        ],
    }
    provenance = {
        "mock": True,
        "source": "deterministic_extractive_rebuild",
        "provider": "mock.local",
        "model_alias": "llm.none",
        "resolved_model": "extractive-v1",
        "provider_request_id": None,
        "pipeline_version": "correction-rebuild.v1",
        "prompt_version": "none",
        "schema_version": "RecordingIntelligence.v1",
        "policy_version": "demo-policy.v1",
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    return payload, provenance


def _publish_safe_extractive_intelligence(
    db: Session, recording: Recording, transcript: TranscriptVersion
) -> IntelligenceVersion:
    payload, provenance = _safe_extractive_intelligence_values(db, recording, transcript)
    intelligence = _publish_intelligence(db, recording, transcript.version, payload, provenance)
    recording.intelligence_version = intelligence.version
    return intelligence


def regenerate_intelligence(
    db: Session,
    recording: Recording,
    llm: LLMAdapter,
    summary_style: str,
    request_id: str,
    budget_usd: float,
    *,
    deep: bool = False,
) -> IntelligenceVersion:
    transcript = db.scalar(
        select(TranscriptVersion).where(
            TranscriptVersion.recording_id == recording.id,
            TranscriptVersion.is_current.is_(True),
        )
    )
    if transcript is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="A canonical transcript is required")
    segments = db.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcript_id == transcript.id)
        .order_by(TranscriptSegment.start_ms)
    ).all()
    values = [_segment_payload(item, transcript.version) for item in segments]
    prior = db.scalar(
        select(IntelligenceVersion).where(
            IntelligenceVersion.recording_id == recording.id,
            IntelligenceVersion.is_current.is_(True),
        )
    )
    expected_generation = recording.deletion_generation
    expected_transcript_id = transcript.id
    expected_transcript_version = transcript.version
    expected_intelligence_id = prior.id if prior is not None else None
    expected_intelligence_version = recording.intelligence_version
    intelligence: IntelligenceVersion | None = None
    estimate_intelligence = getattr(llm, "estimate_intelligence_reservation", None)
    regeneration_reservation = (
        estimate_intelligence(
            recording_id=recording.id,
            transcript_version=transcript.version,
            segments=values,
            budget_usd=budget_usd,
            deep=deep,
        )
        if callable(estimate_intelligence)
        else 0.0
    )
    reserve_budget(
        db,
        attempt_id=request_id,
        workspace_id=recording.workspace_id,
        recording_id=recording.id,
        stage="regenerate_intelligence",
        amount_usd=regeneration_reservation,
        per_request_cap_usd=budget_usd,
        recording_cap_usd=budget_usd,
    )
    mark_budget_dispatched(db, attempt_id=request_id)
    db.commit()
    provider_dispatched = False
    try:
        provider_dispatched = True
        payload, provenance = llm.extract_intelligence(
            recording_id=recording.id,
            transcript_version=transcript.version,
            segments=values,
            request_id=request_id,
            budget_usd=regeneration_reservation,
            deep=deep,
        )
    except ProviderUnavailable as failure:
        if isinstance(failure, ProviderBilledFailure):
            db.rollback()
            _ledger_billed_failure(
                db,
                failure,
                workspace_id=recording.workspace_id,
                recording_id=recording.id,
                stage="regenerate_intelligence",
            )
            db.commit()
            raise
        if regeneration_reservation > 0:
            db.rollback()
            settle_interrupted_budget(
                db,
                attempt_id=request_id,
                provider_dispatched=provider_dispatched,
                reason="regeneration_provider_unavailable",
            )
            db.commit()
            raise
        if prior is None:
            payload, provenance = _safe_extractive_intelligence_values(db, recording, transcript)
        else:
            payload = json.loads(json.dumps(prior.payload))
            provenance = {
                **(prior.provenance or {}),
                "mock": True,
                "source": "deterministic_existing_evidence_regeneration",
                "llm_called": False,
                "based_on_intelligence_version": prior.version,
            }
            intelligence = None
    except Exception:
        db.rollback()
        settle_interrupted_budget(
            db,
            attempt_id=request_id,
            provider_dispatched=provider_dispatched,
            reason="regeneration_provider_exception",
        )
        db.commit()
        raise

    # The reservation commit deliberately released the route's initial row
    # lock before provider work. Reacquire it and prove that the exact source
    # snapshot is still current before publishing anything derived from it.
    db.expire_all()
    current_recording = db.scalar(
        select(Recording).where(Recording.id == recording.id).with_for_update()
    )
    current_transcript = db.scalar(
        select(TranscriptVersion).where(
            TranscriptVersion.recording_id == recording.id,
            TranscriptVersion.is_current.is_(True),
        )
    )
    current_intelligence = db.scalar(
        select(IntelligenceVersion).where(
            IntelligenceVersion.recording_id == recording.id,
            IntelligenceVersion.is_current.is_(True),
        )
    )
    source_is_stale = (
        current_recording is None
        or current_recording.deleted_at is not None
        or current_recording.cancel_requested
        or current_recording.deletion_generation != expected_generation
        or current_recording.transcript_version != expected_transcript_version
        or current_recording.intelligence_version != expected_intelligence_version
        or current_transcript is None
        or current_transcript.id != expected_transcript_id
        or (current_intelligence.id if current_intelligence is not None else None)
        != expected_intelligence_id
    )
    if source_is_stale:
        settle_interrupted_budget(
            db,
            attempt_id=request_id,
            provider_dispatched=provider_dispatched,
            reason="regeneration_source_changed",
        )
        db.commit()
        raise StaleGeneration("Recording changed while intelligence was being regenerated")
    recording = current_recording
    transcript = current_transcript
    if summary_style == "brief":
        payload["summary"]["detailed"] = payload["summary"]["short"]
    elif summary_style == "action_focused":
        tasks = "; ".join(item["task"] for item in payload.get("actions", []))
        if tasks:
            payload["summary"]["short"] = tasks
    provenance = dict(provenance)
    provenance["summary_style"] = summary_style
    provenance["deep_requested"] = deep
    if intelligence is None:
        intelligence = _publish_intelligence(db, recording, transcript.version, payload, provenance)
    else:
        # The safe extractive fallback was already published; replace whole
        # JSON values so SQLAlchemy persists style/provenance changes.
        intelligence.payload = payload
        intelligence.provenance = provenance
    _cost_once(
        db,
        attempt_id=request_id,
        workspace_id=recording.workspace_id,
        recording_id=recording.id,
        ask_session_id=None,
        stage="regenerate_intelligence",
        provider=provenance.get("provider", "mock.local"),
        model_alias=provenance.get("model_alias", "llm.none"),
        resolved_model=provenance.get("resolved_model", "deterministic-existing-evidence-v1"),
        usage=provenance.get("usage", {"input_tokens": 0, "output_tokens": 0}),
        estimated=_provider_actual_cost(provenance),
        provenance=provenance,
    )
    commit_budget(
        db,
        attempt_id=request_id,
        actual_usd=_provider_actual_cost(provenance),
    )
    recording.intelligence_version = intelligence.version
    recording.intelligence_ready = True
    recording.summary_style = summary_style
    recording.etag_version += 1
    emit_event(db, recording, "intelligence.finalized", {"version": intelligence.version})
    return intelligence


TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "did",
    "do",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "the",
    "to",
    "was",
    "we",
    "what",
    "when",
    "who",
}


def normalize_text(value: str) -> str:
    return " ".join(TOKEN_PATTERN.findall(value.casefold()))


def query_terms(value: str) -> list[str]:
    terms = []
    for token in TOKEN_PATTERN.findall(value.casefold()):
        if token in STOP_WORDS:
            continue
        if len(token) > 5 and token.endswith("ing"):
            token = token[:-3]
        elif len(token) > 4 and token.endswith("ed"):
            token = token[:-2]
        elif len(token) > 4 and token.endswith("s"):
            token = token[:-1]
        terms.append(token)
        if token == "vendor":
            terms.append("provider")
        elif token == "provider":
            terms.append("vendor")
    return terms


def _looks_like_untrusted_instruction(text: str) -> bool:
    normalized = normalize_text(text)
    targets = ("ask pocket", "assistant", "language model", "system prompt")
    directives = (
        "should answer",
        "must answer",
        "ignore instructions",
        "ignore the instructions",
        "abstain if",
        "respond with",
        "do not answer",
    )
    return any(target in normalized for target in targets) and any(
        directive in normalized for directive in directives
    )


def _sanitize_untrusted_instructions(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(
        sentence for sentence in sentences if not _looks_like_untrusted_instruction(sentence)
    ).strip()


def search_evidence(
    db: Session,
    workspace_id: str,
    query: str,
    *,
    recording_ids: list[str] | None = None,
    speaker: str | None = None,
    speaker_ids: list[str] | None = None,
    segment_ids: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    statement = (
        select(EvidenceUnit, Recording)
        .join(Recording, Recording.id == EvidenceUnit.recording_id)
        .where(
            EvidenceUnit.workspace_id == workspace_id,
            Recording.workspace_id == workspace_id,
            Recording.deleted_at.is_(None),
            Recording.indexed_ready.is_(True),
            EvidenceUnit.deletion_generation == Recording.deletion_generation,
        )
    )
    if recording_ids:
        statement = statement.where(EvidenceUnit.recording_id.in_(recording_ids))
    if speaker_ids:
        statement = statement.where(EvidenceUnit.speaker_id.in_(speaker_ids))
    elif speaker:
        statement = statement.where(EvidenceUnit.speaker_id == speaker)
    rows = db.execute(statement).all()
    terms = query_terms(query)
    phrase = normalize_text(query)
    scored = []
    allowed_segment_ids = set(segment_ids or [])
    for evidence, recording in rows:
        if allowed_segment_ids and evidence.citation.get("segment_id") not in allowed_segment_ids:
            continue
        normalized = evidence.text_normalized
        term_score = sum(1 for term in terms if term in normalized)
        phrase_bonus = 2 if phrase and phrase in normalized else 0
        if not terms:
            term_score = 1 if phrase in normalized else 0
        score = term_score + phrase_bonus
        if score:
            scored.append(
                {
                    "id": evidence.id,
                    "recording": {"id": recording.id, "display_name": recording.display_name},
                    "snippet": evidence.text,
                    "score": score,
                    "citation": evidence.citation,
                    "match_type": "lexical",
                }
            )
    scored.sort(key=lambda item: (-item["score"], item["citation"]["start_ms"], item["id"]))
    return scored[:limit]


def answer_question(
    db: Session,
    *,
    ask_session_id: str,
    workspace_id: str,
    question: str,
    recording_ids: list[str],
    selection_segment_ids: list[str] | None = None,
    budget_usd: float = 0.10,
    llm: LLMAdapter | None = None,
    deep: bool = False,
) -> AskMessage:
    structured = None
    if not selection_segment_ids and not deep:
        structured = _structured_answer(
            db, workspace_id=workspace_id, question=question, recording_ids=recording_ids
        )
    if structured is not None:
        answer, citations, strategy = structured
        results = [{"citation": item} for item in citations]
    else:
        results = []
        for item in search_evidence(
                db,
                workspace_id,
                question,
                recording_ids=recording_ids or None,
                segment_ids=selection_segment_ids,
                limit=8,
            ):
            sanitized = _sanitize_untrusted_instructions(item["snippet"])
            if sanitized:
                results.append({**item, "snippet": sanitized})
            if len(results) == 3:
                break
        answer = ""
        citations = []
        strategy = "deterministic_lexical_extractive"
    message_id = str(uuid.uuid4())
    ask_attempt_id = f"ask:{message_id}"
    provider_result = None
    reservation_amount = 0.0
    provider_dispatched = False
    if results and structured is None and llm is not None:
        ask_request = AskRequest(
            question=question,
            evidence=results,
            request_id=ask_attempt_id,
            budget_usd=budget_usd,
            deep=deep,
        )
        estimate_ask = getattr(llm, "estimate_ask_reservation", None)
        reservation_amount = estimate_ask(ask_request) if callable(estimate_ask) else 0.0
        if reservation_amount == 0:
            try:
                provider_result = llm.answer(ask_request)
            except ProviderUnavailable:
                # A zero-cost local adapter may decline a question; the
                # conservative extractive fallback below remains available.
                provider_result = None
        if reservation_amount > 0:
            retrieved_recording_ids = {
                str(item["citation"]["recording_id"])
                for item in results
                if isinstance(item.get("citation"), dict)
                and item["citation"].get("recording_id")
            }
            source_rows = db.scalars(
                select(Recording).where(
                    Recording.workspace_id == workspace_id,
                    Recording.deleted_at.is_(None),
                    Recording.indexed_ready.is_(True),
                    Recording.id.in_(retrieved_recording_ids),
                )
            ).all()
            if {item.id for item in source_rows} != retrieved_recording_ids or any(
                not item.provider_data_approved for item in source_rows
            ):
                raise ProviderDataPolicyDenied(
                    "Remote Ask requires persisted data-policy approval for every evidence source."
                )
            source_snapshot = {
                item.id: (
                    item.deletion_generation,
                    item.transcript_version,
                    item.intelligence_version,
                    item.provider_data_approved,
                )
                for item in source_rows
            }
            reserve_budget(
                db,
                attempt_id=ask_attempt_id,
                workspace_id=workspace_id,
                ask_session_id=ask_session_id,
                stage="ask",
                amount_usd=reservation_amount,
                per_request_cap_usd=budget_usd,
            )
            mark_budget_dispatched(db, attempt_id=ask_attempt_id)
            db.commit()
            try:
                provider_dispatched = True
                provider_result = llm.answer(
                    AskRequest(
                        question=question,
                        evidence=results,
                        request_id=ask_attempt_id,
                        budget_usd=reservation_amount,
                        deep=deep,
                    )
                )
            except Exception as failure:
                db.rollback()
                if isinstance(failure, ProviderBilledFailure):
                    _ledger_billed_failure(
                        db,
                        failure,
                        workspace_id=workspace_id,
                        recording_id=None,
                        ask_session_id=ask_session_id,
                        stage="ask",
                    )
                else:
                    settle_interrupted_budget(
                        db,
                        attempt_id=ask_attempt_id,
                        provider_dispatched=provider_dispatched,
                        reason="ask_provider_exception",
                    )
                db.commit()
                raise
            current_rows = db.scalars(
                select(Recording)
                .where(
                    Recording.workspace_id == workspace_id,
                    Recording.deleted_at.is_(None),
                    Recording.indexed_ready.is_(True),
                    Recording.id.in_(retrieved_recording_ids),
                )
                .with_for_update()
            ).all()
            current_snapshot = {
                item.id: (
                    item.deletion_generation,
                    item.transcript_version,
                    item.intelligence_version,
                    item.provider_data_approved,
                )
                for item in current_rows
            }
            if current_snapshot != source_snapshot:
                actual = _provider_actual_cost(provider_result.provenance)
                _cost_once(
                    db,
                    attempt_id=ask_attempt_id,
                    workspace_id=workspace_id,
                    recording_id=None,
                    ask_session_id=ask_session_id,
                    stage="ask",
                    provider=provider_result.provenance.get("provider", "google.gemini"),
                    model_alias=provider_result.provenance.get("model_alias", "llm.unknown"),
                    resolved_model=provider_result.provenance.get("resolved_model", "unknown"),
                    usage=provider_result.provenance.get("usage", {}),
                    estimated=actual,
                    provenance={**provider_result.provenance, "publication": "source_changed"},
                )
                commit_budget(db, attempt_id=ask_attempt_id, actual_usd=actual)
                db.commit()
                raise StaleGeneration("Ask evidence changed while the provider was answering")
    if structured is not None:
        abstained = False
    elif provider_result is not None:
        citations = provider_result.citations
        answer = provider_result.answer
        abstained = provider_result.abstained
        strategy = "gemini_grounded_evidence"
    elif results:
        citations = [item["citation"] for item in results]
        quotes = [f"“{item['snippet']}”" for item in results]
        answer = "The available evidence says: " + " ".join(quotes)
        abstained = False
    else:
        citations = []
        answer = "I don't have enough accessible evidence in this scope to answer that question."
        abstained = True
    provenance = (
        {**provider_result.provenance, "strategy": strategy}
        if provider_result is not None
        else {
            "mock": True,
            "strategy": strategy,
            "llm_called": False,
            "deep_requested": deep,
            "grounding_validation": "passed" if results else "abstained_no_evidence",
        }
    )
    message = AskMessage(
        id=message_id,
        ask_session_id=ask_session_id,
        workspace_id=workspace_id,
        question=question,
        answer=answer,
        citations=citations,
        abstained=abstained,
        provenance=provenance,
    )
    db.add(message)
    if reservation_amount == 0:
        reserve_budget(
            db,
            attempt_id=ask_attempt_id,
            workspace_id=workspace_id,
            ask_session_id=ask_session_id,
            stage="ask",
            amount_usd=0.0,
            per_request_cap_usd=budget_usd,
        )
    actual_cost = _provider_actual_cost(provenance)
    _cost_once(
        db,
        attempt_id=ask_attempt_id,
        workspace_id=workspace_id,
        recording_id=None,
        ask_session_id=ask_session_id,
        stage="ask",
        provider=provenance.get("provider", "mock.local"),
        model_alias=provenance.get("model_alias", "llm.none"),
        resolved_model=provenance.get("resolved_model", "deterministic-lexical-extractive-v1"),
        usage={
            **provenance.get("usage", {"input_tokens": 0, "output_tokens": 0}),
            "retrieved_units": len(results),
        },
        estimated=actual_cost,
        provenance=provenance,
    )
    commit_budget(db, attempt_id=ask_attempt_id, actual_usd=actual_cost)
    return message


def _structured_answer(
    db: Session,
    *,
    workspace_id: str,
    question: str,
    recording_ids: list[str],
) -> tuple[str, list[dict[str, Any]], str] | None:
    normalized = normalize_text(question)
    scope = list(recording_ids)
    recording_query = select(Recording).where(
        Recording.workspace_id == workspace_id,
        Recording.deleted_at.is_(None),
        Recording.intelligence_ready.is_(True),
    )
    if scope:
        recording_query = recording_query.where(Recording.id.in_(scope))
    recordings = db.scalars(recording_query).all()
    if not recordings:
        return None
    scoped_ids = [item.id for item in recordings]
    intelligence_rows = db.scalars(
        select(IntelligenceVersion).where(
            IntelligenceVersion.workspace_id == workspace_id,
            IntelligenceVersion.recording_id.in_(scoped_ids),
            IntelligenceVersion.is_current.is_(True),
        )
    ).all()
    if "how many" in normalized and "action" in normalized:
        task_query = select(ActionItem).where(
            ActionItem.workspace_id == workspace_id,
            ActionItem.recording_id.in_(scoped_ids),
        )
        if "open" in normalized:
            task_query = task_query.where(ActionItem.status == "open")
        tasks = db.scalars(task_query).all()
        citations = [citation for item in tasks for citation in item.evidence]
        noun = "action item" if len(tasks) == 1 else "action items"
        return (
            f"There {_is_are(len(tasks))} {_number_word(len(tasks))} matching {noun}.",
            citations,
            "structured_sql_actions_count",
        )

    live_tasks = db.scalars(
        select(ActionItem).where(
            ActionItem.workspace_id == workspace_id,
            ActionItem.recording_id.in_(scoped_ids),
        )
    ).all()
    if "how many" in normalized and "decision" in normalized:
        decisions = [
            item
            for intelligence in intelligence_rows
            for item in intelligence.payload.get("decisions", [])
        ]
        citations = [citation for item in decisions for citation in item.get("evidence", [])]
        noun = "decision" if len(decisions) == 1 else "decisions"
        return (
            f"There {_is_are(len(decisions))} {_number_word(len(decisions))} recorded {noun}.",
            citations,
            "structured_projection_decisions_count",
        )

    if "how many" in normalized and "speaker" in normalized:
        transcripts = db.scalars(
            select(TranscriptVersion).where(
                TranscriptVersion.workspace_id == workspace_id,
                TranscriptVersion.recording_id.in_(scoped_ids),
                TranscriptVersion.is_current.is_(True),
            )
        ).all()
        transcript_ids = [item.id for item in transcripts]
        segments = (
            db.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.transcript_id.in_(transcript_ids))
                .order_by(TranscriptSegment.start_ms)
            ).all()
            if transcript_ids
            else []
        )
        by_speaker: dict[tuple[str, str], TranscriptSegment] = {}
        for segment in segments:
            if segment.speaker_cluster_id:
                by_speaker.setdefault((segment.recording_id, segment.speaker_cluster_id), segment)
        citations = []
        version_by_id = {item.id: item.version for item in transcripts}
        for segment in by_speaker.values():
            citations.append(
                {
                    "recording_id": segment.recording_id,
                    "transcript_version": version_by_id[segment.transcript_id],
                    "segment_id": segment.id.split(":", 1)[1],
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "speaker_id": segment.speaker_cluster_id,
                    "quote": segment.text,
                }
            )
        count = len(by_speaker)
        noun = "cluster" if count == 1 else "clusters"
        return (
            f"The transcript contains {_number_word(count)} anonymous speaker {noun}.",
            citations,
            "structured_sql_speaker_count",
        )

    actions = [
        item
        for intelligence in intelligence_rows
        for item in intelligence.payload.get("actions", [])
    ]
    decisions = [
        item
        for intelligence in intelligence_rows
        for item in intelligence.payload.get("decisions", [])
    ]
    facts = [
        item for intelligence in intelligence_rows for item in intelligence.payload.get("facts", [])
    ]

    if "action" in normalized and "status" in normalized and live_tasks:
        task = live_tasks[0]
        return (
            f"The action item's status is {task.status}.",
            task.evidence,
            "structured_sql_action_status",
        )
    if "unresolved" in normalized and "decision" in normalized:
        unresolved_decisions = [item for item in decisions if item.get("status") == "unresolved"]
        if unresolved_decisions:
            citations = [
                citation for item in unresolved_decisions for citation in item.get("evidence", [])
            ]
            return (
                " ".join(item["decision"] for item in unresolved_decisions),
                citations,
                "structured_projection_unresolved_decisions",
            )
        citations = [citation for item in decisions for citation in item.get("evidence", [])]
        return (
            "There are no unresolved decisions in the accessible evidence.",
            citations,
            "structured_projection_unresolved_decisions_none",
        )
    action_ambiguity_intent = "timing" in normalized or (
        "unresolved" in normalized
        and any(term in normalized for term in ("action", "task", "deadline", "due"))
    )
    if action_ambiguity_intent and actions:
        item = actions[0]
        ambiguities = item.get("ambiguities", [])
        if ambiguities:
            return (
                "The unresolved timing details are: " + " ".join(ambiguities),
                item.get("evidence", []),
                "structured_projection_action_ambiguities",
            )
    if (
        any(
            term in normalized
            for term in ("next step", "responsible", "owns", "expected to prepare", "checklist due")
        )
        and actions
    ):
        item = actions[0]
        parts = [item["task"]]
        if item.get("owner_text"):
            parts.append(f"Owner: {item['owner_text']}.")
        if item.get("due_text"):
            parts.append(f"Due: {item['due_text']}.")
        return " ".join(parts), item.get("evidence", []), "structured_projection_action"
    if ("decision" in normalized or "browser based" in normalized) and decisions:
        item = decisions[0]
        return item["decision"], item.get("evidence", []), "structured_projection_decision"
    if any(term in normalized for term in ("mainly about", "project recap", "brief recap")):
        summaries = [item.payload.get("summary", {}) for item in intelligence_rows]
        if summaries:
            citations = [
                citation
                for intelligence in intelligence_rows
                for citation in intelligence.payload.get("title", {}).get("evidence", [])
            ] + [citation for item in summaries for citation in item.get("evidence", [])]
            titles = [item.payload.get("title", {}).get("text", "") for item in intelligence_rows]
            return (
                " ".join(
                    [value for value in titles if value]
                    + [item.get("short", "") for item in summaries if item.get("short")]
                ),
                citations,
                "structured_projection_summary",
            )
    if any(term in normalized for term in ("processing expense", "processing cost")) and facts:
        item = facts[0]
        return item["claim"], item.get("evidence", []), "structured_projection_fact"
    return None


def _number_word(value: int) -> str:
    words = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
    return words.get(value, str(value))


def _is_are(value: int) -> str:
    return "is" if value == 1 else "are"


def serialize_cost(cost: CostEvent) -> dict[str, Any]:
    return {
        "id": cost.id,
        "recording_id": cost.recording_id,
        "ask_session_id": cost.ask_session_id,
        "stage": cost.stage,
        "provider": cost.provider,
        "model_alias": cost.model_alias,
        "resolved_model": cost.resolved_model,
        "price_catalog_version": cost.price_catalog_version,
        "usage": cost.usage,
        "estimated_incurred_cost_usd": cost.estimated_cost_usd,
        "reconciled_cost_usd": cost.reconciled_cost_usd,
        "currency": cost.currency,
        "cache_reuse": cost.cache_reuse,
        "escalation_reason": cost.escalation_reason,
        "provenance": cost.provenance,
        "created_at": cost.created_at,
    }


def export_content(
    db: Session,
    workspace_id: str,
    export_format: str,
    recording_ids: list[str],
    include: str,
) -> tuple[bytes, str, str]:
    recordings_query = select(Recording).where(
        Recording.workspace_id == workspace_id, Recording.deleted_at.is_(None)
    )
    if recording_ids:
        recordings_query = recordings_query.where(Recording.id.in_(recording_ids))
    recordings = db.scalars(recordings_query.order_by(Recording.created_at).with_for_update()).all()
    if include == "tasks":
        task_query = (
            select(ActionItem)
            .join(Recording, Recording.id == ActionItem.recording_id)
            .where(
                ActionItem.workspace_id == workspace_id,
                Recording.workspace_id == workspace_id,
                Recording.deleted_at.is_(None),
            )
        )
        if recording_ids:
            task_query = task_query.where(ActionItem.recording_id.in_(recording_ids))
        tasks = db.scalars(task_query.order_by(ActionItem.created_at)).all()
        return _export_tasks(tasks, export_format)
    rows = []
    for recording in recordings:
        rows.append(
            {
                "recording": recording_payload(recording),
                "transcript": transcript_payload(db, recording),
                "intelligence": intelligence_payload(db, recording),
            }
        )
    if export_format == "json":
        return (
            json.dumps({"recordings": rows}, default=str, indent=2).encode(),
            "application/json",
            "pocket-recordings.json",
        )
    if export_format == "markdown":
        chunks = ["# Pocket recordings export\n"]
        for row in rows:
            recording = row["recording"]
            chunks.append(f"## {recording['display_name']}\n")
            for segment in row["transcript"].get("segments", []):
                chunks.append(f"- `{segment['start_ms']}–{segment['end_ms']} ms` {segment['text']}")
            chunks.append("")
        return "\n".join(chunks).encode(), "text/markdown", "pocket-recordings.md"
    if export_format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["recording_id", "recording", "start_ms", "end_ms", "speaker", "text"])
        for row in rows:
            for segment in row["transcript"].get("segments", []):
                writer.writerow(
                    [
                        row["recording"]["id"],
                        row["recording"]["display_name"],
                        segment["start_ms"],
                        segment["end_ms"],
                        segment.get("speaker_display_name") or segment.get("speaker_cluster_id"),
                        segment["text"],
                    ]
                )
        return output.getvalue().encode(), "text/csv", "pocket-recordings.csv"
    raise ValueError("ICS export is available for tasks, not recordings")


def _export_tasks(tasks: list[ActionItem], export_format: str) -> tuple[bytes, str, str]:
    values = [
        {
            "id": item.id,
            "recording_id": item.recording_id,
            "task": item.task,
            "owner": item.owner_text,
            "due_text": item.due_text,
            "due_at": item.due_at.isoformat() if item.due_at else None,
            "status": item.status,
            "ambiguities": item.ambiguities,
            "evidence": item.evidence,
        }
        for item in tasks
    ]
    if export_format == "json":
        return (
            json.dumps({"tasks": values}, indent=2).encode(),
            "application/json",
            "pocket-tasks.json",
        )
    if export_format == "markdown":
        lines = ["# Pocket tasks export", ""]
        for item in values:
            marker = "x" if item["status"] in {"done", "completed"} else " "
            owner = f" — {item['owner']}" if item["owner"] else ""
            lines.append(f"- [{marker}] {item['task']}{owner}")
        return "\n".join(lines).encode(), "text/markdown", "pocket-tasks.md"
    if export_format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["id", "recording_id", "task", "owner", "due_text", "due_at", "status"],
        )
        writer.writeheader()
        for item in values:
            writer.writerow({key: item[key] for key in writer.fieldnames})
        return output.getvalue().encode(), "text/csv", "pocket-tasks.csv"
    if export_format == "ics":
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Pocket Demo//EN"]
        for item in values:
            task_status = "COMPLETED" if item["status"] in {"done", "completed"} else "NEEDS-ACTION"
            lines.extend(
                [
                    "BEGIN:VTODO",
                    f"UID:{_ics(item['id'])}@pocket-demo",
                    f"SUMMARY:{_ics(item['task'])}",
                    f"STATUS:{task_status}",
                ]
            )
            if item["due_at"]:
                due = datetime.fromisoformat(item["due_at"]).astimezone(UTC)
                lines.append(f"DUE:{due.strftime('%Y%m%dT%H%M%SZ')}")
            if item["due_text"]:
                lines.append(f"DESCRIPTION:Original due phrase: {_ics(item['due_text'])}")
            lines.append("END:VTODO")
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines).encode(), "text/calendar", "pocket-tasks.ics"
    raise ValueError("Unsupported export format")


def _ics(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )
