from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from app.database import Database
from app.models import Principal, Workspace
from app.worker import run_worker


def test_worker_once_bootstraps_and_drains_disposable_sqlite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "worker.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blobs"))
    monkeypatch.setenv("FIXTURE_ROOT", str(Path(__file__).resolve().parents[3] / "fixtures"))
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("PROVIDER_MODE", "fixture")
    monkeypatch.setenv("ALLOW_REMOTE_PROVIDER_CALLS", "false")

    run_worker(once=True, poll_seconds=0)

    database = Database(f"sqlite:///{database_path}")
    try:
        with database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Principal)) == 2
            assert session.scalar(select(func.count()).select_from(Workspace)) == 2
    finally:
        database.close()
