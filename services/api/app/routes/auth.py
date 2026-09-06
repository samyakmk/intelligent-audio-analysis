from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import (
    SESSION_COOKIE,
    AuthContext,
    hash_token,
    require_auth,
    require_mutation_auth,
    serialize_identity,
)
from ..database import get_db
from ..models import DemoSession, Membership, Principal, utcnow
from ..schemas import LoginRequest, WorkspaceSwitchRequest

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.get("/demo-users")
def demo_users(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    if not request.app.state.settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")
    principals = db.scalars(select(Principal).order_by(Principal.id)).all()
    return {
        "items": [
            {"id": item.id, "email": item.email, "display_name": item.display_name}
            for item in principals
        ]
    }


def _login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session,
) -> dict[str, object]:
    settings = request.app.state.settings
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")
    principal = db.get(Principal, payload.principal_id)
    if principal is None:
        raise HTTPException(status_code=401, detail="Unknown demo principal")
    membership = db.scalar(
        select(Membership)
        .where(Membership.principal_id == principal.id)
        .order_by(Membership.workspace_id)
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Principal has no workspace")
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    demo_session = DemoSession(
        id=str(uuid.uuid4()),
        token_hash=hash_token(raw_token),
        csrf_token=csrf_token,
        principal_id=principal.id,
        workspace_id=membership.workspace_id,
        expires_at=utcnow() + timedelta(seconds=settings.session_ttl_seconds),
    )
    db.add(demo_session)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    auth = AuthContext(
        session_id=demo_session.id,
        principal_id=demo_session.principal_id,
        workspace_id=demo_session.workspace_id,
        csrf_token=csrf_token,
    )
    return serialize_identity(db, auth, settings)


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _login(payload, request, response, db)


@router.post("/demo-login")
def demo_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _login(payload, request, response, db)


@router.get("/session")
def get_session(
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
) -> dict[str, object]:
    return serialize_identity(db, auth, request.app.state.settings)


@router.post("/workspace")
def switch_workspace(
    payload: WorkspaceSwitchRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
) -> dict[str, object]:
    membership = db.get(
        Membership,
        {"principal_id": auth.principal_id, "workspace_id": payload.workspace_id},
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of that workspace")
    demo_session = db.get(DemoSession, auth.session_id)
    demo_session.workspace_id = payload.workspace_id
    demo_session.csrf_token = secrets.token_urlsafe(24)
    db.commit()
    updated = AuthContext(
        session_id=demo_session.id,
        principal_id=demo_session.principal_id,
        workspace_id=demo_session.workspace_id,
        csrf_token=demo_session.csrf_token,
    )
    return serialize_identity(db, updated, request.app.state.settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_mutation_auth),
) -> Response:
    db.execute(delete(DemoSession).where(DemoSession.id == auth.session_id))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
