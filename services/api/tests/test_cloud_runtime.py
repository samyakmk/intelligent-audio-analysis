from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.blobstore import BlobAlreadyExists, BlobNotFound, GCSBlobStore
from app.config import Settings, database_url_from_environment
from app.demo_fixture import load_fixture_wav
from app.main import create_app
from app.models import UploadSession

from .conftest import login, mutation_headers


class FakeNotFound(Exception):
    pass


class FakePreconditionFailed(Exception):
    pass


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str):
        self.bucket = bucket
        self.name = name

    def upload_from_string(self, data: bytes, **kwargs: object) -> None:
        if kwargs.get("if_generation_match") == 0 and self.name in self.bucket.objects:
            raise FakePreconditionFailed
        self.bucket.objects[self.name] = data

    def download_as_bytes(self, **_: object) -> bytes:
        try:
            return self.bucket.objects[self.name]
        except KeyError as exc:
            raise FakeNotFound from exc

    def exists(self, **_: object) -> bool:
        return self.name in self.bucket.objects

    def delete(self) -> None:
        try:
            del self.bucket.objects[self.name]
        except KeyError as exc:
            raise FakeNotFound from exc

    def rewrite(self, source: FakeBlob, **kwargs: object) -> tuple[None, int, int]:
        if kwargs.get("if_generation_match") == 0 and self.name in self.bucket.objects:
            raise FakePreconditionFailed
        data = source.download_as_bytes()
        self.bucket.objects[self.name] = data
        return None, len(data), len(data)

    def create_resumable_upload_session(self, **_: object) -> str:
        return f"https://storage.example.invalid/upload/{self.name}"


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


def fake_gcs_store() -> GCSBlobStore:
    store = object.__new__(GCSBlobStore)
    store.bucket_name = "test-bucket"
    store.prefix = "demo"
    store._not_found = FakeNotFound
    store._precondition_failed = FakePreconditionFailed
    store.client = object()
    store.bucket = FakeBucket()
    return store


def test_cloud_sql_settings_build_socket_url_without_machine_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("INSTANCE_CONNECTION_NAME", "project:region:instance")
    monkeypatch.setenv("DB_USER", "demo user")
    monkeypatch.setenv("DB_PASSWORD", "p@ss/word")
    monkeypatch.setenv("DB_NAME", "demo db")

    settings = Settings.from_environment()

    assert settings.database_url == (
        "postgresql+psycopg://demo+user:p%40ss%2Fword@/demo+db?"
        "host=%2Fcloudsql%2Fproject%3Aregion%3Ainstance"
    )


def test_cloud_sql_migration_url_uses_the_same_socket_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("INSTANCE_CONNECTION_NAME", "project:region:instance")
    monkeypatch.setenv("DB_USER", "migration-user")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    monkeypatch.setenv("DB_NAME", "audio_analysis")

    assert database_url_from_environment() == (
        "postgresql+psycopg://migration-user:secret@/audio_analysis?"
        "host=%2Fcloudsql%2Fproject%3Aregion%3Ainstance"
    )


def test_default_fixture_path_does_not_depend_on_source_tree_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FIXTURE_ROOT", raising=False)

    assert Settings.from_environment().fixture_root == Path("fixtures")


def test_gcs_blob_contract_preserves_immutable_objects_and_promotes() -> None:
    store = fake_gcs_store()
    store.put("quarantine/workspace/upload", b"audio")
    assert store.get("quarantine/workspace/upload") == b"audio"

    store.promote("quarantine/workspace/upload", "original/workspace/audio")
    assert not store.exists("quarantine/workspace/upload")
    assert store.get("original/workspace/audio") == b"audio"

    with pytest.raises(BlobAlreadyExists):
        store.put("original/workspace/audio", b"different", immutable=True)
    with pytest.raises(BlobNotFound):
        store.get("missing")


def test_direct_cloud_upload_is_reconciled_before_processing(settings: Settings) -> None:
    with TestClient(create_app(settings), base_url="https://demo.example") as client:
        cloud_store = fake_gcs_store()
        client.app.state.blob_store = cloud_store
        csrf, _ = login(client)
        data = load_fixture_wav(settings.fixture_root)
        digest = hashlib.sha256(data).hexdigest()
        created = client.post(
            "/v1/upload-sessions",
            json={
                "filename": "cloud.wav",
                "content_type": "audio/wav",
                "size_bytes": len(data),
                "sha256": digest,
                "language": "en",
                "vocabulary_hints": [],
                "mode": "standard",
            },
            headers=mutation_headers(csrf, "cloud-direct-create"),
        )
        assert created.status_code == 201, created.text
        upload = created.json()
        assert upload["upload_url"].startswith("https://storage.example.invalid/")

        with client.app.state.database.session_factory() as db:
            row = db.get(UploadSession, upload["id"])
            assert row is not None
            quarantine_key = row.quarantine_key
        cloud_store.put(quarantine_key, data)
        completed = client.post(
            f"/v1/recordings/{upload['recording_id']}/complete",
            json={"upload_session_id": upload["id"], "sha256": digest},
            headers=mutation_headers(csrf, "cloud-direct-complete"),
        )
        assert completed.status_code == 202, completed.text
        detail = client.get(f"/v1/recordings/{upload['recording_id']}")
        assert detail.status_code == 200
        assert detail.json()["state"] == "ready"
        replay = client.post(
            "/v1/upload-sessions",
            json={
                "filename": "cloud.wav",
                "content_type": "audio/wav",
                "size_bytes": len(data),
                "sha256": digest,
                "language": "en",
                "vocabulary_hints": [],
                "mode": "standard",
            },
            headers=mutation_headers(csrf, "cloud-direct-create"),
        )
        assert replay.status_code == 201
        assert replay.json()["upload_url"].startswith(
            "https://demo.example/v1/upload-sessions/"
        )


def test_static_web_uses_exported_routes_and_does_not_mask_api_404s(
    tmp_path: Path, settings: Settings
) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("home", encoding="utf-8")
    (web / "upload.html").write_text("upload", encoding="utf-8")
    assets = web / "_expo"
    assets.mkdir()
    (assets / "app.js").write_text("script", encoding="utf-8")
    settings.web_dist_root = web

    with TestClient(create_app(settings)) as client:
        assert client.get("/").text == "home"
        assert client.get("/upload").text == "upload"
        assert client.get("/recordings/dynamic-id").text == "home"
        assert client.get("/_expo/app.js").headers["cache-control"].endswith("immutable")
        assert client.get("/v1/not-a-route").status_code == 404
        assert client.get("/missing.js").status_code == 404
