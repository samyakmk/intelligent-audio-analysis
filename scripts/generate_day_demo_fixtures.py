#!/usr/bin/env python3
"""Generate long deterministic carriers and sidecars for the day-memory demo.

The WAVs are tone carriers, not speech. Their scripted transcripts deliberately contain
cross-batch references, reversals, reassignments, and resolutions. This keeps local tests
fully deterministic while making the mock boundary explicit.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "day-demo"
CLIENT_DIR = ROOT / "apps" / "client" / "assets" / "day-demo-audio"
SAMPLE_RATE = 16_000
SEGMENT_SLOT_MS = 7_000
SPEECH_MS = 6_200


def segment(index: int, speaker: str, text: str) -> dict[str, Any]:
    start = index * SEGMENT_SLOT_MS
    return {
        "id": f"segment-{index + 1}",
        "start_ms": start,
        "end_ms": start + SPEECH_MS,
        "speaker_id": speaker,
        "language_bcp47": "en-US",
        "text": text,
        "confidence": 1.0,
    }


def operation(
    op_id: str,
    trigger: int,
    action: str,
    kind: str,
    key: str,
    text: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": op_id,
        "trigger_segment_id": f"segment-{trigger}",
        "operation": action,
        "kind": kind,
        "key": key,
        "text": text,
        **extra,
    }


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "atlas-launch-day",
        "title": "Atlas launch day",
        "description": "A launch plan evolves across the day as performance and legal evidence arrives.",
        "filename": "atlas-launch-day.wav",
        "segments": [
            segment(0, "maya", "At the morning kickoff, the Atlas beta is planned for Friday afternoon."),
            segment(1, "jordan", "The team expects Nimbus to provide the analytics layer for the beta."),
            segment(2, "maya", "We are choosing Nimbus for now because its integration is already complete."),
            segment(3, "jordan", "Maya will finish the launch checklist by Thursday at three in the afternoon."),
            segment(4, "priya", "Northstar says enterprise approval requires searchable audit logs from day one."),
            segment(5, "maya", "Nimbus lists audit logs on its roadmap, so that requirement is still unverified."),
            segment(6, "jordan", "We can keep preparing, but vendor approval must remain provisional until validation."),
            segment(7, "priya", "The performance test measured Nimbus authentication latency at nine hundred milliseconds, triple our limit."),
            segment(8, "maya", "That result blocks the Friday launch, so pause the launch decision and do not approve Nimbus."),
            segment(9, "jordan", "I will compare Cedar today because it advertises audit logs and lower authentication latency."),
            segment(10, "priya", "Cedar passed the latency test at two hundred milliseconds and its audit log export is available now."),
            segment(11, "maya", "Replace Nimbus with Cedar, move the beta launch to Monday, and transfer the checklist to Priya."),
            segment(12, "jordan", "Legal has signed Cedar's data processing agreement, so the remaining vendor risk is closed."),
            segment(13, "priya", "The revised launch checklist is complete and includes rollback, monitoring, and audit-log verification."),
            segment(14, "maya", "The final decision is Cedar with a Monday beta launch; no Friday release will happen."),
            segment(15, "jordan", "End-of-day recap: Cedar is approved, Priya completed the checklist, and Monday is the committed launch date."),
        ],
        "operations": [
            operation("atlas-launch-1", 1, "add", "decision", "launch-date", "Launch the Atlas beta Friday afternoon.", status="provisional"),
            operation("atlas-vendor-1", 3, "add", "decision", "analytics-vendor", "Use Nimbus for Atlas analytics.", status="provisional"),
            operation("atlas-checklist-1", 4, "add", "action", "launch-checklist", "Finish the Atlas launch checklist.", owner="Maya", due="Thursday 3:00 PM", status="open"),
            operation("atlas-audit-fact", 5, "add", "fact", "audit-requirement", "Northstar requires searchable audit logs from day one.", status="current"),
            operation("atlas-audit-question", 6, "add", "open_question", "vendor-audit-support", "Does the selected vendor provide audit logs now?", status="open"),
            operation("atlas-latency", 8, "add", "fact", "nimbus-latency", "Nimbus authentication latency measured 900 ms against a 300 ms limit.", status="current"),
            operation("atlas-launch-hold", 9, "supersede", "decision", "launch-date", "Pause the Friday launch pending vendor validation.", status="provisional"),
            operation("atlas-vendor-hold", 9, "supersede", "decision", "analytics-vendor", "Do not approve Nimbus after the failed performance test.", status="provisional"),
            operation("atlas-vendor-final", 12, "supersede", "decision", "analytics-vendor", "Use Cedar for Atlas analytics.", status="current"),
            operation("atlas-launch-final", 12, "supersede", "decision", "launch-date", "Launch the Atlas beta on Monday.", status="current"),
            operation("atlas-checklist-2", 12, "supersede", "action", "launch-checklist", "Finish the revised Atlas launch checklist.", owner="Priya", due="Before Monday launch", status="open"),
            operation("atlas-audit-resolved", 11, "resolve", "open_question", "vendor-audit-support", "Cedar provides audit-log export now.", status="resolved"),
            operation("atlas-dpa", 13, "add", "fact", "cedar-dpa", "Legal signed Cedar's data processing agreement.", status="current"),
            operation("atlas-checklist-done", 14, "resolve", "action", "launch-checklist", "The revised launch checklist is complete.", owner="Priya", status="resolved"),
        ],
        "summaries": [
            {"through_segment_id": "segment-4", "text": "Atlas is provisionally planned for Friday using Nimbus; Maya owns the launch checklist."},
            {"through_segment_id": "segment-7", "text": "Friday preparation continues, but Nimbus approval is provisional because audit-log support is unverified."},
            {"through_segment_id": "segment-10", "text": "Nimbus failed latency validation, the Friday launch is paused, and Cedar is being evaluated."},
            {"through_segment_id": "segment-12", "text": "Cedar passed technical checks; the team selected it, moved launch to Monday, and reassigned the checklist to Priya."},
            {"through_segment_id": "segment-16", "text": "Atlas will launch Monday on Cedar. Legal approval and the revised checklist are complete."},
        ],
        "ask_answers": [
            {
                "question": "What is the current Atlas launch plan?",
                "keywords": ["current", "atlas", "launch", "plan"],
                "versions": [
                    {"through_segment_id": "segment-1", "answer": "The current plan is a provisional Friday afternoon beta launch.", "citation_segment_ids": ["segment-1"], "provisional": True},
                    {"through_segment_id": "segment-9", "answer": "The Friday launch is paused while the vendor is re-evaluated.", "citation_segment_ids": ["segment-8", "segment-9"], "provisional": True},
                    {"through_segment_id": "segment-12", "answer": "The current plan is to launch Monday using Cedar.", "citation_segment_ids": ["segment-11", "segment-12"], "provisional": True},
                    {"through_segment_id": "segment-16", "answer": "The final plan is a Monday Atlas beta launch using Cedar.", "citation_segment_ids": ["segment-15", "segment-16"], "provisional": False},
                ],
            },
            {
                "question": "Who owns the launch checklist?",
                "keywords": ["who", "owns", "launch", "checklist"],
                "versions": [
                    {"through_segment_id": "segment-4", "answer": "Maya owns the launch checklist, due Thursday at 3 PM.", "citation_segment_ids": ["segment-4"], "provisional": True},
                    {"through_segment_id": "segment-12", "answer": "Ownership moved to Priya for the revised checklist.", "citation_segment_ids": ["segment-12"], "provisional": True},
                    {"through_segment_id": "segment-14", "answer": "Priya owned the revised checklist and has completed it.", "citation_segment_ids": ["segment-12", "segment-14"], "provisional": False},
                ],
            },
        ],
        "suggested_questions": [
            "What is the current Atlas launch plan?",
            "Who owns the launch checklist?",
            "Why was Nimbus rejected?",
        ],
    },
    {
        "id": "meridian-incident-day",
        "title": "Meridian incident day",
        "description": "An incident diagnosis changes twice as later telemetry and partner evidence arrive.",
        "filename": "meridian-incident-day.wav",
        "segments": [
            segment(0, "nia", "The Meridian incident began with duplicate invoices reported by three customers."),
            segment(1, "leo", "My first hypothesis is database replica lag causing invoice writes to repeat."),
            segment(2, "nia", "Nia owns the rollback investigation and will report back before noon."),
            segment(3, "omar", "Until we know more, disable the automated invoice export to contain customer impact."),
            segment(4, "leo", "Database write identifiers are unique and replica lag stayed normal, so the first hypothesis is unsupported."),
            segment(5, "nia", "The worker logs show repeated delivery attempts with the same internal job identifier."),
            segment(6, "leo", "The working diagnosis is now an internal retry-queue defect rather than the database."),
            segment(7, "omar", "I am checking the partner webhook responses because every repeated job followed an external timeout."),
            segment(8, "omar", "The partner returned accepted, then a delayed server error, which made our client replay a completed event."),
            segment(9, "nia", "That evidence supersedes the retry-queue diagnosis; the root cause is ambiguous partner acknowledgement handling."),
            segment(10, "leo", "Mitigate by deduplicating on the partner event identifier before any invoice write."),
            segment(11, "nia", "Omar will own the mitigation because he has the partner integration context."),
            segment(12, "omar", "The event-identifier deduplication patch is deployed to the canary worker."),
            segment(13, "leo", "No duplicate invoices appeared during the forty-minute canary observation window."),
            segment(14, "nia", "The incident is resolved; automated invoice export can resume gradually."),
            segment(15, "omar", "Follow-up for Tuesday: document partner acknowledgement semantics and add a replay regression test."),
        ],
        "operations": [
            operation("incident-impact", 1, "add", "fact", "customer-impact", "Three customers reported duplicate invoices.", status="current"),
            operation("incident-cause-1", 2, "add", "decision", "root-cause", "Database replica lag is the leading hypothesis.", status="provisional"),
            operation("incident-owner-1", 3, "add", "action", "mitigation-owner", "Investigate and roll back the duplicate-invoice cause.", owner="Nia", due="Before noon", status="open"),
            operation("incident-containment", 4, "add", "decision", "containment", "Disable automated invoice export.", status="current"),
            operation("incident-db-cleared", 5, "supersede", "decision", "root-cause", "Database replica lag is not supported by telemetry.", status="provisional"),
            operation("incident-cause-2", 7, "supersede", "decision", "root-cause", "An internal retry-queue defect is the working diagnosis.", status="provisional"),
            operation("incident-partner-evidence", 9, "add", "fact", "partner-response", "The partner returned 202 followed by a delayed 500 for the same event.", status="current"),
            operation("incident-cause-final", 10, "supersede", "decision", "root-cause", "Ambiguous partner acknowledgement handling caused completed events to replay.", status="current"),
            operation("incident-mitigation", 11, "add", "decision", "mitigation", "Deduplicate invoice processing by partner event identifier.", status="current"),
            operation("incident-owner-2", 12, "supersede", "action", "mitigation-owner", "Deploy and validate event-identifier deduplication.", owner="Omar", due="Today", status="open"),
            operation("incident-deployed", 13, "add", "fact", "mitigation-deployed", "Event-identifier deduplication is deployed to canary.", status="current"),
            operation("incident-owner-done", 15, "resolve", "action", "mitigation-owner", "The mitigation is deployed and validated.", owner="Omar", status="resolved"),
            operation("incident-resolved", 15, "resolve", "decision", "containment", "The incident is resolved and invoice export may resume gradually.", status="resolved"),
            operation("incident-followup", 16, "add", "action", "follow-up", "Document partner acknowledgement semantics and add a replay regression test.", owner="Omar", due="Tuesday", status="open"),
        ],
        "summaries": [
            {"through_segment_id": "segment-4", "text": "Duplicate invoices triggered containment; database lag is the initial hypothesis and Nia owns investigation."},
            {"through_segment_id": "segment-7", "text": "Database telemetry cleared the first hypothesis; the team now suspects the internal retry queue."},
            {"through_segment_id": "segment-10", "text": "Partner response evidence superseded both earlier diagnoses; ambiguous acknowledgements caused replay."},
            {"through_segment_id": "segment-13", "text": "The team chose event-ID deduplication, transferred ownership to Omar, and deployed a canary patch."},
            {"through_segment_id": "segment-16", "text": "The incident is resolved after event-ID deduplication stopped duplicates; Omar owns Tuesday follow-up."},
        ],
        "ask_answers": [
            {
                "question": "What caused the Meridian incident?",
                "keywords": ["what", "caused", "meridian", "incident"],
                "versions": [
                    {"through_segment_id": "segment-2", "answer": "Database replica lag is the initial, unconfirmed hypothesis.", "citation_segment_ids": ["segment-2"], "provisional": True},
                    {"through_segment_id": "segment-7", "answer": "The working diagnosis is an internal retry-queue defect; database lag was ruled out.", "citation_segment_ids": ["segment-5", "segment-7"], "provisional": True},
                    {"through_segment_id": "segment-10", "answer": "Ambiguous partner acknowledgements caused completed events to be replayed.", "citation_segment_ids": ["segment-9", "segment-10"], "provisional": True},
                    {"through_segment_id": "segment-16", "answer": "The confirmed cause was ambiguous partner acknowledgement handling, which replayed completed events.", "citation_segment_ids": ["segment-9", "segment-10"], "provisional": False},
                ],
            },
            {
                "question": "Who owns the mitigation?",
                "keywords": ["who", "owns", "mitigation"],
                "versions": [
                    {"through_segment_id": "segment-3", "answer": "Nia initially owns the rollback investigation.", "citation_segment_ids": ["segment-3"], "provisional": True},
                    {"through_segment_id": "segment-12", "answer": "Mitigation ownership transferred to Omar.", "citation_segment_ids": ["segment-12"], "provisional": True},
                    {"through_segment_id": "segment-15", "answer": "Omar owned and completed the mitigation deployment and validation.", "citation_segment_ids": ["segment-12", "segment-15"], "provisional": False},
                ],
            },
        ],
        "suggested_questions": [
            "What caused the Meridian incident?",
            "Who owns the mitigation?",
            "What evidence ruled out the database?",
        ],
    },
]


def triangle(sample_index: int, frequency_hz: int, amplitude: int) -> int:
    phase = (sample_index * frequency_hz * 4) % (SAMPLE_RATE * 4)
    quadrant, offset = divmod(phase, SAMPLE_RATE)
    slope = (2 * amplitude * offset) // SAMPLE_RATE
    if quadrant == 0:
        return slope
    if quadrant == 1:
        return (2 * amplitude) - slope
    if quadrant == 2:
        return -slope
    return (-2 * amplitude) + slope


def build_wav(scenario_index: int, segment_count: int) -> bytes:
    duration_ms = segment_count * SEGMENT_SLOT_MS
    total_samples = SAMPLE_RATE * duration_ms // 1_000
    samples = [0] * total_samples
    frequencies = (220, 277, 330, 392)
    for segment_index in range(segment_count):
        start = SAMPLE_RATE * segment_index * SEGMENT_SLOT_MS // 1_000
        end = SAMPLE_RATE * (segment_index * SEGMENT_SLOT_MS + SPEECH_MS) // 1_000
        frequency = frequencies[(segment_index + scenario_index) % len(frequencies)]
        length = end - start
        fade = SAMPLE_RATE // 100
        for index in range(start, end):
            local = index - start
            edge = min(local, length - local - 1, fade)
            gain = max(edge, 0)
            primary = triangle(index, frequency, 4_800)
            harmonic = triangle(index, frequency * 2, 1_400)
            samples[index] = ((primary + harmonic) * gain) // (2 * fade)
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    header = b"".join(
        (
            b"RIFF",
            struct.pack("<I", 36 + len(pcm)),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16),
            b"data",
            struct.pack("<I", len(pcm)),
        )
    )
    return header + pcm


def generated_payload() -> tuple[dict[str, Any], dict[str, bytes]]:
    manifest: dict[str, Any] = {
        "schema_version": "intelligent-audio-analysis.day-demo.v1",
        "notice": "Audio is a deterministic tone carrier; transcripts are scripted mock data.",
        "fixtures": [],
    }
    media: dict[str, bytes] = {}
    for scenario_index, scenario in enumerate(SCENARIOS):
        audio = build_wav(scenario_index, len(scenario["segments"]))
        digest = hashlib.sha256(audio).hexdigest()
        duration_ms = len(scenario["segments"]) * SEGMENT_SLOT_MS
        item = {
            **scenario,
            "duration_ms": duration_ms,
            "bytes": len(audio),
            "sha256": digest,
            "source_type": "deterministic-tone-carrier",
            "quality_gate_eligible": False,
            "provenance": {
                "mock": True,
                "recognition_performed": False,
                "pipeline_version": "day-memory-demo.v1",
                "notice": "The transcript and evolving memory are scripted fixture data, not ASR output.",
            },
        }
        manifest["fixtures"].append(item)
        media[scenario["filename"]] = audio
    return manifest, media


def main() -> int:
    manifest, media = generated_payload()
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    CLIENT_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    for filename, payload in media.items():
        (FIXTURE_DIR / filename).write_bytes(payload)
        (CLIENT_DIR / filename).write_bytes(payload)
    print(
        "generated day-demo fixtures: "
        + ", ".join(f"{item['id']} ({item['duration_ms'] // 1000}s)" for item in manifest["fixtures"])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
