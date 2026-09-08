from __future__ import annotations

import os

from sqlalchemy import delete, select

from .blobstore import BlobStore, create_blob_store
from .config import Settings
from .database import Database
from .lifecycle import delete_recording_content
from .models import DemoSession, Membership, Recording

CONFIRMATION = "delete-current-recordings-and-revoke-old-demo-access"


def retire_current_demo_data(database: Database, blob_store: BlobStore) -> tuple[int, int]:
    """Delete live recordings through the normal lifecycle and revoke obsolete access."""

    with database.session_factory() as session:
        recording_ids = session.scalars(
            select(Recording.id).where(Recording.deleted_at.is_(None)).order_by(Recording.id)
        ).all()

    deleted_recordings = 0
    for recording_id in recording_ids:
        with database.session_factory() as session:
            recording = session.scalar(
                select(Recording)
                .where(Recording.id == recording_id, Recording.deleted_at.is_(None))
                .with_for_update()
            )
            if recording is None:
                continue
            if not delete_recording_content(
                session,
                blob_store,
                recording,
                reason="operator_demo_reset",
            ):
                raise RuntimeError(
                    f"Physical deletion remains pending for recording {recording_id}"
                )
            deleted_recordings += 1

    with database.session_factory() as session:
        revoked_sessions = session.execute(delete(DemoSession)).rowcount or 0
        session.execute(delete(Membership).where(Membership.principal_id != "test-account"))
        session.commit()
    return deleted_recordings, revoked_sessions


def reset_demo_data(settings: Settings) -> tuple[int, int]:
    if os.environ.get("CONFIRM_RESET_DEMO_DATA") != CONFIRMATION:
        raise RuntimeError("Set CONFIRM_RESET_DEMO_DATA to the exact reset confirmation")
    if not settings.demo_mode or settings.seed_demo_recordings:
        raise RuntimeError("Demo reset requires DEMO_MODE=true and SEED_DEMO_RECORDINGS=false")

    database = Database(settings.database_url)
    try:
        if database.engine.dialect.name != "postgresql":
            raise RuntimeError("Demo reset is restricted to the hosted PostgreSQL database")
        return retire_current_demo_data(database, create_blob_store(settings))
    finally:
        database.close()


def main() -> None:
    deleted_recordings, revoked_sessions = reset_demo_data(Settings.from_environment())
    print(
        f"Demo reset complete: deleted_recordings={deleted_recordings}, "
        f"revoked_sessions={revoked_sessions}"
    )


if __name__ == "__main__":
    main()
