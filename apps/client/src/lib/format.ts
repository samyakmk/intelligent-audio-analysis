import type { Citation, RecordingState } from '@/types/api';

export function formatBytes(value?: number): string {
  if (value === undefined || Number.isNaN(value)) return '—';
  if (value === 0) return '0 B';
  const units = ['B', 'KiB', 'MiB', 'GiB'];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatDuration(milliseconds?: number): string {
  if (milliseconds === undefined || !Number.isFinite(milliseconds)) return '—';
  const total = Math.max(0, Math.round(milliseconds / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`;
}

export function formatMoney(value?: number, precision = 3): string {
  if (value === undefined || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: value < 0.01 ? precision : 2,
    maximumFractionDigits: value < 0.01 ? precision : 2,
  }).format(value);
}

export function formatDate(value?: string, includeTime = false): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
    hour: includeTime ? 'numeric' : undefined,
    minute: includeTime ? '2-digit' : undefined,
  }).format(date);
}

export function stateLabel(state: RecordingState): string {
  const labels: Record<RecordingState, string> = {
    uploading: 'Uploading',
    verifying: 'Verifying',
    sealed: 'Queued',
    processing: 'Processing',
    ready: 'Ready',
    partial: 'Partially ready',
    failed_retryable: 'Needs retry',
    failed_final: 'Could not process',
    cancelled: 'Cancelled',
    deleting: 'Deleting',
    deleted: 'Deleted',
  };
  return labels[state];
}

export function citationLabel(citation: Citation): string {
  const source = citation.recording_title ? `${citation.recording_title} · ` : '';
  return `${source}${formatDuration(citation.start_ms)}`;
}

export function isActiveState(state: RecordingState): boolean {
  return ['uploading', 'verifying', 'sealed', 'processing', 'deleting'].includes(state);
}

export function initials(name?: string): string {
  if (!name) return 'P';
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}
