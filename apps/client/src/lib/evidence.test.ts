import { describe, expect, it } from 'vitest';

import { isValidEvidenceRange, recordingEvidenceHref, remainingEvidencePlaybackMs } from './evidence';

describe('evidence playback ranges', () => {
  it('requires a finite positive-length range', () => {
    expect(isValidEvidenceRange({ start_ms: 1_000, end_ms: 2_000 })).toBe(true);
    expect(isValidEvidenceRange({ start_ms: 2_000, end_ms: 2_000 })).toBe(false);
    expect(isValidEvidenceRange({ start_ms: -1, end_ms: 2_000 })).toBe(false);
  });

  it('preserves both citation boundaries in recording links', () => {
    expect(recordingEvidenceHref({
      recording_id: 'recording/1',
      transcript_version: 1,
      segment_id: 'segment-1',
      start_ms: 1_234.4,
      end_ms: 5_678.6,
    })).toBe('/recordings/recording%2F1?start=1234&end=5679');
  });

  it('stops range playback at the cited end boundary', () => {
    expect(remainingEvidencePlaybackMs(2.25, 5)).toBe(2_750);
    expect(remainingEvidencePlaybackMs(5, 5)).toBe(0);
    expect(remainingEvidencePlaybackMs(5.25, 5)).toBe(0);
  });
});
