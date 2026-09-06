from __future__ import annotations

import hashlib
import io
import struct
import wave
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.domain import detect_audio_format
from app.main import create_app
from app.models import IdempotencyRecord, MediaObject, UploadSession, utcnow

from .conftest import FIXTURE_ROOT, login, mutation_headers


def make_wav(*, seconds: float = 0.2, sample_rate: int = 8_000) -> bytes:
    output = io.BytesIO()
    frame_count = int(seconds * sample_rate)
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(struct.pack("<h", 0) * frame_count)
    return output.getvalue()


def upload_audio(
    client: TestClient,
    csrf: str,
    data: bytes,
    *,
    filename: str = "audio.wav",
    idempotency_prefix: str = "upload",
) -> tuple[dict, object]:
    digest = hashlib.sha256(data).hexdigest()
    create = client.post(
        "/v1/upload-sessions",
        json={
            "filename": filename,
            "content_type": "audio/wav",
            "size_bytes": len(data),
            "sha256": digest,
            "language": "en",
            "vocabulary_hints": [],
            "mode": "standard",
        },
        headers=mutation_headers(csrf, f"{idempotency_prefix}-create"),
    )
    assert create.status_code == 201, create.text
    upload = create.json()
    put = client.put(upload["upload_url"], content=data, headers=upload["upload_headers"])
    assert put.status_code == 204, put.text
    complete = client.post(
        f"/v1/recordings/{upload['recording_id']}/complete",
        json={"upload_session_id": upload["id"], "sha256": digest},
        headers=mutation_headers(csrf, f"{idempotency_prefix}-complete"),
    )
    return upload, complete


def test_arbitrary_valid_audio_is_preserved_but_never_invented(client: TestClient) -> None:
    csrf, _ = login(client)
    data = make_wav()
    digest = hashlib.sha256(data).hexdigest()
    upload, complete = upload_audio(client, csrf, data, idempotency_prefix="arbitrary")
    assert complete.status_code == 202, complete.text

    detail = client.get(f"/v1/recordings/{upload['recording_id']}")
    assert detail.status_code == 200
    recording = detail.json()
    assert recording["state"] == "partial"
    assert recording["readiness"] == {
        "original_ready": True,
        "transcript_ready": False,
        "intelligence_ready": False,
        "indexed_ready": False,
    }
    assert recording["issues"][0]["code"] == "speech_unconfigured"
    assert recording["sha256"] == digest
    assert client.get(f"/v1/recordings/{recording['id']}/transcript").status_code == 409
    assert client.get(f"/v1/recordings/{recording['id']}/intelligence").status_code == 409

    grant = client.get(f"/v1/recordings/{recording['id']}/media-grant")
    assert grant.status_code == 200
    media = client.get(grant.json()["url"])
    assert media.status_code == 200
    assert media.content == data
    assert hashlib.sha256(media.content).hexdigest() == digest
    partial = client.get(grant.json()["url"], headers={"Range": "bytes=10-29"})
    assert partial.status_code == 206
    assert partial.content == data[10:30]
    assert partial.headers["content-range"] == f"bytes 10-29/{len(data)}"
    invalid_range = client.get(grant.json()["url"], headers={"Range": "bytes=999999-"})
    assert invalid_range.status_code == 416

    search = client.post(
        "/v1/search",
        json={
            "query": "plausible invented transcript",
            "filters": {"mode": "exact", "recording_id": recording["id"]},
        },
    )
    assert search.status_code == 200
    assert search.json()["total"] == 0


def test_same_byte_put_after_lost_complete_response_is_a_noop(client: TestClient) -> None:
    csrf, _ = login(client)
    from app.demo_fixture import load_fixture_wav

    data = load_fixture_wav(client.app.state.settings.fixture_root)
    upload, complete = upload_audio(
        client,
        csrf,
        data,
        filename="lost-complete-response.wav",
        idempotency_prefix="lost-complete-response",
    )
    assert complete.status_code == 202
    before = client.get(f"/v1/recordings/{upload['recording_id']}").json()
    assert before["state"] == "ready"
    with client.app.state.database.session_factory() as db:
        row = db.get(UploadSession, upload["id"])
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()

    replay = client.put(upload["upload_url"], content=data, headers=upload["upload_headers"])
    assert replay.status_code == 204
    after = client.get(f"/v1/recordings/{upload['recording_id']}").json()
    assert after["state"] == "ready"
    assert after["readiness"] == before["readiness"]
    with client.app.state.database.session_factory() as db:
        row = db.get(UploadSession, upload["id"])
        assert row.status in {"sealed", "sealed_cleanup_pending"}

    different = bytearray(data)
    different[-1] ^= 1
    mismatch = client.put(
        upload["upload_url"],
        content=bytes(different),
        headers=upload["upload_headers"],
    )
    assert mismatch.status_code == 409
    assert client.get(f"/v1/recordings/{upload['recording_id']}").json()["state"] == "ready"


def test_invalid_media_is_terminal_and_never_promoted(client: TestClient) -> None:
    csrf, _ = login(client)
    data = b"not an audio container"
    upload, complete = upload_audio(
        client, csrf, data, filename="misleading.wav", idempotency_prefix="invalid"
    )
    assert complete.status_code == 422
    detail = client.get(f"/v1/recordings/{upload['recording_id']}").json()
    assert detail["state"] == "failed_final"
    assert detail["readiness"] == {
        "original_ready": False,
        "transcript_ready": False,
        "intelligence_ready": False,
        "indexed_ready": False,
    }
    assert detail["size_bytes"] == 0
    with client.app.state.database.session_factory() as db:
        assert (
            db.scalar(select(MediaObject).where(MediaObject.recording_id == upload["recording_id"]))
            is None
        )


def test_upload_admission_and_container_validation_fail_closed(client: TestClient) -> None:
    csrf, _ = login(client)
    zero = client.post(
        "/v1/upload-sessions",
        json={"filename": "empty.wav", "content_type": "audio/wav", "size_bytes": 0},
        headers=mutation_headers(csrf),
    )
    assert zero.status_code == 422

    valid = make_wav()
    reserved = client.post(
        "/v1/upload-sessions",
        json={
            "filename": "reserved.wav",
            "content_type": "audio/wav",
            "size_bytes": 1,
            "sha256": hashlib.sha256(valid).hexdigest(),
        },
        headers=mutation_headers(csrf, "reserved-size"),
    ).json()
    mismatch = client.put(reserved["upload_url"], content=valid, headers=reserved["upload_headers"])
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["code"] == "reserved_size_mismatch"
    with client.app.state.database.session_factory() as db:
        upload = db.get(UploadSession, reserved["id"])
        assert upload.status == "created"
        assert not client.app.state.blob_store.exists(upload.quarantine_key)

    truncated = valid[:-11]
    upload, complete = upload_audio(
        client,
        csrf,
        truncated,
        filename="truncated.wav",
        idempotency_prefix="truncated",
    )
    assert complete.status_code == 422
    assert complete.json()["detail"]["code"] in {"corrupt_media", "partial_media"}
    with client.app.state.database.session_factory() as db:
        assert (
            db.scalar(select(MediaObject).where(MediaObject.recording_id == upload["recording_id"]))
            is None
        )

    trailing = valid + b"not-a-riff-chunk"
    _, trailing_complete = upload_audio(
        client,
        csrf,
        trailing,
        filename="trailing.wav",
        idempotency_prefix="trailing",
    )
    assert trailing_complete.status_code == 422
    assert detect_audio_format(bytes.fromhex("fff15080")) == "aac"


def test_reserved_and_final_checksums_are_terminal(client: TestClient) -> None:
    csrf, _ = login(client)
    data = make_wav()
    digest = hashlib.sha256(data).hexdigest()
    created = client.post(
        "/v1/upload-sessions",
        json={
            "filename": "hash.wav",
            "content_type": "audio/wav",
            "size_bytes": len(data),
            "sha256": "0" * 64,
        },
        headers=mutation_headers(csrf, "reserved-hash"),
    ).json()
    assert (
        client.put(
            created["upload_url"], content=data, headers=created["upload_headers"]
        ).status_code
        == 204
    )
    rejected = client.post(
        f"/v1/recordings/{created['recording_id']}/complete",
        json={"upload_session_id": created["id"], "sha256": digest},
        headers=mutation_headers(csrf, "reserved-hash-complete"),
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "reserved_checksum_mismatch"
    detail = client.get(f"/v1/recordings/{created['recording_id']}").json()
    assert detail["state"] == "failed_final"
    assert detail["readiness"]["original_ready"] is False


def test_upload_idempotency_is_json_safe_and_stores_no_bearer(client: TestClient) -> None:
    csrf, _ = login(client)
    data = make_wav()
    digest = hashlib.sha256(data).hexdigest()
    body = {
        "filename": "retry.wav",
        "content_type": "audio/wav",
        "size_bytes": len(data),
        "sha256": digest,
        "language": "en",
        "vocabulary_hints": [],
        "mode": "standard",
    }
    headers = mutation_headers(csrf, "stable-upload-key")
    first = client.post("/v1/upload-sessions", json=body, headers=headers)
    second = client.post("/v1/upload-sessions", json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    raw_token = first.json()["upload_headers"]["X-Upload-Token"]
    with client.app.state.database.session_factory() as db:
        record = db.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.key == "stable-upload-key")
        )
        serialized = str(record.response)
        assert raw_token not in serialized
        assert "upload_headers" not in record.response


def test_expired_quarantine_is_swept_and_completion_fails(client: TestClient) -> None:
    csrf, _ = login(client)
    data = make_wav()
    digest = hashlib.sha256(data).hexdigest()
    body = {
        "filename": "expires.wav",
        "content_type": "audio/wav",
        "size_bytes": len(data),
        "sha256": digest,
        "language": "en",
        "vocabulary_hints": [],
        "mode": "standard",
    }
    created = client.post(
        "/v1/upload-sessions",
        json=body,
        headers=mutation_headers(csrf, "expiring-upload"),
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
        db.commit()
    complete = client.post(
        f"/v1/recordings/{created['recording_id']}/complete",
        json={"upload_session_id": created["id"], "sha256": digest},
        headers=mutation_headers(csrf, "expired-complete"),
    )
    assert complete.status_code == 410
    detail = client.get(f"/v1/recordings/{created['recording_id']}").json()
    assert detail["issues"][0]["code"] == "upload_expired"
    assert detail["size_bytes"] == 0


def test_quota_check_is_locked_and_idempotent_replay_precedes_admission(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'quota.db'}",
        blob_root=tmp_path / "blobs",
        fixture_root=FIXTURE_ROOT,
        inline_worker=True,
        cookie_secure=False,
        token_signing_secret="test-only-signing-secret-at-least-32-characters",
        workspace_recording_quota=2,
    )
    with TestClient(create_app(settings)) as client:
        csrf, _ = login(client)
        data = make_wav()
        digest = hashlib.sha256(data).hexdigest()
        body = {
            "filename": "last-slot.wav",
            "content_type": "audio/wav",
            "size_bytes": len(data),
            "sha256": digest,
            "language": "en",
            "vocabulary_hints": [],
            "mode": "standard",
        }
        headers = mutation_headers(csrf, "quota-final-slot")
        first = client.post("/v1/upload-sessions", json=body, headers=headers)
        assert first.status_code == 201
        replay = client.post("/v1/upload-sessions", json=body, headers=headers)
        assert replay.status_code == 201
        assert replay.json()["id"] == first.json()["id"]
        rejected = client.post(
            "/v1/upload-sessions",
            json={**body, "filename": "over-limit.wav"},
            headers=mutation_headers(csrf, "quota-over-limit"),
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "recording_quota_exceeded"
