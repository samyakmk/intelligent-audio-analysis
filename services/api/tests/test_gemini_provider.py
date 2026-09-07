from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings, validate_runtime_settings
from app.demo_fixture import load_fixture_wav
from app.gemini_provider import (
    _SYSTEM_INSTRUCTION,
    GeminiAdapter,
    GeminiProviderError,
    GeminiResponseInvalid,
    TransportResponse,
    _AskAnswer,
    _estimate_tokens,
    _provider_schema,
    _RecordingIntelligence,
    _structured_input_token_upper_bound,
)
from app.models import Recording
from app.providers import AskRequest, ProviderBilledFailure, SpeechRequest

from .conftest import FIXTURE_ROOT, login, mutation_headers


@dataclass
class FakeTransport:
    responses: list[TransportResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        timeout_seconds: float,
    ) -> TransportResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "json": json_body,
                "content": content,
                "timeout_seconds": timeout_seconds,
            }
        )
        if not self.responses:
            raise AssertionError(f"unexpected transport call: {method} {url}")
        return self.responses.pop(0)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'gemini-provider.db'}",
        blob_root=tmp_path / "blobs",
        fixture_root=FIXTURE_ROOT,
        provider_mode="gemini",
        allow_remote_provider_calls=True,
        gemini_api_key="dummy-gemini-key-for-unit-tests-only",
        gemini_speech_model="gemini-3.5-flash-lite",
        token_signing_secret="test-only-signing-secret-at-least-32-characters",
    )


def _json_response(value: dict[str, Any], **headers: str) -> TransportResponse:
    return TransportResponse(
        status_code=200,
        headers={key.casefold(): item for key, item in headers.items()},
        body=json.dumps(value).encode(),
    )


def _interaction(payload: dict[str, Any], *, model: str, request_id: str) -> TransportResponse:
    return _json_response(
        {
            "id": request_id,
            "model": model,
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "finish_reason": "STOP",
                    "content": [{"type": "text", "text": json.dumps(payload)}],
                }
            ],
            "usage": {
                "total_input_tokens": 800,
                "total_output_tokens": 120,
                "total_thought_tokens": 30,
                "total_cached_tokens": 0,
                "total_tokens": 950,
            },
        }
    )


def _speech_request(*, budget_usd: float = 2.0) -> SpeechRequest:
    return SpeechRequest(
        recording_id="recording-1",
        audio_sha256="a" * 64,
        audio_reference="media-1",
        original_time_offset_ms=0,
        language="auto",
        vocabulary_hints=("Pocket",),
        require_diarization=True,
        require_timestamps=True,
        budget_usd=budget_usd,
        request_id="speech-attempt-1",
        audio_bytes=b"RIFF-dummy-audio",
        content_type="audio/wav",
        duration_ms=1_000,
    )


def _intelligence_payload(
    recording_id: str = "recording-1", transcript_version: int = 1
) -> dict[str, Any]:
    citation = {
        "recording_id": recording_id,
        "transcript_version": transcript_version,
        "segment_id": "segment-1",
        "start_ms": 0,
        "end_ms": 1_000,
        "speaker_id": "speaker-a",
        "quote": "Pocket validates citations.",
    }
    return {
        "title": {
            "text": "Citation validation",
            "evidence": [citation],
            "confidence": 0.96,
        },
        "summary": {
            "short": "Pocket validates citations.",
            "detailed": "Pocket validates citations before publishing intelligence.",
            "evidence": [citation],
            "confidence": 0.95,
        },
        "facts": [
            {"claim": "Pocket validates citations.", "evidence": [citation], "confidence": 0.96}
        ],
        "decisions": [],
        "actions": [
            {
                "id": "action-1",
                "task": "Review the citation validation report.",
                "owner_text": "Alex",
                "owner_id": None,
                "due_text": None,
                "due_at": None,
                "timezone": None,
                "status": "open",
                "ambiguities": [],
                "evidence": [citation],
                "confidence": 0.91,
            }
        ],
        "topics": [
            {
                "label": "Validation",
                "parent": None,
                "intervals": [{"start_ms": 0, "end_ms": 1_000}],
                "evidence": [citation],
            }
        ],
        "participants": [
            {
                "speaker_cluster_id": "speaker-a",
                "display_name": None,
                "confidence": 0.9,
                "evidence": [citation],
            }
        ],
        "open_questions": [],
        "warnings": [],
    }


def test_runtime_settings_fail_closed_without_real_key(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.gemini_api_key = "replace-me-gemini-api-key"

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        validate_runtime_settings(settings)


def test_provider_diagnostics_redact_the_configured_api_key(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    transport = FakeTransport(
        [
            TransportResponse(
                status_code=400,
                headers={},
                body=json.dumps(
                    {
                        "error": {
                            "status": "INVALID_ARGUMENT",
                            "message": (
                                "Rejected credential " + settings.gemini_api_key
                            ),
                        }
                    }
                ).encode(),
            )
        ]
    )
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)

    with pytest.raises(GeminiProviderError) as failure:
        adapter.transcribe(_speech_request())

    assert settings.gemini_api_key not in str(failure.value)
    assert "[REDACTED]" in str(failure.value)


def test_recommended_model_registry_is_pinned_and_legacy_strong_is_rejected(
    tmp_path: Path,
) -> None:
    recommended = _settings(tmp_path)
    recommended.gemini_speech_model = "gemini-3.5-transcribe"
    validate_runtime_settings(recommended)

    assert recommended.llm_cheap_model == "gemini-3.5-flash-lite"
    assert recommended.llm_strong_model == "gemini-3.8-flash"

    recommended.llm_strong_model = "gemini-3.1-pro-preview"
    with pytest.raises(RuntimeError, match="pinned, priced demo registry"):
        validate_runtime_settings(recommended)


def test_files_transcription_uses_key_only_on_google_control_plane(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    transcript = {
        "segments": [
            {
                "id": "segment-1",
                "start_ms": 0,
                "end_ms": 1_000,
                "language_bcp47": "en-US",
                "speaker_cluster_id": "speaker-a",
                "text": "Pocket validates citations.",
                "confidence": 0.97,
            }
        ],
        "warnings": [],
    }
    transport = FakeTransport(
        [
            _json_response(
                {},
                **{
                    "x-goog-upload-url": (
                        "https://generativelanguage.googleapis.com/upload/session-1"
                    )
                },
            ),
            _json_response(
                {
                    "file": {
                        "name": "files/audio-1",
                        "uri": "https://generativelanguage.googleapis.com/v1beta/files/audio-1",
                        "mimeType": "audio/wav",
                        "state": "ACTIVE",
                    }
                }
            ),
            _interaction(
                transcript,
                model=settings.llm_cheap_model,
                request_id="gemini-speech-response",
            ),
            _json_response({}),
        ]
    )
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)

    result = adapter.transcribe(_speech_request())

    assert result.segments[0]["text"] == "Pocket validates citations."
    assert result.provider == "google.gemini"
    assert result.usage["estimated_cost_usd"] > 0
    assert result.provenance["grounding_validation"] == "passed"
    assert result.provenance["provider_file_delete_attempted"] is True
    assert transport.calls[0]["headers"]["x-goog-api-key"] == settings.gemini_api_key
    assert "x-goog-api-key" not in transport.calls[1]["headers"]
    assert transport.calls[1]["content"] == b"RIFF-dummy-audio"
    assert transport.calls[2]["json"]["store"] is False
    assert "safety_settings" not in transport.calls[2]["json"]
    assert transport.calls[-1]["method"] == "DELETE"


def test_dedicated_transcribe_is_preferred_for_timestamped_short_audio(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.gemini_speech_model = "gemini-3.5-transcribe"
    transport = FakeTransport(
        [
            _json_response(
                {},
                **{
                    "x-goog-upload-url": (
                        "https://generativelanguage.googleapis.com/upload/session-transcribe"
                    )
                },
            ),
            _json_response(
                {
                    "file": {
                        "name": "files/audio-transcribe",
                        "uri": (
                            "https://generativelanguage.googleapis.com/v1beta/"
                            "files/audio-transcribe"
                        ),
                        "mimeType": "audio/wav",
                        "state": "ACTIVE",
                    }
                }
            ),
            _json_response(
                {
                    "id": "transcribe-response",
                    "model": "gemini-3.5-transcribe",
                    "status": "completed",
                    "steps": [
                        {
                            "type": "model_output",
                            "finish_reason": "STOP",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Pocket validates citations.",
                                    "annotations": [
                                        {
                                            "type": "word_info",
                                            "text": "Pocket",
                                            "speaker": "speaker-a",
                                            "start_offset": "0s",
                                            "end_offset": "0.4s",
                                        },
                                        {
                                            "type": "word_info",
                                            "text": "validates",
                                            "speaker": "speaker-a",
                                            "start_offset": "0.4s",
                                            "end_offset": "0.7s",
                                        },
                                        {
                                            "type": "word_info",
                                            "text": "citations.",
                                            "speaker": "speaker-a",
                                            "start_offset": "0.7s",
                                            "end_offset": "1s",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                    "usage": {
                        "total_input_tokens": 25,
                        "total_output_tokens": 3,
                        "total_tokens": 28,
                    },
                }
            ),
            _json_response({}),
        ]
    )
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)

    result = adapter.transcribe(replace(_speech_request(), language="en"))

    assert result.resolved_model == "gemini-3.5-transcribe"
    assert result.segments[0]["text"] == "Pocket validates citations."
    interaction = transport.calls[2]["json"]
    assert interaction["model"] == "gemini-3.5-transcribe"
    assert interaction["generation_config"]["transcription_config"]["mode"] == {
        "type": "verbatim",
        "diarization_mode": "speaker",
        "timestamp_granularities": ["word"],
    }


def test_dedicated_transcribe_rejects_completed_empty_audio_result(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.gemini_speech_model = "gemini-3.5-transcribe"
    transport = FakeTransport(
        [
            _json_response(
                {},
                **{
                    "x-goog-upload-url": (
                        "https://generativelanguage.googleapis.com/upload/session-empty"
                    )
                },
            ),
            _json_response(
                {
                    "file": {
                        "name": "files/audio-empty",
                        "uri": (
                            "https://generativelanguage.googleapis.com/v1beta/files/audio-empty"
                        ),
                        "mimeType": "audio/wav",
                        "state": "ACTIVE",
                    }
                }
            ),
            _json_response(
                {
                    "id": "transcribe-empty-response",
                    "model": "gemini-3.5-transcribe",
                    "status": "completed",
                    "steps": [],
                    "usage": {
                        "total_input_tokens": 25,
                        "total_output_tokens": 0,
                        "total_tokens": 25,
                    },
                }
            ),
            _json_response({}),
        ]
    )
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)

    with pytest.raises(ProviderBilledFailure) as failure:
        adapter.transcribe(replace(_speech_request(), language="en"))

    assert failure.value.provenance["failure_category"] == "transcript_validation"
    assert transport.calls[-1]["method"] == "DELETE"


def test_long_timestamped_audio_falls_back_to_structured_flash_lite(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    settings.gemini_speech_model = "gemini-3.5-transcribe"
    transcript = {
        "segments": [
            {
                "id": "segment-1",
                "start_ms": 0,
                "end_ms": 1_000,
                "language_bcp47": "en-US",
                "speaker_cluster_id": "speaker-a",
                "text": "Pocket validates citations.",
                "confidence": 0.97,
            }
        ],
        "warnings": [],
    }
    transport = FakeTransport(
        [
            _json_response(
                {},
                **{
                    "x-goog-upload-url": (
                        "https://generativelanguage.googleapis.com/upload/session-long"
                    )
                },
            ),
            _json_response(
                {
                    "file": {
                        "name": "files/audio-long",
                        "uri": "https://generativelanguage.googleapis.com/v1beta/files/audio-long",
                        "mimeType": "audio/wav",
                        "state": "ACTIVE",
                    }
                }
            ),
            _interaction(
                transcript,
                model=settings.llm_cheap_model,
                request_id="flash-lite-long-audio",
            ),
            _json_response({}),
        ]
    )
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)
    request = replace(
        _speech_request(),
        language="en",
        duration_ms=31 * 60 * 1_000,
    )

    result = adapter.transcribe(request)

    assert result.resolved_model == "gemini-3.5-flash-lite"
    assert transport.calls[2]["json"]["model"] == "gemini-3.5-flash-lite"
    assert any("structured-audio fallback" in item for item in result.provenance["warnings"])


def test_long_audio_fallback_rejects_empty_transcript(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.gemini_speech_model = "gemini-3.5-transcribe"
    empty_transcript = {"segments": [], "warnings": []}
    transport = FakeTransport(
        [
            _json_response(
                {},
                **{
                    "x-goog-upload-url": (
                        "https://generativelanguage.googleapis.com/upload/session-long-empty"
                    )
                },
            ),
            _json_response(
                {
                    "file": {
                        "name": "files/audio-long-empty",
                        "uri": (
                            "https://generativelanguage.googleapis.com/v1beta/"
                            "files/audio-long-empty"
                        ),
                        "mimeType": "audio/wav",
                        "state": "ACTIVE",
                    }
                }
            ),
            _interaction(
                empty_transcript,
                model=settings.llm_cheap_model,
                request_id="flash-lite-empty-1",
            ),
            _interaction(
                empty_transcript,
                model=settings.llm_cheap_model,
                request_id="flash-lite-empty-2",
            ),
            _json_response({}),
        ]
    )
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)
    request = replace(
        _speech_request(),
        language="en",
        duration_ms=31 * 60 * 1_000,
    )

    with pytest.raises(ProviderBilledFailure) as failure:
        adapter.transcribe(request)

    assert failure.value.provenance["failure_category"] == "schema_validation"
    assert transport.calls[-1]["method"] == "DELETE"


def test_upload_redirect_host_is_validated_before_audio_or_key_is_sent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    transport = FakeTransport(
        [_json_response({}, **{"x-goog-upload-url": "https://attacker.invalid/steal"})]
    )
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)

    with pytest.raises(GeminiResponseInvalid, match="secure upload URL"):
        adapter.transcribe(_speech_request())

    assert len(transport.calls) == 1
    assert transport.calls[0]["content"] is None


def test_resumable_upload_start_is_not_blindly_replayed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    transport = FakeTransport(
        [
            TransportResponse(status_code=503, headers={}, body=b"{}"),
            _json_response(
                {},
                **{
                    "x-goog-upload-url": (
                        "https://generativelanguage.googleapis.com/upload/should-not-run"
                    )
                },
            ),
        ]
    )
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)

    with pytest.raises(GeminiProviderError, match="HTTP status 503"):
        adapter.transcribe(_speech_request())

    assert len(transport.calls) == 1


def test_intelligence_repairs_cheap_then_escalates_once_to_strong(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    transport = FakeTransport(
        [
            _interaction({}, model=settings.llm_cheap_model, request_id="cheap-1"),
            _interaction({}, model=settings.llm_cheap_model, request_id="cheap-2"),
            _interaction(
                _intelligence_payload(),
                model=settings.llm_strong_model,
                request_id="strong-1",
            ),
        ]
    )
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)
    segments = [
        {
            "id": "segment-1",
            "start_ms": 0,
            "end_ms": 1_000,
            "speaker_cluster_id": "speaker-a",
            "text": "Pocket validates citations.",
        }
    ]
    reservation = adapter.estimate_intelligence_reservation(
        recording_id="recording-1",
        transcript_version=1,
        segments=segments,
        budget_usd=2.0,
    )

    payload, provenance = adapter.extract_intelligence(
        recording_id="recording-1",
        transcript_version=1,
        segments=segments,
        request_id="intelligence-attempt-1",
        budget_usd=reservation,
    )

    assert payload["topics"][0]["label"] == "Validation"
    assert provenance["model_alias"] == "llm.strong"
    assert provenance["escalated"] is True
    assert provenance["escalation_reason"] == "schema_or_grounding_failure"
    assert [call["json"]["model"] for call in transport.calls] == [
        settings.llm_cheap_model,
        settings.llm_cheap_model,
        settings.llm_strong_model,
    ]
    assert 0 < provenance["estimated_cost_usd"] <= reservation


def test_safety_block_is_billed_but_never_repaired_or_escalated(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    blocked = _json_response(
        {
            "id": "blocked-1",
            "model": settings.llm_cheap_model,
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "finish_reason": "SAFETY",
                    "safety_ratings": [
                        {
                            "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                            "probability": "HIGH",
                            "blocked": True,
                        }
                    ],
                    "content": [],
                }
            ],
            "usage": {
                "total_input_tokens": 40,
                "total_output_tokens": 0,
                "total_thought_tokens": 0,
                "total_tokens": 40,
            },
        }
    )
    transport = FakeTransport([blocked])
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)
    request = AskRequest(
        question="What does the evidence say?",
        evidence=[{"citation": _intelligence_payload()["title"]["evidence"][0]}],
        request_id="ask-attempt-1",
        budget_usd=0.10,
    )

    with pytest.raises(ProviderBilledFailure) as caught:
        adapter.answer(request)

    assert caught.value.estimated_cost_usd > 0
    assert caught.value.provenance["failure_category"] == "safety_policy_block"
    assert len(transport.calls) == 1


def test_incomplete_provider_response_is_ledgerable_and_not_retried(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    transport = FakeTransport(
        [
            _json_response(
                {
                    "id": "incomplete-1",
                    "model": settings.llm_cheap_model,
                    "status": "incomplete",
                    "steps": [],
                    "usage": {
                        "total_input_tokens": 50,
                        "total_output_tokens": 12,
                        "total_thought_tokens": 4,
                        "total_tokens": 66,
                    },
                }
            )
        ]
    )
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)
    request = AskRequest(
        question="What does the evidence say?",
        evidence=[{"citation": _intelligence_payload()["title"]["evidence"][0]}],
        request_id="ask-incomplete",
        budget_usd=0.10,
    )

    with pytest.raises(ProviderBilledFailure) as caught:
        adapter.answer(request)

    assert caught.value.provenance["failure_category"] == "provider_status_incomplete"
    assert caught.value.estimated_cost_usd > 0
    assert len(transport.calls) == 1


def test_reservations_are_nonzero_conservative_and_not_cap_clamped(tmp_path: Path) -> None:
    adapter = GeminiAdapter(_settings(tmp_path), transport=FakeTransport([]))
    speech = adapter.estimate_transcription_reservation(_speech_request(budget_usd=0.000001))
    ask = adapter.estimate_ask_reservation(
        AskRequest(
            question="Summarize the evidence",
            evidence=[{"citation": _intelligence_payload()["title"]["evidence"][0]}],
            request_id="ask-attempt-2",
            budget_usd=0.000001,
        )
    )

    assert speech > 0.000001
    assert ask > 0.000001


def test_token_admission_uses_utf8_byte_upper_bound() -> None:
    assert _estimate_tokens(";;;;;;;;") == 8
    assert _estimate_tokens("é") == 2
    assert _estimate_tokens("🧪") == 4


def test_structured_input_bound_includes_system_and_full_schema() -> None:
    prompt = "short prompt"
    intelligence_schema = _provider_schema(_RecordingIntelligence)
    ask_schema = _provider_schema(_AskAnswer)

    intelligence = _structured_input_token_upper_bound(prompt, intelligence_schema)
    ask = _structured_input_token_upper_bound(prompt, ask_schema)

    assert intelligence >= _estimate_tokens(prompt)
    assert intelligence >= _estimate_tokens(_SYSTEM_INSTRUCTION)
    assert intelligence >= _estimate_tokens(
        json.dumps(intelligence_schema, ensure_ascii=False, separators=(",", ":"))
    )
    assert intelligence > ask


@dataclass
class PipelineTransport:
    settings: Settings
    calls: list[dict[str, Any]] = field(default_factory=list)
    interaction_count: int = 0

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
        content: bytes | None = None,
        timeout_seconds: float,
    ) -> TransportResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "json": json_body,
                "content_size": len(content) if content is not None else None,
                "timeout_seconds": timeout_seconds,
            }
        )
        if method == "DELETE":
            return _json_response({})
        if "/upload/" in url and url.endswith("/files"):
            return _json_response(
                {},
                **{
                    "x-goog-upload-url": (
                        "https://generativelanguage.googleapis.com/upload/pipeline-session"
                    )
                },
            )
        if url.endswith("/upload/pipeline-session"):
            return _json_response(
                {
                    "file": {
                        "name": "files/pipeline-audio",
                        "uri": (
                            "https://generativelanguage.googleapis.com/v1beta/"
                            "files/pipeline-audio"
                        ),
                        "mimeType": "audio/wav",
                        "state": "ACTIVE",
                    }
                }
            )
        if url.endswith("/interactions") and isinstance(json_body, dict):
            self.interaction_count += 1
            prompt = str((json_body.get("input") or [{}])[0].get("text") or "")
            model = str(json_body["model"])
            if any(
                isinstance(item, dict) and item.get("type") == "audio"
                for item in json_body.get("input") or []
            ):
                payload = {
                    "segments": [
                        {
                            "id": "segment-1",
                            "start_ms": 0,
                            "end_ms": 1_000,
                            "language_bcp47": "en-US",
                            "speaker_cluster_id": "speaker-a",
                            "text": "Pocket validates citations.",
                            "confidence": 0.97,
                        }
                    ],
                    "warnings": [],
                }
            elif "TRANSCRIPT_JSON:\n" in prompt:
                source = json.loads(prompt.split("TRANSCRIPT_JSON:\n", 1)[1])
                payload = _intelligence_payload(
                    recording_id=source["recording_id"],
                    transcript_version=source["transcript_version"],
                )
            elif "EVIDENCE_JSON:\n" in prompt:
                evidence = json.loads(prompt.split("EVIDENCE_JSON:\n", 1)[1])
                payload = {
                    "answer": "Citations keep each answer tied to its source moment.",
                    "citations": [evidence[0]["citation"]],
                    "abstained": False,
                }
            else:  # pragma: no cover - diagnostic guard
                raise AssertionError(f"unexpected interaction prompt: {prompt[:80]}")
            return _interaction(
                payload,
                model=model,
                request_id=f"pipeline-interaction-{self.interaction_count}",
            )
        raise AssertionError(f"unexpected transport call: {method} {url}")


def test_local_api_full_gemini_flow_with_fake_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    settings.inline_worker = True
    transport = PipelineTransport(settings)
    adapter = GeminiAdapter(settings, transport=transport, sleep=lambda _: None)
    monkeypatch.setattr(
        main_module,
        "create_provider_adapters",
        lambda _settings: (adapter, adapter),
    )

    with TestClient(main_module.create_app(settings), base_url="http://testserver") as client:
        csrf, _ = login(client)
        audio = load_fixture_wav(settings.fixture_root)
        digest = hashlib.sha256(audio).hexdigest()
        unapproved = client.post(
            "/v1/upload-sessions",
            json={
                "filename": "unapproved.wav",
                "content_type": "audio/wav",
                "size_bytes": len(audio),
                "sha256": digest,
                "language": "en",
                "vocabulary_hints": [],
                "mode": "standard",
                "provider_data_approved": False,
            },
            headers=mutation_headers(csrf, "gemini-unapproved-create"),
        )
        assert unapproved.status_code == 422
        assert unapproved.json()["detail"]["code"] == "provider_data_approval_required"
        assert transport.calls == []
        auto_language = client.post(
            "/v1/upload-sessions",
            json={
                "filename": "auto-language.wav",
                "content_type": "audio/wav",
                "size_bytes": len(audio),
                "sha256": digest,
                "language": "auto",
                "vocabulary_hints": [],
                "mode": "standard",
                "provider_data_approved": True,
            },
            headers=mutation_headers(csrf, "gemini-auto-language-create"),
        )
        assert auto_language.status_code == 422
        assert auto_language.json()["detail"]["code"] == "provider_language_required"
        assert transport.calls == []
        created = client.post(
            "/v1/upload-sessions",
            json={
                "filename": "approved-gemini-demo.wav",
                "content_type": "audio/wav",
                "size_bytes": len(audio),
                "sha256": digest,
                "language": "en",
                "vocabulary_hints": ["Pocket"],
                "mode": "standard",
                "provider_data_approved": True,
            },
            headers=mutation_headers(csrf, "gemini-pipeline-create"),
        )
        assert created.status_code == 201, created.text
        upload = created.json()
        stored = client.put(
            upload["upload_url"],
            content=audio,
            headers=upload["upload_headers"],
        )
        assert stored.status_code == 204, stored.text
        completed = client.post(
            f"/v1/recordings/{upload['recording_id']}/complete",
            json={"upload_session_id": upload["id"], "sha256": digest},
            headers=mutation_headers(csrf, "gemini-pipeline-complete"),
        )
        assert completed.status_code == 202, completed.text

        recording = client.get(f"/v1/recordings/{upload['recording_id']}").json()
        assert recording["state"] == "ready"
        assert all(recording["readiness"].values())
        transcript = client.get(
            f"/v1/recordings/{upload['recording_id']}/transcript"
        ).json()
        assert transcript["segments"][0]["text"] == "Pocket validates citations."
        assert transcript["provenance"]["provider"] == "google.gemini"
        intelligence = client.get(
            f"/v1/recordings/{upload['recording_id']}/intelligence"
        ).json()
        assert intelligence["topics"][0]["label"] == "Validation"
        assert intelligence["actions"][0]["task"] == (
            "Review the citation validation report."
        )

        search = client.post(
            "/v1/search",
            json={
                "query": "validates citations",
                "filters": {"mode": "exact", "recording_id": upload["recording_id"]},
            },
        )
        assert search.status_code == 200
        assert search.json()["items"][0]["citation"]["segment_id"] == "segment-1"
        tasks = client.get("/v1/tasks").json()
        assert any(
            item["task"] == "Review the citation validation report."
            for item in tasks["items"]
        )

        ask_session = client.post(
            "/v1/ask-sessions",
            json={
                "scope": {
                    "type": "recording",
                    "recording_id": upload["recording_id"],
                }
            },
            headers=mutation_headers(csrf, "gemini-pipeline-ask-session"),
        )
        assert ask_session.status_code == 201, ask_session.text
        answer = client.post(
            f"/v1/ask-sessions/{ask_session.json()['id']}/messages",
            json={"content": "Explain why citations matter", "deep": False},
            headers=mutation_headers(csrf, "gemini-pipeline-ask"),
        )
        assert answer.status_code == 201, answer.text
        message = answer.json()["message"]
        assert message["status"] == "complete"
        assert message["citations"][0]["segment_id"] == "segment-1"
        assert message["provenance"]["provider"] == "google.gemini"

        customer_ask_session = client.post(
            "/v1/ask-sessions",
            json={
                "scope": {
                    "type": "recording",
                    "recording_id": upload["recording_id"],
                }
            },
            headers=mutation_headers(csrf, "gemini-customer-ask-session"),
        )
        supported_customer_answer = client.post(
            f"/v1/ask-sessions/{customer_ask_session.json()['id']}/messages",
            json={"content": "What did the customer say about citations?", "deep": False},
            headers=mutation_headers(csrf, "gemini-customer-ask"),
        )
        assert supported_customer_answer.status_code == 201
        assert supported_customer_answer.json()["message"]["status"] == "complete"

        costs = client.get("/v1/costs").json()["events"]
        remote_costs = [item for item in costs if item["provider"] == "google.gemini"]
        assert {item["stage"] for item in remote_costs} >= {"speech", "intelligence", "ask"}
        assert all(item["estimated_incurred_cost_usd"] > 0 for item in remote_costs)
        assert all(item["reconciled_cost_usd"] is None for item in remote_costs)
        assert transport.interaction_count == 4

        # Persisted approval gates every derived provider call as well as the
        # initial audio upload. This covers legacy or administratively revoked
        # rows without transmitting transcript text.
        with client.app.state.database.session_factory() as db:
            recording_row = db.get(Recording, upload["recording_id"])
            assert recording_row is not None
            recording_row.provider_data_approved = False
            db.commit()

        blocked_regeneration = client.post(
            f"/v1/recordings/{upload['recording_id']}/regenerate",
            json={"mode": "standard", "summary_style": "standard"},
            headers=mutation_headers(csrf, "gemini-unapproved-regeneration"),
        )
        assert blocked_regeneration.status_code == 422
        assert blocked_regeneration.json()["detail"]["code"] == (
            "provider_data_approval_required"
        )

        blocked_ask_session = client.post(
            "/v1/ask-sessions",
            json={
                "scope": {
                    "type": "recording",
                    "recording_id": upload["recording_id"],
                }
            },
            headers=mutation_headers(csrf, "gemini-unapproved-ask-session"),
        )
        blocked_answer = client.post(
            f"/v1/ask-sessions/{blocked_ask_session.json()['id']}/messages",
            json={"content": "Explain why citations matter", "deep": False},
            headers=mutation_headers(csrf, "gemini-unapproved-ask"),
        )
        assert blocked_answer.status_code == 422
        assert blocked_answer.json()["detail"]["code"] == "provider_data_approval_required"
        assert transport.interaction_count == 4
