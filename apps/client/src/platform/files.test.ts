import { describe, expect, it } from 'vitest';

import { recordingFilename } from './recordingFile';

describe('recordingFilename', () => {
  it('uses a stable web-safe name and WebM extension in browsers', () => {
    expect(recordingFilename(Date.UTC(2026, 8, 9, 12, 34, 56), 'audio/webm', 'web'))
      .toBe('demo-recording-2026-09-09T12-34-56-000Z.webm');
  });

  it('uses the native high-quality preset extension on mobile', () => {
    expect(recordingFilename(0, 'audio/mp4', 'ios')).toBe('demo-recording-1970-01-01T00-00-00-000Z.m4a');
  });
});
