import type { Citation } from '@/types/api';

export interface EvidenceRange {
  start_ms: number;
  end_ms: number;
}

export function isValidEvidenceRange(range: EvidenceRange): boolean {
  return Number.isFinite(range.start_ms)
    && Number.isFinite(range.end_ms)
    && range.start_ms >= 0
    && range.end_ms > range.start_ms;
}

export function recordingEvidenceHref(citation: Citation): string {
  const start = Math.max(0, Math.round(citation.start_ms));
  const end = Math.max(start + 1, Math.round(citation.end_ms));
  return `/recordings/${encodeURIComponent(citation.recording_id)}?start=${start}&end=${end}`;
}

export function remainingEvidencePlaybackMs(currentSeconds: number, endSeconds: number): number {
  if (!Number.isFinite(currentSeconds) || !Number.isFinite(endSeconds)) return 0;
  return Math.max(0, (endSeconds - currentSeconds) * 1_000);
}
