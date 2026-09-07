import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api, setSessionCsrf } from './api';
import { resetOperationKeysForTests } from './idempotency';
import type { ProviderCapabilities, UploadOptions } from '../types/api';

vi.mock('expo-crypto', () => ({
  randomUUID: vi.fn(() => '00000000-0000-4000-8000-000000000099'),
}));

const capabilities: ProviderCapabilities = {
  provider_mode: 'gemini',
  remote_processing: true,
  data_policy: 'synthetic-approved-only',
  allowed_languages: ['en'],
  max_audio_duration_seconds: 7_200,
  speech: {
    model_alias: 'speech.standard',
    max_duration_seconds: 7_200,
    diarization: true,
    timestamps: true,
    vocabulary_hints: true,
  },
  intelligence: {
    cheap_model_alias: 'llm.cheap',
    strong_model_alias: 'llm.strong',
    deep_available: true,
  },
  ask: {
    cheap_model_alias: 'llm.cheap',
    strong_model_alias: 'llm.strong',
    deep_available: true,
  },
  features: {
    transcript: true,
    intelligence: true,
    mind_map: true,
    search: true,
    ask: true,
    tasks: true,
    exports: true,
  },
};

describe('capability API boundary', () => {
  beforeEach(() => {
    resetOperationKeysForTests();
    setSessionCsrf('test-session');
    vi.restoreAllMocks();
  });

  it('loads the public provider capability contract', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify(capabilities), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.capabilities()).resolves.toEqual(capabilities);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain('/v1/capabilities');
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).method).toBe('GET');
  });

  it('sends the explicit provider-data approval with upload admission', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ id: 'upload-1', recording_id: 'recording-1', upload_url: '/upload' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const options: UploadOptions = {
      filename: 'approved.wav',
      content_type: 'audio/wav',
      size_bytes: 44,
      sha256: 'a'.repeat(64),
      language: 'en',
      vocabulary_hints: [],
      mode: 'deep',
      provider_data_approved: true,
    };

    await api.createUpload(options);

    const body = JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit).body));
    expect(body).toMatchObject({ mode: 'deep', provider_data_approved: true });
  });
});
