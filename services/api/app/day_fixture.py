from __future__ import annotations

import hashlib
import io
import json
import wave
from pathlib import Path
from typing import Any


def load_day_fixture_manifest(fixture_root: Path) -> dict[str, Any]:
    path = fixture_root / "day-demo" / "manifest.json"
    if not path.is_file():
        return {"fixtures": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("fixtures"), list):
        raise RuntimeError("Day-demo fixture manifest is invalid")
    return payload


def find_day_fixture(fixture_root: Path, sha256: str) -> dict[str, Any] | None:
    manifest = load_day_fixture_manifest(fixture_root)
    matches = [item for item in manifest["fixtures"] if item.get("sha256") == sha256]
    if not matches:
        return None
    if len(matches) != 1:
        raise RuntimeError("Day-demo fixture hashes must be unique")
    fixture = matches[0]
    media_path = fixture_root / "day-demo" / str(fixture["filename"])
    data = media_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256 or len(data) != fixture.get("bytes"):
        raise RuntimeError(f"Day-demo fixture {fixture.get('id')} failed integrity validation")
    return json.loads(json.dumps(fixture))


def choose_batch_boundaries(
    duration_ms: int, batch_count: int, segments: list[dict[str, Any]]
) -> list[int]:
    """Prefer semantic segment ends while keeping every requested batch non-empty."""

    candidates = sorted(
        {
            int(item["end_ms"])
            for item in segments
            if 0 < int(item["end_ms"]) < duration_ms
        }
    )
    if len(candidates) < batch_count - 1:
        return [duration_ms * index // batch_count for index in range(batch_count + 1)]

    boundaries = [0]
    remaining = list(candidates)
    for index in range(1, batch_count):
        target = duration_ms * index / batch_count
        batches_after = batch_count - index
        valid = [
            value
            for candidate_index, value in enumerate(remaining)
            if value > boundaries[-1] and len(remaining) - candidate_index - 1 >= batches_after - 1
        ]
        if not valid:
            return [duration_ms * value // batch_count for value in range(batch_count + 1)]
        chosen = min(valid, key=lambda value: (abs(value - target), value))
        boundaries.append(chosen)
        remaining = [value for value in remaining if value > chosen]
    boundaries.append(duration_ms)
    return boundaries


def split_wav(source: bytes, boundaries_ms: list[int]) -> list[bytes]:
    """Split PCM WAV bytes at deterministic timeline boundaries."""

    with wave.open(io.BytesIO(source), "rb") as audio:
        params = audio.getparams()
        if audio.getcomptype() != "NONE":
            raise ValueError("Day-demo splitting currently requires uncompressed WAV audio")
        frames = audio.readframes(audio.getnframes())
        frame_width = audio.getnchannels() * audio.getsampwidth()
        sample_rate = audio.getframerate()

    results: list[bytes] = []
    for start_ms, end_ms in zip(
        boundaries_ms[:-1], boundaries_ms[1:], strict=True
    ):
        start_frame = sample_rate * start_ms // 1_000
        end_frame = sample_rate * end_ms // 1_000
        part = frames[start_frame * frame_width : end_frame * frame_width]
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setparams(params)
            writer.writeframes(part)
        results.append(output.getvalue())
    return results
