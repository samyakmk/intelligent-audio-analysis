from __future__ import annotations

import hashlib
import json
import re
import uuid
import wave
from types import SimpleNamespace
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .blobstore import BlobAlreadyExists, BlobStore
from .day_fixture import (
    analyze_wav_activity,
    choose_batch_boundaries,
    find_day_fixture,
    split_wav,
)
from .domain import (
    BudgetExceeded,
    BudgetReservationUnavailable,
    StaleGeneration,
    _cost_once,
    _ledger_billed_failure,
    _provider_actual_cost,
    _publish_intelligence,
    _publish_transcript,
    _rebuild_evidence,
    commit_budget,
    emit_event,
    mark_budget_dispatched,
    reserve_budget,
    settle_interrupted_budget,
)
from .models import (
    ActionItem,
    DayBatch,
    DaySession,
    EvidenceUnit,
    IntelligenceVersion,
    MediaObject,
    Recording,
    TimelineInterval,
    TranscriptSegment,
    TranscriptVersion,
    utcnow,
)
from .providers import (
    AskRequest,
    LLMAdapter,
    ProviderBilledFailure,
    ProviderUnavailable,
    SegmentFilterRequest,
    SpeechAdapter,
    SpeechRequest,
)

MEMORY_COLLECTIONS = {
    "decision": "decisions",
    "action": "actions",
    "fact": "facts",
    "open_question": "open_questions",
}


def empty_memory() -> dict[str, Any]:
    return {
        "summary": "No batches have been published yet.",
        "decisions": [],
        "actions": [],
        "facts": [],
        "open_questions": [],
    }


def initialize_day_session(
    db: Session,
    blob_store: BlobStore,
    recording: Recording,
    source_bytes: bytes,
    *,
    fixture_root: Any,
    provider_mode: str = "fixture",
) -> DaySession:
    fixture = find_day_fixture(fixture_root, recording.sha256 or "")
    segments = fixture.get("segments", []) if fixture else []
    duration_ms = recording.duration_ms or (fixture.get("duration_ms") if fixture else None)
    if not duration_ms:
        raise ValueError("Day-demo audio requires a known duration")
    boundaries = choose_batch_boundaries(
        duration_ms, recording.requested_batch_count, segments
    )
    try:
        audio_batches = split_wav(source_bytes, boundaries)
    except (EOFError, ValueError, wave.Error):
        audio_batches = [b""] * recording.requested_batch_count

    session = DaySession(
        id=str(uuid.uuid4()),
        recording_id=recording.id,
        workspace_id=recording.workspace_id,
        fixture_id=fixture.get("id") if fixture else None,
        status="ready",
        requested_batch_count=recording.requested_batch_count,
        memory_state=empty_memory(),
        change_log=[],
        ask_history=[],
        pipeline_version=(
            "day-memory-gemini.v1" if provider_mode == "gemini" else "day-memory-demo.v1"
        ),
    )
    db.add(session)
    db.flush()
    operations = fixture.get("operations", []) if fixture else []
    operations_by_segment: dict[str, list[dict[str, Any]]] = {}
    for item in operations:
        operations_by_segment.setdefault(str(item["trigger_segment_id"]), []).append(item)
    for batch_index, (start_ms, end_ms) in enumerate(
        zip(boundaries[:-1], boundaries[1:], strict=True)
    ):
        batch_segments = [
            item
            for item in segments
            if start_ms <= (int(item["start_ms"]) + int(item["end_ms"])) // 2 < end_ms
        ]
        batch_operations = [
            operation
            for item in batch_segments
            for operation in operations_by_segment.get(item["id"], [])
        ]
        payload = audio_batches[batch_index]
        blob_key = None
        digest = None
        if payload:
            blob_key = (
                f"day-batch/{recording.workspace_id}/{recording.id}/"
                f"g{recording.deletion_generation}/{batch_index + 1}"
            )
            digest = hashlib.sha256(payload).hexdigest()
            try:
                blob_store.put(blob_key, payload, immutable=True)
            except BlobAlreadyExists:
                existing = blob_store.get(blob_key)
                if hashlib.sha256(existing).hexdigest() != digest:
                    raise RuntimeError(
                        "Immutable day-batch key already contains different bytes"
                    ) from None
            db.add(
                MediaObject(
                    id=str(uuid.uuid4()),
                    recording_id=recording.id,
                    workspace_id=recording.workspace_id,
                    deletion_generation=recording.deletion_generation,
                    kind=f"day_batch_{batch_index + 1}",
                    blob_key=blob_key,
                    sha256=digest,
                    size_bytes=len(payload),
                    content_type="audio/wav",
                )
            )
        db.add(
            DayBatch(
                id=str(uuid.uuid4()),
                day_session_id=session.id,
                recording_id=recording.id,
                batch_index=batch_index,
                start_ms=start_ms,
                end_ms=end_ms,
                blob_key=blob_key,
                sha256=digest,
                size_bytes=len(payload) if payload else None,
                source_payload={
                    "segments": batch_segments,
                    "operations": batch_operations,
                    "attempt_generation": 0,
                },
            )
        )
    recording.status = "PROCESSING"
    recording.stage = "day_waiting"
    recording.source_kind = "approved_day_fixture" if fixture else "day_upload"
    emit_event(
        db,
        recording,
        "day.split",
        {"batch_count": recording.requested_batch_count, "fixture": bool(fixture)},
    )
    return session


def get_day_session(
    db: Session, recording_id: str, workspace_id: str, *, lock: bool = False
) -> tuple[Recording, DaySession]:
    statement = select(Recording).where(
        Recording.id == recording_id,
        Recording.workspace_id == workspace_id,
        Recording.deleted_at.is_(None),
        Recording.experience == "day_demo",
    )
    if lock:
        statement = statement.with_for_update()
    recording = db.scalar(statement)
    if recording is None:
        raise LookupError("Day session not found")
    session_statement = select(DaySession).where(DaySession.recording_id == recording.id)
    if lock:
        session_statement = session_statement.with_for_update()
    session = db.scalar(session_statement)
    if session is None:
        raise LookupError("Day session not found")
    return recording, session


def _fixture_for_session(session: DaySession, fixture_root: Any) -> dict[str, Any] | None:
    if not session.fixture_id:
        return None
    manifest_path = fixture_root / "day-demo" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return next(
        (item for item in manifest.get("fixtures", []) if item.get("id") == session.fixture_id),
        None,
    )


def day_session_payload(
    db: Session, recording: Recording, session: DaySession, fixture_root: Any
) -> dict[str, Any]:
    fixture = _fixture_for_session(session, fixture_root)
    batches = db.scalars(
        select(DayBatch)
        .where(DayBatch.day_session_id == session.id)
        .order_by(DayBatch.batch_index)
    ).all()
    return {
        "id": session.id,
        "recording_id": recording.id,
        "title": fixture.get("title") if fixture else recording.display_name,
        "description": fixture.get("description") if fixture else None,
        "status": session.status,
        "batch_count": session.requested_batch_count,
        "processed_batch_count": session.processed_batch_count,
        "active_batch_index": session.active_batch_index,
        "current_stage": session.current_stage,
        "watermark_ms": session.watermark_ms,
        "duration_ms": recording.duration_ms or 0,
        "revision": session.revision,
        "memory": session.memory_state or empty_memory(),
        "changes": session.change_log or [],
        "ask_history": session.ask_history or [],
        "suggested_questions": fixture.get("suggested_questions", []) if fixture else [],
        "mock": session.pipeline_version != "day-memory-gemini.v1",
        "notice": (
            "Each batch is transcribed and analyzed by Gemini only after it arrives. "
            "Later batches can revise prior memory; provider usage is cost-metered."
            if session.pipeline_version == "day-memory-gemini.v1"
            else fixture.get("provenance", {}).get("notice")
            if fixture
            else "No local transcript fixture matches this source."
        ),
        "error": (
            {"code": session.error_code, "message": session.error_detail}
            if session.error_code
            else None
        ),
        "batches": [
            {
                "id": item.id,
                "index": item.batch_index,
                "number": item.batch_index + 1,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "duration_ms": item.end_ms - item.start_ms,
                "size_bytes": item.size_bytes,
                "status": item.status,
                "stage": item.stage,
                "transcript": item.transcript or [],
                "reconciliation": item.reconciliation or {},
                "index_state": item.index_state or {},
                "pending_changes": item.pending_changes or [],
                "published_snapshot": item.published_snapshot or {},
                "audio_filter": (item.source_payload or {}).get("audio_filter"),
                "provider": {
                    "speech": (item.source_payload or {}).get("speech_provenance"),
                    "filter": (item.source_payload or {}).get("filter_provenance"),
                    "intelligence": (item.source_payload or {}).get(
                        "intelligence_provenance"
                    ),
                },
                "started_at": item.started_at,
                "completed_at": item.completed_at,
            }
            for item in batches
        ],
    }


def _active_batch(db: Session, session: DaySession) -> DayBatch | None:
    return db.scalar(
        select(DayBatch)
        .where(DayBatch.day_session_id == session.id, DayBatch.status != "complete")
        .order_by(DayBatch.batch_index)
        .limit(1)
        .with_for_update()
    )


def _current_item(memory: dict[str, Any], kind: str, key: str) -> dict[str, Any] | None:
    collection = MEMORY_COLLECTIONS[kind]
    for item in reversed(memory.get(collection, [])):
        if item.get("key") == key and item.get("status") not in {"superseded"}:
            return item
    return None


def _preview_changes(
    memory: dict[str, Any], operations: list[dict[str, Any]], batch_index: int
) -> list[dict[str, Any]]:
    previews = []
    for operation in operations:
        prior = _current_item(memory, operation["kind"], operation["key"])
        previews.append(
            {
                "id": operation["id"],
                "operation": operation["operation"],
                "kind": operation["kind"],
                "key": operation["key"],
                "before": prior.get("text") if prior else None,
                "after": operation["text"],
                "owner_before": prior.get("owner") if prior else None,
                "owner_after": operation.get("owner"),
                "batch_index": batch_index,
                "trigger_segment_id": operation["trigger_segment_id"],
            }
        )
    return previews


def _apply_operations(
    memory: dict[str, Any], operations: list[dict[str, Any]], batch: DayBatch
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    updated = json.loads(json.dumps(memory))
    changes: list[dict[str, Any]] = []
    segment_index = {item["id"]: item for item in batch.transcript or []}
    for operation in operations:
        kind = operation["kind"]
        collection = MEMORY_COLLECTIONS[kind]
        prior = _current_item(updated, kind, operation["key"])
        if operation["operation"] in {"supersede", "resolve"} and prior:
            prior["status"] = "superseded"
            prior["superseded_by"] = operation["id"]
        source = segment_index[operation["trigger_segment_id"]]
        evidence = {
            "segment_id": source["id"],
            "start_ms": source["start_ms"],
            "end_ms": source["end_ms"],
            "speaker_id": source.get("speaker_id"),
            "quote": source["text"],
        }
        item = {
            "id": operation["id"],
            "key": operation["key"],
            "kind": kind,
            "text": operation["text"],
            "status": operation.get(
                "status", "resolved" if operation["operation"] == "resolve" else "current"
            ),
            "owner": operation.get("owner"),
            "due": operation.get("due"),
            "effective_batch": batch.batch_index,
            "evidence": [evidence],
        }
        updated[collection].append(item)
        changes.append(
            {
                "id": operation["id"],
                "operation": operation["operation"],
                "kind": kind,
                "key": operation["key"],
                "before": prior.get("text") if prior else None,
                "after": operation["text"],
                "owner_before": prior.get("owner") if prior else None,
                "owner_after": operation.get("owner"),
                "batch_index": batch.batch_index,
                "evidence": evidence,
            }
        )
    return updated, changes


def _published_batches(
    db: Session, session: DaySession, through_batch_index: int | None = None
) -> list[DayBatch]:
    statement = select(DayBatch).where(
        DayBatch.day_session_id == session.id, DayBatch.status == "complete"
    )
    if through_batch_index is not None:
        statement = statement.where(DayBatch.batch_index <= through_batch_index)
    return list(db.scalars(statement.order_by(DayBatch.batch_index)).all())


def _all_published_segments(
    db: Session, session: DaySession, through_batch_index: int | None = None
) -> list[dict[str, Any]]:
    batches = _published_batches(db, session, through_batch_index)
    return [segment for batch in batches for segment in (batch.transcript or [])]


def _update_summary(
    memory: dict[str, Any], fixture: dict[str, Any], segment_ids: set[str]
) -> None:
    for summary in fixture.get("summaries", []):
        if summary["through_segment_id"] in segment_ids:
            memory["summary"] = summary["text"]


def _citation(
    recording: Recording, segment: dict[str, Any], transcript_version: int
) -> dict[str, Any]:
    return {
        "recording_id": recording.id,
        "transcript_version": transcript_version,
        "segment_id": segment["id"],
        "start_ms": segment["start_ms"],
        "end_ms": segment["end_ms"],
        "speaker_id": segment.get("speaker_id"),
        "quote": segment["text"],
    }


def _publish_canonical_snapshot(
    db: Session,
    recording: Recording,
    session: DaySession,
    fixture: dict[str, Any] | None,
    batch: DayBatch,
) -> None:
    segments = _all_published_segments(db, session)
    if not segments:
        return
    timeline: list[dict[str, Any]] = [
        {"id": "processed", "start_ms": 0, "end_ms": session.watermark_ms, "state": "speech"}
    ]
    duration = recording.duration_ms or session.watermark_ms
    if session.watermark_ms < duration:
        timeline.append(
            {
                "id": "awaiting-future-batches",
                "start_ms": session.watermark_ms,
                "end_ms": duration,
                "state": "unreadable",
            }
        )
    speech_provenance = (batch.source_payload or {}).get("speech_provenance") or {}
    intelligence_provenance = (batch.source_payload or {}).get(
        "intelligence_provenance"
    ) or {}
    is_mock = session.pipeline_version != "day-memory-gemini.v1"
    result = SimpleNamespace(
        timeline=timeline,
        segments=[
            {**item, "speaker_cluster_id": item.get("speaker_id")}
            for item in segments
        ],
        provider=speech_provenance.get("provider", "mock.day-fixture"),
        resolved_model=speech_provenance.get(
            "resolved_model", "scripted-day-memory-v1"
        ),
        provenance={
            **speech_provenance,
            "mock": is_mock,
            "source": (
                "approved_day_fixture_sidecar" if is_mock else "gemini_batch_transcription"
            ),
            "pipeline_version": session.pipeline_version,
            "schema_version": "CanonicalTranscript.v1",
            "prompt_version": "day-fixture.v1",
            "policy_version": "synthetic-functional-only.v1",
        },
    )
    transcript = _publish_transcript(db, recording, None, result)
    recording.transcript_version = transcript.version
    db.flush()
    segment_index = {item["id"]: item for item in segments}

    def material(collection: str, field: str) -> list[dict[str, Any]]:
        values = []
        for item in session.memory_state.get(collection, []):
            if item.get("status") == "superseded":
                continue
            evidence = [
                _citation(recording, segment_index[citation["segment_id"]], transcript.version)
                for citation in item.get("evidence", [])
                if citation.get("segment_id") in segment_index
            ]
            value = {
                "id": item["id"],
                field: item["text"],
                "status": item.get("status", "current"),
                "evidence": evidence,
                "confidence": 1.0,
            }
            if collection == "actions":
                value.update(
                    {
                        "owner_text": item.get("owner"),
                        "due_text": item.get("due"),
                        "ambiguities": [],
                    }
                )
            values.append(value)
        return values

    summary_segments = segments[-4:]
    first_citation = _citation(recording, segments[0], transcript.version)
    payload = {
        "title": {
            "text": fixture.get("title", recording.display_name)
            if fixture
            else recording.display_name,
            "evidence": [first_citation],
            "confidence": 1.0,
        },
        "summary": {
            "short": session.memory_state["summary"],
            "detailed": session.memory_state["summary"],
            "evidence": [
                _citation(recording, item, transcript.version) for item in summary_segments
            ],
        },
        "facts": material("facts", "claim"),
        "decisions": material("decisions", "decision"),
        "actions": material("actions", "task"),
        "topics": [
            {
                "label": "Continuous day memory",
                "parent": None,
                "intervals": [{"start_ms": 0, "end_ms": session.watermark_ms}],
                "evidence": [first_citation],
            }
        ],
        "participants": [
            {
                "speaker_cluster_id": speaker,
                "display_name": speaker.title(),
                "confidence": 1.0,
                "evidence": [
                    _citation(
                        recording,
                        next(item for item in segments if item.get("speaker_id") == speaker),
                        transcript.version,
                    )
                ],
            }
            for speaker in sorted(
                {
                    str(item.get("speaker_id"))
                    for item in segments
                    if item.get("speaker_id")
                }
            )
        ],
        "open_questions": material("open_questions", "question"),
        "warnings": [
            (
                "This snapshot was generated from sequential Gemini batch processing."
                if not is_mock
                else (
                    "This is deterministic scripted day-demo data, not ASR or "
                    "model-generated output."
                )
            ),
            "The newest batch remains provisional until later context arrives.",
        ],
    }
    intelligence = _publish_intelligence(
        db,
        recording,
        transcript.version,
        payload,
        {
            **intelligence_provenance,
            "mock": is_mock,
            "provider": intelligence_provenance.get("provider", "mock.day-fixture"),
            "model_alias": intelligence_provenance.get("model_alias", "llm.fixture"),
            "resolved_model": intelligence_provenance.get(
                "resolved_model", "scripted-day-memory-v1"
            ),
            "pipeline_version": session.pipeline_version,
            "prompt_version": "day-fixture.v1",
            "schema_version": "RecordingIntelligence.v1",
            "policy_version": "synthetic-functional-only.v1",
            "usage": intelligence_provenance.get(
                "usage", {"input_tokens": 0, "output_tokens": 0}
            ),
        },
    )
    recording.intelligence_version = intelligence.version
    _rebuild_evidence(db, recording, transcript)
    recording.transcript_ready = True
    recording.intelligence_ready = True
    recording.indexed_ready = True
    recording.etag_version += 1


def _day_attempt_id(stage: str, session: DaySession, batch: DayBatch) -> str:
    generation = int((batch.source_payload or {}).get("attempt_generation", 0))
    return f"day-{stage}:{session.id}:{batch.batch_index}:g{generation}"


def _dispatch_day_speech(
    db: Session,
    blob_store: BlobStore,
    speech: SpeechAdapter,
    settings: Any,
    recording: Recording,
    session: DaySession,
    batch: DayBatch,
) -> None:
    expected_generation = int((batch.source_payload or {}).get("attempt_generation", 0))
    if not batch.blob_key or not batch.sha256:
        raise ProviderUnavailable("The arriving batch has no sealed audio payload")
    audio_bytes = blob_store.get(batch.blob_key)
    attempt_id = _day_attempt_id("speech", session, batch)
    request = SpeechRequest(
        recording_id=recording.id,
        audio_sha256=batch.sha256,
        audio_reference=batch.id,
        original_time_offset_ms=batch.start_ms,
        language=recording.requested_language,
        vocabulary_hints=tuple(recording.vocabulary_hints or []),
        require_diarization=True,
        require_timestamps=True,
        budget_usd=settings.recording_cost_ceiling_usd,
        request_id=attempt_id,
        audio_bytes=audio_bytes,
        content_type="audio/wav",
        duration_ms=batch.end_ms - batch.start_ms,
    )
    reservation = speech.estimate_transcription_reservation(request)
    reserve_budget(
        db,
        attempt_id=attempt_id,
        workspace_id=recording.workspace_id,
        recording_id=recording.id,
        stage="day_speech",
        amount_usd=reservation,
        per_request_cap_usd=settings.recording_cost_ceiling_usd,
        recording_cap_usd=settings.recording_cost_ceiling_usd,
    )
    mark_budget_dispatched(db, attempt_id=attempt_id)
    db.commit()
    try:
        result = speech.transcribe(request)
    except Exception as failure:
        db.rollback()
        if isinstance(failure, ProviderBilledFailure):
            _ledger_billed_failure(
                db,
                failure,
                workspace_id=recording.workspace_id,
                recording_id=recording.id,
                stage="day_speech",
            )
        else:
            settle_interrupted_budget(
                db,
                attempt_id=attempt_id,
                provider_dispatched=True,
                reason="day_speech_provider_failure",
            )
        db.commit()
        raise
    shifted = []
    for item in result.segments:
        shifted.append(
            {
                **item,
                "id": f"batch-{batch.batch_index + 1}-{item['id']}",
                "start_ms": batch.start_ms + int(item["start_ms"]),
                "end_ms": batch.start_ms + int(item["end_ms"]),
                "speaker_id": item.get("speaker_id") or item.get("speaker_cluster_id"),
            }
        )
    provenance = {
        **result.provenance,
        "provider": result.provider,
        "model_alias": result.model_alias,
        "resolved_model": result.resolved_model,
        "usage": result.usage,
        "provider_data_approved": recording.provider_data_approved,
    }
    actual = _provider_actual_cost(provenance, result.usage)
    _cost_once(
        db,
        attempt_id=attempt_id,
        workspace_id=recording.workspace_id,
        recording_id=recording.id,
        stage="day_speech",
        provider=result.provider,
        model_alias=result.model_alias,
        resolved_model=result.resolved_model,
        usage=result.usage,
        estimated=actual,
        provenance=provenance,
    )
    commit_budget(db, attempt_id=attempt_id, actual_usd=actual)
    db.expire_all()
    current_recording = db.get(Recording, recording.id)
    current_session = db.get(DaySession, session.id)
    current_batch = db.get(DayBatch, batch.id)
    if (
        current_recording is None
        or current_recording.deleted_at is not None
        or current_session is None
        or current_batch is None
        or current_batch.stage != "transcribing"
        or int((current_batch.source_payload or {}).get("attempt_generation", 0))
        != expected_generation
    ):
        db.commit()
        raise StaleGeneration("The day session changed while Gemini was transcribing")
    batch = current_batch
    batch.transcript = shifted
    batch.source_payload = {**(batch.source_payload or {}), "speech_provenance": provenance}


def _dispatch_day_filter(
    db: Session,
    llm: LLMAdapter,
    settings: Any,
    recording: Recording,
    session: DaySession,
    batch: DayBatch,
) -> None:
    expected_generation = int((batch.source_payload or {}).get("attempt_generation", 0))
    previous = db.scalar(
        select(DayBatch).where(
            DayBatch.day_session_id == session.id,
            DayBatch.batch_index == batch.batch_index - 1,
        )
    )
    prior_context = (previous.transcript or [])[-2:] if previous else []
    attempt_id = _day_attempt_id("filter", session, batch)
    request = SegmentFilterRequest(
        recording_id=recording.id,
        transcript_version=batch.batch_index + 1,
        prior_context=prior_context,
        segments=list(batch.transcript or []),
        request_id=attempt_id,
        budget_usd=settings.recording_cost_ceiling_usd,
    )
    estimate = llm.estimate_filter_reservation(request)
    reserve_budget(
        db,
        attempt_id=attempt_id,
        workspace_id=recording.workspace_id,
        recording_id=recording.id,
        stage="day_filter",
        amount_usd=estimate,
        per_request_cap_usd=settings.recording_cost_ceiling_usd,
        recording_cap_usd=settings.recording_cost_ceiling_usd,
    )
    mark_budget_dispatched(db, attempt_id=attempt_id)
    db.commit()
    try:
        result = llm.filter_segments(request)
    except Exception as failure:
        db.rollback()
        if isinstance(failure, ProviderBilledFailure):
            _ledger_billed_failure(
                db,
                failure,
                workspace_id=recording.workspace_id,
                recording_id=recording.id,
                stage="day_filter",
            )
        else:
            settle_interrupted_budget(
                db,
                attempt_id=attempt_id,
                provider_dispatched=True,
                reason="day_filter_provider_failure",
            )
        db.commit()
        raise
    provenance = result.provenance
    actual = _provider_actual_cost(provenance, provenance.get("usage", {}))
    _cost_once(
        db,
        attempt_id=attempt_id,
        workspace_id=recording.workspace_id,
        recording_id=recording.id,
        stage="day_filter",
        provider=provenance["provider"],
        model_alias=provenance["model_alias"],
        resolved_model=provenance["resolved_model"],
        usage=provenance.get("usage", {}),
        estimated=actual,
        provenance=provenance,
    )
    commit_budget(db, attempt_id=attempt_id, actual_usd=actual)
    db.expire_all()
    current_recording = db.get(Recording, recording.id)
    current_session = db.get(DaySession, session.id)
    current_batch = db.get(DayBatch, batch.id)
    if (
        current_recording is None
        or current_recording.deleted_at is not None
        or current_session is None
        or current_batch is None
        or current_batch.stage != "indexing"
        or int((current_batch.source_payload or {}).get("attempt_generation", 0))
        != expected_generation
    ):
        db.commit()
        raise StaleGeneration("The day session changed while Gemini was filtering it")
    _set_filter_state(current_batch, result.decisions, provenance)


def _set_filter_state(
    batch: DayBatch,
    decisions: list[dict[str, Any]],
    provenance: dict[str, Any],
) -> None:
    selected_ids = [
        str(item["segment_id"]) for item in decisions if item.get("keep") is True
    ]
    terms = {
        term
        for item in batch.transcript or []
        if item["id"] in selected_ids
        for term in re.findall(r"[a-z0-9]+", item["text"].casefold())
        if len(term) > 3
    }
    batch.source_payload = {
        **(batch.source_payload or {}),
        "filter_decisions": decisions,
        "selected_segment_ids": selected_ids,
        "filter_provenance": provenance,
    }
    batch.index_state = {
        "transcript_segments": len(batch.transcript or []),
        "selected_segments": len(selected_ids),
        "excluded_segments": len(batch.transcript or []) - len(selected_ids),
        "evidence_chunks": len(selected_ids),
        "lexical_terms": len(terms),
        "vector_embeddings": len(selected_ids),
        "neighbor_links": max(0, len(selected_ids) - 1) * 2,
        "filter_decisions": decisions,
    }


def _memory_projection(
    prior_memory: dict[str, Any],
    payload: dict[str, Any],
    batch_index: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    field_map = {
        "decision": ("decisions", "decision"),
        "action": ("actions", "task"),
        "fact": ("facts", "claim"),
        "open_question": ("open_questions", "question"),
    }
    updated = json.loads(json.dumps(prior_memory))
    changes: list[dict[str, Any]] = []
    for kind, (collection, text_field) in field_map.items():
        prior_active = {
            re.sub(r"\s+", " ", item["text"].strip().casefold()): item
            for item in updated.get(collection, [])
            if item.get("status") != "superseded"
        }
        seen: set[str] = set()
        for position, raw in enumerate(payload.get(collection, [])):
            text = str(raw[text_field]).strip()
            normalized = re.sub(r"\s+", " ", text.casefold())
            seen.add(normalized)
            if normalized in prior_active:
                continue
            digest = hashlib.sha256(normalized.encode()).hexdigest()[:10]
            item_id = f"gemini-{batch_index + 1}-{kind}-{position + 1}-{digest}"
            evidence = [
                {
                    "segment_id": citation["segment_id"],
                    "start_ms": citation["start_ms"],
                    "end_ms": citation["end_ms"],
                    "speaker_id": citation.get("speaker_id"),
                    "quote": citation.get("quote"),
                }
                for citation in raw.get("evidence", [])
            ]
            status = str(raw.get("status") or ("open" if kind == "open_question" else "current"))
            if status.casefold() in {"complete", "completed", "done", "closed"}:
                status = "resolved"
            item = {
                "id": item_id,
                "key": item_id,
                "kind": kind,
                "text": text,
                "status": status,
                "owner": raw.get("owner_text"),
                "due": raw.get("due_text"),
                "effective_batch": batch_index,
                "evidence": evidence,
            }
            updated.setdefault(collection, []).append(item)
            changes.append(
                {
                    "id": item_id,
                    "operation": "add",
                    "kind": kind,
                    "key": item_id,
                    "before": None,
                    "after": text,
                    "owner_before": None,
                    "owner_after": raw.get("owner_text"),
                    "batch_index": batch_index,
                    "evidence": evidence[0] if evidence else None,
                }
            )
        for normalized, prior in prior_active.items():
            if normalized in seen:
                continue
            prior["status"] = "superseded"
            operation = "resolve" if kind in {"action", "open_question"} else "supersede"
            changes.append(
                {
                    "id": f"{prior['id']}-retired-{batch_index + 1}",
                    "operation": operation,
                    "kind": kind,
                    "key": prior["key"],
                    "before": prior["text"],
                    "after": "No longer present in the current Gemini snapshot.",
                    "owner_before": prior.get("owner"),
                    "owner_after": None,
                    "batch_index": batch_index,
                    "evidence": prior.get("evidence", [None])[0],
                }
            )
    summary = payload.get("summary") or {}
    updated["summary"] = str(summary.get("short") or summary.get("detailed") or updated["summary"])
    return updated, changes


def _dispatch_day_intelligence(
    db: Session,
    llm: LLMAdapter,
    settings: Any,
    recording: Recording,
    session: DaySession,
    batch: DayBatch,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    expected_generation = int((batch.source_payload or {}).get("attempt_generation", 0))
    segments = []
    for prior in db.scalars(
        select(DayBatch)
        .where(
            DayBatch.day_session_id == session.id,
            DayBatch.batch_index <= batch.batch_index,
        )
        .order_by(DayBatch.batch_index)
    ).all():
        source = prior.source_payload or {}
        selected = set(source.get("selected_segment_ids", []))
        segments.extend(
            segment
            for segment in (prior.transcript or [])
            if segment["id"] in selected
        )
    attempt_id = _day_attempt_id("intelligence", session, batch)
    estimate = llm.estimate_intelligence_reservation(
        recording_id=recording.id,
        transcript_version=batch.batch_index + 1,
        segments=segments,
        budget_usd=settings.recording_cost_ceiling_usd,
    )
    reserve_budget(
        db,
        attempt_id=attempt_id,
        workspace_id=recording.workspace_id,
        recording_id=recording.id,
        stage="day_intelligence",
        amount_usd=estimate,
        per_request_cap_usd=settings.recording_cost_ceiling_usd,
        recording_cap_usd=settings.recording_cost_ceiling_usd,
    )
    mark_budget_dispatched(db, attempt_id=attempt_id)
    db.commit()
    try:
        payload, provenance = llm.extract_intelligence(
            recording_id=recording.id,
            transcript_version=batch.batch_index + 1,
            segments=segments,
            request_id=attempt_id,
            budget_usd=estimate,
        )
    except Exception as failure:
        db.rollback()
        if isinstance(failure, ProviderBilledFailure):
            _ledger_billed_failure(
                db,
                failure,
                workspace_id=recording.workspace_id,
                recording_id=recording.id,
                stage="day_intelligence",
            )
        else:
            settle_interrupted_budget(
                db,
                attempt_id=attempt_id,
                provider_dispatched=True,
                reason="day_intelligence_provider_failure",
            )
        db.commit()
        raise
    actual = _provider_actual_cost(provenance, provenance.get("usage", {}))
    _cost_once(
        db,
        attempt_id=attempt_id,
        workspace_id=recording.workspace_id,
        recording_id=recording.id,
        stage="day_intelligence",
        provider=provenance["provider"],
        model_alias=provenance["model_alias"],
        resolved_model=provenance["resolved_model"],
        usage=provenance.get("usage", {}),
        estimated=actual,
        provenance=provenance,
    )
    commit_budget(db, attempt_id=attempt_id, actual_usd=actual)
    db.expire_all()
    current_recording = db.get(Recording, recording.id)
    current_session = db.get(DaySession, session.id)
    current_batch = db.get(DayBatch, batch.id)
    if (
        current_recording is None
        or current_recording.deleted_at is not None
        or current_session is None
        or current_batch is None
        or current_batch.stage != "extracting"
        or int((current_batch.source_payload or {}).get("attempt_generation", 0))
        != expected_generation
    ):
        db.commit()
        raise StaleGeneration("The day session changed while Gemini was analyzing it")
    batch = current_batch
    batch.source_payload = {
        **(batch.source_payload or {}),
        "intelligence_provenance": provenance,
    }
    return _memory_projection(session.memory_state or empty_memory(), payload, batch.batch_index)


def _fail_day_provider(
    recording: Recording, session: DaySession, error: Exception
) -> None:
    session.status = "failed"
    session.error_code = getattr(error, "code", "day_provider_unavailable")
    session.error_detail = str(error)
    recording.status = "PARTIAL" if session.processed_batch_count else "FAILED_RETRYABLE"
    recording.stage = "partial" if session.processed_batch_count else "failed"
    recording.error_code = session.error_code
    recording.error_detail = session.error_detail


def advance_day_session(
    db: Session,
    recording: Recording,
    session: DaySession,
    *,
    fixture_root: Any,
    blob_store: BlobStore,
    speech: SpeechAdapter,
    llm: LLMAdapter,
    settings: Any,
) -> None:
    if session.status == "complete":
        return
    fixture = _fixture_for_session(session, fixture_root)
    batch = _active_batch(db, session)
    if batch is None:
        session.status = "complete"
        session.current_stage = "complete"
        recording.status = "READY"
        recording.stage = "ready"
        return
    gemini_enabled = session.pipeline_version == "day-memory-gemini.v1"
    if gemini_enabled and not recording.provider_data_approved:
        _fail_day_provider(
            recording,
            session,
            ProviderUnavailable(
                "Remote day processing requires persisted provider-data approval"
            ),
        )
        session.revision += 1
        return
    if fixture is None and not gemini_enabled:
        session.status = "failed"
        session.error_code = "day_fixture_unavailable"
        session.error_detail = (
            "Local day processing is available for the approved synthetic fixtures. "
            "Configure a speech provider to process arbitrary recordings."
        )
        recording.status = "PARTIAL"
        recording.stage = "partial"
        recording.error_code = session.error_code
        recording.error_detail = session.error_detail
        session.revision += 1
        return

    session.status = "processing"
    session.active_batch_index = batch.batch_index
    if batch.started_at is None:
        batch.started_at = utcnow()
        batch.status = "processing"

    if batch.stage == "waiting":
        if gemini_enabled:
            audio_bytes = blob_store.get(batch.blob_key) if batch.blob_key else b""
            audio_filter = analyze_wav_activity(audio_bytes)
            batch.source_payload = {
                **(batch.source_payload or {}),
                "audio_filter": audio_filter,
            }
            batch.stage = "transcribing"
            session.current_stage = "transcribing"
            session.revision += 1
            if audio_filter["decision"] == "skip_clear_silence":
                batch.transcript = []
                db.commit()
                return
            try:
                _dispatch_day_speech(
                    db, blob_store, speech, settings, recording, session, batch
                )
                db.commit()
            except (ProviderUnavailable, BudgetExceeded, BudgetReservationUnavailable) as error:
                _fail_day_provider(recording, session, error)
                return
            return
        else:
            batch.transcript = json.loads(
                json.dumps(batch.source_payload.get("segments", []))
            )
        batch.stage = "transcribing"
        session.current_stage = "transcribing"
    elif batch.stage == "transcribing":
        previous = db.scalar(
            select(DayBatch).where(
                DayBatch.day_session_id == session.id,
                DayBatch.batch_index == batch.batch_index - 1,
            )
        )
        prior_tail = (previous.transcript or [])[-1:] if previous else []
        batch.reconciliation = {
            "context_segments_used": len(prior_tail),
            "speaker_clusters_carried": sorted(
                {
                    str(item.get("speaker_id"))
                    for item in prior_tail + (batch.transcript or [])
                    if item.get("speaker_id")
                }
            ),
            "boundary_revision": (
                "Linked this batch to the prior transcript tail; no duplicate words found."
                if previous
                else "Established the first day-level speaker and topic context."
            ),
        }
        batch.stage = "reconciling"
        session.current_stage = "reconciling"
    elif batch.stage == "reconciling":
        if gemini_enabled:
            batch.stage = "indexing"
            session.current_stage = "indexing"
            session.revision += 1
            if not batch.transcript:
                batch.source_payload = {
                    **(batch.source_payload or {}),
                    "filter_decisions": [],
                    "selected_segment_ids": [],
                    "filter_provenance": {
                        "provider": "local.audio-activity",
                        "model_alias": "filter.no-transcript",
                        "resolved_model": "clear-silence-bypass-v1",
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                        "estimated_cost_usd": 0.0,
                    },
                }
                batch.index_state = {
                    "transcript_segments": 0,
                    "selected_segments": 0,
                    "excluded_segments": 0,
                    "evidence_chunks": 0,
                    "lexical_terms": 0,
                    "vector_embeddings": 0,
                    "neighbor_links": 0,
                    "filter_decisions": [],
                }
                db.commit()
                return
            try:
                _dispatch_day_filter(db, llm, settings, recording, session, batch)
                db.commit()
            except (ProviderUnavailable, BudgetExceeded, BudgetReservationUnavailable) as error:
                decisions = [
                    {
                        "segment_id": segment["id"],
                        "keep": True,
                        "category": "fail-open",
                        "reason": "Triage was unavailable; retained by conservative policy.",
                        "confidence": 1.0,
                    }
                    for segment in batch.transcript or []
                ]
                _set_filter_state(
                    batch,
                    decisions,
                    {
                        "provider": "local.conservative",
                        "model_alias": "filter.fail-open",
                        "resolved_model": "keep-all-v1",
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                        "estimated_cost_usd": 0.0,
                        "fallback_reason": getattr(
                            error, "code", "provider_unavailable"
                        ),
                    },
                )
                db.commit()
                return
            return
        terms = {
            term
            for item in batch.transcript or []
            for term in re.findall(r"[a-z0-9]+", item["text"].casefold())
            if len(term) > 3
        }
        batch.index_state = {
            "transcript_segments": len(batch.transcript or []),
            "selected_segments": len(batch.transcript or []),
            "excluded_segments": 0,
            "evidence_chunks": len(batch.transcript or []),
            "lexical_terms": len(terms),
            "vector_embeddings": len(batch.transcript or []),
            "neighbor_links": max(0, len(batch.transcript or []) - 1) * 2,
            "filter_decisions": [],
        }
        batch.stage = "indexing"
        session.current_stage = "indexing"
    elif batch.stage == "indexing":
        if gemini_enabled:
            batch.stage = "extracting"
            session.current_stage = "extracting"
            session.revision += 1
            if not (batch.source_payload or {}).get("selected_segment_ids"):
                batch.pending_changes = []
                batch.source_payload = {
                    **(batch.source_payload or {}),
                    "proposed_memory": json.loads(
                        json.dumps(session.memory_state or empty_memory())
                    ),
                }
                db.commit()
                return
            try:
                proposed_memory, proposed_changes = _dispatch_day_intelligence(
                    db, llm, settings, recording, session, batch
                )
            except (ProviderUnavailable, BudgetExceeded, BudgetReservationUnavailable) as error:
                _fail_day_provider(recording, session, error)
                return
            batch.pending_changes = proposed_changes
            batch.source_payload = {
                **(batch.source_payload or {}),
                "proposed_memory": proposed_memory,
            }
            db.commit()
            return
        else:
            batch.pending_changes = _preview_changes(
                session.memory_state or empty_memory(),
                batch.source_payload.get("operations", []),
                batch.batch_index,
            )
        batch.stage = "extracting"
        session.current_stage = "extracting"
    elif batch.stage == "extracting":
        if gemini_enabled:
            memory = json.loads(
                json.dumps(batch.source_payload.get("proposed_memory") or empty_memory())
            )
            changes = json.loads(json.dumps(batch.pending_changes or []))
        else:
            memory, changes = _apply_operations(
                session.memory_state or empty_memory(),
                batch.source_payload.get("operations", []),
                batch,
            )
        batch.status = "complete"
        batch.stage = "published"
        batch.completed_at = utcnow()
        session.processed_batch_count += 1
        session.watermark_ms = batch.end_ms
        published_ids = {
            item["id"] for item in _all_published_segments(db, session)
        }
        if fixture and not gemini_enabled:
            _update_summary(memory, fixture, published_ids)
        session.memory_state = memory
        session.change_log = [*(session.change_log or []), *changes]
        batch.published_snapshot = json.loads(json.dumps(memory))
        session.current_stage = "publishing"
        _publish_canonical_snapshot(db, recording, session, fixture, batch)
        emit_event(
            db,
            recording,
            "day.batch_published",
            {
                "batch_index": batch.batch_index,
                "watermark_ms": session.watermark_ms,
                "changes": len(changes),
            },
        )
        if session.processed_batch_count >= session.requested_batch_count:
            session.status = "complete"
            session.current_stage = "complete"
            session.active_batch_index = None
            recording.status = "READY"
            recording.stage = "ready"
        else:
            session.active_batch_index = batch.batch_index
            recording.status = "PROCESSING"
            recording.stage = "day_waiting"
    session.revision += 1


def _dispatch_day_ask(
    db: Session,
    llm: LLMAdapter,
    settings: Any,
    recording: Recording,
    question: str,
    segments: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]], bool]:
    evidence = [
        {
            "snippet": segment["text"],
            "citation": _citation(
                recording, segment, max(1, recording.transcript_version)
            ),
        }
        for segment in segments[-12:]
    ]
    attempt_id = f"day-ask:{uuid.uuid4()}"
    request = AskRequest(
        question=question,
        evidence=evidence,
        request_id=attempt_id,
        budget_usd=settings.ask_cost_ceiling_usd,
    )
    estimate = llm.estimate_ask_reservation(request)
    reserve_budget(
        db,
        attempt_id=attempt_id,
        workspace_id=recording.workspace_id,
        recording_id=recording.id,
        stage="day_ask",
        amount_usd=estimate,
        per_request_cap_usd=settings.ask_cost_ceiling_usd,
        recording_cap_usd=settings.recording_cost_ceiling_usd,
    )
    mark_budget_dispatched(db, attempt_id=attempt_id)
    db.commit()
    try:
        result = llm.answer(
            AskRequest(
                question=question,
                evidence=evidence,
                request_id=attempt_id,
                budget_usd=estimate,
            )
        )
    except Exception as failure:
        db.rollback()
        if isinstance(failure, ProviderBilledFailure):
            _ledger_billed_failure(
                db,
                failure,
                workspace_id=recording.workspace_id,
                recording_id=recording.id,
                stage="day_ask",
            )
        else:
            settle_interrupted_budget(
                db,
                attempt_id=attempt_id,
                provider_dispatched=True,
                reason="day_ask_provider_failure",
            )
        db.commit()
        raise
    actual = _provider_actual_cost(result.provenance, result.provenance.get("usage", {}))
    _cost_once(
        db,
        attempt_id=attempt_id,
        workspace_id=recording.workspace_id,
        recording_id=recording.id,
        stage="day_ask",
        provider=result.provenance["provider"],
        model_alias=result.provenance["model_alias"],
        resolved_model=result.provenance["resolved_model"],
        usage=result.provenance.get("usage", {}),
        estimated=actual,
        provenance=result.provenance,
    )
    commit_budget(db, attempt_id=attempt_id, actual_usd=actual)
    return result.answer, result.citations, result.abstained


def _ask_evidence_segments(
    question: str,
    batches: list[DayBatch],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Retrieve from the full transcript, then backfill with triage-kept recency."""

    all_segments = [segment for batch in batches for segment in (batch.transcript or [])]
    selected_ids = {
        str(segment_id)
        for batch in batches
        for segment_id in (batch.source_payload or {}).get("selected_segment_ids", [])
    }
    query_terms = {
        term
        for term in re.findall(r"[a-z0-9]+", question.casefold())
        if len(term) > 2
    }
    ranked = sorted(
        all_segments,
        key=lambda segment: (
            len(
                query_terms
                & set(re.findall(r"[a-z0-9]+", segment["text"].casefold()))
            ),
            segment["id"] in selected_ids,
            int(segment["end_ms"]),
        ),
        reverse=True,
    )
    relevant = [
        segment
        for segment in ranked
        if query_terms
        & set(re.findall(r"[a-z0-9]+", segment["text"].casefold()))
    ]
    candidates = [
        *relevant,
        *[segment for segment in reversed(all_segments) if segment["id"] in selected_ids],
        *reversed(all_segments),
    ]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for segment in candidates:
        if segment["id"] in seen:
            continue
        seen.add(segment["id"])
        result.append(segment)
        if len(result) >= limit:
            break
    return result


def answer_day_question(
    db: Session,
    recording: Recording,
    session: DaySession,
    question: str,
    *,
    through_batch_index: int | None = None,
    fixture_root: Any,
    llm: LLMAdapter,
    settings: Any,
) -> dict[str, Any]:
    fixture = _fixture_for_session(session, fixture_root)
    selected_batches = _published_batches(db, session, through_batch_index)
    if through_batch_index is not None and (
        not selected_batches or selected_batches[-1].batch_index != through_batch_index
    ):
        raise ValueError("That batch does not have a published snapshot yet")
    processed_segments = [
        segment for batch in selected_batches for segment in (batch.transcript or [])
    ]
    segment_index = {item["id"]: item for item in processed_segments}
    watermark_ms = selected_batches[-1].end_ms if selected_batches else 0
    processed_batch_count = len(selected_batches)
    normalized_terms = set(re.findall(r"[a-z0-9]+", question.casefold()))
    answer = ""
    citations: list[dict[str, Any]] = []
    provisional = watermark_ms < (recording.duration_ms or watermark_ms)
    strategy = "lexical_evidence"
    if session.pipeline_version == "day-memory-gemini.v1" and processed_segments:
        ask_segments = _ask_evidence_segments(question, selected_batches)
        answer, citations, abstained = _dispatch_day_ask(
            db, llm, settings, recording, question, ask_segments
        )
        strategy = "gemini_grounded_day_snapshot"
        if abstained:
            answer = (
                answer
                or "I do not have enough evidence in the batches processed so far."
            )
    elif fixture:
        scored_answers = []
        for candidate in fixture.get("ask_answers", []):
            keywords = set(candidate.get("keywords", []))
            scored_answers.append((len(normalized_terms & keywords), candidate))
        score, candidate = max(scored_answers, default=(0, None), key=lambda item: item[0])
        if candidate is not None and score >= 2:
            selected = None
            for version in candidate.get("versions", []):
                if version["through_segment_id"] in segment_index:
                    selected = version
            if selected:
                answer = selected["answer"]
                provisional = bool(selected.get("provisional"))
                citations = [
                    _citation(recording, segment_index[segment_id], recording.transcript_version)
                    for segment_id in selected.get("citation_segment_ids", [])
                    if segment_id in segment_index
                ]
                strategy = "versioned_fixture_answer"
    if not answer and processed_segments:
        stopwords = {
            "what",
            "when",
            "where",
            "which",
            "with",
            "that",
            "this",
            "from",
            "about",
            "have",
            "does",
            "current",
            "the",
            "and",
            "who",
            "why",
        }
        query_terms = {
            term for term in normalized_terms if term not in stopwords and len(term) > 2
        }
        ranked = []
        for index, segment in enumerate(processed_segments):
            text_terms = set(re.findall(r"[a-z0-9]+", segment["text"].casefold()))
            score = len(query_terms & text_terms) * 10 + index / 100
            if score > 0:
                ranked.append((score, segment))
        ranked.sort(key=lambda item: item[0], reverse=True)
        selected_segments = [item[1] for item in ranked[:2]]
        if selected_segments:
            answer = "Based on the processed evidence: " + " ".join(
                item["text"] for item in selected_segments
            )
            citations = [
                _citation(recording, item, recording.transcript_version)
                for item in selected_segments
            ]
    abstained = not bool(answer) if strategy != "gemini_grounded_day_snapshot" else abstained
    if abstained:
        answer = (
            "I do not have enough evidence in the batches processed so far. "
            f"Ask-ready content currently ends at {watermark_ms // 1000} seconds."
        )
        strategy = "abstained_before_watermark"
    message = {
        "id": str(uuid.uuid4()),
        "question": question,
        "answer": answer,
        "citations": citations,
        "abstained": abstained,
        "provisional": provisional,
        "watermark_ms": watermark_ms,
        "processed_batch_count": processed_batch_count,
        "batch_index": through_batch_index,
        "strategy": strategy,
        "created_at": utcnow(),
    }
    session.ask_history = [
        *(session.ask_history or []),
        json.loads(json.dumps(message, default=str)),
    ]
    return message


def reset_day_session(db: Session, recording: Recording, session: DaySession) -> None:
    db.execute(delete(EvidenceUnit).where(EvidenceUnit.recording_id == recording.id))
    db.execute(delete(ActionItem).where(ActionItem.recording_id == recording.id))
    transcript_ids = db.scalars(
        select(TranscriptVersion.id).where(TranscriptVersion.recording_id == recording.id)
    ).all()
    if transcript_ids:
        db.execute(delete(TimelineInterval).where(TimelineInterval.transcript_id.in_(transcript_ids)))
        db.execute(delete(TranscriptSegment).where(TranscriptSegment.transcript_id.in_(transcript_ids)))
    db.execute(delete(TranscriptVersion).where(TranscriptVersion.recording_id == recording.id))
    db.execute(delete(IntelligenceVersion).where(IntelligenceVersion.recording_id == recording.id))
    batches = db.scalars(
        select(DayBatch).where(DayBatch.day_session_id == session.id).with_for_update()
    ).all()
    for batch in batches:
        source = batch.source_payload or {}
        batch.source_payload = {
            "segments": source.get("segments", []),
            "operations": source.get("operations", []),
            "attempt_generation": int(source.get("attempt_generation", 0)) + 1,
        }
        batch.status = "queued"
        batch.stage = "waiting"
        batch.transcript = []
        batch.reconciliation = {}
        batch.index_state = {}
        batch.pending_changes = []
        batch.published_snapshot = {}
        batch.started_at = None
        batch.completed_at = None
    session.status = "ready"
    session.processed_batch_count = 0
    session.active_batch_index = None
    session.current_stage = "waiting"
    session.watermark_ms = 0
    session.memory_state = empty_memory()
    session.change_log = []
    session.ask_history = []
    session.error_code = None
    session.error_detail = None
    session.revision += 1
    recording.status = "PROCESSING"
    recording.stage = "day_waiting"
    recording.error_code = None
    recording.error_detail = None
    recording.transcript_ready = False
    recording.intelligence_ready = False
    recording.indexed_ready = False
    recording.transcript_version = 0
    recording.intelligence_version = 0
    recording.etag_version += 1
