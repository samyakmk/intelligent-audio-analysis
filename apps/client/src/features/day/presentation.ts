import type { DayBatch, DayMemory, DayMemoryItem, DaySession } from '@/types/api';

export const dayStages = ['transcribing', 'reconciling', 'indexing', 'extracting', 'publishing'] as const;

const stageNames: Record<string, string> = {
  waiting: 'Waiting for arrival',
  transcribing: 'Transcribing batch',
  reconciling: 'Reconciling boundary',
  indexing: 'Building retrieval index',
  extracting: 'Extracting memory changes',
  publishing: 'Publishing revision',
  published: 'Published',
  complete: 'Day complete',
};

export function dayStageLabel(stage?: string): string {
  return stageNames[stage ?? 'waiting'] ?? stage?.replaceAll('_', ' ') ?? 'Waiting';
}

export function stageProgress(session: DaySession): number {
  if (session.status === 'complete') return 100;
  const complete = session.processed_batch_count * dayStages.length;
  const stage = Math.max(0, dayStages.indexOf(session.current_stage as (typeof dayStages)[number]));
  return ((complete + stage) / (session.batch_count * dayStages.length)) * 100;
}

export function visibleBatch(session: DaySession): DayBatch | undefined {
  const active = session.batches.find((batch) => batch.index === session.active_batch_index);
  if (active) return active;
  return [...session.batches].reverse().find((batch) => batch.status === 'complete') ?? session.batches[0];
}

export function currentMemory(memory: DayMemory): DayMemoryItem[] {
  return [memory.decisions, memory.actions, memory.facts, memory.open_questions]
    .flat()
    .filter((item) => item.status !== 'superseded');
}

export function memorySummary(memory: DayMemory): string {
  if (memory.summary && memory.summary !== 'No batches have been published yet.') {
    return memory.summary;
  }
  const items = currentMemory(memory).slice(0, 2);
  if (!items.length) return memory.summary || 'No memory has been published yet.';
  return items.map((item) => item.text).join(' ');
}

export function snapshotMemory(session: DaySession, batchIndex: number | null): DayMemory {
  if (batchIndex === null) return session.memory;
  const batch = session.batches.find((candidate) => candidate.index === batchIndex);
  if (batch?.status !== 'complete' || !batch.published_snapshot.summary) return session.memory;
  return batch.published_snapshot as DayMemory;
}

export function snapshotWatermark(session: DaySession, batchIndex: number | null): number {
  if (batchIndex === null) return session.watermark_ms;
  return session.batches.find((batch) => batch.index === batchIndex)?.end_ms ?? session.watermark_ms;
}

export function changesThroughBatch(session: DaySession, batchIndex: number | null) {
  return batchIndex === null
    ? session.changes
    : session.changes.filter((change) => change.batch_index <= batchIndex);
}

export function asksThroughWatermark(session: DaySession, watermarkMs: number) {
  return session.ask_history.filter((message) => message.watermark_ms <= watermarkMs);
}

export function revisionVerb(operation: string): string {
  if (operation === 'supersede') return 'REVISED';
  if (operation === 'resolve') return 'RESOLVED';
  return 'ADDED';
}
