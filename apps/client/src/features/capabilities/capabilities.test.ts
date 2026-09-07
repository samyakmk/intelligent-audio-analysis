import { describe, expect, it } from 'vitest';

import {
  canUseDeepAsk,
  canUseDeepIntelligence,
  canUploadInConfiguredLanguage,
  fixtureCapabilities,
  loadCapabilitySnapshot,
  normalizeCapabilities,
  isProviderDataApprovalSatisfied,
  isRemoteGemini,
  requiresProviderDataApproval,
  resolveUploadLanguage,
  supportsEnglish,
} from './capabilities';

const remoteResponse = {
  ...fixtureCapabilities,
  provider_mode: 'gemini',
  remote_processing: true,
  speech: { ...fixtureCapabilities.speech, model_alias: 'speech.gemini' },
  intelligence: { ...fixtureCapabilities.intelligence, strong_model_alias: 'llm.strong', deep_available: true },
  ask: { ...fixtureCapabilities.ask, strong_model_alias: 'llm.strong', deep_available: true },
};

describe('provider capabilities', () => {
  it('enables Deep only for a configured Gemini remote route', () => {
    const capabilities = normalizeCapabilities(remoteResponse);
    expect(canUseDeepIntelligence(capabilities)).toBe(true);
    expect(canUseDeepAsk(capabilities)).toBe(true);
  });

  it('fails closed when a fixture response claims Deep availability', () => {
    const capabilities = normalizeCapabilities({
      ...remoteResponse,
      provider_mode: 'fixture',
    });
    expect(capabilities.remote_processing).toBe(false);
    expect(capabilities.intelligence.deep_available).toBe(false);
    expect(capabilities.ask.deep_available).toBe(false);
  });

  it('fails closed when required feature flags disable the operation', () => {
    const capabilities = normalizeCapabilities({
      ...remoteResponse,
      features: { ...fixtureCapabilities.features, intelligence: false, ask: false },
    });
    expect(canUseDeepIntelligence(capabilities)).toBe(false);
    expect(canUseDeepAsk(capabilities)).toBe(false);
  });

  it('does not infer languages or feature support from an incomplete remote response', () => {
    const capabilities = normalizeCapabilities({
      provider_mode: 'gemini',
      remote_processing: true,
      data_policy: 'synthetic-approved-only',
      intelligence: { strong_model_alias: 'llm.strong', deep_available: true },
      ask: { strong_model_alias: 'llm.strong', deep_available: true },
    });
    expect(capabilities.allowed_languages).toEqual([]);
    expect(capabilities.features.intelligence).toBe(false);
    expect(capabilities.features.ask).toBe(false);
    expect(canUseDeepIntelligence(capabilities)).toBe(false);
    expect(canUseDeepAsk(capabilities)).toBe(false);
  });

  it('fails closed when Deep is claimed without a strong model alias', () => {
    const capabilities = normalizeCapabilities({
      ...remoteResponse,
      intelligence: { ...remoteResponse.intelligence, strong_model_alias: null },
      ask: { ...remoteResponse.ask, strong_model_alias: '' },
    });
    expect(canUseDeepIntelligence(capabilities)).toBe(false);
    expect(canUseDeepAsk(capabilities)).toBe(false);
  });

  it('requires explicit data approval for Gemini uploads but not fixture uploads', () => {
    const remote = normalizeCapabilities(remoteResponse);
    expect(requiresProviderDataApproval(remote)).toBe(true);
    expect(isProviderDataApprovalSatisfied(remote, false)).toBe(false);
    expect(isProviderDataApprovalSatisfied(remote, true)).toBe(true);
    expect(requiresProviderDataApproval(fixtureCapabilities)).toBe(false);
    expect(isProviderDataApprovalSatisfied(fixtureCapabilities, false)).toBe(true);
  });

  it('pins remote Gemini uploads to English while preserving fixture auto-detect', () => {
    const remote = normalizeCapabilities(remoteResponse);
    expect(isRemoteGemini(remote)).toBe(true);
    expect(supportsEnglish(remote)).toBe(true);
    expect(resolveUploadLanguage(remote, 'auto')).toBe('en');
    expect(resolveUploadLanguage(remote, 'en')).toBe('en');
    expect(canUploadInConfiguredLanguage(remote)).toBe(true);

    expect(isRemoteGemini(fixtureCapabilities)).toBe(false);
    expect(resolveUploadLanguage(fixtureCapabilities, 'auto')).toBe('auto');
  });

  it('blocks remote upload if the server does not advertise English transcription', () => {
    const remote = normalizeCapabilities({ ...remoteResponse, allowed_languages: ['fr'] });
    expect(resolveUploadLanguage(remote, 'auto')).toBe('en');
    expect(canUploadInConfiguredLanguage(remote)).toBe(false);
  });

  it('uses fixture capabilities only when the endpoint is absent', async () => {
    const snapshot = await loadCapabilitySnapshot(async () => {
      throw Object.assign(new Error('Not found'), { status: 404 });
    });
    expect(snapshot).toEqual({ capabilities: fixtureCapabilities, source: 'fixture-fallback' });

    const outage = Object.assign(new Error('Unavailable'), { status: 503 });
    await expect(loadCapabilitySnapshot(async () => { throw outage; })).rejects.toBe(outage);
  });
});
