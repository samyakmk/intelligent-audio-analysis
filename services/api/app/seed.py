from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Membership, Principal, Workspace

DEMO_PRINCIPALS = (
    {
        "id": "test-account",
        "email": "test-account@demo.invalid",
        "display_name": "Test Account",
    },
)

DEMO_WORKSPACES = (
    {"id": "test-workspace", "name": "Test Workspace", "timezone": "America/Los_Angeles"},
)


def seed_reference_data(db: Session, *, monthly_spend_limit_usd: float | None = None) -> None:
    for item in DEMO_WORKSPACES:
        workspace = db.get(Workspace, item["id"])
        if workspace is None:
            db.add(Workspace(**item))
        elif monthly_spend_limit_usd is not None:
            workspace.monthly_spend_limit_usd = monthly_spend_limit_usd
    if monthly_spend_limit_usd is not None:
        db.flush()
        for item in DEMO_WORKSPACES:
            workspace = db.get(Workspace, item["id"])
            workspace.monthly_spend_limit_usd = monthly_spend_limit_usd
    for item in DEMO_PRINCIPALS:
        if db.get(Principal, item["id"]) is None:
            db.add(Principal(**item))
    db.flush()
    memberships = (("test-account", "test-workspace", "owner"),)
    for principal_id, workspace_id, role in memberships:
        key = {"principal_id": principal_id, "workspace_id": workspace_id}
        if db.get(Membership, key) is None:
            db.add(Membership(**key, role=role))
    db.commit()
