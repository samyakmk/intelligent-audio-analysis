from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..auth import AuthContext, require_auth, require_mutation_auth
from ..database import get_db
from ..domain import (
    BudgetExceeded,
    BudgetReservationUnavailable,
    StaleGeneration,
    answer_question,
    export_content,
    invalidate_dependent_views,
    normalize_text,
    query_terms,
    search_evidence,
    serialize_cost,
)
from ..models import (
    ActionItem,
    AskSession,
    CostEvent,
    IntelligenceVersion,
    Recap,
    Recording,
    TranscriptSegment,
    TranscriptVersion,
    Workspace,
)
from ..providers import ProviderDataPolicyDenied, ProviderUnavailable
from ..schemas import (
    AskMessageCreate,
    AskSessionCreate,
    ExportRequest,
    RecapCreate,
    SearchRequest,
    TaskPatch,
)
from .recordings import (
    _idempotent_response,
    _remember_idempotency,
    _request_fingerprint,
)

router = APIRouter(prefix="/v1", tags=["discovery"])


@router.post("/search")
def search(
    payload: SearchRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> dict[str, Any]:
    started = datetime.now(UTC)
    # Keep authorization/deletion generations stable through response
    # assembly. PostgreSQL deletion/correction waits on these rows, closing the
    # candidate-query-to-citation revocation race.
    db.scalars(
        select(Recording.id)
        .where(
            Recording.workspace_id == auth.workspace_id,
            Recording.deleted_at.is_(None),
            Recording.indexed_ready.is_(True),
        )
        .with_for_update()
    ).all()
    recording_ids = list(payload.filters.recording_ids)
    if payload.filters.recording_id:
        recording_ids.append(payload.filters.recording_id)
    constrained_scope = bool(recording_ids)
    topic_citations: set[tuple[str, str]] | None = None
    if payload.filters.date_from or payload.filters.date_to:
        date_query = select(Recording.id).where(
            Recording.workspace_id == auth.workspace_id,
            Recording.deleted_at.is_(None),
        )
        if payload.filters.date_from:
            date_query = date_query.where(
                Recording.created_at >= _parse_date(payload.filters.date_from, end=False)
            )
        if payload.filters.date_to:
            date_query = date_query.where(
                Recording.created_at <= _parse_date(payload.filters.date_to, end=True)
            )
        date_ids = set(db.scalars(date_query).all())
        if constrained_scope:
            recording_ids = [item for item in recording_ids if item in date_ids]
        else:
            recording_ids = list(date_ids)
        constrained_scope = True
    if payload.filters.topic:
        intelligence = db.scalars(
            select(IntelligenceVersion).where(
                IntelligenceVersion.workspace_id == auth.workspace_id,
                IntelligenceVersion.is_current.is_(True),
            )
        ).all()
        topic_term = normalize_text(payload.filters.topic)
        topic_ids = set()
        topic_citations = set()
        for item in intelligence:
            for topic in item.payload.get("topics", []):
                if topic_term not in normalize_text(topic.get("label", "")):
                    continue
                topic_ids.add(item.recording_id)
                topic_citations.update(
                    (item.recording_id, citation["segment_id"])
                    for citation in topic.get("evidence", [])
                )
        if constrained_scope:
            recording_ids = [item for item in recording_ids if item in topic_ids]
        else:
            recording_ids = list(topic_ids)
        constrained_scope = True
    if constrained_scope and not recording_ids:
        return _empty_search(payload.filters.mode, started)
    speaker_ids = _resolve_speaker_ids(
        db,
        auth.workspace_id,
        payload.filters.speaker,
        recording_ids if constrained_scope else None,
    )
    if payload.filters.speaker and not speaker_ids:
        return _empty_search(payload.filters.mode, started)
    action_state = payload.filters.action_state or payload.filters.action_status
    if action_state:
        action_query = (
            select(ActionItem, Recording)
            .join(Recording, Recording.id == ActionItem.recording_id)
            .where(
                ActionItem.workspace_id == auth.workspace_id,
                Recording.workspace_id == auth.workspace_id,
                Recording.deleted_at.is_(None),
                ActionItem.status == action_state,
            )
        )
        if recording_ids:
            action_query = action_query.where(ActionItem.recording_id.in_(recording_ids))
        action_rows = db.execute(action_query).all()
        terms = query_terms(payload.query)
        action_items = []
        for action, recording in action_rows:
            normalized_action = normalize_text(
                " ".join(
                    filter(None, [action.task, action.owner_text, action.due_text, action.status])
                )
            )
            score = sum(1 for term in terms if term in normalized_action)
            if terms and not score:
                continue
            citation = action.evidence[0] if action.evidence else None
            if citation is None:
                continue
            if speaker_ids and citation.get("speaker_id") not in speaker_ids:
                continue
            if (
                topic_citations is not None
                and (
                    recording.id,
                    citation["segment_id"],
                )
                not in topic_citations
            ):
                continue
            action_items.append(
                {
                    "id": action.id,
                    "recording_id": recording.id,
                    "recording_title": recording.display_name,
                    "kind": "action",
                    "snippet": action.task,
                    "start_ms": citation["start_ms"],
                    "end_ms": citation["end_ms"],
                    "speaker": citation.get("speaker_id"),
                    "score": score or 1,
                    "citation": {**citation, "recording_title": recording.display_name},
                }
            )
        action_items.sort(key=lambda item: (-item["score"], item["start_ms"]))
        return _search_response(action_items[: payload.limit], payload.filters.mode, started)
    results = search_evidence(
        db,
        auth.workspace_id,
        payload.query,
        recording_ids=recording_ids if constrained_scope else None,
        speaker_ids=speaker_ids,
        limit=payload.limit,
    )
    if topic_citations is not None:
        results = [
            item
            for item in results
            if (
                item["recording"]["id"],
                item["citation"]["segment_id"],
            )
            in topic_citations
        ]
    items = [
        {
            "id": item["id"],
            "recording_id": item["recording"]["id"],
            "recording_title": item["recording"]["display_name"],
            "kind": "transcript",
            "snippet": item["snippet"],
            "start_ms": item["citation"]["start_ms"],
            "end_ms": item["citation"]["end_ms"],
            "speaker": item["citation"].get("speaker_id"),
            "score": item["score"],
            "citation": {
                **item["citation"],
                "recording_title": item["recording"]["display_name"],
            },
        }
        for item in results
    ]
    return _search_response(items, payload.filters.mode, started)


@router.post("/ask-sessions", status_code=201)
def create_ask_session(
    payload: AskSessionCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    fingerprint = _request_fingerprint(payload)
    operation = f"ask-session:{auth.principal_id}"
    workspace = db.scalar(
        select(Workspace).where(Workspace.id == auth.workspace_id).with_for_update()
    )
    if workspace is None:
        raise HTTPException(status_code=403, detail="Workspace is unavailable")
    prior = _idempotent_response(db, auth.workspace_id, operation, idempotency_key, fingerprint)
    if prior is not None:
        return prior
    scope = payload.scope
    scope_type = payload.scope_type or scope.type
    recording_ids = list(payload.recording_ids)
    selection_ids = list(scope.segment_ids)
    if scope.recording_id:
        recording_ids = [scope.recording_id]
    if scope_type in {"recording", "selection"} and not recording_ids:
        raise HTTPException(status_code=422, detail="This Ask scope requires a recording_id")
    if recording_ids:
        authorized = set(
            db.scalars(
                select(Recording.id).where(
                    Recording.workspace_id == auth.workspace_id,
                    Recording.deleted_at.is_(None),
                    Recording.id.in_(recording_ids),
                )
            ).all()
        )
        if authorized != set(recording_ids):
            raise HTTPException(status_code=404, detail="Recording not found")
    if scope_type == "selection":
        transcript = db.scalar(
            select(TranscriptVersion).where(
                TranscriptVersion.workspace_id == auth.workspace_id,
                TranscriptVersion.recording_id == recording_ids[0],
                TranscriptVersion.is_current.is_(True),
            )
        )
        if transcript is None:
            raise HTTPException(status_code=409, detail="Selection transcript is not ready")
        public_ids = {
            item.id.split(":", 1)[1]
            for item in db.scalars(
                select(TranscriptSegment).where(TranscriptSegment.transcript_id == transcript.id)
            ).all()
        }
        if not selection_ids or not set(selection_ids).issubset(public_ids):
            raise HTTPException(status_code=422, detail="Selection contains unknown segment IDs")
    ask_session = AskSession(
        id=str(uuid.uuid4()),
        workspace_id=auth.workspace_id,
        principal_id=auth.principal_id,
        scope_type=scope_type,
        recording_ids=recording_ids,
        selection_segment_ids=selection_ids,
    )
    db.add(ask_session)
    db.flush()
    response_scope: dict[str, Any] = {"type": scope_type}
    if recording_ids:
        response_scope["recording_id"] = recording_ids[0]
    if selection_ids:
        response_scope["segment_ids"] = selection_ids
    result = jsonable_encoder(
        {
            "id": ask_session.id,
            "scope": response_scope,
            "created_at": ask_session.created_at,
            "max_spend_usd": request.app.state.settings.ask_cost_ceiling_usd,
        }
    )
    _remember_idempotency(
        db,
        auth.workspace_id,
        operation,
        idempotency_key,
        fingerprint,
        result,
        201,
    )
    db.commit()
    return result


@router.post("/ask-sessions/{ask_session_id}/messages", status_code=201)
def ask_message(
    ask_session_id: str,
    payload: AskMessageCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    question = payload.content or payload.question
    if not question:
        raise HTTPException(status_code=422, detail="Message content is required")
    settings = request.app.state.settings
    if payload.deep and (
        settings.provider_mode != "gemini" or not settings.allow_remote_provider_calls
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "capability_unavailable",
                "message": "Deep Ask requires the configured Gemini provider.",
            },
        )
    workspace = db.scalar(
        select(Workspace).where(Workspace.id == auth.workspace_id).with_for_update()
    )
    if workspace is None:
        raise HTTPException(status_code=403, detail="Workspace is unavailable")
    ask_session = db.scalar(
        select(AskSession).where(
            AskSession.id == ask_session_id,
            AskSession.workspace_id == auth.workspace_id,
            AskSession.principal_id == auth.principal_id,
        )
    )
    if ask_session is None:
        raise HTTPException(status_code=404, detail="Ask session not found")
    fingerprint = _request_fingerprint(payload)
    operation = f"ask-message:{auth.principal_id}:{ask_session.id}"
    # Hold the source rows through answer publication.  Corrections, deletion,
    # and regeneration all update these rows, so PostgreSQL serializes them
    # behind this read and cannot publish a stale answer after revocation.
    scope_query = select(Recording).where(
        Recording.workspace_id == auth.workspace_id,
        Recording.deleted_at.is_(None),
        Recording.indexed_ready.is_(True),
    )
    if ask_session.recording_ids:
        scope_query = scope_query.where(Recording.id.in_(ask_session.recording_ids))
    locked_recordings = db.scalars(scope_query.with_for_update()).all()
    if ask_session.recording_ids and {item.id for item in locked_recordings} != set(
        ask_session.recording_ids
    ):
        raise HTTPException(status_code=404, detail="Ask scope is no longer accessible")
    prior = _idempotent_response(db, auth.workspace_id, operation, idempotency_key, fingerprint)
    if prior is not None:
        return prior
    try:
        message = answer_question(
            db,
            ask_session_id=ask_session.id,
            workspace_id=auth.workspace_id,
            question=question,
            recording_ids=ask_session.recording_ids,
            selection_segment_ids=ask_session.selection_segment_ids,
            budget_usd=settings.ask_cost_ceiling_usd,
            llm=request.app.state.llm_adapter,
            deep=payload.deep,
        )
    except (BudgetExceeded, BudgetReservationUnavailable) as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": getattr(exc, "code", "budget_unavailable"),
                "message": str(exc),
            },
        ) from exc
    except StaleGeneration as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "source_changed", "message": str(exc)},
        ) from exc
    except ProviderDataPolicyDenied as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={"code": "provider_data_approval_required", "message": str(exc)},
        ) from exc
    except ProviderUnavailable as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail={"code": "provider_unavailable", "message": str(exc)},
        ) from exc
    result = jsonable_encoder(
        {
            "session_id": ask_session.id,
            "message": {
                "id": message.id,
                "role": "assistant",
                "content": message.answer,
                "created_at": message.created_at,
                "citations": message.citations,
                "status": "abstained" if message.abstained else "complete",
                "abstention_reason": "insufficient_accessible_evidence"
                if message.abstained
                else None,
                "cost_usd": float(message.provenance.get("estimated_cost_usd", 0.0)),
                "provenance": message.provenance,
            },
        }
    )
    _remember_idempotency(
        db,
        auth.workspace_id,
        operation,
        idempotency_key,
        fingerprint,
        result,
        201,
    )
    db.commit()
    return result


@router.get("/tasks")
def list_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> dict[str, Any]:
    query = (
        select(ActionItem, Recording)
        .join(Recording, Recording.id == ActionItem.recording_id)
        .where(
            ActionItem.workspace_id == auth.workspace_id,
            Recording.workspace_id == auth.workspace_id,
            Recording.deleted_at.is_(None),
        )
    )
    if status_filter:
        query = query.where(ActionItem.status == status_filter)
    rows = db.execute(query.order_by(ActionItem.created_at.desc()).with_for_update()).all()
    items = [_task_payload(task, recording.display_name) for task, recording in rows]
    return {"items": items, "total": len(items), "next_cursor": None}


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str,
    payload: TaskPatch,
    response: Response,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    task = db.scalar(
        select(ActionItem).where(
            ActionItem.id == task_id,
            ActionItem.workspace_id == auth.workspace_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    recording = db.scalar(
        select(Recording)
        .where(
            Recording.id == task.recording_id,
            Recording.workspace_id == auth.workspace_id,
            Recording.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if recording is None:
        raise HTTPException(status_code=404, detail="Task not found")
    expected = payload.version or _if_match_version(if_match)
    compare_version = expected if expected is not None else task.version
    changed = db.execute(
        update(ActionItem)
        .where(
            ActionItem.id == task_id,
            ActionItem.workspace_id == auth.workspace_id,
            ActionItem.recording_id == recording.id,
            ActionItem.version == compare_version,
        )
        .values(status=payload.status, version=ActionItem.version + 1)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=412, detail="Task version changed; refresh first")
    db.expire(task)
    db.refresh(task)
    invalidate_dependent_views(db, recording)
    db.commit()
    response.headers["ETag"] = f'"{task.version}"'
    return _task_payload(task, recording.display_name)


@router.get("/summary-styles")
def summary_styles(_: AuthContext = Depends(require_auth)) -> dict[str, Any]:
    items = [
        {"id": "standard", "name": "Standard", "description": "Balanced fixture summary."},
        {"id": "brief", "name": "Brief", "description": "Short extractive summary."},
        {"id": "detailed", "name": "Detailed", "description": "Full fixture summary."},
        {
            "id": "action_focused",
            "name": "Action focused",
            "description": "Highlights grounded action items.",
        },
    ]
    return {"items": items, "total": len(items)}


@router.get("/costs")
def costs(
    recording_id: str | None = None,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> dict[str, Any]:
    db.scalars(
        select(Recording.id)
        .where(
            Recording.workspace_id == auth.workspace_id,
            Recording.deleted_at.is_(None),
        )
        .with_for_update()
    ).all()
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    month_end = (
        datetime(now.year + 1, 1, 1, tzinfo=UTC)
        if now.month == 12
        else datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    )
    query = select(CostEvent).where(
        CostEvent.workspace_id == auth.workspace_id,
        CostEvent.created_at >= month_start,
        CostEvent.created_at < month_end,
    )
    if recording_id:
        recording = db.scalar(
            select(Recording).where(
                Recording.id == recording_id,
                Recording.workspace_id == auth.workspace_id,
                Recording.deleted_at.is_(None),
            )
        )
        if recording is None:
            raise HTTPException(status_code=404, detail="Recording not found")
        query = query.where(CostEvent.recording_id == recording_id)
    events = db.scalars(query.order_by(CostEvent.created_at.desc())).all()
    recording_titles = {
        item.id: item.display_name
        for item in db.scalars(
            select(Recording).where(Recording.workspace_id == auth.workspace_id)
        ).all()
    }
    estimated = sum(item.estimated_cost_usd for item in events)
    reconciled_values = [
        item.reconciled_cost_usd for item in events if item.reconciled_cost_usd is not None
    ]
    reconciled = sum(reconciled_values)
    by_stage: dict[str, float] = defaultdict(float)
    for item in events:
        by_stage[item.stage] += item.estimated_cost_usd
    workspace = db.get(Workspace, auth.workspace_id)
    return {
        "period": now.strftime("%Y-%m"),
        "estimated_incurred_usd": round(estimated, 6),
        "reconciled_usd": round(reconciled, 6),
        "budget_usd": workspace.monthly_spend_limit_usd,
        "baseline_estimate_usd": 0.0,
        "optimized_estimate_usd": round(estimated, 6),
        "modeled_delta_usd": 0.0,
        "events": [
            _frontend_cost(item, recording_titles.get(item.recording_id)) for item in events
        ],
        "by_stage": [
            {"stage": stage, "amount_usd": round(amount, 6)}
            for stage, amount in sorted(by_stage.items())
        ],
        "baseline_version": "not-computed-functional-fixture",
        "quality_gate_passed": False,
        "comparison_eligible": False,
        "notice": (
            "Gemini costs are provider-usage-metered public-rate estimates; invoice "
            "reconciliation and savings claims are not implemented."
            if any(item.provider == "google.gemini" for item in events)
            else "Fixture calls cost $0 and are excluded from savings and model-quality claims."
        ),
    }


@router.post("/recaps", status_code=201)
def create_recap(
    payload: RecapCreate,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    fingerprint = _request_fingerprint(payload)
    operation = f"recap:{auth.principal_id}"
    workspace = db.scalar(
        select(Workspace).where(Workspace.id == auth.workspace_id).with_for_update()
    )
    if workspace is None:
        raise HTTPException(status_code=403, detail="Workspace is unavailable")
    recording_query = select(Recording).where(
        Recording.workspace_id == auth.workspace_id,
        Recording.deleted_at.is_(None),
        Recording.intelligence_ready.is_(True),
    )
    if payload.kind == "daily":
        recording_query = recording_query.where(
            Recording.created_at >= datetime.now(UTC) - timedelta(days=1)
        )
    elif payload.kind == "project":
        recording_query = recording_query.where(Recording.folder == payload.project)
    # Keep source versions stable until the recap and its dependency snapshot
    # commit.  Metadata moves, corrections, regeneration, and deletion all
    # contend on the same rows in PostgreSQL.
    recordings = db.scalars(recording_query.with_for_update()).all()
    prior = _idempotent_response(db, auth.workspace_id, operation, idempotency_key, fingerprint)
    if prior is not None:
        return prior
    intelligence = (
        db.scalars(
            select(IntelligenceVersion).where(
                IntelligenceVersion.workspace_id == auth.workspace_id,
                IntelligenceVersion.recording_id.in_([item.id for item in recordings]),
                IntelligenceVersion.is_current.is_(True),
            )
        ).all()
        if recordings
        else []
    )
    summaries = [item.payload.get("summary", {}) for item in intelligence]
    topics = [topic for item in intelligence for topic in item.payload.get("topics", [])]
    decisions = [
        decision for item in intelligence for decision in item.payload.get("decisions", [])
    ]
    task_rows = db.execute(
        select(ActionItem, Recording)
        .join(Recording, Recording.id == ActionItem.recording_id)
        .where(
            ActionItem.workspace_id == auth.workspace_id,
            Recording.deleted_at.is_(None),
            ActionItem.recording_id.in_([item.id for item in recordings]),
        )
    ).all()
    citations = [citation for item in summaries for citation in item.get("evidence", [])]
    data = {
        "title": f"{payload.kind.title()} Intelligent Audio Analysis recap",
        "period": datetime.now(UTC).date().isoformat(),
        "summary": " ".join(item.get("short", "") for item in summaries if item.get("short"))
        or "No grounded recording summaries are available.",
        "topics": topics,
        "decisions": decisions,
        "actions": [_task_payload(task, recording.display_name) for task, recording in task_rows],
        "citations": citations,
    }
    recap = Recap(
        id=str(uuid.uuid4()),
        workspace_id=auth.workspace_id,
        principal_id=auth.principal_id,
        kind=payload.kind,
        project=payload.project,
        payload=data,
        input_versions={item.recording_id: item.version for item in intelligence},
    )
    db.add(recap)
    db.flush()
    result = jsonable_encoder({"id": recap.id, **data, "generated_at": recap.created_at})
    _remember_idempotency(
        db,
        auth.workspace_id,
        operation,
        idempotency_key,
        fingerprint,
        result,
        201,
    )
    db.commit()
    return result


@router.post("/exports", status_code=201)
def create_export(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
) -> dict[str, Any]:
    resource = (
        "tasks" if payload.resource == "tasks" or payload.include == "tasks" else "recordings"
    )
    recording_ids = list(payload.recording_ids)
    if payload.recording_id:
        recording_ids = [payload.recording_id]
    if payload.resource == "recap":
        if not payload.recap_id:
            raise HTTPException(status_code=422, detail="recap_id is required")
        recap = db.scalar(
            select(Recap).where(
                Recap.id == payload.recap_id, Recap.workspace_id == auth.workspace_id
            )
        )
        if recap is None:
            raise HTTPException(status_code=404, detail="Recap not found")
        # Lock source recordings before the recap row to match the lock order
        # used by corrections, metadata changes, task updates, and deletion.
        # Those mutations delete dependent recaps while holding a Recording
        # lock, so a completed invalidation cannot race a stale export.
        _validate_recap_inputs(db, recap, auth.workspace_id)
        recap = db.scalar(
            select(Recap)
            .where(Recap.id == payload.recap_id, Recap.workspace_id == auth.workspace_id)
            .with_for_update()
        )
        if recap is None:
            raise HTTPException(status_code=404, detail="Recap not found")
        if payload.format == "json":
            content = json.dumps({"id": recap.id, **recap.payload}, indent=2)
            content_type, filename = "application/json", "intelligent-audio-analysis-recap.json"
        elif payload.format == "markdown":
            content = f"# {recap.payload['title']}\n\n{recap.payload['summary']}\n"
            content_type, filename = "text/markdown", "intelligent-audio-analysis-recap.md"
        else:
            raise HTTPException(status_code=422, detail="Recaps support Markdown or JSON export")
        return {"filename": filename, "content_type": content_type, "content": content}
    try:
        content, content_type, filename = export_content(
            db, auth.workspace_id, payload.format, recording_ids, resource
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "filename": filename,
        "content_type": content_type,
        "content": content.decode("utf-8"),
    }


def _validate_recap_inputs(db: Session, recap: Recap, workspace_id: str) -> None:
    """Fail closed if a persisted recap no longer matches live source versions."""

    input_versions = recap.input_versions or {}
    if not input_versions:
        return
    rows = db.execute(
        select(Recording, IntelligenceVersion)
        .join(
            IntelligenceVersion,
            (IntelligenceVersion.recording_id == Recording.id)
            & (IntelligenceVersion.is_current.is_(True)),
        )
        .where(
            Recording.workspace_id == workspace_id,
            Recording.deleted_at.is_(None),
            Recording.id.in_(list(input_versions)),
        )
        .with_for_update()
    ).all()
    current = {recording.id: intelligence.version for recording, intelligence in rows}
    expected = {str(key): int(value) for key, value in input_versions.items()}
    if current != expected:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "recap_stale",
                "message": "Recap sources changed; generate a new recap before exporting.",
            },
        )


def _task_payload(task: ActionItem, recording_title: str) -> dict[str, Any]:
    return {
        "id": task.id,
        "recording_id": task.recording_id,
        "recording_title": recording_title,
        "task": task.task,
        "owner_text": task.owner_text,
        "due_text": task.due_text,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "status": task.status,
        "ambiguities": task.ambiguities,
        "evidence": task.evidence,
        "version": task.version,
    }


def _frontend_cost(cost: CostEvent, recording_title: str | None) -> dict[str, Any]:
    value = serialize_cost(cost)
    usage = cost.usage or {}
    if "billed_audio_seconds" in usage:
        billed_units = f"{usage['billed_audio_seconds']} audio seconds"
    elif "retrieved_units" in usage:
        billed_units = f"{usage['retrieved_units']} retrieved evidence units"
    else:
        billed_units = "0 provider units"
    return {
        **value,
        "recording_title": recording_title,
        "billed_units": billed_units,
        "estimated_cost_usd": value["estimated_incurred_cost_usd"],
        "cached": cost.cache_reuse,
        "reused": cost.cache_reuse,
    }


def _if_match_version(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.strip('"'))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="If-Match must be a version number") from exc


def _parse_date(value: str, *, end: bool) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Date filter must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if end and len(value) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


def _search_response(
    items: list[dict[str, Any]], requested_mode: str, started: datetime
) -> dict[str, Any]:
    took_ms = max(0, int((datetime.now(UTC) - started).total_seconds() * 1000))
    retrieval_note = (
        "Semantic embeddings are not configured; authorized lexical retrieval was used."
        if requested_mode in {"mixed", "semantic"}
        else "Authorized lexical retrieval was used."
    )
    return {
        "items": items,
        "total": len(items),
        "took_ms": took_ms,
        "mode": "exact",
        "requested_mode": requested_mode,
        "effective_mode": "lexical",
        "semantic_available": False,
        "retrieval_note": retrieval_note,
        "notice": retrieval_note,
    }


def _empty_search(requested_mode: str, started: datetime) -> dict[str, Any]:
    return _search_response([], requested_mode, started)


def _resolve_speaker_ids(
    db: Session,
    workspace_id: str,
    requested: str | None,
    recording_ids: list[str] | None,
) -> list[str] | None:
    if not requested:
        return None
    query = (
        select(TranscriptSegment)
        .join(TranscriptVersion, TranscriptVersion.id == TranscriptSegment.transcript_id)
        .join(Recording, Recording.id == TranscriptSegment.recording_id)
        .where(
            Recording.workspace_id == workspace_id,
            Recording.deleted_at.is_(None),
            TranscriptVersion.is_current.is_(True),
        )
    )
    if recording_ids:
        query = query.where(Recording.id.in_(recording_ids))
    value = requested.casefold()
    matches = set()
    for segment in db.scalars(query).all():
        speaker_id = segment.speaker_cluster_id
        if not speaker_id:
            continue
        label = speaker_id.replace("speaker-", "Speaker ").title()
        if value in {
            speaker_id.casefold(),
            label.casefold(),
            (segment.speaker_display_name or "").casefold(),
        }:
            matches.add(speaker_id)
    return sorted(matches)
