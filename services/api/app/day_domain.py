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
from .day_fixture import choose_batch_boundaries, find_day_fixture, split_wav
from .domain import (
    _publish_intelligence,
    _publish_transcript,
    _rebuild_evidence,
    emit_event,
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
        "mock": bool(fixture),
        "notice": (
            fixture.get("provenance", {}).get("notice")
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


def _all_published_segments(db: Session, session: DaySession) -> list[dict[str, Any]]:
    batches = db.scalars(
        select(DayBatch)
        .where(DayBatch.day_session_id == session.id, DayBatch.status == "complete")
        .order_by(DayBatch.batch_index)
    ).all()
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
    fixture: dict[str, Any],
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
    result = SimpleNamespace(
        timeline=timeline,
        segments=[
            {**item, "speaker_cluster_id": item.get("speaker_id")}
            for item in segments
        ],
        provider="mock.day-fixture",
        resolved_model="scripted-day-memory-v1",
        provenance={
            "mock": True,
            "source": "approved_day_fixture_sidecar",
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
            "text": fixture.get("title", recording.display_name),
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
            "This is deterministic scripted day-demo data, not ASR or model-generated output.",
            "The newest batch remains provisional until later context arrives.",
        ],
    }
    intelligence = _publish_intelligence(
        db,
        recording,
        transcript.version,
        payload,
        {
            "mock": True,
            "provider": "mock.day-fixture",
            "model_alias": "llm.fixture",
            "resolved_model": "scripted-day-memory-v1",
            "pipeline_version": session.pipeline_version,
            "prompt_version": "day-fixture.v1",
            "schema_version": "RecordingIntelligence.v1",
            "policy_version": "synthetic-functional-only.v1",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    )
    recording.intelligence_version = intelligence.version
    _rebuild_evidence(db, recording, transcript)
    recording.transcript_ready = True
    recording.intelligence_ready = True
    recording.indexed_ready = True
    recording.etag_version += 1


def advance_day_session(
    db: Session,
    recording: Recording,
    session: DaySession,
    *,
    fixture_root: Any,
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
    if fixture is None:
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
        batch.transcript = json.loads(json.dumps(batch.source_payload.get("segments", [])))
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
        terms = {
            term
            for item in batch.transcript or []
            for term in re.findall(r"[a-z0-9]+", item["text"].casefold())
            if len(term) > 3
        }
        batch.index_state = {
            "evidence_chunks": len(batch.transcript or []),
            "lexical_terms": len(terms),
            "vector_embeddings": len(batch.transcript or []),
            "neighbor_links": max(0, len(batch.transcript or []) - 1) * 2,
        }
        batch.stage = "indexing"
        session.current_stage = "indexing"
    elif batch.stage == "indexing":
        batch.pending_changes = _preview_changes(
            session.memory_state or empty_memory(),
            batch.source_payload.get("operations", []),
            batch.batch_index,
        )
        batch.stage = "extracting"
        session.current_stage = "extracting"
    elif batch.stage == "extracting":
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
        _update_summary(memory, fixture, published_ids)
        session.memory_state = memory
        session.change_log = [*(session.change_log or []), *changes]
        batch.published_snapshot = json.loads(json.dumps(memory))
        session.current_stage = "publishing"
        _publish_canonical_snapshot(db, recording, session, fixture)
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


def answer_day_question(
    db: Session,
    recording: Recording,
    session: DaySession,
    question: str,
    *,
    fixture_root: Any,
) -> dict[str, Any]:
    fixture = _fixture_for_session(session, fixture_root)
    processed_segments = _all_published_segments(db, session)
    segment_index = {item["id"]: item for item in processed_segments}
    normalized_terms = set(re.findall(r"[a-z0-9]+", question.casefold()))
    answer = ""
    citations: list[dict[str, Any]] = []
    provisional = session.status != "complete"
    strategy = "lexical_evidence"
    if fixture:
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
    abstained = not bool(answer)
    if abstained:
        answer = (
            "I do not have enough evidence in the batches processed so far. "
            f"Ask-ready content currently ends at {session.watermark_ms // 1000} seconds."
        )
        strategy = "abstained_before_watermark"
    message = {
        "id": str(uuid.uuid4()),
        "question": question,
        "answer": answer,
        "citations": citations,
        "abstained": abstained,
        "provisional": provisional,
        "watermark_ms": session.watermark_ms,
        "processed_batch_count": session.processed_batch_count,
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
