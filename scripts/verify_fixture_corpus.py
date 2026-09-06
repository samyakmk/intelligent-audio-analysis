#!/usr/bin/env python3
"""Verify deterministic media, canonical sidecars, and quality-gate honesty."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import wave
from pathlib import Path
from typing import Any, NoReturn

from generate_fixture_wav import build_wav


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def fail(message: str) -> NoReturn:
    raise SystemExit(f"fixture verification failed: {message}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read {path.relative_to(ROOT)}: {error}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def fixture_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        fail(f"unsafe fixture-relative path: {relative!r}")
    resolved = (FIXTURES / candidate).resolve()
    if FIXTURES.resolve() not in resolved.parents:
        fail(f"path escapes fixture directory: {relative!r}")
    return resolved


def verify_citation(citation: Any, segments: dict[str, dict[str, Any]]) -> None:
    if not isinstance(citation, dict):
        fail("an evidence entry is not an object")
    segment_id = citation.get("segment_id")
    if segment_id not in segments:
        fail(f"citation references unknown segment {segment_id!r}")
    segment = segments[segment_id]
    start_ms = citation.get("start_ms")
    end_ms = citation.get("end_ms")
    if not isinstance(start_ms, int) or not isinstance(end_ms, int):
        fail(f"citation for {segment_id} has non-integer bounds")
    if start_ms < segment["start_ms"] or end_ms > segment["end_ms"] or end_ms <= start_ms:
        fail(f"citation for {segment_id} falls outside its source segment")
    quote = citation.get("quote")
    if quote is not None and quote not in segment["text"]:
        fail(f"citation quote does not occur in {segment_id}")


def walk_evidence(value: Any, segments: dict[str, dict[str, Any]]) -> int:
    count = 0
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "evidence":
                if not isinstance(child, list):
                    fail("an evidence field is not an array")
                for citation in child:
                    verify_citation(citation, segments)
                    count += 1
            else:
                count += walk_evidence(child, segments)
    elif isinstance(value, list):
        for child in value:
            count += walk_evidence(child, segments)
    return count


def verify_sidecar(path: Path, fixture: dict[str, Any]) -> set[str]:
    sidecar = load_json(path)
    if sidecar.get("fixture_id") != fixture["id"]:
        fail(f"sidecar identity does not match {fixture['id']}")

    duration_ms = fixture["duration_ms"]
    timeline = sidecar.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        fail(f"{fixture['id']} timeline must be a non-empty array")
    cursor = 0
    allowed_states = {"speech", "silence", "unreadable"}
    for interval in timeline:
        if not isinstance(interval, dict):
            fail(f"{fixture['id']} has a non-object timeline interval")
        if interval.get("start_ms") != cursor:
            fail(f"{fixture['id']} timeline has a gap or overlap at {cursor} ms")
        end_ms = interval.get("end_ms")
        if not isinstance(end_ms, int) or end_ms <= cursor:
            fail(f"{fixture['id']} timeline has invalid bounds")
        if interval.get("state") not in allowed_states:
            fail(f"{fixture['id']} timeline has an invalid state")
        cursor = end_ms
    if cursor != duration_ms:
        fail(f"{fixture['id']} timeline ends at {cursor}, expected {duration_ms}")

    raw_segments = sidecar.get("segments")
    if not isinstance(raw_segments, list):
        fail(f"{fixture['id']} segments must be an array")
    segments: dict[str, dict[str, Any]] = {}
    for segment in raw_segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("id"), str):
            fail(f"{fixture['id']} has a segment without a string id")
        segment_id = segment["id"]
        if segment_id in segments:
            fail(f"{fixture['id']} repeats segment id {segment_id}")
        start_ms = segment.get("start_ms")
        end_ms = segment.get("end_ms")
        if (
            not isinstance(start_ms, int)
            or not isinstance(end_ms, int)
            or start_ms < 0
            or end_ms <= start_ms
            or end_ms > duration_ms
        ):
            fail(f"{fixture['id']} segment {segment_id} has invalid bounds")
        if not isinstance(segment.get("text"), str) or not segment["text"].strip():
            fail(f"{fixture['id']} segment {segment_id} has empty text")
        segments[segment_id] = segment

    intelligence = sidecar.get("intelligence")
    if not isinstance(intelligence, dict):
        fail(f"{fixture['id']} intelligence must be an object")
    for collection_name in ("facts", "decisions", "actions"):
        collection = intelligence.get(collection_name)
        if not isinstance(collection, list):
            fail(f"{fixture['id']} intelligence.{collection_name} must be an array")
        for index, item in enumerate(collection):
            if not isinstance(item, dict):
                fail(f"{fixture['id']} {collection_name}[{index}] must be an object")
            if not item.get("evidence") and not item.get("unresolved"):
                fail(
                    f"{fixture['id']} {collection_name}[{index}] has neither evidence nor unresolved state"
                )
    if walk_evidence(intelligence, segments) == 0:
        fail(f"{fixture['id']} intelligence contains no citations")
    return set(segments)


def verify_media(fixture: dict[str, Any], expected_bytes: bytes) -> None:
    media = fixture_path(fixture["media"])
    try:
        payload = media.read_bytes()
    except OSError as error:
        fail(f"cannot read {media.relative_to(ROOT)}: {error}")

    if payload != expected_bytes:
        fail(f"{fixture['id']} does not match scripts/generate_fixture_wav.py")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != fixture.get("sha256"):
        fail(f"{fixture['id']} SHA-256 is {digest}, manifest says {fixture.get('sha256')}")
    if len(payload) != fixture.get("bytes"):
        fail(f"{fixture['id']} byte count does not match the manifest")

    try:
        with wave.open(io.BytesIO(payload), "rb") as audio:
            sample_rate = audio.getframerate()
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            frames = audio.getnframes()
            compression = audio.getcomptype()
    except (EOFError, wave.Error) as error:
        fail(f"{fixture['id']} is not a valid WAV: {error}")

    duration_ms = frames * 1_000 // sample_rate
    expected = (
        fixture.get("duration_ms"),
        fixture.get("sample_rate_hz"),
        fixture.get("channels"),
    )
    actual = (duration_ms, sample_rate, channels)
    if actual != expected:
        fail(f"{fixture['id']} WAV metadata {actual} does not match manifest {expected}")
    if sample_width != 2 or compression != "NONE":
        fail(f"{fixture['id']} must be uncompressed 16-bit PCM")


def verify_backend_identity(fixture: dict[str, Any], expected_bytes: bytes) -> None:
    module_path = ROOT / "services" / "api" / "app" / "demo_fixture.py"
    if not module_path.is_file():
        fail("backend fixture identity module is missing")
    spec = importlib.util.spec_from_file_location("pocket_demo_fixture_contract", module_path)
    if spec is None or spec.loader is None:
        fail("cannot load backend fixture identity module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if module.FIXTURE_ID != fixture["id"]:
        fail(
            f"backend fixture id {module.FIXTURE_ID!r} does not match manifest {fixture['id']!r}"
        )
    if module.FIXTURE_DURATION_MS != fixture["duration_ms"]:
        fail("backend fixture duration does not match the manifest")
    if module.FIXTURE_SHA256 != fixture["sha256"]:
        fail("backend fixture SHA-256 does not match the manifest")
    if module.load_fixture_wav(FIXTURES) != expected_bytes:
        fail("backend fixture loader does not return the checked-in canonical bytes")


def verify_questions(path: Path, fixture_id: str, segment_ids: set[str]) -> int:
    evaluation = load_json(path)
    if evaluation.get("fixture_id") != fixture_id:
        fail("Ask evaluation fixture_id does not match the manifest fixture")
    questions = evaluation.get("questions")
    if not isinstance(questions, list) or len(questions) < 20:
        fail("Ask evaluation must contain at least 20 labeled questions")

    ids: set[str] = set()
    kinds: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            fail("Ask evaluation contains a non-object question")
        question_id = question.get("id")
        if not isinstance(question_id, str) or question_id in ids:
            fail(f"Ask evaluation has a missing or duplicate id: {question_id!r}")
        ids.add(question_id)
        kind = question.get("kind")
        if kind not in {"exact", "semantic"}:
            fail(f"{question_id} has unsupported kind {kind!r}")
        kinds.add(kind)
        cited = question.get("expected_segment_ids")
        if not isinstance(cited, list) or not set(cited).issubset(segment_ids):
            fail(f"{question_id} references an unknown expected segment")
        answers = question.get("expected_answer_contains")
        if not isinstance(answers, list):
            fail(f"{question_id} expected_answer_contains must be an array")
        if question.get("should_abstain") and (cited or answers):
            fail(f"{question_id} abstains but also declares an answer or citation")
        if not question.get("should_abstain") and (not cited or not answers):
            fail(f"{question_id} needs both expected answer text and citations")
    if kinds != {"exact", "semantic"}:
        fail("Ask evaluation must exercise both exact and semantic retrieval")
    return len(questions)


def verify_gate(path: Path, question_count: int) -> None:
    gate = load_json(path)
    required = gate.get("required_corpus", {})
    current = gate.get("current_corpus", {})
    if required.get("minimum_recordings", 0) < 24:
        fail("quality gate requires fewer than 24 recordings")
    cohorts = required.get("cohorts")
    if not isinstance(cohorts, list) or len(cohorts) != 6:
        fail("quality gate must define all six required cohorts")
    if required.get("minimum_per_overlapping_cohort", 0) < 4:
        fail("quality gate requires fewer than four examples per cohort")
    if required.get("minimum_exact_or_semantic_ask_questions", 0) < 20:
        fail("quality gate requires fewer than 20 Ask questions")
    if current.get("functional_labeled_ask_questions") != question_count:
        fail("quality gate Ask question count is stale")

    eligible = current.get("quality_eligible_recordings", 0)
    passed = gate.get("quality_gate_passed")
    if passed and eligible < required["minimum_recordings"]:
        fail("quality gate claims success without the required corpus")
    if gate.get("claim_permitted") and not passed:
        fail("quality claims are permitted while the quality gate is not passed")


def main() -> int:
    manifest = load_json(FIXTURES / "manifest.json")
    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list) or len(fixtures) != 1:
        fail("this seed corpus must declare exactly one deterministic fixture")
    fixture = fixtures[0]
    if not isinstance(fixture, dict) or fixture.get("id") != "pocket-demo-fixture":
        fail("manifest is missing pocket-demo-fixture")
    if fixture.get("quality_gate_eligible") is not False:
        fail("the tone fixture must remain excluded from the quality gate")

    expected_bytes = build_wav()
    verify_media(fixture, expected_bytes)
    verify_backend_identity(fixture, expected_bytes)
    segment_ids = verify_sidecar(fixture_path(fixture["sidecar"]), fixture)
    question_count = verify_questions(
        FIXTURES / "quality" / "ask-questions.json",
        fixture["id"],
        segment_ids,
    )
    verify_gate(FIXTURES / "quality" / "quality-gate.json", question_count)

    print(
        "fixture verification passed: "
        f"1 functional fixture, {len(segment_ids)} segments, "
        f"{question_count} labeled Ask questions; quality claims remain blocked"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
