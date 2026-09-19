#!/usr/bin/env python3
"""Verify long-form day-demo media, scripted memory operations, and client copies."""

from __future__ import annotations

import json

from generate_day_demo_fixtures import CLIENT_DIR, FIXTURE_DIR, generated_payload


def fail(message: str) -> None:
    raise SystemExit(f"day-demo fixture verification failed: {message}")


def main() -> int:
    expected_manifest, expected_media = generated_payload()
    manifest_path = FIXTURE_DIR / "manifest.json"
    if not manifest_path.is_file():
        fail("manifest is missing")
    actual_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if actual_manifest != expected_manifest:
        fail("manifest differs from the deterministic generator")
    for fixture in actual_manifest["fixtures"]:
        filename = fixture["filename"]
        expected = expected_media[filename]
        fixture_path = FIXTURE_DIR / filename
        client_path = CLIENT_DIR / filename
        if fixture_path.read_bytes() != expected:
            fail(f"{filename} differs from the deterministic generator")
        if client_path.read_bytes() != expected:
            fail(f"client copy of {filename} differs from the fixture source")
        segments = fixture["segments"]
        if len(segments) < 16 or fixture["duration_ms"] < 90_000:
            fail(f"{fixture['id']} is too short to exercise meaningful batches")
        segment_ids = {item["id"] for item in segments}
        if len(segment_ids) != len(segments):
            fail(f"{fixture['id']} repeats a segment id")
        operations = fixture["operations"]
        if not any(item["operation"] == "supersede" for item in operations):
            fail(f"{fixture['id']} does not exercise future-batch supersession")
        if not any(item["operation"] == "resolve" for item in operations):
            fail(f"{fixture['id']} does not exercise later resolution")
        if any(item["trigger_segment_id"] not in segment_ids for item in operations):
            fail(f"{fixture['id']} operation references an unknown segment")
        for answer in fixture["ask_answers"]:
            for version in answer["versions"]:
                if version["through_segment_id"] not in segment_ids:
                    fail(f"{fixture['id']} Ask version has an unknown watermark segment")
                if not set(version["citation_segment_ids"]).issubset(segment_ids):
                    fail(f"{fixture['id']} Ask answer cites an unknown segment")
    print(
        "day-demo fixture verification passed: "
        f"{len(actual_manifest['fixtures'])} long-form scenarios with revisions and Ask labels"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
