from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'intelligent-audio-analysis-test.db'}",
        blob_root=tmp_path / "blobs",
        fixture_root=FIXTURE_ROOT,
        inline_worker=True,
        cookie_secure=False,
        token_signing_secret="test-only-signing-secret-at-least-32-characters",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings), base_url="http://testserver") as value:
        yield value


def login(client: TestClient, principal_id: str = "test-account") -> tuple[str, dict]:
    response = client.post("/v1/auth/demo-login", json={"principal_id": principal_id})
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload["csrf_token"], payload


def mutation_headers(csrf: str, idempotency_key: str | None = None) -> dict[str, str]:
    result = {"X-CSRF-Token": csrf}
    if idempotency_key:
        result["Idempotency-Key"] = idempotency_key
    return result
