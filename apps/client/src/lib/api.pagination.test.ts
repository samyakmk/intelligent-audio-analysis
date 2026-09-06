import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api, setSessionCsrf } from './api';
import { resetOperationKeysForTests } from './idempotency';
import type { Recording } from '../types/api';

vi.mock('expo-crypto', () => ({
  randomUUID: vi.fn(() => 'pagination-operation-id'),
}));

function recording(id: string): Recording {
  return {
    id,
    title: id,
    filename: `${id}.wav`,
    content_type: 'audio/wav',
    language: 'en',
    mode: 'standard',
    tags: [],
    state: 'ready',
    readiness: {
      original_ready: true,
      transcript_ready: true,
      intelligence_ready: true,
      indexed_ready: true,
    },
    size_bytes: 44,
    version: 1,
    created_at: '2026-09-06T00:00:00Z',
    expires_at: '2026-10-06T00:00:00Z',
  };
}

describe('recording pagination', () => {
  beforeEach(() => {
    resetOperationKeysForTests();
    setSessionCsrf('test-session');
    vi.restoreAllMocks();
  });

  it('hydrates every page used by library-scoped feature pickers', async () => {
    const first = Array.from({ length: 100 }, (_, index) => recording(`r-${index}`));
    const second = [recording('r-100')];
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: first, total: 101, next_cursor: '100' }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: second, total: 101, next_cursor: null }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const result = await api.recordings();

    expect(result.items).toHaveLength(101);
    expect(result.total).toBe(101);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('limit=100');
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain('cursor=100');
  });
});
