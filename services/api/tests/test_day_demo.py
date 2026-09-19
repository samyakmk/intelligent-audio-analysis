from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import DayBatch, DaySession, MediaObject

from .conftest import FIXTURE_ROOT, login, mutation_headers


def load_day_audio(fixture_id: str = "atlas-launch-day") -> tuple[dict, bytes]:
    manifest = json.loads(
        (FIXTURE_ROOT / "day-demo" / "manifest.json").read_text(encoding="utf-8")
    )
    fixture = next(item for item in manifest["fixtures"] if item["id"] == fixture_id)
    return fixture, (FIXTURE_ROOT / "day-demo" / fixture["filename"]).read_bytes()


def upload_day(
    client: TestClient,
    csrf: str,
    *,
    fixture_id: str = "atlas-launch-day",
    batch_count: int = 5,
) -> tuple[str, dict]:
    fixture, data = load_day_audio(fixture_id)
    digest = hashlib.sha256(data).hexdigest()
    create = client.post(
        "/v1/upload-sessions",
        json={
            "filename": fixture["filename"],
            "content_type": "audio/wav",
            "size_bytes": len(data),
            "sha256": digest,
            "language": "en",
            "vocabulary_hints": [],
            "mode": "standard",
            "experience": "day_demo",
            "batch_count": batch_count,
        },
        headers=mutation_headers(csrf, f"{fixture_id}-{batch_count}-create"),
    )
    assert create.status_code == 201, create.text
    upload = create.json()
    assert (
        client.put(upload["upload_url"], content=data, headers=upload["upload_headers"]).status_code
        == 204
    )
    complete = client.post(
        f"/v1/recordings/{upload['recording_id']}/complete",
        json={"upload_session_id": upload["id"], "sha256": digest},
        headers=mutation_headers(csrf, f"{fixture_id}-{batch_count}-complete"),
    )
    assert complete.status_code == 202, complete.text
    assert complete.json()["experience"] == "day_demo"
    return upload["recording_id"], complete.json()


def advance(client: TestClient, csrf: str, recording_id: str, state: dict) -> dict:
    response = client.post(
        f"/v1/day-sessions/{recording_id}/advance",
        json={"expected_revision": state["revision"]},
        headers=mutation_headers(csrf),
    )
    assert response.status_code == 200, response.text
    return response.json()


def publish_next_batch(client: TestClient, csrf: str, recording_id: str, state: dict) -> dict:
    before = state["processed_batch_count"]
    for _ in range(5):
        state = advance(client, csrf, recording_id, state)
    assert state["processed_batch_count"] == before + 1
    return state


def test_day_demo_advances_stage_by_stage_and_revises_prior_memory(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    recording_id, _ = upload_day(client, csrf)
    initial = client.get(f"/v1/day-sessions/{recording_id}")
    assert initial.status_code == 200
    state = initial.json()
    assert state["status"] == "ready"
    assert state["batch_count"] == 5
    assert all(batch["status"] == "queued" for batch in state["batches"])
    assert all("source_payload" not in batch for batch in state["batches"])
    assert state["watermark_ms"] == 0

    first_stage = advance(client, csrf, recording_id, state)
    assert first_stage["current_stage"] == "transcribing"
    assert first_stage["batches"][0]["transcript"]
    assert first_stage["memory"]["decisions"] == []

    replay = client.post(
        f"/v1/day-sessions/{recording_id}/advance",
        json={"expected_revision": state["revision"]},
        headers=mutation_headers(csrf),
    )
    assert replay.status_code == 200
    assert replay.json()["revision"] == first_stage["revision"]
    assert replay.json()["current_stage"] == "transcribing"

    state = first_stage
    for _ in range(4):
        state = advance(client, csrf, recording_id, state)
    assert state["processed_batch_count"] == 1
    assert state["watermark_ms"] == state["batches"][0]["end_ms"]
    assert any(item["key"] == "launch-date" for item in state["memory"]["decisions"])
    first_plan = client.post(
        f"/v1/day-sessions/{recording_id}/ask",
        json={"question": "What is the current Atlas launch plan?"},
        headers=mutation_headers(csrf),
    )
    assert first_plan.status_code == 201
    assert "Friday" in first_plan.json()["answer"]
    assert first_plan.json()["provisional"] is True

    state = publish_next_batch(client, csrf, recording_id, state)
    state = publish_next_batch(client, csrf, recording_id, state)
    current_launch = [
        item
        for item in state["memory"]["decisions"]
        if item["key"] == "launch-date" and item["status"] != "superseded"
    ]
    assert len(current_launch) == 1
    assert "Pause" in current_launch[0]["text"]
    assert any(
        item["operation"] == "supersede" and item["key"] == "launch-date"
        for item in state["changes"]
    )
    revised_plan = client.post(
        f"/v1/day-sessions/{recording_id}/ask",
        json={"question": "What is the current Atlas launch plan?"},
        headers=mutation_headers(csrf),
    ).json()
    assert "paused" in revised_plan["answer"]

    while state["status"] != "complete":
        state = advance(client, csrf, recording_id, state)
    assert state["processed_batch_count"] == 5
    assert state["watermark_ms"] == state["duration_ms"]
    final_plan = client.post(
        f"/v1/day-sessions/{recording_id}/ask",
        json={"question": "What is the current Atlas launch plan?"},
        headers=mutation_headers(csrf),
    ).json()
    assert "Monday" in final_plan["answer"]
    assert "Cedar" in final_plan["answer"]
    assert final_plan["provisional"] is False
    historical_plan = client.post(
        f"/v1/day-sessions/{recording_id}/ask",
        json={
            "question": "What is the current Atlas launch plan?",
            "batch_index": 0,
        },
        headers=mutation_headers(csrf),
    ).json()
    assert "Friday" in historical_plan["answer"]
    assert historical_plan["provisional"] is True
    assert historical_plan["watermark_ms"] == state["batches"][0]["end_ms"]
    assert historical_plan["processed_batch_count"] == 1
    owner = client.post(
        f"/v1/day-sessions/{recording_id}/ask",
        json={"question": "Who owns the launch checklist?"},
        headers=mutation_headers(csrf),
    ).json()
    assert "Priya" in owner["answer"]
    assert "completed" in owner["answer"]

    transcript = client.get(f"/v1/recordings/{recording_id}/transcript")
    assert transcript.status_code == 200
    assert len(transcript.json()["segments"]) == 16
    search = client.post(
        "/v1/search",
        json={
            "query": "Cedar Monday",
            "filters": {"mode": "exact", "recording_id": recording_id},
        },
    )
    assert search.status_code == 200
    assert search.json()["total"] >= 1


def test_dynamic_batch_count_creates_physical_batches_and_reset_is_replayable(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    recording_id, _ = upload_day(
        client, csrf, fixture_id="meridian-incident-day", batch_count=7
    )
    state = client.get(f"/v1/day-sessions/{recording_id}").json()
    assert len(state["batches"]) == 7
    assert all((batch["size_bytes"] or 0) > 44 for batch in state["batches"])
    with client.app.state.database.session_factory() as db:
        assert db.scalar(
            select(func.count()).select_from(DayBatch).where(DayBatch.recording_id == recording_id)
        ) == 7
        assert db.scalar(
            select(func.count())
            .select_from(MediaObject)
            .where(
                MediaObject.recording_id == recording_id,
                MediaObject.kind.like("day_batch_%"),
            )
        ) == 7

    state = publish_next_batch(client, csrf, recording_id, state)
    assert state["processed_batch_count"] == 1
    reset = client.post(
        f"/v1/day-sessions/{recording_id}/reset",
        json={"expected_revision": state["revision"]},
        headers=mutation_headers(csrf),
    )
    assert reset.status_code == 200, reset.text
    reset_state = reset.json()
    assert reset_state["status"] == "ready"
    assert reset_state["processed_batch_count"] == 0
    assert reset_state["memory"]["decisions"] == []
    assert all(batch["stage"] == "waiting" for batch in reset_state["batches"])


def test_day_ask_abstains_before_any_batch_is_published(client: TestClient) -> None:
    csrf, _ = login(client)
    recording_id, _ = upload_day(client, csrf)
    response = client.post(
        f"/v1/day-sessions/{recording_id}/ask",
        json={"question": "What is the final launch decision?"},
        headers=mutation_headers(csrf),
    )
    assert response.status_code == 201
    assert response.json()["abstained"] is True
    assert response.json()["watermark_ms"] == 0
    unavailable = client.post(
        f"/v1/day-sessions/{recording_id}/ask",
        json={"question": "What changed?", "batch_index": 0},
        headers=mutation_headers(csrf),
    )
    assert unavailable.status_code == 409


def test_deleting_day_demo_revokes_session_and_purges_batch_media(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    recording_id, _ = upload_day(client, csrf, batch_count=3)
    with client.app.state.database.session_factory() as db:
        assert db.scalar(
            select(func.count()).select_from(MediaObject).where(
                MediaObject.recording_id == recording_id,
                MediaObject.kind.like("day_batch_%"),
            )
        ) == 3

    deleted = client.delete(
        f"/v1/recordings/{recording_id}", headers=mutation_headers(csrf)
    )
    assert deleted.status_code == 204
    assert client.get(f"/v1/day-sessions/{recording_id}").status_code == 404
    with client.app.state.database.session_factory() as db:
        assert db.scalar(
            select(func.count()).select_from(DaySession).where(
                DaySession.recording_id == recording_id
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(DayBatch).where(
                DayBatch.recording_id == recording_id
            )
        ) == 0
        assert db.scalar(
            select(func.count()).select_from(MediaObject).where(
                MediaObject.recording_id == recording_id
            )
        ) == 0
