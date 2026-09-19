import { describe, expect, it } from 'vitest';

import type { DaySession } from '@/types/api';

import {
  asksThroughWatermark,
  changesThroughBatch,
  currentMemory,
  dayStageLabel,
  memorySummary,
  snapshotMemory,
  snapshotWatermark,
  stageProgress,
  visibleBatch,
} from './presentation';

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
    expect(memorySummary(memory)).toBe('Monday');
  });

  it('projects memory, changes, and Ask history through a selected batch', () => {
    const value = session();
    value.batches[0]!.published_snapshot = {
      summary: 'First snapshot',
      decisions: [],
      actions: [],
      facts: [],
      open_questions: [],
    };
    value.changes = [
      { id: 'one', operation: 'add', kind: 'fact', key: 'one', after: 'One', batch_index: 0 },
      { id: 'two', operation: 'add', kind: 'fact', key: 'two', after: 'Two', batch_index: 1 },
    ];
    value.ask_history = [
      { id: 'early', question: 'Q', answer: 'A', citations: [], abstained: false, provisional: true, watermark_ms: 20_000, processed_batch_count: 1, strategy: 'fixture', created_at: '2026-01-01' },
      { id: 'late', question: 'Q', answer: 'B', citations: [], abstained: false, provisional: true, watermark_ms: 40_000, processed_batch_count: 2, strategy: 'fixture', created_at: '2026-01-01' },
    ];
    expect(snapshotMemory(value, 0).summary).toBe('First snapshot');
    expect(snapshotWatermark(value, 0)).toBe(20_000);
    expect(changesThroughBatch(value, 0).map((change) => change.id)).toEqual(['one']);
    expect(asksThroughWatermark(value, 20_000).map((message) => message.id)).toEqual(['early']);
  });
});
