from __future__ import annotations

import argparse
import signal
import time
import uuid

from .blobstore import create_blob_store
from .config import Settings, validate_runtime_settings
from .database import Database
from .domain import (
    claim_next_run,
    process_run,
    retry_sealed_quarantine_cleanup,
)
from .lifecycle import (
    retry_pending_blob_purges,
    sweep_expired_recordings,
    sweep_expired_uploads,
)
from .providers import MockFixtureLLMAdapter, MockFixtureSpeechAdapter
from .seed import seed_reference_data


def run_worker(*, once: bool = False, poll_seconds: float = 1.0) -> None:
    settings = Settings.from_environment()
    validate_runtime_settings(settings)
    database = Database(settings.database_url)
    if database.engine.dialect.name == "sqlite":
        database.create_all()
    with database.session_factory() as db:
        seed_reference_data(
            db,
            monthly_spend_limit_usd=settings.workspace_monthly_cost_ceiling_usd,
        )
    blob_store = create_blob_store(settings)
    speech = MockFixtureSpeechAdapter(settings.fixture_root)
    llm = MockFixtureLLMAdapter(settings.fixture_root)
    lease_owner = f"worker:{uuid.uuid4()}"
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            sweep_expired_uploads(database, blob_store)
            sweep_expired_recordings(database, blob_store)
            retry_pending_blob_purges(database, blob_store)
            retry_sealed_quarantine_cleanup(database, blob_store)
            run_id = claim_next_run(
                database,
                lease_owner,
                lease_seconds=settings.worker_lease_seconds,
            )
            if run_id:
                process_run(
                    database,
                    blob_store,
                    speech,
                    llm,
                    settings,
                    run_id,
                    lease_owner=lease_owner,
                )
            elif once:
                break
            else:
                time.sleep(max(0.1, poll_seconds))
    finally:
        database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Pocket demo database-backed worker")
    parser.add_argument("--once", action="store_true", help="Drain at most the current queue")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    run_worker(once=args.once, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    main()
