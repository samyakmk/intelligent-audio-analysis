import { describe, expect, it } from 'vitest';

import { citationLabel, formatBytes, formatDuration, stateLabel } from './format';

describe('presentation formatting', () => {
  it('formats media sizes and long durations', () => {
    expect(formatBytes(524_288_000)).toBe('500.0 MiB');
    expect(formatDuration(7_261_000)).toBe('2:01:01');
  });

  it('uses human language for lifecycle states', () => {
    expect(stateLabel('failed_retryable')).toBe('Needs retry');
    expect(stateLabel('partial')).toBe('Partially ready');
  });

  it('makes citations source-specific and seekable', () => {
    expect(
      citationLabel({
        recording_id: 'r1',
        recording_title: 'Research sync',
        transcript_version: 1,
        segment_id: 's1',
        start_ms: 65_000,
        end_ms: 70_000,
      }),
    ).toBe('Research sync · 1:05');
  });
});
