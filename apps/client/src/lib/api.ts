import * as Crypto from 'expo-crypto';

import {
  acquireOperationKey,
  operationSignature,
  retireOperationKey,
} from './idempotency';
import type {
  ActionTask,
  AskReply,
  AskScope,
  AskSession,
  CostSummary,
  ExportRequest,
  ExportResult,
  Page,
  ProviderCapabilities,
  Recap,
  Recording,
  RecordingIntelligence,
  SearchFilters,
  SearchResponse,
  Session,
  SummaryStyle,
  Transcript,
  UploadOptions,
  UploadSession,
} from '@/types/api';

export const API_BASE_URL = (process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');

let csrfToken: string | undefined;
let unauthorizedHandler: (() => void) | undefined;

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly details?: unknown;

  constructor(message: string, status: number, code?: string, details?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown;
  idempotent?: boolean;
};

function messageFromPayload(payload: unknown, fallback: string): { message: string; code?: string } {
  if (!payload || typeof payload !== 'object') return { message: fallback };
  const value = payload as Record<string, unknown>;
  const detail = value.detail;
  if (typeof detail === 'string') return { message: detail, code: stringValue(value.code) };
  if (detail && typeof detail === 'object') {
    const typed = detail as Record<string, unknown>;
    return {
      message: stringValue(typed.message) ?? fallback,
      code: stringValue(typed.code) ?? stringValue(value.code),
    };
  }
  return { message: stringValue(value.message) ?? fallback, code: stringValue(value.code) };
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase();
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  if (options.body !== undefined && !(options.body instanceof FormData) && !(options.body instanceof Blob)) {
    headers.set('Content-Type', 'application/json');
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }
  const idempotencySignature = options.idempotent
    ? operationSignature(csrfToken, method, path, options.body)
    : undefined;
  const idempotencyKey = idempotencySignature
    ? acquireOperationKey(idempotencySignature, Crypto.randomUUID)
    : undefined;
  if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      method,
      credentials: 'include',
      headers,
      body:
        options.body === undefined || options.body instanceof FormData || options.body instanceof Blob
          ? (options.body as BodyInit | undefined)
          : JSON.stringify(options.body),
    });
  } catch (error) {
    // Keep the key: the server may have committed before the response was lost.
    throw new ApiError(
      `Could not reach the Pocket API at ${API_BASE_URL}. Check that it is running and reachable from this device.`,
      0,
      'network_error',
      error,
    );
  }

  const responseCsrf = response.headers.get('x-csrf-token');
  if (responseCsrf) csrfToken = responseCsrf;
  if (response.status === 204) {
    if (idempotencySignature && idempotencyKey) {
      retireOperationKey(idempotencySignature, idempotencyKey);
    }
    return undefined as T;
  }

  const contentType = response.headers.get('content-type') ?? '';
  const payload: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');

  if (!response.ok) {
    const parsed = messageFromPayload(payload, `Request failed (${response.status})`);
    if (response.status === 401) unauthorizedHandler?.();
    // A 5xx may follow a commit whose response could not be assembled. Retain
    // its key; definitive client/domain responses may safely begin a new user
    // operation later.
    if (response.status < 500 && idempotencySignature && idempotencyKey) {
      retireOperationKey(idempotencySignature, idempotencyKey);
    }
    throw new ApiError(parsed.message, response.status, parsed.code, payload);
  }
  if (idempotencySignature && idempotencyKey) {
    retireOperationKey(idempotencySignature, idempotencyKey);
  }
  return payload as T;
}

function query(values: Record<string, string | number | undefined>): string {
  const params = Object.entries(values).filter((entry): entry is [string, string | number] => entry[1] !== undefined);
  if (!params.length) return '';
  return `?${params.map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`).join('&')}`;
}

async function allRecordings(state?: string): Promise<Page<Recording>> {
  const byId = new Map<string, Recording>();
  const seenCursors = new Set<string>();
  let cursor: string | undefined;
  let pageCount = 0;
  do {
    const page = await request<Page<Recording>>(
      `/v1/recordings${query({ cursor, state, limit: 100 })}`,
    );
    for (const recording of page.items) byId.set(recording.id, recording);
    cursor = page.next_cursor ?? undefined;
    if (cursor) {
      if (seenCursors.has(cursor)) throw new ApiError('Recording pagination repeated a cursor', 0, 'pagination_loop');
      seenCursors.add(cursor);
    }
    pageCount += 1;
    if (pageCount > 100) throw new ApiError('Recording pagination exceeded its safety bound', 0, 'pagination_limit');
  } while (cursor);
  return { items: [...byId.values()], total: byId.size, next_cursor: null };
}

export function setSessionCsrf(token?: string) {
  csrfToken = token;
}

export function setUnauthorizedHandler(handler?: () => void) {
  unauthorizedHandler = handler;
}

function normalizeSession(value: Session & Record<string, unknown>): Session {
  const rawPrincipal = value.principal as (Session['principal'] & { display_name?: string }) | undefined;
  const rawWorkspace = value.workspace as (Session['workspace'] & { display_name?: string }) | undefined;
  const principal = rawPrincipal
    ? { ...rawPrincipal, name: rawPrincipal.name ?? rawPrincipal.display_name ?? 'Demo user' }
    : { id: 'demo', name: 'Demo user' };
  const workspace = rawWorkspace
    ? { ...rawWorkspace, name: rawWorkspace.name ?? rawWorkspace.display_name ?? 'Demo workspace' }
    : { id: 'demo', name: 'Demo workspace' };
  const candidates = Array.isArray(value.workspaces)
    ? value.workspaces
    : Array.isArray(value.available_workspaces)
      ? (value.available_workspaces as Session['workspaces'])
      : [workspace];
  return {
    ...value,
    principal,
    workspace,
    workspaces: candidates.map((item) => {
      const candidate = item as typeof item & { display_name?: string };
      return { ...candidate, name: candidate.name ?? candidate.display_name ?? 'Demo workspace' };
    }),
  };
}

export const api = {
  capabilities: () => request<ProviderCapabilities>('/v1/capabilities'),
  session: async () => normalizeSession(await request<Session & Record<string, unknown>>('/v1/auth/session')),
  demoLogin: (principalId: string) =>
    request<Session & Record<string, unknown>>('/v1/auth/demo-login', {
      method: 'POST',
      body: { principal_id: principalId },
    }).then(normalizeSession),
  logout: () => request<void>('/v1/auth/logout', { method: 'POST' }),
  switchWorkspace: (workspaceId: string) =>
    request<Session & Record<string, unknown>>('/v1/auth/workspace', {
      method: 'POST',
      body: { workspace_id: workspaceId },
    }).then(normalizeSession),

  recordings: (state?: string) => allRecordings(state),
  recording: (id: string) => request<Recording>(`/v1/recordings/${encodeURIComponent(id)}`),
  updateRecording: (id: string, body: Partial<Pick<Recording, 'title' | 'tags' | 'folder'>>, version?: number) =>
    request<Recording>(`/v1/recordings/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: version === undefined ? undefined : { 'If-Match': String(version) },
      body,
    }),
  createUpload: (body: UploadOptions) =>
    request<UploadSession>('/v1/upload-sessions', { method: 'POST', body, idempotent: true }),
  uploadBytes: async (session: UploadSession, data: ArrayBuffer, contentType: string) => {
    const destination = /^https?:\/\//i.test(session.upload_url)
      ? session.upload_url
      : `${API_BASE_URL}${session.upload_url.startsWith('/') ? '' : '/'}${session.upload_url}`;
    const response = await fetch(destination, {
      method: session.upload_method ?? 'PUT',
      headers: { 'Content-Type': contentType, ...(session.upload_headers ?? {}) },
      body: data,
    });
    if (!response.ok) throw new ApiError(`Upload failed (${response.status})`, response.status, 'upload_failed');
  },
  completeUpload: (recordingId: string, uploadSessionId: string, sha256: string) =>
    request<Recording>(`/v1/recordings/${encodeURIComponent(recordingId)}/complete`, {
      method: 'POST',
      body: { upload_session_id: uploadSessionId, sha256 },
      idempotent: true,
    }),
  transcript: (id: string) => request<Transcript>(`/v1/recordings/${encodeURIComponent(id)}/transcript`),
  intelligence: (id: string) =>
    request<RecordingIntelligence>(`/v1/recordings/${encodeURIComponent(id)}/intelligence`),
  mediaGrant: (id: string, disposition: 'playback' | 'download') =>
    request<{ url: string; expires_at: string }>(
      `/v1/recordings/${encodeURIComponent(id)}/media-grant${query({ disposition })}`,
    ),
  correctTranscript: (id: string, segmentId: string, text: string, version?: number) =>
    request<Transcript>(`/v1/recordings/${encodeURIComponent(id)}/corrections`, {
      method: 'POST',
      headers: version === undefined ? undefined : { 'If-Match': String(version) },
      body: { segment_id: segmentId, text },
      idempotent: true,
    }),
  updateSpeaker: (id: string, speakerId: string, displayName: string, mergeInto?: string, version?: number) =>
    request<Transcript>(`/v1/recordings/${encodeURIComponent(id)}/speakers`, {
      method: 'POST',
      headers: version === undefined ? undefined : { 'If-Match': String(version) },
      body: { speaker_id: speakerId, display_name: displayName, merge_into: mergeInto },
      idempotent: true,
    }),
  regenerate: (id: string, summaryStyle: string, mode: 'standard' | 'deep') =>
    request<Recording>(`/v1/recordings/${encodeURIComponent(id)}/regenerate`, {
      method: 'POST',
      body: { summary_style: summaryStyle, mode },
      idempotent: true,
    }),
  retry: (id: string) =>
    request<Recording>(`/v1/recordings/${encodeURIComponent(id)}/retry`, {
      method: 'POST',
      body: {},
      idempotent: true,
    }),
  cancel: (id: string) =>
    request<Recording>(`/v1/recordings/${encodeURIComponent(id)}/cancel`, { method: 'POST', body: {} }),
  deleteRecording: (id: string) =>
    request<void>(`/v1/recordings/${encodeURIComponent(id)}`, { method: 'DELETE' }),

  search: (text: string, filters: SearchFilters) =>
    request<SearchResponse>('/v1/search', { method: 'POST', body: { query: text, filters } }),
  createAskSession: (scope: AskScope) =>
    request<AskSession>('/v1/ask-sessions', { method: 'POST', body: { scope }, idempotent: true }),
  ask: (sessionId: string, content: string, deep = false) =>
    request<AskReply>(`/v1/ask-sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: 'POST',
      body: { content, deep },
      idempotent: true,
    }),

  tasks: (status?: string) => request<Page<ActionTask>>(`/v1/tasks${query({ status })}`),
  updateTask: (id: string, status: ActionTask['status'], version?: number) =>
    request<ActionTask>(`/v1/tasks/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: version === undefined ? undefined : { 'If-Match': String(version) },
      body: { status },
    }),
  createRecap: (kind: 'daily' | 'project', project?: string) =>
    request<Recap>('/v1/recaps', { method: 'POST', body: { kind, project }, idempotent: true }),
  summaryStyles: () => request<Page<SummaryStyle> | SummaryStyle[]>('/v1/summary-styles'),
  costs: (recordingId?: string) => request<CostSummary>(`/v1/costs${query({ recording_id: recordingId })}`),
  createExport: (body: ExportRequest) =>
    request<ExportResult>('/v1/exports', { method: 'POST', body, idempotent: true }),
};

export function unwrapItems<T>(value: Page<T> | T[]): T[] {
  return Array.isArray(value) ? value : value.items;
}
