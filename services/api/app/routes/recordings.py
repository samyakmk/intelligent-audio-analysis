from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import UTC, timedelta

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import AuthContext, hash_token, require_auth, require_mutation_auth
from ..blobstore import BlobAlreadyExists
from ..database import get_db
from ..demo_fixture import FIXTURE_SHA256
from ..domain import (
    BudgetReservationUnavailable,
    StaleGeneration,
    ValidationFailure,
    clone_transcript_with_edit,
    create_processing_run,
    emit_event,
    intelligence_payload,
    invalidate_dependent_views,
    process_run,
    recording_detail_payload,
    regenerate_intelligence,
    require_recording,
    settle_interrupted_budget,
    settle_run_reservations,
    transcript_payload,
    validate_audio,
)
from ..lifecycle import delete_recording_content, expire_upload_session
from ..models import (
    DomainEvent,
    IdempotencyRecord,
    MediaGrant,
    MediaObject,
    OutboxEvent,
    ProcessingRun,
    Recording,
    UploadSession,
    Workspace,
    utcnow,
)
from ..schemas import (
    CompleteUploadRequest,
    CorrectionCreate,
    RecordingPatch,
    RegenerateRequest,
    SpeakerUpdate,
    UploadSessionCreate,
)

router = APIRouter(prefix="/v1", tags=["recordings"])
media_router = APIRouter(tags=["media"])


def _request_fingerprint(payload: object) -> str:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _idempotent_response(
    db: Session,
    workspace_id: str,
    operation: str,
    key: str | None,
    fingerprint: str,
) -> dict | None:
    if not key:
        return None
    if len(key) > 180:
        raise HTTPException(status_code=400, detail="Idempotency-Key is too long")
    item = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.workspace_id == workspace_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key == key,
        )
    )
    if item is None:
        return None
    if item.request_hash != fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used with a different request",
        )
    return item.response


def _remember_idempotency(
    db: Session,
    workspace_id: str,
    operation: str,
    key: str | None,
    fingerprint: str,
    response: dict,
    status_code: int,
) -> None:
    if not key:
        return
    db.add(
        IdempotencyRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            operation=operation,
            key=key,
            request_hash=fingerprint,
            response=jsonable_encoder(response),
            status_code=status_code,
        )
    )


@router.post("/upload-sessions", status_code=status.HTTP_201_CREATED)
def create_upload_session(
    payload: UploadSessionCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    settings = request.app.state.settings
    fingerprint = _request_fingerprint(payload)
    workspace = db.scalar(
        select(Workspace).where(Workspace.id == auth.workspace_id).with_for_update()
    )
    if workspace is None:
        raise HTTPException(status_code=403, detail="Workspace is unavailable")
    prior = _idempotent_response(
        db, auth.workspace_id, "create-upload-session", idempotency_key, fingerprint
    )
    if prior is not None:
        prior_recording = db.get(Recording, prior["recording_id"])
        if prior_recording is None or prior_recording.deleted_at is not None:
            raise HTTPException(
                status_code=410,
                detail={
                    "code": "idempotent_resource_deleted",
                    "message": "The original upload reservation was deleted.",
                },
            )
        return {
            **prior,
            "upload_headers": {"X-Upload-Token": _derive_upload_token(settings, prior["id"])},
        }
    if payload.mode == "deep":
        if settings.provider_mode != "gemini" or not settings.allow_remote_provider_calls:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "capability_unavailable",
                    "message": "Deep processing requires the configured Gemini provider.",
                },
            )
    if (
        settings.provider_mode == "gemini"
        and settings.allow_remote_provider_calls
        and not payload.provider_data_approved
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "provider_data_approval_required",
                "message": (
                    "This upload must be explicitly approved for the configured remote "
                    "provider data-policy lane."
                ),
            },
        )
    if (
        settings.provider_mode == "gemini"
        and settings.allow_remote_provider_calls
        and payload.language.casefold() == "auto"
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "provider_language_required",
                "message": (
                    "Gemini uploads require an explicit allowlisted language before audio leaves "
                    "the local machine. English is the evaluated demo route."
                ),
            },
        )
    if payload.size_bytes > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds workspace file-size limit")
    live_recordings = db.scalars(
        select(Recording).where(
            Recording.workspace_id == auth.workspace_id,
            Recording.deleted_at.is_(None),
        )
    ).all()
    if len(live_recordings) >= settings.workspace_recording_quota:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "recording_quota_exceeded",
                "message": "Workspace retained-recording quota is full.",
            },
        )
    retained_bytes = sum(item.size_bytes or 0 for item in live_recordings)
    if retained_bytes + payload.size_bytes > settings.workspace_storage_quota_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "storage_quota_exceeded",
                "message": "Upload reservation would exceed workspace storage quota.",
            },
        )
    recording_id = str(uuid.uuid4())
    upload_id = str(uuid.uuid4())
    upload_token = _derive_upload_token(settings, upload_id)
    expires_at = utcnow() + timedelta(hours=24)
    filename = payload.filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not filename or any(ord(char) < 32 for char in filename):
        raise HTTPException(status_code=422, detail="Filename is invalid")
    recording = Recording(
        id=recording_id,
        workspace_id=auth.workspace_id,
        created_by=auth.principal_id,
        display_name=filename.rsplit(".", 1)[0] or "Untitled recording",
        original_filename=filename,
        content_type=payload.content_type,
        requested_language=payload.language,
        requested_mode=payload.mode,
        provider_data_approved=payload.provider_data_approved,
        vocabulary_hints=payload.vocabulary_hints,
        size_bytes=payload.size_bytes,
        status="UPLOADING",
        stage="uploading",
        retention_expires_at=utcnow() + timedelta(days=settings.recording_retention_days),
    )
    upload = UploadSession(
        id=upload_id,
        recording_id=recording_id,
        workspace_id=auth.workspace_id,
        deletion_generation=0,
        quarantine_key=f"quarantine/{auth.workspace_id}/{recording_id}/g0/{upload_id}",
        upload_token_hash=hash_token(upload_token),
        expected_size=payload.size_bytes,
        expected_sha256=payload.sha256,
        status="created",
        expires_at=expires_at,
    )
    db.add(recording)
    db.add(upload)
    db.flush()
    upload_url = str(request.url_for("upload_content", upload_session_id=upload_id))
    response = jsonable_encoder(
        {
            "id": upload_id,
            "recording_id": recording_id,
            "upload_url": upload_url,
            "upload_method": "PUT",
            "upload_headers": {"X-Upload-Token": upload_token},
            "expires_at": expires_at,
            "max_bytes": settings.max_upload_bytes,
            "provider_data_approved": recording.provider_data_approved,
        }
    )
    persisted_response = {key: value for key, value in response.items() if key != "upload_headers"}
    _remember_idempotency(
        db,
        auth.workspace_id,
        "create-upload-session",
        idempotency_key,
        fingerprint,
        persisted_response,
        201,
    )
    emit_event(db, recording, "upload.created", {})
    db.commit()
    return response


@router.put("/upload-sessions/{upload_session_id}/content", name="upload_content")
async def upload_content(
    upload_session_id: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    upload_token: str | None = Header(default=None, alias="X-Upload-Token"),
) -> Response:
    settings = request.app.state.settings
    if not upload_token:
        raise HTTPException(status_code=401, detail="Missing upload token")
    row = db.execute(
        select(UploadSession, Recording)
        .join(Recording, Recording.id == UploadSession.recording_id)
        .where(
            UploadSession.id == upload_session_id,
            UploadSession.upload_token_hash == hash_token(upload_token),
        )
        .with_for_update()
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Upload session not found")
    upload, recording = row
    expiry = upload.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if upload.status in {"created", "uploaded"} and expiry <= utcnow():
        expire_upload_session(db, request.app.state.blob_store, upload, recording)
    elif upload.status == "expired_cleanup_pending":
        expire_upload_session(db, request.app.state.blob_store, upload, recording)
    if (
        recording.deleted_at is not None
        or recording.deletion_generation != upload.deletion_generation
        or upload.status in {"expired", "expired_cleanup_pending"}
    ):
        raise HTTPException(status_code=410, detail="Upload session expired")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Content-Length must be an integer"
            ) from exc
        if declared_length < 0:
            raise HTTPException(status_code=400, detail="Content-Length cannot be negative")
        if declared_length > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Upload exceeds file-size limit")
    data = await request.body()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds file-size limit")
    actual_hash = hashlib.sha256(data).hexdigest()
    if upload.status in {"sealed", "sealed_cleanup_pending"}:
        if upload.actual_sha256 == actual_hash and upload.actual_size == len(data):
            response.status_code = 204
            return response
        raise HTTPException(
            status_code=409,
            detail="Upload session is finalized with different bytes",
        )
    if upload.status == "uploaded":
        if upload.actual_sha256 == actual_hash and upload.actual_size == len(data):
            response.status_code = 204
            return response
        raise HTTPException(status_code=409, detail="Upload bytes are already sealed in quarantine")
    if upload.status == "expired":
        raise HTTPException(status_code=410, detail="Upload session expired")
    if upload.status == "rejected":
        raise HTTPException(status_code=409, detail="Upload session was rejected")
    if upload.status != "created":
        raise HTTPException(status_code=409, detail="Upload session is not writable")
    if upload.expected_size is not None and len(data) != upload.expected_size:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "reserved_size_mismatch",
                "message": "Received bytes differ from the reserved upload size.",
            },
        )
    request.app.state.blob_store.put(upload.quarantine_key, data)
    upload.actual_size = len(data)
    upload.actual_sha256 = actual_hash
    upload.status = "uploaded"
    recording.stage = "verifying"
    recording.status = "VERIFYING"
    emit_event(db, recording, "upload.received", {"size_bytes": len(data)})
    db.commit()
    response.status_code = 204
    return response


@router.post("/recordings/{recording_id}/complete", status_code=status.HTTP_202_ACCEPTED)
def complete_upload(
    recording_id: str,
    payload: CompleteUploadRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    fingerprint = _request_fingerprint(payload)
    prior = _idempotent_response(
        db, auth.workspace_id, f"complete:{recording_id}", idempotency_key, fingerprint
    )
    if prior is not None:
        queued = db.scalar(
            select(ProcessingRun).where(
                ProcessingRun.recording_id == recording.id,
                ProcessingRun.status == "queued",
            )
        )
        if queued is not None and request.app.state.settings.inline_worker:
            background_tasks.add_task(
                process_run,
                request.app.state.database,
                request.app.state.blob_store,
                request.app.state.speech_adapter,
                request.app.state.llm_adapter,
                request.app.state.settings,
                queued.id,
            )
        return recording_detail_payload(db, recording)
    upload_query = select(UploadSession).where(
        UploadSession.recording_id == recording.id,
        UploadSession.workspace_id == auth.workspace_id,
    )
    if payload.upload_session_id:
        upload_query = upload_query.where(UploadSession.id == payload.upload_session_id)
    upload = db.scalar(upload_query)
    if upload is None:
        raise HTTPException(status_code=404, detail="Upload session not found")
    expiry = upload.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if upload.status in {"created", "uploaded"} and expiry <= utcnow():
        expire_upload_session(db, request.app.state.blob_store, upload, recording)
    elif upload.status == "expired_cleanup_pending":
        expire_upload_session(db, request.app.state.blob_store, upload, recording)
    if upload.status in {"expired", "expired_cleanup_pending"}:
        raise HTTPException(status_code=410, detail="Upload session expired")
    if recording.original_ready:
        if recording.sha256 != payload.sha256:
            raise HTTPException(status_code=409, detail="Recording was completed with other bytes")
        queued = db.scalar(
            select(ProcessingRun).where(
                ProcessingRun.recording_id == recording.id,
                ProcessingRun.status == "queued",
            )
        )
        if queued is not None and request.app.state.settings.inline_worker:
            background_tasks.add_task(
                process_run,
                request.app.state.database,
                request.app.state.blob_store,
                request.app.state.speech_adapter,
                request.app.state.llm_adapter,
                request.app.state.settings,
                queued.id,
            )
        return recording_detail_payload(db, recording)
    if upload.status != "uploaded":
        raise HTTPException(status_code=409, detail="Upload bytes have not arrived")
    if upload.deletion_generation != recording.deletion_generation:
        raise HTTPException(status_code=410, detail="Upload belongs to a stale deletion generation")
    data = request.app.state.blob_store.get(upload.quarantine_key)
    actual_hash = hashlib.sha256(data).hexdigest()
    if payload.sha256 != actual_hash or upload.actual_sha256 != actual_hash:
        recording.status = "FAILED_FINAL"
        recording.stage = "failed"
        recording.error_code = "checksum_mismatch"
        recording.error_detail = "Final SHA-256 did not match the quarantined bytes."
        recording.size_bytes = 0
        upload.status = "rejected"
        request.app.state.blob_store.delete(upload.quarantine_key)
        emit_event(db, recording, "upload.rejected", {"code": "checksum_mismatch"})
        db.commit()
        raise HTTPException(status_code=422, detail="SHA-256 mismatch; upload was rejected")
    if upload.expected_sha256 and upload.expected_sha256 != actual_hash:
        recording.status = "FAILED_FINAL"
        recording.stage = "failed"
        recording.error_code = "reserved_checksum_mismatch"
        recording.error_detail = "SHA-256 differs from the upload reservation."
        recording.size_bytes = 0
        upload.status = "rejected"
        request.app.state.blob_store.delete(upload.quarantine_key)
        emit_event(db, recording, "upload.rejected", {"code": recording.error_code})
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "reserved_checksum_mismatch",
                "message": "SHA-256 differs from the upload reservation.",
            },
        )
    if upload.expected_size is not None and upload.expected_size != len(data):
        raise HTTPException(status_code=422, detail="Byte count differs from upload reservation")
    try:
        probe = validate_audio(data, request.app.state.settings)
    except ValidationFailure as exc:
        recording.status = "FAILED_FINAL"
        recording.stage = "failed"
        recording.error_code = exc.code
        recording.error_detail = str(exc)
        recording.size_bytes = 0
        upload.status = "rejected"
        request.app.state.blob_store.delete(upload.quarantine_key)
        emit_event(db, recording, "upload.rejected", {"code": exc.code})
        db.commit()
        raise HTTPException(
            status_code=422, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    original_key = (
        f"original/{auth.workspace_id}/{recording.id}/g{recording.deletion_generation}/audio"
    )
    try:
        request.app.state.blob_store.put(original_key, data, immutable=True)
    except BlobAlreadyExists as exc:
        existing = request.app.state.blob_store.get(original_key)
        if hashlib.sha256(existing).hexdigest() != actual_hash:
            raise HTTPException(
                status_code=409,
                detail="Immutable original key already contains different bytes",
            ) from exc
    media = MediaObject(
        id=str(uuid.uuid4()),
        recording_id=recording.id,
        workspace_id=auth.workspace_id,
        deletion_generation=recording.deletion_generation,
        kind="original",
        blob_key=original_key,
        sha256=actual_hash,
        size_bytes=len(data),
        content_type=probe.content_type,
    )
    db.add(media)
    recording.sha256 = actual_hash
    if actual_hash == FIXTURE_SHA256:
        recording.source_kind = "approved_fixture"
    recording.size_bytes = len(data)
    recording.duration_ms = probe.duration_ms
    recording.content_type = probe.content_type
    recording.original_ready = True
    recording.status = "SEALED"
    recording.stage = "sealed"
    upload.status = "sealed"
    run = create_processing_run(db, recording)
    db.add(
        OutboxEvent(
            id=str(uuid.uuid4()),
            event_key=f"recording.sealed:{recording.id}:g{recording.deletion_generation}",
            event_type="recording.sealed.v1",
            recording_id=recording.id,
            workspace_id=auth.workspace_id,
            deletion_generation=recording.deletion_generation,
        )
    )
    emit_event(db, recording, "recording.sealed", {})
    response = recording_detail_payload(db, recording)
    _remember_idempotency(
        db,
        auth.workspace_id,
        f"complete:{recording_id}",
        idempotency_key,
        fingerprint,
        response,
        202,
    )
    db.commit()
    # Copy-first makes the DB transaction redrivable if it fails after the
    # immutable original write.  Quarantine is removed only after the sealed
    # MediaObject and outbox state are durable.
    if request.app.state.settings.inline_worker:
        background_tasks.add_task(
            process_run,
            request.app.state.database,
            request.app.state.blob_store,
            request.app.state.speech_adapter,
            request.app.state.llm_adapter,
            request.app.state.settings,
            run.id,
        )
    try:
        request.app.state.blob_store.delete(upload.quarantine_key)
    except Exception:
        upload.status = "sealed_cleanup_pending"
        db.commit()
    return response


@router.get("/recordings")
def list_recordings(
    state: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid cursor") from exc
    query = select(Recording).where(
        Recording.workspace_id == auth.workspace_id, Recording.deleted_at.is_(None)
    )
    if state:
        query = query.where(Recording.status == state.upper())
    all_items = db.scalars(query.order_by(Recording.created_at.desc()).with_for_update()).all()
    page = all_items[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(all_items) else None
    return {
        "items": [recording_detail_payload(db, item) for item in page],
        "total": len(all_items),
        "next_cursor": next_cursor,
    }


@router.get("/recordings/{recording_id}")
def get_recording(
    recording_id: str,
    response: Response,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    response.headers["ETag"] = f'"{recording.etag_version}"'
    return recording_detail_payload(db, recording)


@router.patch("/recordings/{recording_id}")
def update_recording(
    recording_id: str,
    payload: RecordingPatch,
    response: Response,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict:
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    _check_version(if_match, recording.etag_version)
    invalidates_views = False
    title = payload.title if payload.title is not None else payload.display_name
    if title is not None and title != recording.display_name:
        recording.display_name = title
        invalidates_views = True
    if payload.tags is not None:
        recording.tags = sorted(set(payload.tags))
    if payload.folder is not None and (payload.folder or None) != recording.folder:
        recording.folder = payload.folder or None
        invalidates_views = True
    if payload.summary_style is not None:
        recording.summary_style = payload.summary_style
    recording.etag_version += 1
    if invalidates_views:
        invalidate_dependent_views(db, recording)
    emit_event(db, recording, "recording.updated", {})
    db.commit()
    response.headers["ETag"] = f'"{recording.etag_version}"'
    return recording_detail_payload(db, recording)


@router.get("/recordings/{recording_id}/transcript")
def get_transcript(
    recording_id: str,
    response: Response,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    if not recording.transcript_ready:
        raise HTTPException(
            status_code=409,
            detail={
                "code": recording.error_code or "transcript_not_ready",
                "message": recording.error_detail or "Transcript is not ready.",
            },
        )
    response.headers["ETag"] = f'"{recording.transcript_version}"'
    return transcript_payload(db, recording)


@router.get("/recordings/{recording_id}/intelligence")
def get_intelligence(
    recording_id: str,
    response: Response,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    if not recording.intelligence_ready:
        raise HTTPException(
            status_code=409,
            detail={
                "code": recording.error_code or "intelligence_not_ready",
                "message": recording.error_detail or "Intelligence is not ready.",
            },
        )
    response.headers["ETag"] = f'"{recording.intelligence_version}"'
    return intelligence_payload(db, recording)


@router.post("/recordings/{recording_id}/corrections")
def correct_transcript(
    recording_id: str,
    payload: CorrectionCreate,
    response: Response,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    fingerprint = _request_fingerprint(payload)
    prior = _idempotent_response(
        db, auth.workspace_id, f"correction:{recording_id}", idempotency_key, fingerprint
    )
    if prior is not None:
        return transcript_payload(db, recording)
    version = (
        payload.base_transcript_version or _version_header(if_match) or recording.transcript_version
    )
    clone_transcript_with_edit(
        db,
        recording,
        expected_version=version,
        segment_id=payload.segment_id,
        replacement_text=payload.text,
    )
    result = transcript_payload(db, recording)
    _remember_idempotency(
        db,
        auth.workspace_id,
        f"correction:{recording_id}",
        idempotency_key,
        fingerprint,
        {"recording_id": recording.id, "transcript_version": recording.transcript_version},
        200,
    )
    db.commit()
    response.headers["ETag"] = f'"{recording.transcript_version}"'
    return result


@router.post("/recordings/{recording_id}/speakers")
def update_speaker(
    recording_id: str,
    payload: SpeakerUpdate,
    response: Response,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    fingerprint = _request_fingerprint(payload)
    prior = _idempotent_response(
        db, auth.workspace_id, f"speaker:{recording_id}", idempotency_key, fingerprint
    )
    if prior is not None:
        return transcript_payload(db, recording)
    version = (
        payload.base_transcript_version or _version_header(if_match) or recording.transcript_version
    )
    clone_transcript_with_edit(
        db,
        recording,
        expected_version=version,
        speaker_id=payload.speaker_id,
        display_name=payload.display_name,
        merge_into=payload.merge_into or payload.merge_into_speaker_id,
    )
    result = transcript_payload(db, recording)
    _remember_idempotency(
        db,
        auth.workspace_id,
        f"speaker:{recording_id}",
        idempotency_key,
        fingerprint,
        {"recording_id": recording.id, "transcript_version": recording.transcript_version},
        200,
    )
    db.commit()
    response.headers["ETag"] = f'"{recording.transcript_version}"'
    return result


@router.post("/recordings/{recording_id}/regenerate", status_code=202)
def regenerate(
    recording_id: str,
    payload: RegenerateRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    workspace = db.scalar(
        select(Workspace).where(Workspace.id == auth.workspace_id).with_for_update()
    )
    if workspace is None:
        raise HTTPException(status_code=403, detail="Workspace is unavailable")
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    settings = request.app.state.settings
    if (
        settings.provider_mode == "gemini"
        and settings.allow_remote_provider_calls
        and not recording.provider_data_approved
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "provider_data_approval_required",
                "message": (
                    "This recording was not approved for the configured remote data-policy lane."
                ),
            },
        )
    if payload.mode == "deep" and (
        settings.provider_mode != "gemini" or not settings.allow_remote_provider_calls
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "capability_unavailable",
                "message": "Deep regeneration requires the configured Gemini provider.",
            },
        )
    fingerprint = _request_fingerprint(payload)
    prior = _idempotent_response(
        db, auth.workspace_id, f"regenerate:{recording_id}", idempotency_key, fingerprint
    )
    if prior is not None:
        return recording_detail_payload(db, recording)
    request_nonce = idempotency_key or str(uuid.uuid4())
    request_identity = hashlib.sha256(request_nonce.encode()).hexdigest()[:20]
    attempt_id = (
        f"regenerate:{recording.id}:g{recording.deletion_generation}:"
        f"t{recording.transcript_version}:i{recording.intelligence_version}:{request_identity}"
    )
    try:
        regenerate_intelligence(
            db,
            recording,
            request.app.state.llm_adapter,
            payload.summary_style,
            attempt_id,
            request.app.state.settings.recording_cost_ceiling_usd,
            deep=payload.mode == "deep",
        )
        invalidate_dependent_views(db, recording)
        response = recording_detail_payload(db, recording)
        _remember_idempotency(
            db,
            auth.workspace_id,
            f"regenerate:{recording_id}",
            idempotency_key,
            fingerprint,
            response,
            202,
        )
        db.commit()
    except BudgetReservationUnavailable as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except StaleGeneration as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "source_changed",
                "message": "Recording changed while regeneration was running; retry it.",
            },
        ) from exc
    except Exception:
        db.rollback()
        settle_interrupted_budget(
            db,
            attempt_id=attempt_id,
            provider_dispatched=True,
            reason="regeneration_post_dispatch_failure",
        )
        db.commit()
        raise
    return response


@router.post("/recordings/{recording_id}/retry", status_code=202)
def retry_recording(
    recording_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    # The endpoint has no request body and the recording id is already part of
    # the operation name.  Do not fingerprint mutable server-side versions:
    # a network replay after successful processing must still match.
    fingerprint = _request_fingerprint({})
    prior = _idempotent_response(
        db, auth.workspace_id, f"retry:{recording_id}", idempotency_key, fingerprint
    )
    if prior is not None:
        return recording_detail_payload(db, recording)
    if recording.status not in {"PARTIAL", "FAILED_RETRYABLE", "CANCELLED"}:
        raise HTTPException(status_code=409, detail="Recording has no retryable work")
    recording.cancel_requested = False
    for prior_run in db.scalars(
        select(ProcessingRun).where(
            ProcessingRun.recording_id == recording.id,
            ProcessingRun.status.in_(["failed_retryable", "retryable", "partial"]),
        )
    ).all():
        prior_run.status = "superseded"
        prior_run.lease_owner = None
        prior_run.lease_expires_at = None
    run = create_processing_run(db, recording)
    recording.status = "PROCESSING"
    recording.stage = "transcribing"
    result = recording_detail_payload(db, recording)
    _remember_idempotency(
        db,
        auth.workspace_id,
        f"retry:{recording_id}",
        idempotency_key,
        fingerprint,
        {"recording_id": recording.id, "run_id": run.id},
        202,
    )
    db.commit()
    if request.app.state.settings.inline_worker:
        background_tasks.add_task(
            process_run,
            request.app.state.database,
            request.app.state.blob_store,
            request.app.state.speech_adapter,
            request.app.state.llm_adapter,
            request.app.state.settings,
            run.id,
        )
    return result


@router.post("/recordings/{recording_id}/cancel")
def cancel_recording(
    recording_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
) -> dict:
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    if recording.status in {"READY", "FAILED_FINAL"}:
        raise HTTPException(status_code=409, detail="Recording is already terminal")
    recording.cancel_requested = True
    recording.status = "CANCELLED"
    recording.stage = "cancelled"
    for run in db.scalars(
        select(ProcessingRun).where(
            ProcessingRun.recording_id == recording.id,
            ProcessingRun.status.in_(["queued", "claimed", "processing", "retryable"]),
        )
    ).all():
        dispatched = (
            {f"speech:{run.id}", f"intelligence:{run.id}"}
            if run.status in {"claimed", "processing"}
            else set()
        )
        settle_run_reservations(
            db,
            run.id,
            dispatched_attempts=dispatched,
            reason="processing_cancelled",
        )
        run.status = "cancelled"
        run.completed_at = utcnow()
        run.lease_owner = None
        run.lease_expires_at = None
    emit_event(db, recording, "processing.cancelled", {})
    db.commit()
    return recording_detail_payload(db, recording)


@router.get("/recordings/{recording_id}/media-grant")
def media_grant(
    recording_id: str,
    request: Request,
    disposition: str = Query(default="playback", pattern="^(playback|download)$"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    # Serialize grant creation with the logical tombstone transaction. If
    # deletion wins the row lock, this rechecks as not found; if grant issuance
    # wins, deletion revokes the just-created grant before becoming visible.
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    if not recording.original_ready:
        raise HTTPException(status_code=409, detail="Original media is not ready")
    raw_token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(seconds=request.app.state.settings.media_grant_ttl_seconds)
    db.add(
        MediaGrant(
            id=str(uuid.uuid4()),
            token_hash=hash_token(raw_token),
            recording_id=recording.id,
            workspace_id=auth.workspace_id,
            deletion_generation=recording.deletion_generation,
            expires_at=expires_at,
        )
    )
    db.commit()
    url = str(request.url_for("read_media", token=raw_token))
    if disposition == "download":
        url += "?download=1"
    return {
        "url": url,
        "expires_at": expires_at,
        "ttl_seconds": request.app.state.settings.media_grant_ttl_seconds,
        "disclosure": "Grant expires quickly and is invalidated immediately by demo deletion.",
    }


@media_router.get("/v1/media/{token}", name="read_media")
def read_media(
    token: str,
    request: Request,
    download: bool = False,
    range_header: str | None = Header(default=None, alias="Range"),
    db: Session = Depends(get_db),
) -> Response:
    grant = db.scalar(select(MediaGrant).where(MediaGrant.token_hash == hash_token(token)))
    if grant is None:
        raise HTTPException(status_code=404, detail="Media grant not found")
    expiry = grant.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    recording = db.scalar(
        select(Recording)
        .where(
            Recording.id == grant.recording_id,
            Recording.workspace_id == grant.workspace_id,
        )
        .with_for_update()
    )
    if (
        expiry <= utcnow()
        or recording is None
        or recording.deleted_at is not None
        or recording.deletion_generation != grant.deletion_generation
    ):
        raise HTTPException(status_code=404, detail="Media grant not found")
    media = db.scalar(
        select(MediaObject).where(
            MediaObject.recording_id == recording.id,
            MediaObject.kind == "original",
            MediaObject.deletion_generation == recording.deletion_generation,
        )
    )
    if media is None:
        raise HTTPException(status_code=404, detail="Media grant not found")
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
        "Content-Disposition": (
            f'attachment; filename="{recording.original_filename.replace(chr(34), "")}"'
            if download
            else "inline"
        ),
    }
    data = request.app.state.blob_store.get(media.blob_key)
    if range_header:
        start, end = _parse_byte_range(range_header, len(data))
        headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
        headers["Content-Length"] = str(end - start + 1)
        return Response(
            data[start : end + 1],
            status_code=206,
            media_type=media.content_type,
            headers=headers,
        )
    headers["Content-Length"] = str(len(data))
    return Response(data, media_type=media.content_type, headers=headers)


@router.get("/recordings/{recording_id}/events")
def recording_events(
    recording_id: str,
    after: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> StreamingResponse:
    recording = require_recording(db, recording_id, auth.workspace_id, lock=True)
    events = db.scalars(
        select(DomainEvent)
        .where(
            DomainEvent.recording_id == recording.id,
            DomainEvent.workspace_id == auth.workspace_id,
            DomainEvent.sequence > after,
        )
        .order_by(DomainEvent.sequence)
    ).all()
    snapshot = recording_detail_payload(db, recording)

    def stream():
        for item in events:
            data = json.dumps(item.payload)
            yield f"id: {item.sequence}\nevent: {item.event_type}\ndata: {data}\n\n"
        yield f"event: snapshot\ndata: {json.dumps(snapshot, default=str)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/recordings/{recording_id}", status_code=204)
def delete_recording(
    recording_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
) -> Response:
    recording = db.scalar(
        select(Recording)
        .where(
            Recording.id == recording_id,
            Recording.workspace_id == auth.workspace_id,
            Recording.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")

    delete_recording_content(
        db,
        request.app.state.blob_store,
        recording,
        reason="user_requested",
    )
    return Response(status_code=204)


def _version_header(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.strip('"'))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="If-Match must be a version number") from exc


def _check_version(value: str | None, current: int) -> None:
    expected = _version_header(value)
    if expected is not None and expected != current:
        raise HTTPException(status_code=412, detail="Resource version changed; refresh first")


def _derive_upload_token(settings: object, upload_id: str) -> str:
    return hmac.new(
        settings.token_signing_secret.encode("utf-8"),
        f"upload:{upload_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _parse_byte_range(value: str, size: int) -> tuple[int, int]:
    if not value.startswith("bytes=") or "," in value:
        raise HTTPException(
            status_code=416,
            detail="Only one byte range is supported",
            headers={"Content-Range": f"bytes */{size}"},
        )
    spec = value[6:].strip()
    try:
        first, last = spec.split("-", 1)
        if not first:
            suffix = int(last)
            if suffix <= 0:
                raise ValueError
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(first)
            end = int(last) if last else size - 1
        if start < 0 or start >= size or end < start:
            raise ValueError
        end = min(end, size - 1)
        return start, end
    except (ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=416,
            detail="Requested byte range is not satisfiable",
            headers={"Content-Range": f"bytes */{size}"},
        ) from exc
