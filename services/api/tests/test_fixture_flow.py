from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.demo_fixture import (
    FIXTURE_DURATION_MS,
    FIXTURE_ID,
    FIXTURE_SHA256,
    load_fixture_manifest,
    load_fixture_sidecar,
    load_fixture_wav,
)

from .conftest import FIXTURE_ROOT, login, mutation_headers


def _fixture_recording(client: TestClient) -> dict:
    response = client.get("/v1/recordings")
    assert response.status_code == 200
    return next(item for item in response.json()["items"] if item["is_fixture"])


def test_canonical_fixture_files_match_backend_contract() -> None:
    media = load_fixture_wav(FIXTURE_ROOT)
    manifest = load_fixture_manifest(FIXTURE_ROOT)
    sidecar = load_fixture_sidecar(FIXTURE_ROOT)
    item = next(value for value in manifest["fixtures"] if value["id"] == FIXTURE_ID)
    assert item["sha256"] == FIXTURE_SHA256
    assert item["duration_ms"] == FIXTURE_DURATION_MS
    assert item["bytes"] == len(media)
    assert sidecar["fixture_id"] == FIXTURE_ID
    assert sidecar["provenance"]["provider_mode"] == "fixture"


def test_seeded_fixture_exposes_complete_ui_contract(client: TestClient) -> None:
    csrf, session = login(client)
    assert session["principal"]["name"] == "Alice Rivera"
    assert session["workspace"]["role"] == "owner"
    assert session["workspace"]["retained_recordings"] == 1
    assert session["workspace"]["retained_bytes"] > 0

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["provider_mode"] == "approved_fixture_only"

    recording = _fixture_recording(client)
    assert recording["state"] == "ready"
    assert all(recording["readiness"].values())
    assert recording["duration_ms"] == FIXTURE_DURATION_MS
    assert recording["expires_at"]

    transcript_response = client.get(f"/v1/recordings/{recording['id']}/transcript")
    assert transcript_response.status_code == 200
    transcript = transcript_response.json()
    assert transcript["duration_ms"] == FIXTURE_DURATION_MS
    assert transcript["intervals"] == [
        {"id": "timeline-1", "start_ms": 0, "end_ms": 18_000, "state": "speech"}
    ]
    assert len(transcript["segments"]) == 4
    assert len(transcript["speakers"]) == 2
    assert transcript["provenance"]["mock"] is True
    assert transcript["provenance"]["source"] == "approved_fixture_sidecar"

    intelligence_response = client.get(f"/v1/recordings/{recording['id']}/intelligence")
    assert intelligence_response.status_code == 200
    intelligence = intelligence_response.json()
    assert intelligence["title"]["text"] == "Pocket architecture demo planning"
    assert intelligence["actions"][0]["owner_text"] == "Jordan"
    assert intelligence["provenance"]["mock"] is True
    for group in ("facts", "decisions", "actions", "topics"):
        for item in intelligence[group]:
            assert item["evidence"]
            assert all(citation["recording_id"] == recording["id"] for citation in item["evidence"])

    styles = client.get("/v1/summary-styles")
    assert styles.status_code == 200
    assert styles.json()["total"] == 4
    assert csrf


def test_all_labeled_ask_questions_are_grounded_or_abstain(client: TestClient) -> None:
    csrf, _ = login(client)
    recording = _fixture_recording(client)
    session_response = client.post(
        "/v1/ask-sessions",
        json={"scope": {"type": "recording", "recording_id": recording["id"]}},
        headers=mutation_headers(csrf, "ask-session-fixture"),
    )
    assert session_response.status_code == 201, session_response.text
    ask_session_id = session_response.json()["id"]
    corpus = json.loads(
        (FIXTURE_ROOT / "quality" / "ask-questions.json").read_text(encoding="utf-8")
    )
    for item in corpus["questions"]:
        response = client.post(
            f"/v1/ask-sessions/{ask_session_id}/messages",
            json={"content": item["question"], "deep": False},
            headers=mutation_headers(csrf, item["id"]),
        )
        assert response.status_code == 201, (item["id"], response.text)
        message = response.json()["message"]
        assert (message["status"] == "abstained") is item["should_abstain"], item["id"]
        answer = message["content"].casefold()
        for expected in item["expected_answer_contains"]:
            assert expected.casefold() in answer, (item["id"], answer)
        cited = {citation["segment_id"] for citation in message["citations"]}
        assert set(item["expected_segment_ids"]).issubset(cited), (item["id"], cited)
        if not item["should_abstain"]:
            assert message["citations"]


def test_search_filters_tasks_costs_recap_and_exports(client: TestClient) -> None:
    csrf, _ = login(client)
    recording = _fixture_recording(client)
    search = client.post(
        "/v1/search",
        json={
            "query": "validation checklist",
            "filters": {
                "mode": "semantic",
                "recording_id": recording["id"],
                "speaker": "speaker-a",
                "topic": "Browser upload",
            },
        },
    )
    assert search.status_code == 200, search.text
    search_payload = search.json()
    assert search_payload["total"] == 1
    assert search_payload["items"][0]["citation"]["segment_id"] == "segment-3"
    assert search_payload["requested_mode"] == "semantic"
    assert search_payload["effective_mode"] == "lexical"
    assert search_payload["semantic_available"] is False

    action_search = client.post(
        "/v1/search",
        json={
            "query": "validation",
            "filters": {"mode": "exact", "action_state": "open"},
        },
    )
    assert action_search.status_code == 200
    assert action_search.json()["items"][0]["kind"] == "action"

    tasks = client.get("/v1/tasks").json()
    assert tasks["total"] == 1
    task = tasks["items"][0]
    updated = client.patch(
        f"/v1/tasks/{task['id']}",
        json={"status": "done"},
        headers={**mutation_headers(csrf), "If-Match": str(task["version"])},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "done"

    recap = client.post(
        "/v1/recaps",
        json={"kind": "daily"},
        headers=mutation_headers(csrf, "daily-recap"),
    )
    assert recap.status_code == 201
    assert "browser upload" in recap.json()["summary"].casefold()

    for body, marker in (
        (
            {"format": "markdown", "resource": "recording", "recording_id": recording["id"]},
            "Pocket recordings export",
        ),
        ({"format": "csv", "resource": "tasks"}, "recording_id"),
        ({"format": "ics", "resource": "tasks"}, "BEGIN:VCALENDAR"),
        ({"format": "json", "resource": "recap", "recap_id": recap.json()["id"]}, '"id"'),
    ):
        export = client.post("/v1/exports", json=body, headers=mutation_headers(csrf))
        assert export.status_code == 201, export.text
        assert marker in export.json()["content"]

    costs = client.get(f"/v1/costs?recording_id={recording['id']}")
    assert costs.status_code == 200
    cost_payload = costs.json()
    assert cost_payload["quality_gate_passed"] is False
    assert cost_payload["modeled_delta_usd"] == 0
    assert all(event["estimated_cost_usd"] == 0 for event in cost_payload["events"])
