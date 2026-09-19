from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import AuthContext, require_auth, require_mutation_auth
from ..database import get_db
from ..day_domain import (
    advance_day_session,
    answer_day_question,
    day_session_payload,
    get_day_session,
    reset_day_session,
)
from ..schemas import DayAdvanceRequest, DayAskRequest, DayResetRequest

router = APIRouter(prefix="/v1/day-sessions", tags=["day-sessions"])


def _not_found(error: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail="Day session not found")


@router.get("/{recording_id}")
def get_day(
    recording_id: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> dict:
    try:
        recording, session = get_day_session(db, recording_id, auth.workspace_id)
    except LookupError as error:
        raise _not_found(error) from error
    return day_session_payload(db, recording, session, request.app.state.settings.fixture_root)


@router.post("/{recording_id}/advance")
def advance_day(
    recording_id: str,
    payload: DayAdvanceRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
) -> dict:
    try:
        recording, session = get_day_session(db, recording_id, auth.workspace_id, lock=True)
    except LookupError as error:
        raise _not_found(error) from error
    if payload.expected_revision > session.revision:
        raise HTTPException(status_code=409, detail="Day session revision is ahead of the server")
    if payload.expected_revision == session.revision:
        advance_day_session(
            db,
            recording,
            session,
            fixture_root=request.app.state.settings.fixture_root,
        )
        db.commit()
    return day_session_payload(db, recording, session, request.app.state.settings.fixture_root)


@router.post("/{recording_id}/ask", status_code=201)
def ask_day(
    recording_id: str,
    payload: DayAskRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
) -> dict:
    try:
        recording, session = get_day_session(db, recording_id, auth.workspace_id, lock=True)
    except LookupError as error:
        raise _not_found(error) from error
    try:
        message = answer_day_question(
            db,
            recording,
            session,
            payload.question,
            through_batch_index=payload.batch_index,
            fixture_root=request.app.state.settings.fixture_root,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return message


@router.post("/{recording_id}/reset")
def reset_day(
    recording_id: str,
    payload: DayResetRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
) -> dict:
    try:
        recording, session = get_day_session(db, recording_id, auth.workspace_id, lock=True)
    except LookupError as error:
        raise _not_found(error) from error
    if payload.expected_revision != session.revision:
        raise HTTPException(status_code=409, detail="Day session changed before reset")
    reset_day_session(db, recording, session)
    db.commit()
    return day_session_payload(db, recording, session, request.app.state.settings.fixture_root)
