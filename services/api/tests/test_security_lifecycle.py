from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.domain import claim_next_run, process_run, reserve_budget
from app.models import (
    BudgetReservation,
    EvidenceUnit,
    IntelligenceVersion,
    MediaGrant,
    ProcessingRun,
    Recording,
    StageRun,
    TranscriptVersion,
    Workspace,
)
from app.providers import MockFixtureLLMAdapter, MockFixtureSpeechAdapter, SpeechRequest

from .conftest import login, mutation_headers
from .test_uploads import upload_audio


def fixture_recording_id(client: TestClient) -> str:
    items = client.get("/v1/recordings").json()["items"]
    return next(item["id"] for item in items if item["is_fixture"])


def test_csrf_and_workspace_isolation_fail_closed(client: TestClient) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    denied_mutation = client.patch(f"/v1/recordings/{recording_id}", json={"title": "No CSRF"})
    assert denied_mutation.status_code == 403

    with client.app.state.database.session_factory() as db:
        db.add(Workspace(id="other-workspace", name="Other Workspace", timezone="UTC"))
        recording = db.get(Recording, recording_id)
        recording.workspace_id = "other-workspace"
        db.commit()

    forbidden = client.get(f"/v1/recordings/{recording_id}")
    nonexistent = client.get(f"/v1/recordings/{uuid.uuid4()}")
    assert forbidden.status_code == nonexistent.status_code == 404
    assert forbidden.json() == nonexistent.json()


def test_correction_rebuilds_without_speech_and_invalidates_answers(client: TestClient) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    ask = client.post(
        "/v1/ask-sessions",
        json={"scope": {"type": "recording", "recording_id": recording_id}},
        headers=mutation_headers(csrf, "correction-ask-session"),
    ).json()
    answer = client.post(
        f"/v1/ask-sessions/{ask['id']}/messages",
        json={"content": "When will the browser upload flow ship?"},
        headers=mutation_headers(csrf, "pre-correction-answer"),
    )
    assert answer.status_code == 201

    class ForbiddenSpeech:
        def transcribe(self, request: SpeechRequest):
            raise AssertionError("Corrections must never rerun speech")

    client.app.state.speech_adapter = ForbiddenSpeech()
    transcript = client.get(f"/v1/recordings/{recording_id}/transcript").json()
    correction = client.post(
        f"/v1/recordings/{recording_id}/corrections",
        json={"segment_id": "segment-2", "text": "Ship the corrected browser flow Monday."},
        headers={
            **mutation_headers(csrf, "manual-correction"),
            "If-Match": str(transcript["version"]),
        },
    )
    assert correction.status_code == 200, correction.text
    assert correction.json()["version"] == transcript["version"] + 1
    assert "corrected" in correction.json()["segments"][1]["text"]
    intelligence = client.get(f"/v1/recordings/{recording_id}/intelligence").json()
    assert intelligence["transcript_version"] == correction.json()["version"]
    assert intelligence["provenance"]["source"] == "deterministic_manual_edit_revalidation"
    assert len(intelligence["facts"]) == 1
    assert len(intelligence["actions"]) == 1
    assert intelligence["decisions"] == []
    assert any("removed for review" in item for item in intelligence["warnings"])

    with client.app.state.database.session_factory() as db:
        from app.models import AskMessage

        assert db.scalar(select(AskMessage).where(AskMessage.ask_session_id == ask["id"])) is None


def test_selection_scope_requires_live_segment_ids(client: TestClient) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    empty = client.post(
        "/v1/ask-sessions",
        json={
            "scope": {
                "type": "selection",
                "recording_id": recording_id,
                "segment_ids": [],
            }
        },
        headers=mutation_headers(csrf),
    )
    unknown = client.post(
        "/v1/ask-sessions",
        json={
            "scope": {
                "type": "selection",
                "recording_id": recording_id,
                "segment_ids": ["missing"],
            }
        },
        headers=mutation_headers(csrf),
    )
    assert empty.status_code == unknown.status_code == 422


def test_selection_retrieval_filters_before_top_k(client: TestClient) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    with client.app.state.database.session_factory() as db:
        rows = db.scalars(
            select(EvidenceUnit).where(EvidenceUnit.recording_id == recording_id)
        ).all()
        assert len(rows) == 4
        for row in rows:
            row.text = f"{row.text} selectionneedle"
            row.text_normalized = f"{row.text_normalized} selectionneedle"
        db.commit()

    session = client.post(
        "/v1/ask-sessions",
        json={
            "scope": {
                "type": "selection",
                "recording_id": recording_id,
                "segment_ids": ["segment-4"],
            }
        },
        headers=mutation_headers(csrf, "low-rank-selection-session"),
    )
    assert session.status_code == 201
    answer = client.post(
        f"/v1/ask-sessions/{session.json()['id']}/messages",
        json={"content": "selectionneedle"},
        headers=mutation_headers(csrf, "low-rank-selection-answer"),
    )
    assert answer.status_code == 201
    message = answer.json()["message"]
    assert message["status"] == "complete"
    assert [item["segment_id"] for item in message["citations"]] == ["segment-4"]


def test_task_update_rejects_stale_version(client: TestClient) -> None:
    csrf, _ = login(client)
    task = client.get("/v1/tasks").json()["items"][0]
    first = client.patch(
        f"/v1/tasks/{task['id']}",
        json={"status": "done"},
        headers={**mutation_headers(csrf), "If-Match": str(task["version"])},
    )
    assert first.status_code == 200
    stale = client.patch(
        f"/v1/tasks/{task['id']}",
        json={"status": "dismissed"},
        headers={**mutation_headers(csrf), "If-Match": str(task["version"])},
    )
    assert stale.status_code == 412
    current = next(
        item for item in client.get("/v1/tasks").json()["items"] if item["id"] == task["id"]
    )
    assert current["status"] == "done"
    assert current["version"] == task["version"] + 1


def test_speaker_edit_and_regeneration_preserve_task_state(client: TestClient) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    task = client.get("/v1/tasks").json()["items"][0]
    done = client.patch(
        f"/v1/tasks/{task['id']}",
        json={"status": "done"},
        headers={**mutation_headers(csrf), "If-Match": str(task["version"])},
    )
    assert done.status_code == 200

    transcript = client.get(f"/v1/recordings/{recording_id}/transcript").json()
    speaker = client.post(
        f"/v1/recordings/{recording_id}/speakers",
        json={"speaker_id": "speaker-a", "display_name": "Jordan"},
        headers={
            **mutation_headers(csrf, "speaker-preserves-projections"),
            "If-Match": str(transcript["version"]),
        },
    )
    assert speaker.status_code == 200, speaker.text
    assert any(item["display_name"] == "Jordan" for item in speaker.json()["speakers"])
    tasks = client.get("/v1/tasks").json()["items"]
    assert len(tasks) == 1
    assert tasks[0]["status"] == "done"
    intelligence = client.get(f"/v1/recordings/{recording_id}/intelligence").json()
    assert len(intelligence["actions"]) == 1
    assert (
        next(
            item
            for item in intelligence["participants"]
            if item["speaker_cluster_id"] == "speaker-a"
        )["display_name"]
        == "Jordan"
    )

    merged = client.post(
        f"/v1/recordings/{recording_id}/speakers",
        json={"speaker_id": "speaker-b", "merge_into": "speaker-a"},
        headers={
            **mutation_headers(csrf, "merge-preserves-projections"),
            "If-Match": str(speaker.json()["version"]),
        },
    )
    assert merged.status_code == 200, merged.text
    assert [item["id"] for item in merged.json()["speakers"]] == ["speaker-a"]
    merged_intelligence = client.get(f"/v1/recordings/{recording_id}/intelligence").json()
    assert [item["speaker_cluster_id"] for item in merged_intelligence["participants"]] == [
        "speaker-a"
    ]
    assert merged_intelligence["decisions"][0]["participants"] == ["speaker-a"]

    for style in ("standard", "brief", "detailed", "action_focused"):
        regenerated = client.post(
            f"/v1/recordings/{recording_id}/regenerate",
            json={"mode": "standard", "summary_style": style},
            headers=mutation_headers(csrf, f"regenerate-{style}"),
        )
        assert regenerated.status_code == 202, regenerated.text
        assert regenerated.json()["summary_style"] == style
        projected = client.get(f"/v1/recordings/{recording_id}/intelligence").json()
        assert projected["provenance"]["summary_style"] == style
        assert projected["actions"][0]["status"] == "done"
        assert len(client.get("/v1/tasks").json()["items"]) == 1
        assert client.get("/v1/tasks").json()["items"][0]["status"] == "done"


def test_deep_processing_requests_fail_closed(client: TestClient) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    deep_regenerate = client.post(
        f"/v1/recordings/{recording_id}/regenerate",
        json={"mode": "deep", "summary_style": "standard"},
        headers=mutation_headers(csrf),
    )
    assert deep_regenerate.status_code == 409
    assert deep_regenerate.json()["detail"]["code"] == "capability_unavailable"
    deep_upload = client.post(
        "/v1/upload-sessions",
        json={
            "filename": "deep.wav",
            "content_type": "audio/wav",
            "size_bytes": 100,
            "mode": "deep",
        },
        headers=mutation_headers(csrf),
    )
    assert deep_upload.status_code == 409
    assert deep_upload.json()["detail"]["code"] == "capability_unavailable"


def test_delete_invalidates_grant_search_ask_and_artifacts(client: TestClient) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    grant = client.get(f"/v1/recordings/{recording_id}/media-grant").json()["url"]
    ask = client.post(
        "/v1/ask-sessions",
        json={"scope": {"type": "recording", "recording_id": recording_id}},
        headers=mutation_headers(csrf, "delete-ask-session"),
    ).json()
    costs_before = client.get("/v1/costs").json()["events"]
    deleted_cost_count = sum(item["recording_id"] == recording_id for item in costs_before)
    assert deleted_cost_count >= 2
    deleted = client.delete(f"/v1/recordings/{recording_id}", headers=mutation_headers(csrf))
    assert deleted.status_code == 204
    assert client.get(f"/v1/recordings/{recording_id}").status_code == 404
    assert client.get(f"/v1/recordings/{recording_id}/media-grant").status_code == 404
    assert client.get(grant).status_code == 404
    search = client.post(
        "/v1/search",
        json={
            "query": "browser upload",
            "filters": {"mode": "exact", "recording_id": recording_id},
        },
    )
    assert search.status_code == 200
    assert search.json()["total"] == 0
    ask_after = client.post(
        f"/v1/ask-sessions/{ask['id']}/messages",
        json={"content": "What was decided?"},
        headers=mutation_headers(csrf),
    )
    assert ask_after.status_code == 404
    costs_after = client.get("/v1/costs").json()["events"]
    redacted = [item for item in costs_after if item["provenance"].get("recording_deleted") is True]
    assert len(redacted) == deleted_cost_count
    assert all(item["recording_id"] is None for item in redacted)
    assert recording_id not in json.dumps(redacted)


def test_deleted_upload_idempotency_is_a_tombstone_not_resurrection(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    body = {
        "filename": "private-name.wav",
        "content_type": "audio/wav",
        "size_bytes": 44,
    }
    headers = mutation_headers(csrf, "deleted-upload-fence")
    created = client.post("/v1/upload-sessions", json=body, headers=headers)
    assert created.status_code == 201
    recording_id = created.json()["recording_id"]
    assert (
        client.delete(f"/v1/recordings/{recording_id}", headers=mutation_headers(csrf)).status_code
        == 204
    )
    replay = client.post("/v1/upload-sessions", json=body, headers=headers)
    assert replay.status_code == 410
    assert replay.json()["detail"]["code"] == "idempotent_resource_deleted"
    with client.app.state.database.session_factory() as db:
        from app.models import IdempotencyRecord

        row = db.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key == "deleted-upload-fence")
        )
        assert row.response == {"recording_id": recording_id, "deleted": True}
        assert "private-name" not in json.dumps(row.response)
    with client.app.state.database.session_factory() as db:
        assert (
            db.scalar(
                select(TranscriptVersion).where(TranscriptVersion.recording_id == recording_id)
            )
            is None
        )
        tombstone = db.get(Recording, recording_id)
        assert tombstone.status == "DELETED"
        assert tombstone.deletion_generation == 1


def test_lease_claim_is_exclusive(client: TestClient) -> None:
    database = client.app.state.database
    with database.session_factory() as db:
        recording = db.get(Recording, "demo-recording-test")
        run = ProcessingRun(
            id=str(uuid.uuid4()),
            recording_id=recording.id,
            workspace_id=recording.workspace_id,
            deletion_generation=recording.deletion_generation,
            status="queued",
            attempt=99,
        )
        db.add(run)
        db.commit()
    first = claim_next_run(database, "worker-one", lease_seconds=60)
    second = claim_next_run(database, "worker-two", lease_seconds=60)
    assert first == run.id
    assert second is None


def test_delete_during_provider_call_blocks_late_publication(client: TestClient) -> None:
    csrf, _ = login(client)
    client.app.state.settings.inline_worker = False
    from app.demo_fixture import load_fixture_wav

    data = load_fixture_wav(client.app.state.settings.fixture_root)
    upload, complete = upload_audio(
        client, csrf, data, filename="race-fixture.wav", idempotency_prefix="race"
    )
    assert complete.status_code == 202
    with client.app.state.database.session_factory() as db:
        run_id = db.scalar(
            select(ProcessingRun.id).where(
                ProcessingRun.recording_id == upload["recording_id"],
                ProcessingRun.status == "queued",
            )
        )

    entered = threading.Event()
    release = threading.Event()
    delegate = MockFixtureSpeechAdapter(client.app.state.settings.fixture_root)

    class BlockingSpeech:
        def transcribe(self, request: SpeechRequest):
            entered.set()
            assert release.wait(timeout=5)
            return delegate.transcribe(request)

    worker = threading.Thread(
        target=process_run,
        args=(
            client.app.state.database,
            client.app.state.blob_store,
            BlockingSpeech(),
            client.app.state.llm_adapter,
            client.app.state.settings,
            run_id,
        ),
    )
    worker.start()
    assert entered.wait(timeout=5)
    with client.app.state.database.session_factory() as db:
        reservation_id = db.scalar(
            select(BudgetReservation.id).where(BudgetReservation.attempt_id == f"speech:{run_id}")
        )
        assert reservation_id is not None
    deleted = client.delete(
        f"/v1/recordings/{upload['recording_id']}", headers=mutation_headers(csrf)
    )
    assert deleted.status_code == 204
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    with client.app.state.database.session_factory() as db:
        tombstone = db.get(Recording, upload["recording_id"])
        assert tombstone.status == "DELETED"
        assert (
            db.scalar(
                select(TranscriptVersion).where(
                    TranscriptVersion.recording_id == upload["recording_id"]
                )
            )
            is None
        )
        reservation = db.get(BudgetReservation, reservation_id)
        assert reservation.status == "released"
        assert reservation.recording_id is None
        assert reservation.attempt_id != f"speech:{run_id}"


def test_generic_adapter_failure_releases_zero_cost_reservation(client: TestClient) -> None:
    csrf, _ = login(client)
    client.app.state.settings.inline_worker = False
    from app.demo_fixture import load_fixture_wav

    data = load_fixture_wav(client.app.state.settings.fixture_root)
    upload, complete = upload_audio(
        client,
        csrf,
        data,
        filename="adapter-failure.wav",
        idempotency_prefix="adapter-failure",
    )
    assert complete.status_code == 202
    with client.app.state.database.session_factory() as db:
        run_id = db.scalar(
            select(ProcessingRun.id).where(
                ProcessingRun.recording_id == upload["recording_id"],
                ProcessingRun.status == "queued",
            )
        )

    class FailingSpeech:
        def transcribe(self, request: SpeechRequest):
            raise RuntimeError("adapter failed after dispatch")

    process_run(
        client.app.state.database,
        client.app.state.blob_store,
        FailingSpeech(),
        client.app.state.llm_adapter,
        client.app.state.settings,
        run_id,
    )
    with client.app.state.database.session_factory() as db:
        run = db.get(ProcessingRun, run_id)
        assert run.status == "failed_retryable"
        assert run.completed_at is not None
        failed_stage = db.scalar(
            select(StageRun).where(
                StageRun.processing_run_id == run_id,
                StageRun.stage == "transcribing",
            )
        )
        assert failed_stage.status == "failed"
        reservation = db.scalar(
            select(BudgetReservation).where(BudgetReservation.attempt_id == f"speech:{run_id}")
        )
        assert reservation.status == "released"
        assert reservation.release_reason == "provider_or_processing_exception"

    retried = client.post(
        f"/v1/recordings/{upload['recording_id']}/retry",
        headers=mutation_headers(csrf, "adapter-failure-retry"),
    )
    assert retried.status_code == 202
    with client.app.state.database.session_factory() as db:
        retry_run_id = db.scalar(
            select(ProcessingRun.id).where(
                ProcessingRun.recording_id == upload["recording_id"],
                ProcessingRun.status == "queued",
            )
        )
        assert retry_run_id != run_id
    process_run(
        client.app.state.database,
        client.app.state.blob_store,
        client.app.state.speech_adapter,
        client.app.state.llm_adapter,
        client.app.state.settings,
        retry_run_id,
    )
    with client.app.state.database.session_factory() as db:
        assert db.get(Recording, upload["recording_id"]).status == "READY"
        retry_reservation = db.scalar(
            select(BudgetReservation).where(
                BudgetReservation.attempt_id == f"speech:{retry_run_id}"
            )
        )
        assert retry_reservation.status == "committed"


def test_cancel_settles_inflight_zero_cost_reservation(client: TestClient) -> None:
    csrf, _ = login(client)
    client.app.state.settings.inline_worker = False
    from app.demo_fixture import load_fixture_wav

    data = load_fixture_wav(client.app.state.settings.fixture_root)
    upload, complete = upload_audio(
        client,
        csrf,
        data,
        filename="cancel-inflight.wav",
        idempotency_prefix="cancel-inflight",
    )
    assert complete.status_code == 202
    with client.app.state.database.session_factory() as db:
        run_id = db.scalar(
            select(ProcessingRun.id).where(
                ProcessingRun.recording_id == upload["recording_id"],
                ProcessingRun.status == "queued",
            )
        )

    entered = threading.Event()
    release = threading.Event()
    delegate = MockFixtureSpeechAdapter(client.app.state.settings.fixture_root)

    class BlockingSpeech:
        def transcribe(self, request: SpeechRequest):
            entered.set()
            assert release.wait(timeout=5)
            return delegate.transcribe(request)

    worker = threading.Thread(
        target=process_run,
        args=(
            client.app.state.database,
            client.app.state.blob_store,
            BlockingSpeech(),
            client.app.state.llm_adapter,
            client.app.state.settings,
            run_id,
        ),
    )
    worker.start()
    assert entered.wait(timeout=5)
    cancelled = client.post(
        f"/v1/recordings/{upload['recording_id']}/cancel",
        headers=mutation_headers(csrf),
    )
    assert cancelled.status_code == 200
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    with client.app.state.database.session_factory() as db:
        run = db.get(ProcessingRun, run_id)
        assert run.status == "cancelled"
        reservation = db.scalar(
            select(BudgetReservation).where(BudgetReservation.attempt_id == f"speech:{run_id}")
        )
        assert reservation.status == "released"
        assert reservation.release_reason == "processing_cancelled"


def test_worker_rechecks_transcript_after_llm_and_preserves_concurrent_correction(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    client.app.state.settings.inline_worker = False
    from app.demo_fixture import load_fixture_wav

    data = load_fixture_wav(client.app.state.settings.fixture_root)
    upload, complete = upload_audio(
        client,
        csrf,
        data,
        filename="worker-correction-race.wav",
        idempotency_prefix="worker-correction-race",
    )
    assert complete.status_code == 202
    with client.app.state.database.session_factory() as db:
        run_id = db.scalar(
            select(ProcessingRun.id).where(
                ProcessingRun.recording_id == upload["recording_id"],
                ProcessingRun.status == "queued",
            )
        )

    entered = threading.Event()
    release = threading.Event()
    delegate = MockFixtureLLMAdapter(client.app.state.settings.fixture_root)

    class BlockingLLM:
        def extract_intelligence(self, **kwargs):
            entered.set()
            assert release.wait(timeout=5)
            return delegate.extract_intelligence(**kwargs)

    worker = threading.Thread(
        target=process_run,
        args=(
            client.app.state.database,
            client.app.state.blob_store,
            client.app.state.speech_adapter,
            BlockingLLM(),
            client.app.state.settings,
            run_id,
        ),
    )
    worker.start()
    assert entered.wait(timeout=5)
    transcript = client.get(f"/v1/recordings/{upload['recording_id']}/transcript").json()
    assert transcript["version"] == 1
    corrected = client.post(
        f"/v1/recordings/{upload['recording_id']}/corrections",
        json={"segment_id": "segment-2", "text": "The corrected source wins."},
        headers={
            **mutation_headers(csrf, "worker-race-correction"),
            "If-Match": "1",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["version"] == 2
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    with client.app.state.database.session_factory() as db:
        recording = db.get(Recording, upload["recording_id"])
        assert recording.status == "READY"
        assert recording.transcript_version == 2
        current = db.scalar(
            select(IntelligenceVersion).where(
                IntelligenceVersion.recording_id == recording.id,
                IntelligenceVersion.is_current.is_(True),
            )
        )
        assert current.transcript_version == 2
        run = db.get(ProcessingRun, run_id)
        assert run.status == "cancelled"
        reservation = db.scalar(
            select(BudgetReservation).where(
                BudgetReservation.attempt_id == f"intelligence:{run_id}"
            )
        )
        assert reservation.status == "released"


def test_invalid_regeneration_output_settles_post_dispatch_reservation(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)

    class InvalidLLM:
        def extract_intelligence(self, **kwargs):
            return (
                {
                    "title": {"text": "Ungrounded", "evidence": []},
                    "summary": {"short": "Bad", "detailed": "Bad", "evidence": []},
                    "facts": [],
                    "decisions": [],
                    "actions": [],
                    "topics": [],
                    "participants": [],
                    "open_questions": [],
                    "warnings": [],
                },
                {
                    "provider": "invalid.test",
                    "model_alias": "invalid",
                    "resolved_model": "invalid-v1",
                    "usage": {},
                },
            )

    client.app.state.llm_adapter = InvalidLLM()
    with pytest.raises(ValueError, match="lacks evidence"):
        client.post(
            f"/v1/recordings/{recording_id}/regenerate",
            json={"mode": "standard", "summary_style": "standard"},
            headers=mutation_headers(csrf, "invalid-regeneration-output"),
        )
    with client.app.state.database.session_factory() as db:
        recording = db.get(Recording, recording_id)
        assert recording.intelligence_version == 1
        reservations = db.scalars(
            select(BudgetReservation).where(
                BudgetReservation.stage == "regenerate_intelligence",
                BudgetReservation.recording_id == recording_id,
            )
        ).all()
        assert len(reservations) == 1
        assert reservations[0].status == "released"
        assert reservations[0].release_reason == "regeneration_post_dispatch_failure"


def test_zero_cost_regeneration_can_retry_same_idempotency_key_after_failure(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    delegate = MockFixtureLLMAdapter(client.app.state.settings.fixture_root)

    class FailOnceLLM:
        calls = 0

        def extract_intelligence(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated fixture adapter failure")
            return delegate.extract_intelligence(**kwargs)

    adapter = FailOnceLLM()
    client.app.state.llm_adapter = adapter
    headers = mutation_headers(csrf, "retry-same-regeneration-attempt")
    with pytest.raises(RuntimeError, match="simulated fixture adapter failure"):
        client.post(
            f"/v1/recordings/{recording_id}/regenerate",
            json={"mode": "standard", "summary_style": "brief"},
            headers=headers,
        )
    with client.app.state.database.session_factory() as db:
        reservation = db.scalar(
            select(BudgetReservation).where(
                BudgetReservation.stage == "regenerate_intelligence",
                BudgetReservation.recording_id == recording_id,
            )
        )
        reservation_id = reservation.id
        assert reservation.status == "released"

    retry = client.post(
        f"/v1/recordings/{recording_id}/regenerate",
        json={"mode": "standard", "summary_style": "brief"},
        headers=headers,
    )
    assert retry.status_code == 202, retry.text
    assert adapter.calls == 2
    with client.app.state.database.session_factory() as db:
        reservation = db.get(BudgetReservation, reservation_id)
        assert reservation.status == "committed"
        assert reservation.committed_usd == 0


def test_reconciliation_pending_regeneration_never_redispatches(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    idempotency_key = "ambiguous-regeneration-attempt"

    class ForbiddenLLM:
        calls = 0

        def extract_intelligence(self, **kwargs):
            self.calls += 1
            raise AssertionError("ambiguous attempts must not be redispatched")

    adapter = ForbiddenLLM()
    client.app.state.llm_adapter = adapter
    with client.app.state.database.session_factory() as db:
        recording = db.get(Recording, recording_id)
        request_identity = hashlib.sha256(idempotency_key.encode()).hexdigest()[:20]
        attempt_id = (
            f"regenerate:{recording.id}:g{recording.deletion_generation}:"
            f"t{recording.transcript_version}:i{recording.intelligence_version}:"
            f"{request_identity}"
        )
        reservation = reserve_budget(
            db,
            attempt_id=attempt_id,
            workspace_id=recording.workspace_id,
            recording_id=recording.id,
            stage="regenerate_intelligence",
            amount_usd=0.0,
            per_request_cap_usd=client.app.state.settings.recording_cost_ceiling_usd,
        )
        reservation.status = "reconciliation_pending"
        reservation.release_reason = "ambiguous_provider_outcome:test"
        db.commit()

    response = client.post(
        f"/v1/recordings/{recording_id}/regenerate",
        json={"mode": "standard", "summary_style": "standard"},
        headers=mutation_headers(csrf, idempotency_key),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "budget_reconciliation_pending"
    assert adapter.calls == 0


def test_regeneration_rechecks_after_delete_and_publishes_nothing_late(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    entered = threading.Event()
    release = threading.Event()
    delegate = MockFixtureLLMAdapter(client.app.state.settings.fixture_root)

    class BlockingLLM:
        def extract_intelligence(self, **kwargs):
            entered.set()
            assert release.wait(timeout=5)
            return delegate.extract_intelligence(**kwargs)

    client.app.state.llm_adapter = BlockingLLM()
    responses = []
    errors = []

    def invoke_regeneration() -> None:
        try:
            responses.append(
                client.post(
                    f"/v1/recordings/{recording_id}/regenerate",
                    json={"mode": "standard", "summary_style": "brief"},
                    headers=mutation_headers(csrf, "delete-during-regeneration"),
                )
            )
        except Exception as exc:  # pragma: no cover - asserted below for diagnostics
            errors.append(exc)

    request_thread = threading.Thread(target=invoke_regeneration)
    request_thread.start()
    assert entered.wait(timeout=5)
    with client.app.state.database.session_factory() as db:
        reservation_id = db.scalar(
            select(BudgetReservation.id).where(
                BudgetReservation.stage == "regenerate_intelligence",
                BudgetReservation.recording_id == recording_id,
            )
        )
    assert reservation_id is not None
    assert (
        client.delete(f"/v1/recordings/{recording_id}", headers=mutation_headers(csrf)).status_code
        == 204
    )
    release.set()
    request_thread.join(timeout=5)
    assert not request_thread.is_alive()
    assert errors == []
    assert len(responses) == 1
    assert responses[0].status_code == 409
    assert responses[0].json()["detail"]["code"] == "source_changed"
    with client.app.state.database.session_factory() as db:
        assert (
            db.scalar(
                select(IntelligenceVersion).where(
                    IntelligenceVersion.recording_id == recording_id
                )
            )
            is None
        )
        reservation = db.get(BudgetReservation, reservation_id)
        assert reservation.status == "released"
        assert reservation.recording_id is None


def test_regeneration_rechecks_after_correction_and_preserves_new_source(
    client: TestClient,
) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    transcript = client.get(f"/v1/recordings/{recording_id}/transcript").json()
    entered = threading.Event()
    release = threading.Event()
    delegate = MockFixtureLLMAdapter(client.app.state.settings.fixture_root)

    class BlockingLLM:
        def extract_intelligence(self, **kwargs):
            entered.set()
            assert release.wait(timeout=5)
            return delegate.extract_intelligence(**kwargs)

    client.app.state.llm_adapter = BlockingLLM()
    responses = []

    def invoke_regeneration() -> None:
        responses.append(
            client.post(
                f"/v1/recordings/{recording_id}/regenerate",
                json={"mode": "standard", "summary_style": "detailed"},
                headers=mutation_headers(csrf, "correction-during-regeneration"),
            )
        )

    request_thread = threading.Thread(target=invoke_regeneration)
    request_thread.start()
    assert entered.wait(timeout=5)
    corrected = client.post(
        f"/v1/recordings/{recording_id}/corrections",
        json={"segment_id": "segment-2", "text": "Corrected while regeneration waited."},
        headers={
            **mutation_headers(csrf, "concurrent-correction"),
            "If-Match": str(transcript["version"]),
        },
    )
    assert corrected.status_code == 200
    release.set()
    request_thread.join(timeout=5)
    assert not request_thread.is_alive()
    assert len(responses) == 1
    assert responses[0].status_code == 409
    assert responses[0].json()["detail"]["code"] == "source_changed"
    with client.app.state.database.session_factory() as db:
        recording = db.get(Recording, recording_id)
        assert recording.transcript_version == corrected.json()["version"]
        current = db.scalar(
            select(IntelligenceVersion).where(
                IntelligenceVersion.recording_id == recording_id,
                IntelligenceVersion.is_current.is_(True),
            )
        )
        assert current.transcript_version == corrected.json()["version"]
        reservations = db.scalars(
            select(BudgetReservation).where(
                BudgetReservation.stage == "regenerate_intelligence",
                BudgetReservation.recording_id == recording_id,
            )
        ).all()
        assert len(reservations) == 1
        assert reservations[0].status == "released"


def test_expired_processing_lease_becomes_retryable(client: TestClient) -> None:
    csrf, _ = login(client)
    client.app.state.settings.inline_worker = False
    from app.demo_fixture import load_fixture_wav

    data = load_fixture_wav(client.app.state.settings.fixture_root)
    upload, complete = upload_audio(
        client,
        csrf,
        data,
        filename="expired-lease.wav",
        idempotency_prefix="expired-lease",
    )
    assert complete.status_code == 202
    with client.app.state.database.session_factory() as db:
        run_id = db.scalar(
            select(ProcessingRun.id).where(
                ProcessingRun.recording_id == upload["recording_id"],
                ProcessingRun.status == "queued",
            )
        )

    entered = threading.Event()
    release = threading.Event()
    delegate = MockFixtureSpeechAdapter(client.app.state.settings.fixture_root)

    class BlockingSpeech:
        def transcribe(self, request: SpeechRequest):
            entered.set()
            assert release.wait(timeout=5)
            return delegate.transcribe(request)

    worker = threading.Thread(
        target=process_run,
        args=(
            client.app.state.database,
            client.app.state.blob_store,
            BlockingSpeech(),
            client.app.state.llm_adapter,
            client.app.state.settings,
            run_id,
        ),
    )
    worker.start()
    assert entered.wait(timeout=5)
    with client.app.state.database.session_factory() as db:
        run = db.get(ProcessingRun, run_id)
        run.lease_expires_at = run.lease_expires_at - timedelta(hours=1)
        db.commit()
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()

    with client.app.state.database.session_factory() as db:
        run = db.get(ProcessingRun, run_id)
        recording = db.get(Recording, upload["recording_id"])
        assert run.status == "cancelled"
        assert recording.status == "FAILED_RETRYABLE"
        assert recording.error_code == "stale_processing_lease"
        reservation = db.scalar(
            select(BudgetReservation).where(BudgetReservation.attempt_id == f"speech:{run_id}")
        )
        assert reservation.status == "released"

    retry = client.post(
        f"/v1/recordings/{upload['recording_id']}/retry",
        headers=mutation_headers(csrf, "retry-expired-lease"),
    )
    assert retry.status_code == 202


def test_recording_artifact_reads_request_a_publication_lock(
    client: TestClient, monkeypatch
) -> None:
    login(client)
    recording_id = fixture_recording_id(client)
    from app.routes import recordings as recording_routes

    original_require = recording_routes.require_recording
    lock_flags = []

    def observe_require(*args, **kwargs):
        lock_flags.append(kwargs.get("lock"))
        return original_require(*args, **kwargs)

    monkeypatch.setattr(recording_routes, "require_recording", observe_require)
    responses = [
        client.get(f"/v1/recordings/{recording_id}"),
        client.get(f"/v1/recordings/{recording_id}/transcript"),
        client.get(f"/v1/recordings/{recording_id}/intelligence"),
        client.get(f"/v1/recordings/{recording_id}/events"),
    ]
    assert all(item.status_code == 200 for item in responses)
    assert lock_flags == [True, True, True, True]


def test_media_grant_is_not_created_when_tombstone_wins(
    client: TestClient, monkeypatch
) -> None:
    csrf, _ = login(client)
    recording_id = fixture_recording_id(client)
    from app.routes import recordings as recording_routes

    original_require = recording_routes.require_recording
    entered = threading.Event()
    release = threading.Event()
    saw_lock = []

    def gated_require(*args, **kwargs):
        saw_lock.append(kwargs.get("lock"))
        entered.set()
        assert release.wait(timeout=5)
        return original_require(*args, **kwargs)

    monkeypatch.setattr(recording_routes, "require_recording", gated_require)
    responses = []
    request_thread = threading.Thread(
        target=lambda: responses.append(client.get(f"/v1/recordings/{recording_id}/media-grant"))
    )
    request_thread.start()
    assert entered.wait(timeout=5)
    assert (
        client.delete(f"/v1/recordings/{recording_id}", headers=mutation_headers(csrf)).status_code
        == 204
    )
    release.set()
    request_thread.join(timeout=5)
    assert not request_thread.is_alive()
    assert saw_lock == [True]
    assert len(responses) == 1
    assert responses[0].status_code == 404
    with client.app.state.database.session_factory() as db:
        assert db.scalar(select(MediaGrant).where(MediaGrant.recording_id == recording_id)) is None
