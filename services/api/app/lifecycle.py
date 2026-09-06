from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .blobstore import BlobStore
from .database import Database
from .domain import emit_event, invalidate_dependent_views
from .models import (
    ActionItem,
    AskMessage,
    AskSession,
    BudgetReservation,
    CostEvent,
    EvidenceUnit,
    IdempotencyRecord,
    IntelligenceVersion,
    MediaGrant,
    MediaObject,
    OutboxEvent,
    ProcessingRun,
    Recording,
    TimelineInterval,
    TranscriptSegment,
    TranscriptVersion,
    UploadSession,
    utcnow,
)


class RetentionMaintenance:
    """Small throttle for opportunistic inline-mode retention enforcement."""

    def __init__(
        self,
        database: Database,
        blob_store: BlobStore,
        *,
        interval_seconds: float = 60.0,
    ) -> None:
        self.database = database
        self.blob_store = blob_store
        self.interval_seconds = max(0.0, interval_seconds)
        self._next_check = 0.0
        self._lock = threading.Lock()

    def run_if_due(self, *, force: bool = False) -> int:
        current = time.monotonic()
        with self._lock:
            if not force and self.interval_seconds > 0 and current < self._next_check:
                return 0
            self._next_check = current + self.interval_seconds
        sweep_expired_uploads(self.database, self.blob_store)
        tombstoned = sweep_expired_recordings(self.database, self.blob_store)
        retry_pending_blob_purges(self.database, self.blob_store)
        return tombstoned


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive round trips for Python comparisons."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _response_mentions_recording(value: object, recording_id: str) -> bool:
    if isinstance(value, dict):
        return any(
            (key in {"recording_id", "id"} and nested == recording_id)
            or _response_mentions_recording(nested, recording_id)
            for key, nested in value.items()
        )
    if isinstance(value, list):
        return any(_response_mentions_recording(item, recording_id) for item in value)
    return False


def _deleted_attempt_id(
    *, workspace_id: str, recording_id: str, attempt_id: str
) -> tuple[str, str]:
    reference_digest = hashlib.sha256(f"{workspace_id}:{recording_id}".encode()).hexdigest()
    attempt_digest = hashlib.sha256(attempt_id.encode()).hexdigest()
    return reference_digest, f"deleted:{reference_digest[:24]}:{attempt_digest}"


def logically_tombstone_recording(
    db: Session,
    recording: Recording,
    *,
    reason: str,
) -> OutboxEvent:
    """Revoke all logical access to a recording without touching object storage.

    The caller must commit this transaction before attempting physical deletion.
    Keeping the two phases separate makes a blob-store outage safe and retryable.
    """

    if recording.deleted_at is not None:
        existing = db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.recording_id == recording.id,
                OutboxEvent.deletion_generation == recording.deletion_generation,
                OutboxEvent.event_type == "recording.deleted.v1",
            )
        )
        if existing is None:
            raise RuntimeError("tombstoned recording is missing its deletion outbox event")
        return existing

    workspace_id = recording.workspace_id
    recording.deleted_at = utcnow()
    recording.deletion_generation += 1
    recording.status = "DELETING"
    recording.stage = "deleting"
    recording.cancel_requested = True

    db.execute(delete(MediaGrant).where(MediaGrant.recording_id == recording.id))
    for run in db.scalars(
        select(ProcessingRun).where(ProcessingRun.recording_id == recording.id)
    ).all():
        if run.status in {
            "queued",
            "claimed",
            "processing",
            "retryable",
            "failed_retryable",
        }:
            run.status = "cancelled"
            run.lease_owner = None
            run.lease_expires_at = None

    # Conservatively revoke cached answers and recaps before removing the
    # recording-scoped projections that grounded them.
    invalidate_dependent_views(db, recording)
    ask_sessions = db.scalars(
        select(AskSession).where(AskSession.workspace_id == workspace_id)
    ).all()
    removed_ask_session_ids: set[str] = set()
    for ask_session in ask_sessions:
        if recording.id in (ask_session.recording_ids or []):
            removed_ask_session_ids.add(ask_session.id)
            db.execute(delete(AskMessage).where(AskMessage.ask_session_id == ask_session.id))
            db.delete(ask_session)
    if removed_ask_session_ids:
        for item in db.scalars(
            select(IdempotencyRecord).where(
                IdempotencyRecord.workspace_id == workspace_id,
                IdempotencyRecord.operation.like("ask-session:%"),
            )
        ).all():
            if item.response.get("id") in removed_ask_session_ids:
                db.delete(item)

    # Retain command keys as replay fences, but remove cached source metadata.
    for item in db.scalars(
        select(IdempotencyRecord).where(IdempotencyRecord.workspace_id == workspace_id)
    ).all():
        if recording.id in item.operation or _response_mentions_recording(
            item.response, recording.id
        ):
            item.response = {"recording_id": recording.id, "deleted": True}
            item.status_code = 410

    db.execute(delete(EvidenceUnit).where(EvidenceUnit.recording_id == recording.id))
    db.execute(delete(ActionItem).where(ActionItem.recording_id == recording.id))
    db.execute(
        delete(IntelligenceVersion).where(IntelligenceVersion.recording_id == recording.id)
    )
    transcripts = db.scalars(
        select(TranscriptVersion).where(TranscriptVersion.recording_id == recording.id)
    ).all()
    for transcript in transcripts:
        db.execute(
            delete(TimelineInterval).where(TimelineInterval.transcript_id == transcript.id)
        )
        db.execute(
            delete(TranscriptSegment).where(TranscriptSegment.transcript_id == transcript.id)
        )
    db.execute(
        delete(TranscriptVersion).where(TranscriptVersion.recording_id == recording.id)
    )

    # Incurred cost stays append-only for admission and audit purposes. Scrub
    # the addressable content identifier and pseudonymize the attempt identity.
    for cost in db.scalars(
        select(CostEvent).where(CostEvent.recording_id == recording.id)
    ).all():
        original_attempt_id = cost.attempt_id
        reference_digest, redacted_attempt_id = _deleted_attempt_id(
            workspace_id=workspace_id,
            recording_id=recording.id,
            attempt_id=original_attempt_id,
        )
        serialized_provenance = json.dumps(cost.provenance or {}).replace(
            recording.id, f"deleted:{reference_digest}"
        )
        serialized_provenance = serialized_provenance.replace(
            original_attempt_id, redacted_attempt_id
        )
        for ask_session_id in removed_ask_session_ids:
            serialized_provenance = serialized_provenance.replace(
                ask_session_id, f"deleted:{reference_digest}"
            )
        redacted_provenance = json.loads(serialized_provenance)
        cost.provenance = {
            **redacted_provenance,
            "recording_deleted": True,
            "deleted_reference_digest": reference_digest,
        }
        cost.attempt_id = redacted_attempt_id
        cost.recording_id = None
        if cost.ask_session_id in removed_ask_session_ids:
            cost.ask_session_id = None

    # Ask costs do not carry a recording_id, but a recording-scoped Ask
    # session is deleted with its source. Preserve the spend while removing
    # that now-dead session/message identity from the ledger.
    if removed_ask_session_ids:
        for cost in db.scalars(
            select(CostEvent).where(CostEvent.ask_session_id.in_(removed_ask_session_ids))
        ).all():
            original_attempt_id = cost.attempt_id
            reference_digest, redacted_attempt_id = _deleted_attempt_id(
                workspace_id=workspace_id,
                recording_id=recording.id,
                attempt_id=original_attempt_id,
            )
            serialized_provenance = json.dumps(cost.provenance or {}).replace(
                original_attempt_id, redacted_attempt_id
            )
            for ask_session_id in removed_ask_session_ids:
                serialized_provenance = serialized_provenance.replace(
                    ask_session_id, f"deleted:{reference_digest}"
                )
            cost.provenance = {
                **json.loads(serialized_provenance),
                "scope_deleted": True,
                "deleted_reference_digest": reference_digest,
            }
            cost.attempt_id = redacted_attempt_id
            cost.ask_session_id = None

    # Reservations are durable admission decisions rather than incurred cost,
    # but they receive the same identifier scrub so the retained ledger cannot
    # be used to recover a deleted recording id.
    for reservation in db.scalars(
        select(BudgetReservation).where(BudgetReservation.recording_id == recording.id)
    ).all():
        if reservation.status == "reserved":
            if reservation.reserved_usd <= 0:
                reservation.status = "released"
                reservation.release_reason = "recording_deleted_zero_cost_attempt"
            else:
                reservation.status = "reconciliation_pending"
                reservation.release_reason = "recording_deleted_possible_provider_charge"
        _, reservation.attempt_id = _deleted_attempt_id(
            workspace_id=workspace_id,
            recording_id=recording.id,
            attempt_id=reservation.attempt_id,
        )
        reservation.recording_id = None
        if reservation.ask_session_id in removed_ask_session_ids:
            reservation.ask_session_id = None
    if removed_ask_session_ids:
        for reservation in db.scalars(
            select(BudgetReservation).where(
                BudgetReservation.ask_session_id.in_(removed_ask_session_ids)
            )
        ).all():
            if reservation.status == "reserved":
                if reservation.reserved_usd <= 0:
                    reservation.status = "released"
                    reservation.release_reason = "recording_deleted_zero_cost_attempt"
                else:
                    reservation.status = "reconciliation_pending"
                    reservation.release_reason = "recording_deleted_possible_provider_charge"
            _, reservation.attempt_id = _deleted_attempt_id(
                workspace_id=workspace_id,
                recording_id=recording.id,
                attempt_id=reservation.attempt_id,
            )
            reservation.ask_session_id = None

    recording.original_ready = False
    recording.transcript_ready = False
    recording.intelligence_ready = False
    recording.indexed_ready = False
    recording.sha256 = None
    recording.size_bytes = None
    recording.duration_ms = None
    recording.display_name = "Deleted recording"
    recording.original_filename = "deleted"
    recording.content_type = "application/octet-stream"
    recording.requested_language = "und"
    recording.vocabulary_hints = []
    recording.tags = []
    recording.folder = None
    recording.source_kind = "deleted_tombstone"
    recording.error_code = None
    recording.error_detail = None

    emit_event(db, recording, "recording.deleting", {"reason": reason})
    outbox = OutboxEvent(
        id=str(uuid.uuid4()),
        event_key=f"recording.deleted:{recording.id}:g{recording.deletion_generation}",
        event_type="recording.deleted.v1",
        recording_id=recording.id,
        workspace_id=workspace_id,
        deletion_generation=recording.deletion_generation,
    )
    db.add(outbox)
    db.flush()
    return outbox


def attempt_physical_purge(
    db: Session,
    blob_store: BlobStore,
    recording: Recording,
    *,
    retried: bool,
) -> bool:
    """Best-effort physical purge for a logically inaccessible recording."""

    if recording.deleted_at is None:
        raise ValueError("physical purge requires a logical tombstone")
    if recording.status == "DELETED":
        return True

    purge_failed = False
    media_objects = db.scalars(
        select(MediaObject).where(MediaObject.recording_id == recording.id)
    ).all()
    media_by_key = {media.blob_key: media for media in media_objects}
    # Completion is intentionally copy-first. If the process crashed after
    # the immutable PUT but before its MediaObject commit, the deterministic
    # key is the only durable recovery handle available to deletion.
    prior_generation = max(0, recording.deletion_generation - 1)
    original_key = (
        f"original/{recording.workspace_id}/{recording.id}/g{prior_generation}/audio"
    )
    for blob_key in {original_key, *media_by_key}:
        try:
            blob_store.delete(blob_key)
        except Exception:
            purge_failed = True
        else:
            media = media_by_key.get(blob_key)
            if media is not None:
                db.delete(media)
    for upload in db.scalars(
        select(UploadSession).where(UploadSession.recording_id == recording.id)
    ).all():
        try:
            blob_store.delete(upload.quarantine_key)
        except Exception:
            purge_failed = True
        else:
            db.delete(upload)

    if purge_failed:
        recording.status = "DELETING"
        recording.stage = "physical_purge_pending"
        recording.error_code = "physical_purge_pending"
        recording.error_detail = (
            "Logical access is revoked; physical blob deletion will be retried."
        )
        return False

    recording.status = "DELETED"
    recording.stage = "deleted"
    recording.error_code = None
    recording.error_detail = None
    outbox = db.scalar(
        select(OutboxEvent).where(
            OutboxEvent.recording_id == recording.id,
            OutboxEvent.deletion_generation == recording.deletion_generation,
            OutboxEvent.event_type == "recording.deleted.v1",
        )
    )
    if outbox is not None:
        outbox.processed_at = utcnow()
    emit_event(
        db,
        recording,
        "recording.deleted",
        {
            "stores": ["blob", "projections", "answers"],
            "cost_ledger": "retained",
            "retried": retried,
        },
    )
    return True


def delete_recording_content(
    db: Session,
    blob_store: BlobStore,
    recording: Recording,
    *,
    reason: str,
) -> bool:
    """Commit logical revocation first, then attempt the physical purge."""

    logically_tombstone_recording(db, recording, reason=reason)
    db.commit()
    completed = attempt_physical_purge(db, blob_store, recording, retried=False)
    db.commit()
    return completed


def expire_upload_session(
    db: Session,
    blob_store: BlobStore,
    upload: UploadSession,
    recording: Recording | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Durably revoke an abandoned upload before deleting its quarantine blob.

    Object storage cannot participate in the database transaction.  The
    ``expired_cleanup_pending`` state is therefore committed first; a failed
    blob delete remains discoverable and retryable by maintenance.
    """

    cutoff = _as_utc(now or utcnow())
    if upload.status in {"created", "uploaded"}:
        if _as_utc(upload.expires_at) > cutoff:
            return False
        upload.status = "expired_cleanup_pending"
        if (
            recording is not None
            and recording.deleted_at is None
            and not recording.original_ready
        ):
            recording.status = "FAILED_FINAL"
            recording.stage = "failed"
            recording.error_code = "upload_expired"
            recording.error_detail = "The quarantined upload expired before completion."
            recording.size_bytes = 0
            emit_event(db, recording, "upload.expired", {})
        db.commit()
    elif upload.status == "expired":
        return True
    elif upload.status != "expired_cleanup_pending":
        return False

    try:
        blob_store.delete(upload.quarantine_key)
    except Exception:
        # Logical expiry is already committed. Leave the explicit pending state
        # for the next maintenance pass rather than masking the revocation.
        return False
    upload.status = "expired"
    db.commit()
    return True


def sweep_expired_uploads(
    database: Database,
    blob_store: BlobStore,
    *,
    now: datetime | None = None,
    workspace_id: str | None = None,
    limit: int = 50,
) -> int:
    """Expire abandoned upload sessions and retry pending blob cleanup.

    This uses independent, per-upload transactions so a later API admission or
    validation failure cannot roll back database state after a blob was removed.
    The worker and inline maintenance both invoke this global sweep.
    """

    cutoff = _as_utc(now or utcnow())
    with database.session_factory() as db:
        statement = select(UploadSession.id).where(
            (
                UploadSession.status.in_(["created", "uploaded"])
                & (UploadSession.expires_at <= cutoff)
            )
            | (UploadSession.status == "expired_cleanup_pending")
        )
        if workspace_id is not None:
            statement = statement.where(UploadSession.workspace_id == workspace_id)
        upload_ids = db.scalars(statement.order_by(UploadSession.expires_at).limit(limit)).all()

    newly_expired = 0
    for upload_id in upload_ids:
        with database.session_factory() as db:
            snapshot = db.get(UploadSession, upload_id)
            if snapshot is None:
                continue
            recording = db.scalar(
                select(Recording)
                .where(Recording.id == snapshot.recording_id)
                .with_for_update(skip_locked=database.engine.dialect.name == "postgresql")
            )
            if recording is None:
                # Recording rows are retained as tombstones, so None means a
                # PostgreSQL SKIP LOCKED conflict (or corrupt referential data).
                # Never expire an upload without serializing with completion.
                continue
            upload = db.scalar(
                select(UploadSession)
                .where(UploadSession.id == upload_id)
                .with_for_update(skip_locked=database.engine.dialect.name == "postgresql")
            )
            if upload is None:
                continue
            was_active = upload.status in {"created", "uploaded"}
            if was_active and _as_utc(upload.expires_at) > cutoff:
                continue
            expire_upload_session(db, blob_store, upload, recording, now=cutoff)
            if was_active:
                newly_expired += 1
    return newly_expired


def sweep_expired_recordings(
    database: Database,
    blob_store: BlobStore,
    *,
    now: datetime | None = None,
    limit: int = 25,
) -> int:
    """Tombstone due recordings and attempt physical purge.

    The returned count is the number newly tombstoned. A failed object-store
    purge remains represented by ``DELETING`` and is retried independently.
    """

    cutoff = _as_utc(now or utcnow())
    with database.session_factory() as db:
        recording_ids = db.scalars(
            select(Recording.id)
            .where(
                Recording.deleted_at.is_(None),
                Recording.retention_expires_at <= cutoff,
            )
            .order_by(Recording.retention_expires_at, Recording.id)
            .limit(limit)
        ).all()

    tombstoned = 0
    for recording_id in recording_ids:
        with database.session_factory() as db:
            recording = db.scalar(
                select(Recording)
                .where(
                    Recording.id == recording_id,
                    Recording.deleted_at.is_(None),
                )
                .with_for_update(
                    skip_locked=database.engine.dialect.name == "postgresql"
                )
            )
            if recording is None or _as_utc(recording.retention_expires_at) > cutoff:
                continue
            logically_tombstone_recording(db, recording, reason="retention_expired")
            db.commit()
            tombstoned += 1
            attempt_physical_purge(db, blob_store, recording, retried=False)
            db.commit()
    return tombstoned


def retry_pending_blob_purges(
    database: Database,
    blob_store: BlobStore,
    *,
    limit: int = 25,
) -> int:
    """Retry physical deletion after logical access has already been revoked."""

    with database.session_factory() as db:
        recording_ids = db.scalars(
            select(Recording.id)
            .where(
                Recording.deleted_at.is_not(None),
                Recording.status == "DELETING",
            )
            .order_by(Recording.deleted_at, Recording.id)
            .limit(limit)
        ).all()

    completed = 0
    for recording_id in recording_ids:
        with database.session_factory() as db:
            recording = db.scalar(
                select(Recording)
                .where(
                    Recording.id == recording_id,
                    Recording.deleted_at.is_not(None),
                    Recording.status == "DELETING",
                )
                .with_for_update(
                    skip_locked=database.engine.dialect.name == "postgresql"
                )
            )
            if recording is None:
                continue
            if attempt_physical_purge(db, blob_store, recording, retried=True):
                completed += 1
            db.commit()
    return completed
