from __future__ import annotations

import json
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.lifecycle import (
    retry_pending_blob_purges,
    sweep_expired_recordings,
    sweep_expired_uploads,
)
from app.models import (
    AskMessage,
    AskSession,
    BudgetReservation,
    CostEvent,
    DomainEvent,
    EvidenceUnit,
    IntelligenceVersion,
    MediaObject,
    OutboxEvent,
    Recording,
    TranscriptVersion,
    UploadSession,
    utcnow,
)

from .conftest import login, mutation_headers
from .test_security_lifecycle import fixture_recording_id


def test_inline_maintenance_tombstones_expired_content_and_scrubs_ledgers(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    grant_url = client.get(f"/v1/recordings/{recording_id}/media-grant").json()["url"]
    ask_session = client.post(
        "/v1/ask-sessions",
        json={"scope": {"type": "recording", "recording_id": recording_id}},
        headers=mutation_headers(csrf, "retention-ask-session"),
    ).json()
    assert (
        client.post(
            f"/v1/ask-sessions/{ask_session['id']}/messages",
            json={"content": "What was decided?"},
            headers=mutation_headers(csrf, "retention-ask-message"),
        ).status_code
        == 201
    )

    with client.app.state.database.session_factory() as db:
        recording = db.get(Recording, recording_id)
        recording.retention_expires_at = utcnow() - timedelta(seconds=1)
        affected_cost_rows = db.scalars(
            select(CostEvent).where(
                    (CostEvent.recording_id == recording_id)
                    | (CostEvent.ask_session_id == ask_session["id"])
                )
        ).all()
        affected_cost_ids = [item.id for item in affected_cost_rows]
        original_attempt_ids = [item.attempt_id for item in affected_cost_rows]
        affected_reservation_ids = list(
            db.scalars(
                select(BudgetReservation.id).where(
                    (BudgetReservation.recording_id == recording_id)
                    | (BudgetReservation.ask_session_id == ask_session["id"])
                )
            ).all()
        )
        cost_count = db.scalar(select(func.count()).select_from(CostEvent))
        db.commit()

    # Inline mode uses the same lifecycle service opportunistically on API
    # traffic, so a long-running local process does not require a second worker.
    client.app.state.retention_maintenance.interval_seconds = 0
    assert client.get("/healthz").status_code == 200
    assert client.get(f"/v1/recordings/{recording_id}").status_code == 404
    assert client.get(grant_url).status_code == 404
    search = client.post(
        "/v1/search",
        json={
            "query": "browser upload",
            "filters": {"mode": "exact", "recording_id": recording_id},
        },
    )
    assert search.status_code == 200
    assert search.json()["total"] == 0

    with client.app.state.database.session_factory() as db:
        tombstone = db.get(Recording, recording_id)
        assert tombstone.deleted_at is not None
        assert tombstone.status == "DELETED"
        assert tombstone.source_kind == "deleted_tombstone"
        assert (
            db.scalar(select(MediaObject).where(MediaObject.recording_id == recording_id))
            is None
        )
        assert (
            db.scalar(
                select(TranscriptVersion).where(
                    TranscriptVersion.recording_id == recording_id
                )
            )
            is None
        )
        assert (
            db.scalar(
                select(IntelligenceVersion).where(
                    IntelligenceVersion.recording_id == recording_id
                )
            )
            is None
        )
        assert (
            db.scalar(select(EvidenceUnit).where(EvidenceUnit.recording_id == recording_id))
            is None
        )
        assert db.get(AskSession, ask_session["id"]) is None
        assert (
            db.scalar(select(AskMessage).where(AskMessage.ask_session_id == ask_session["id"]))
            is None
        )
        assert db.scalar(select(func.count()).select_from(CostEvent)) == cost_count
        costs = db.scalars(select(CostEvent).where(CostEvent.id.in_(affected_cost_ids))).all()
        assert len(costs) == len(affected_cost_ids)
        assert all(item.recording_id is None and item.ask_session_id is None for item in costs)
        assert recording_id not in json.dumps(
            [{"attempt_id": item.attempt_id, "provenance": item.provenance} for item in costs]
        )
        serialized_costs = json.dumps(
            [{"attempt_id": item.attempt_id, "provenance": item.provenance} for item in costs]
        )
        assert all(attempt_id not in serialized_costs for attempt_id in original_attempt_ids)
        reservations = db.scalars(
            select(BudgetReservation).where(BudgetReservation.id.in_(affected_reservation_ids))
        ).all()
        assert len(reservations) == len(affected_reservation_ids)
        assert all(item.status != "reserved" for item in reservations)
        assert all(
            item.recording_id is None and item.ask_session_id is None for item in reservations
        )
        deleting = db.scalar(
            select(DomainEvent).where(
                DomainEvent.recording_id == recording_id,
                DomainEvent.event_type == "recording.deleting",
            )
        )
        assert deleting.payload["reason"] == "retention_expired"
        outbox = db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.recording_id == recording_id,
                OutboxEvent.event_type == "recording.deleted.v1",
            )
        )
        assert outbox.processed_at is not None


def test_retention_retries_physical_purge_and_discovers_copy_first_orphan(
    client: TestClient,
) -> None:
    csrf, session = login(client)
    created = client.post(
        "/v1/upload-sessions",
        json={
            "filename": "orphan.wav",
            "content_type": "audio/wav",
            "size_bytes": 4,
        },
        headers=mutation_headers(csrf, "retention-orphan"),
    )
    assert created.status_code == 201
    recording_id = created.json()["recording_id"]
    original_key = f"original/{session['workspace']['id']}/{recording_id}/g0/audio"
    client.app.state.blob_store.put(original_key, b"RIFF", immutable=True)
    with client.app.state.database.session_factory() as db:
        recording = db.get(Recording, recording_id)
        recording.retention_expires_at = utcnow() - timedelta(seconds=1)
        assert (
            db.scalar(select(MediaObject).where(MediaObject.recording_id == recording_id))
            is None
        )
        db.commit()

    class FailOriginalOnce:
        def __init__(self, delegate):
            self.delegate = delegate
            self.failed = False

        def delete(self, key: str) -> None:
            if key == original_key and not self.failed:
                self.failed = True
                raise OSError("simulated object-store outage")
            self.delegate.delete(key)

        def __getattr__(self, name: str):
            return getattr(self.delegate, name)

    failed_store = FailOriginalOnce(client.app.state.blob_store)
    assert (
        sweep_expired_recordings(
            client.app.state.database,
            failed_store,
            now=utcnow(),
        )
        == 1
    )
    with client.app.state.database.session_factory() as db:
        tombstone = db.get(Recording, recording_id)
        assert tombstone.deleted_at is not None
        assert tombstone.status == "DELETING"
        assert tombstone.stage == "physical_purge_pending"
        assert (
            db.scalar(select(UploadSession).where(UploadSession.recording_id == recording_id))
            is None
        )
    assert client.get(f"/v1/recordings/{recording_id}").status_code == 404
    assert client.app.state.blob_store.exists(original_key)

    assert (
        retry_pending_blob_purges(
            client.app.state.database,
            client.app.state.blob_store,
        )
        == 1
    )
    assert not client.app.state.blob_store.exists(original_key)
    with client.app.state.database.session_factory() as db:
        assert db.get(Recording, recording_id).status == "DELETED"


def test_abandoned_upload_expiry_is_durable_and_blob_cleanup_retries(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    data = b"uncompleted quarantine payload"
    created = client.post(
        "/v1/upload-sessions",
        json={
            "filename": "abandoned.wav",
            "content_type": "audio/wav",
            "size_bytes": len(data),
        },
        headers=mutation_headers(csrf, "abandoned-upload"),
    ).json()
    assert (
        client.put(
            created["upload_url"], content=data, headers=created["upload_headers"]
        ).status_code
        == 204
    )
    with client.app.state.database.session_factory() as db:
        upload = db.get(UploadSession, created["id"])
        upload.expires_at = utcnow() - timedelta(seconds=1)
        quarantine_key = upload.quarantine_key
        db.commit()

    class FailDeleteOnce:
        def __init__(self, delegate):
            self.delegate = delegate
            self.failed = False

        def delete(self, key: str) -> None:
            if key == quarantine_key and not self.failed:
                self.failed = True
                raise OSError("simulated quarantine-store outage")
            self.delegate.delete(key)

        def __getattr__(self, name: str):
            return getattr(self.delegate, name)

    failed_store = FailDeleteOnce(client.app.state.blob_store)
    assert sweep_expired_uploads(client.app.state.database, failed_store) == 1
    with client.app.state.database.session_factory() as db:
        upload = db.get(UploadSession, created["id"])
        recording = db.get(Recording, created["recording_id"])
        assert upload.status == "expired_cleanup_pending"
        assert recording.status == "FAILED_FINAL"
        assert recording.error_code == "upload_expired"
    assert client.app.state.blob_store.exists(quarantine_key)

    assert sweep_expired_uploads(client.app.state.database, client.app.state.blob_store) == 0
    with client.app.state.database.session_factory() as db:
        assert db.get(UploadSession, created["id"]).status == "expired"
    assert not client.app.state.blob_store.exists(quarantine_key)


def test_inline_upload_expiry_survives_later_request_rejection(client: TestClient) -> None:
    csrf, _ = login(client)
    data = b"bytes whose upload response was abandoned"
    created = client.post(
        "/v1/upload-sessions",
        json={
            "filename": "durable-expiry.wav",
            "content_type": "audio/wav",
            "size_bytes": len(data),
        },
        headers=mutation_headers(csrf, "durable-expiry"),
    ).json()
    assert (
        client.put(
            created["upload_url"], content=data, headers=created["upload_headers"]
        ).status_code
        == 204
    )
    with client.app.state.database.session_factory() as db:
        upload = db.get(UploadSession, created["id"])
        upload.expires_at = utcnow() - timedelta(seconds=1)
        quarantine_key = upload.quarantine_key
        db.commit()

    client.app.state.retention_maintenance.interval_seconds = 0
    rejected = client.post(
        "/v1/upload-sessions",
        json={
            "filename": "too-large.wav",
            "content_type": "audio/wav",
            "size_bytes": client.app.state.settings.max_upload_bytes + 1,
        },
        headers=mutation_headers(csrf, "rejected-after-expiry"),
    )
    assert rejected.status_code == 413
    with client.app.state.database.session_factory() as db:
        upload = db.get(UploadSession, created["id"])
        recording = db.get(Recording, created["recording_id"])
        assert upload.status == "expired"
        assert recording.error_code == "upload_expired"
    assert not client.app.state.blob_store.exists(quarantine_key)
