from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

FIXTURE_ID = "pocket-demo-fixture"
FIXTURE_DURATION_MS = 18_000
FIXTURE_SHA256 = "a9ca1574f43258d19643b3c3f0ff35031f0587f30afa7acce62c6ff37e15840c"


def load_fixture_wav(fixture_root: Path) -> bytes:
    """Load and verify the repository's canonical functional mock fixture."""

    path = fixture_root / "media" / "pocket-demo-fixture.wav"
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != FIXTURE_SHA256:
        raise RuntimeError(
            f"Demo fixture hash mismatch: expected {FIXTURE_SHA256}, received {actual}"
        )
    return data


def load_fixture_manifest(fixture_root: Path) -> dict[str, Any]:
    path = fixture_root / "manifest.json"
    if not path.exists():
        return {
            "fixtures": [
                {
                    "id": FIXTURE_ID,
                    "media": "media/pocket-demo-fixture.wav",
                    "sha256": FIXTURE_SHA256,
                    "duration_ms": FIXTURE_DURATION_MS,
                }
            ]
        }
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixture_sidecar(fixture_root: Path) -> dict[str, Any]:
    manifest = load_fixture_manifest(fixture_root)
    matches = [item for item in manifest.get("fixtures", []) if item.get("id") == FIXTURE_ID]
    if len(matches) != 1:
        raise RuntimeError(f"Fixture manifest must contain exactly one {FIXTURE_ID!r} entry")
    item = matches[0]
    if item.get("sha256") != FIXTURE_SHA256 or item.get("duration_ms") != FIXTURE_DURATION_MS:
        raise RuntimeError("Fixture manifest hash or duration differs from backend contract")
    sidecar_path = fixture_root / item["sidecar"]
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if sidecar.get("fixture_id") != FIXTURE_ID:
        raise RuntimeError("Fixture sidecar ID differs from manifest")
    return sidecar
