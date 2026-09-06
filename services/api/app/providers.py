from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .demo_fixture import FIXTURE_SHA256, load_fixture_sidecar


class ProviderUnavailable(RuntimeError):
    pass


class SpeechUnconfigured(ProviderUnavailable):
    pass


@dataclass(frozen=True, slots=True)
class SpeechRequest:
    recording_id: str
    audio_sha256: str
    audio_reference: str
    original_time_offset_ms: int
    language: str
    vocabulary_hints: tuple[str, ...]
    require_diarization: bool
    require_timestamps: bool
    budget_usd: float
    request_id: str


@dataclass(frozen=True, slots=True)
class SpeechResult:
    timeline: list[dict[str, Any]]
    segments: list[dict[str, Any]]
    provider: str
    model_alias: str
    resolved_model: str
    provider_request_id: str
    usage: dict[str, Any]
    provenance: dict[str, Any]


class SpeechAdapter(ABC):
    @abstractmethod
    def transcribe(self, request: SpeechRequest) -> SpeechResult: ...


class LLMAdapter(ABC):
    @abstractmethod
    def extract_intelligence(
        self,
        *,
        recording_id: str,
        transcript_version: int,
        segments: list[dict[str, Any]],
        request_id: str,
        budget_usd: float,
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...


class EmbeddingAdapter(ABC):
    @abstractmethod
    def embed(self, texts: list[str], *, request_id: str) -> dict[str, Any]: ...


class MockFixtureSpeechAdapter(SpeechAdapter):
    """A fixture lookup, deliberately not a pretend general-purpose ASR."""

    def __init__(self, fixture_root: Path):
        self.sidecar = load_fixture_sidecar(fixture_root)

    def transcribe(self, request: SpeechRequest) -> SpeechResult:
        if request.audio_sha256 != FIXTURE_SHA256:
            raise SpeechUnconfigured(
                "No speech provider is configured for this audio hash. The immutable "
                "original is retained, but no transcript or intelligence was invented."
            )
        return SpeechResult(
            timeline=[dict(item) for item in self.sidecar["timeline"]],
            segments=[
                {
                    **item,
                    "speaker_cluster_id": item.get("speaker_cluster_id") or item.get("speaker_id"),
                }
                for item in self.sidecar["segments"]
            ],
            provider="mock.fixture",
            model_alias="speech.fixture",
            resolved_model="builtin-scripted-pocket-demo-v1",
            provider_request_id=request.request_id,
            usage={"submitted_audio_seconds": 18, "billed_audio_seconds": 0},
            provenance={
                "mock": True,
                "source": "approved_checked_in_scripted_fixture",
                "recognition_performed": False,
                "warning": "Transcript loaded from a deterministic fixture sidecar.",
            },
        )


class MockFixtureLLMAdapter(LLMAdapter):
    def __init__(self, fixture_root: Path):
        self.sidecar = load_fixture_sidecar(fixture_root)

    def extract_intelligence(
        self,
        *,
        recording_id: str,
        transcript_version: int,
        segments: list[dict[str, Any]],
        request_id: str,
        budget_usd: float,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        expected = [item["text"] for item in self.sidecar["segments"]]
        if [item["text"] for item in segments] != expected:
            raise ProviderUnavailable(
                "Mock intelligence is available only for the approved fixture transcript."
            )
        payload = _copy_nested(self.sidecar["intelligence"])
        for citation_value in _walk_citations(payload):
            citation_value["recording_id"] = recording_id
            citation_value["transcript_version"] = transcript_version
        provenance = {
            "mock": True,
            "source": "approved_checked_in_scripted_fixture",
            "provider": "mock.fixture",
            "model_alias": "llm.fixture",
            "resolved_model": "deterministic-intelligence-v1",
            "provider_request_id": request_id,
            "pipeline_version": "mock-intelligence-dag.v1",
            "prompt_version": "fixture-sidecar.v1",
            "schema_version": "RecordingIntelligence.v1",
            "policy_version": "demo-policy.v1",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
        return payload, provenance


class MockHashEmbeddingAdapter(EmbeddingAdapter):
    """Stable local fingerprints for provenance; lexical search remains authoritative."""

    def embed(self, texts: list[str], *, request_id: str) -> dict[str, Any]:
        vectors = []
        for value in texts:
            digest = hashlib.sha256(value.casefold().encode("utf-8")).digest()
            vectors.append([round((byte - 127.5) / 127.5, 6) for byte in digest[:8]])
        return {
            "vectors": vectors,
            "dimensions": 8,
            "provider": "mock.local",
            "model_alias": "embed.mock-hash",
            "resolved_model": "sha256-8d-v1",
            "provider_request_id": request_id,
            "usage": {"input_tokens": 0},
            "provenance": {
                "mock": True,
                "semantic_similarity_supported": False,
                "warning": "Vectors are stable fingerprints, not semantic embeddings.",
            },
        }


def _copy_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _copy_nested(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_nested(item) for item in value]
    return value


def _walk_citations(value: Any):
    if isinstance(value, dict):
        if {"segment_id", "start_ms", "end_ms"}.issubset(value):
            yield value
        for nested in value.values():
            yield from _walk_citations(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_citations(nested)
