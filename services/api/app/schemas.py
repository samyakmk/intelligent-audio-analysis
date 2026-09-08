from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginRequest(StrictModel):
    principal_id: Literal["test-account"] = "test-account"


class WorkspaceSwitchRequest(StrictModel):
    workspace_id: str = Field(min_length=1, max_length=64)


class UploadSessionCreate(StrictModel):
    filename: str = Field(min_length=1, max_length=240)
    content_type: str = Field(default="application/octet-stream", max_length=128)
    size_bytes: int = Field(ge=1)
    sha256: str | None = None
    language: str = Field(default="en", min_length=2, max_length=32)
    vocabulary_hints: list[str] = Field(default_factory=list, max_length=100)
    mode: Literal["standard", "deep"] = "standard"
    provider_data_approved: bool = False

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.lower()
        if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
            raise ValueError("sha256 must contain 64 hexadecimal characters")
        return normalized

    @field_validator("vocabulary_hints")
    @classmethod
    def valid_vocabulary(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 100 for item in value):
            raise ValueError("vocabulary hints must be 1-100 characters each")
        return value


class CompleteUploadRequest(StrictModel):
    sha256: str
    upload_session_id: str | None = None

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str) -> str:
        normalized = value.lower()
        if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
            raise ValueError("sha256 must contain 64 hexadecimal characters")
        return normalized


class RecordingPatch(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    display_name: str | None = Field(default=None, min_length=1, max_length=240)
    tags: list[str] | None = Field(default=None, max_length=50)
    folder: str | None = Field(default=None, max_length=160)
    summary_style: Literal["standard", "brief", "detailed", "action_focused"] | None = None


class CorrectionCreate(StrictModel):
    segment_id: str
    text: str = Field(min_length=1, max_length=20_000)
    base_transcript_version: int | None = Field(default=None, ge=1)


class SpeakerUpdate(StrictModel):
    speaker_id: str
    display_name: str | None = Field(default=None, max_length=160)
    merge_into: str | None = None
    merge_into_speaker_id: str | None = None
    base_transcript_version: int | None = Field(default=None, ge=1)


class RegenerateRequest(StrictModel):
    mode: Literal["standard", "deep"] = "standard"
    summary_style: Literal["standard", "brief", "detailed", "action_focused"] = "standard"


class SearchFilters(StrictModel):
    mode: Literal["mixed", "exact", "semantic"] = "mixed"
    date_from: str | None = None
    date_to: str | None = None
    recording_id: str | None = None
    recording_ids: list[str] = Field(default_factory=list, max_length=100)
    speaker: str | None = None
    topic: str | None = None
    action_state: str | None = None
    action_status: str | None = None


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(default=20, ge=1, le=100)


class AskScope(StrictModel):
    type: Literal["library", "recording", "selection"] = "library"
    recording_id: str | None = None
    segment_ids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_scope(self) -> AskScope:
        if self.type in {"recording", "selection"} and not self.recording_id:
            raise ValueError(f"{self.type} scope requires recording_id")
        if self.type == "selection" and not self.segment_ids:
            raise ValueError("selection scope requires at least one segment_id")
        if self.type != "selection" and self.segment_ids:
            raise ValueError("segment_ids are valid only for selection scope")
        return self


class AskSessionCreate(StrictModel):
    scope: AskScope = Field(default_factory=AskScope)
    scope_type: Literal["library", "recording", "selection"] | None = None
    recording_ids: list[str] = Field(default_factory=list, max_length=50)


class AskMessageCreate(StrictModel):
    content: str | None = Field(default=None, min_length=1, max_length=2_000)
    question: str | None = Field(default=None, min_length=1, max_length=2_000)
    deep: bool = False


class TaskPatch(StrictModel):
    status: Literal["open", "in_progress", "done", "dismissed", "unresolved"]
    version: int | None = Field(default=None, ge=1)


class ExportRequest(StrictModel):
    format: Literal["markdown", "json", "csv", "ics"]
    resource: Literal["recording", "tasks", "recap"] = "recording"
    recording_id: str | None = None
    recap_id: str | None = None
    recording_ids: list[str] = Field(default_factory=list, max_length=100)
    include: Literal["recordings", "tasks"] | None = None


class RecapCreate(StrictModel):
    kind: Literal["daily", "project"] = "daily"
    project: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_project(self) -> RecapCreate:
        if self.kind == "project" and not self.project:
            raise ValueError("project recap requires a project/folder name")
        return self
