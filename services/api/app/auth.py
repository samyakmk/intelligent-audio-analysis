from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .database import get_db
from .models import CostEvent, DemoSession, Membership, Principal, Recording, Workspace

SESSION_COOKIE = "intelligent_audio_analysis_session"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class AuthContext:
    session_id: str
    principal_id: str
    workspace_id: str
    csrf_token: str


def require_auth(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    demo_session = db.scalar(select(DemoSession).where(DemoSession.token_hash == hash_token(token)))
    if demo_session is None or _aware(demo_session.expires_at) <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    membership = db.get(
        Membership,
        {"principal_id": demo_session.principal_id, "workspace_id": demo_session.workspace_id},
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Workspace access revoked"
        )
    return AuthContext(
        session_id=demo_session.id,
        principal_id=demo_session.principal_id,
        workspace_id=demo_session.workspace_id,
        csrf_token=demo_session.csrf_token,
    )


def require_mutation_auth(
    request: Request, auth: AuthContext = Depends(require_auth)
) -> AuthContext:
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not hmac.compare_digest(supplied, auth.csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return auth


def serialize_identity(
    db: Session, auth: AuthContext, settings: object | None = None
) -> dict[str, object]:
    principal = db.get(Principal, auth.principal_id)
    workspace = db.get(Workspace, auth.workspace_id)
    memberships = db.scalars(
        select(Membership).where(Membership.principal_id == auth.principal_id)
    ).all()
    workspaces = [db.get(Workspace, item.workspace_id) for item in memberships]
    membership_by_workspace = {item.workspace_id: item for item in memberships}
    retained_recordings = (
        db.scalar(
            select(func.count())
            .select_from(Recording)
            .where(
                Recording.workspace_id == auth.workspace_id,
                Recording.deleted_at.is_(None),
            )
        )
        or 0
    )
    retained_bytes = (
        db.scalar(
            select(func.coalesce(func.sum(Recording.size_bytes), 0)).where(
                Recording.workspace_id == auth.workspace_id,
                Recording.deleted_at.is_(None),
            )
        )
        or 0
    )
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    month_end = (
        datetime(now.year + 1, 1, 1, tzinfo=UTC)
        if now.month == 12
        else datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    )
    monthly_spend = (
        db.scalar(
            select(func.coalesce(func.sum(CostEvent.estimated_cost_usd), 0)).where(
                CostEvent.workspace_id == auth.workspace_id,
                CostEvent.created_at >= month_start,
                CostEvent.created_at < month_end,
            )
        )
        or 0.0
    )
    current_membership = membership_by_workspace[auth.workspace_id]
    return {
        "principal": {
            "id": principal.id,
            "email": principal.email,
            "name": principal.display_name,
            "display_name": principal.display_name,
        },
        "workspace": {
            "id": workspace.id,
            "name": workspace.name,
            "timezone": workspace.timezone,
            "role": current_membership.role,
            "retained_recordings": retained_recordings,
            "retained_bytes": retained_bytes,
            "recording_limit": getattr(settings, "workspace_recording_quota", 200),
            "byte_limit": getattr(
                settings, "workspace_storage_quota_bytes", 5 * 1024 * 1024 * 1024
            ),
            "monthly_spend_usd": monthly_spend,
            "monthly_budget_usd": workspace.monthly_spend_limit_usd,
        },
        "workspaces": [
            {
                "id": item.id,
                "name": item.name,
                "timezone": item.timezone,
                "role": membership_by_workspace[item.id].role,
            }
            for item in workspaces
            if item is not None
        ],
        "csrf_token": auth.csrf_token,
        "demo_mode": bool(getattr(settings, "demo_mode", False)),
    }
