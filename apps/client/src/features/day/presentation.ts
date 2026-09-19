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

export function revisionVerb(operation: string): string {
  if (operation === 'supersede') return 'REVISED';
  if (operation === 'resolve') return 'RESOLVED';
  return 'ADDED';
}
