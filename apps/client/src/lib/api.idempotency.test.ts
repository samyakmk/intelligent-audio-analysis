import * as Crypto from 'expo-crypto';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { request, setSessionCsrf, setUnauthorizedHandler } from './api';
import { resetOperationKeysForTests } from './idempotency';

vi.mock('expo-crypto', () => ({
  randomUUID: vi.fn(),
}));

const firstUuid = '00000000-0000-4000-8000-000000000001';
const secondUuid = '00000000-0000-4000-8000-000000000002';

function requestKey(call: readonly unknown[] | undefined): string | null {
  if (!call) throw new Error('Expected fetch to have been called');
  const init = call[1] as RequestInit;
  return new Headers(init.headers).get('Idempotency-Key');
}

describe('API idempotency retries', () => {
  beforeEach(() => {
    resetOperationKeysForTests();
    setSessionCsrf('test-session-scope');
    setUnauthorizedHandler(undefined);
    vi.resetAllMocks();
    vi.mocked(Crypto.randomUUID)
      .mockReturnValueOnce(firstUuid)
      .mockReturnValueOnce(secondUuid);
  });

  it('reuses a key after a lost response and retires it after success', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError('connection reset after commit'))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: 'recap-1' }), {
          status: 201,
          headers: { 'content-type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: 'recap-2' }), {
          status: 201,
          headers: { 'content-type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const options = { method: 'POST', body: { kind: 'daily' }, idempotent: true } as const;

    await expect(request('/v1/recaps', options)).rejects.toMatchObject({
      code: 'network_error',
    });
    await expect(request('/v1/recaps', options)).resolves.toEqual({ id: 'recap-1' });
    await expect(request('/v1/recaps', options)).resolves.toEqual({ id: 'recap-2' });

    expect(requestKey(fetchMock.mock.calls[0])).toBe(firstUuid);
    expect(requestKey(fetchMock.mock.calls[1])).toBe(firstUuid);
    expect(requestKey(fetchMock.mock.calls[2])).toBe(secondUuid);
  });

  it('retains a key across an ambiguous server failure', async () => {
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: 'response assembly failed' }), {
          status: 500,
          headers: { 'content-type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: 'ask-message-1' }), {
          status: 201,
          headers: { 'content-type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const options = {
      method: 'POST',
      body: { content: 'What changed?' },
      idempotent: true,
    } as const;

    await expect(request('/v1/ask-sessions/session/messages', options)).rejects.toMatchObject({
      status: 500,
    });
    await expect(request('/v1/ask-sessions/session/messages', options)).resolves.toEqual({
      id: 'ask-message-1',
    });

    expect(requestKey(fetchMock.mock.calls[0])).toBe(firstUuid);
    expect(requestKey(fetchMock.mock.calls[1])).toBe(firstUuid);
  });

  it('notifies the session owner before surfacing an unauthorized response', async () => {
    const unauthorized = vi.fn();
    setUnauthorizedHandler(unauthorized);
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Session expired' }), {
        status: 401,
        headers: { 'content-type': 'application/json' },
      }),
    ));

    await expect(request('/v1/recordings')).rejects.toMatchObject({ status: 401 });

    expect(unauthorized).toHaveBeenCalledOnce();
  });
});
