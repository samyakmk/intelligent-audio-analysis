import { describe, expect, it } from 'vitest';

import type { DaySession } from '@/types/api';

import { currentMemory, dayStageLabel, stageProgress, visibleBatch } from './presentation';

function session(overrides: Partial<DaySession> = {}): DaySession {
  return {
    id: 'day',
    recording_id: 'recording',
    title: 'Day',
    status: 'processing',
    batch_count: 5,
    processed_batch_count: 1,
    active_batch_index: 1,
    current_stage: 'indexing',
    watermark_ms: 20_000,
    duration_ms: 100_000,
    revision: 7,
    memory: { summary: '', decisions: [], actions: [], facts: [], open_questions: [] },
    changes: [],
    ask_history: [],
    suggested_questions: [],
    batches: [
      { id: 'one', index: 0, number: 1, start_ms: 0, end_ms: 20_000, duration_ms: 20_000, status: 'complete', stage: 'published', transcript: [], reconciliation: {}, index_state: {}, pending_changes: [], published_snapshot: {} },
      { id: 'two', index: 1, number: 2, start_ms: 20_000, end_ms: 40_000, duration_ms: 20_000, status: 'processing', stage: 'indexing', transcript: [], reconciliation: {}, index_state: {}, pending_changes: [], published_snapshot: {} },
    ],
    mock: true,
    ...overrides,
  };
}

describe('continuous-day presentation', () => {
  it('counts completed batches and the active stage', () => {
    expect(stageProgress(session())).toBeCloseTo(28);
    expect(stageProgress(session({ status: 'complete' }))).toBe(100);
  });

  it('prefers the active batch and falls back to the last published one', () => {
    expect(visibleBatch(session())?.id).toBe('two');
    expect(visibleBatch(session({ active_batch_index: null }))?.id).toBe('one');
  });

  it('hides superseded memory while preserving resolved state', () => {
    const memory = session().memory;
    memory.decisions = [
      { id: 'old', key: 'plan', kind: 'decision', text: 'Friday', status: 'superseded', effective_batch: 0, evidence: [] },
      { id: 'new', key: 'plan', kind: 'decision', text: 'Monday', status: 'current', effective_batch: 2, evidence: [] },
    ];
    expect(currentMemory(memory).map((item) => item.text)).toEqual(['Monday']);
    expect(dayStageLabel('reconciling')).toBe('Reconciling boundary');
  });
});
