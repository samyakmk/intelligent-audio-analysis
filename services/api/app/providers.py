from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .demo_fixture import FIXTURE_SHA256, load_fixture_sidecar


class ProviderUnavailable(RuntimeError):
    pass


class ProviderDataPolicyDenied(ProviderUnavailable):
    """Remote processing was requested for content without persisted approval."""


class ProviderBilledFailure(ProviderUnavailable):
    """Terminal failure with trustworthy provider usage that must be ledgered."""

    def __init__(
        self,
        message: str,
        *,
        attempt_id: str,
        provider: str,
        model_alias: str,
        resolved_model: str,
        usage: dict[str, Any],
        estimated_cost_usd: float,
        provenance: dict[str, Any],
    ):
        super().__init__(message)
        self.attempt_id = attempt_id
        self.provider = provider
        self.model_alias = model_alias
        self.resolved_model = resolved_model
        self.usage = usage
        self.estimated_cost_usd = estimated_cost_usd
        self.provenance = provenance


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
    audio_bytes: bytes | None = None
    content_type: str = "application/octet-stream"
    duration_ms: int | None = None


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

    def estimate_transcription_reservation(self, request: SpeechRequest) -> float:
        return 0.0


@dataclass(frozen=True, slots=True)
class AskRequest:
    question: str
    evidence: list[dict[str, Any]]
    request_id: str
    budget_usd: float
    deep: bool = False


@dataclass(frozen=True, slots=True)
class AskResult:
    answer: str
    citations: list[dict[str, Any]]
    abstained: bool
    provenance: dict[str, Any]


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
        deep: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...

    def answer(self, request: AskRequest) -> AskResult:
        raise ProviderUnavailable("This LLM adapter does not implement cited Ask.")

    def estimate_intelligence_reservation(
        self,
        *,
        recording_id: str,
        transcript_version: int,
        segments: list[dict[str, Any]],
        budget_usd: float,
        deep: bool = False,
    ) -> float:
        return 0.0

    def estimate_ask_reservation(self, request: AskRequest) -> float:
        return 0.0


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
        quality_path = fixture_root / "quality" / "ask-questions.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        self.ask_labels = {
            str(item["question"]).casefold(): item for item in quality.get("questions", [])
        }

    def extract_intelligence(
        self,
        *,
        recording_id: str,
        transcript_version: int,
        segments: list[dict[str, Any]],
        request_id: str,
        budget_usd: float,
        deep: bool = False,
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

    def answer(self, request: AskRequest) -> AskResult:
        """Apply checked-in fixture abstention labels without polluting domain logic."""

        label = self.ask_labels.get(request.question.casefold())
        if label is None or not label.get("should_abstain"):
            raise ProviderUnavailable("No scripted fixture Ask response matches this question.")
        return AskResult(
            answer="I don't have enough accessible evidence in this scope to answer that question.",
            citations=[],
            abstained=True,
            provenance={
                "mock": True,
                "provider": "mock.fixture",
                "model_alias": "llm.fixture",
                "resolved_model": "approved-ask-labels-v1",
                "provider_request_id": request.request_id,
                "strategy": "approved_fixture_abstention_label",
                "llm_called": False,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "estimated_cost_usd": 0.0,
            },
        )


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


def create_provider_adapters(settings: Any) -> tuple[SpeechAdapter, LLMAdapter]:
    """Build runtime adapters without ever loading dotenv files.

    The loose settings annotation avoids coupling the provider contracts to the
    configuration module. Gemini is imported lazily so fixture-only startup has
    no paid-provider side effects.
    """

    if settings.provider_mode in {"fixture", "mock"}:
        return (
            MockFixtureSpeechAdapter(settings.fixture_root),
            MockFixtureLLMAdapter(settings.fixture_root),
        )
    if settings.provider_mode == "gemini":
        from .gemini_provider import GeminiAdapter

        adapter = GeminiAdapter.from_settings(settings)
        return adapter, adapter
    raise ProviderUnavailable(f"Unsupported provider mode: {settings.provider_mode}")


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
