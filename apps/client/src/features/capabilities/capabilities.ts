import type { ProviderCapabilities } from '../../types/api';

export type CapabilitySource = 'server' | 'fixture-fallback';

export interface CapabilitySnapshot {
  capabilities: ProviderCapabilities;
  source: CapabilitySource;
}

export const fixtureCapabilities: ProviderCapabilities = {
  provider_mode: 'fixture',
  remote_processing: false,
  data_policy: 'synthetic-approved-only',
  allowed_languages: ['en'],
  max_audio_duration_seconds: 7_200,
  speech: {
    model_alias: 'speech.fixture',
    max_duration_seconds: 7_200,
    diarization: true,
    timestamps: true,
    vocabulary_hints: true,
  },
  intelligence: {
    cheap_model_alias: 'llm.fixture',
    strong_model_alias: null,
    deep_available: false,
  },
  ask: {
    cheap_model_alias: 'llm.fixture',
    strong_model_alias: null,
    deep_available: false,
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

/**
 * Treat capability responses as untrusted boundary data. Unknown or malformed
 * fields fail closed to the local fixture contract and can never enable Deep.
 */
export function normalizeCapabilities(value: unknown): ProviderCapabilities {
  const raw = record(value);
  const providerMode = raw.provider_mode === 'gemini' ? 'gemini' : 'fixture';
  const remoteProcessing = providerMode === 'gemini' && raw.remote_processing === true;
  const speech = record(raw.speech);
  const intelligence = record(raw.intelligence);
  const ask = record(raw.ask);
  const features = record(raw.features);
  const intelligenceStrongModel = remoteProcessing ? stringValue(intelligence.strong_model_alias) ?? null : null;
  const askStrongModel = remoteProcessing ? stringValue(ask.strong_model_alias) ?? null : null;

  return {
    provider_mode: providerMode,
    remote_processing: remoteProcessing,
    data_policy: stringValue(raw.data_policy) ?? fixtureCapabilities.data_policy,
    allowed_languages: stringList(
      raw.allowed_languages,
      remoteProcessing ? [] : fixtureCapabilities.allowed_languages,
    ),
    max_audio_duration_seconds: positiveNumber(raw.max_audio_duration_seconds, fixtureCapabilities.max_audio_duration_seconds),
    speech: {
      model_alias: stringValue(speech.model_alias) ?? fixtureCapabilities.speech.model_alias,
      max_duration_seconds: positiveNumber(speech.max_duration_seconds, fixtureCapabilities.speech.max_duration_seconds),
      diarization: speech.diarization === true,
      timestamps: speech.timestamps === true,
      vocabulary_hints: speech.vocabulary_hints === true,
    },
    intelligence: {
      cheap_model_alias: stringValue(intelligence.cheap_model_alias) ?? fixtureCapabilities.intelligence.cheap_model_alias,
      strong_model_alias: intelligenceStrongModel,
      deep_available: remoteProcessing && Boolean(intelligenceStrongModel) && intelligence.deep_available === true,
    },
    ask: {
      cheap_model_alias: stringValue(ask.cheap_model_alias) ?? fixtureCapabilities.ask.cheap_model_alias,
      strong_model_alias: askStrongModel,
      deep_available: remoteProcessing && Boolean(askStrongModel) && ask.deep_available === true,
    },
    features: {
      transcript: booleanValue(features.transcript, !remoteProcessing && fixtureCapabilities.features.transcript),
      intelligence: booleanValue(features.intelligence, !remoteProcessing && fixtureCapabilities.features.intelligence),
      mind_map: booleanValue(features.mind_map, !remoteProcessing && fixtureCapabilities.features.mind_map),
      search: booleanValue(features.search, !remoteProcessing && fixtureCapabilities.features.search),
      ask: booleanValue(features.ask, !remoteProcessing && fixtureCapabilities.features.ask),
      tasks: booleanValue(features.tasks, !remoteProcessing && fixtureCapabilities.features.tasks),
      exports: booleanValue(features.exports, !remoteProcessing && fixtureCapabilities.features.exports),
    },
  };
}

export async function loadCapabilitySnapshot(
  fetcher: () => Promise<unknown>,
): Promise<CapabilitySnapshot> {
  try {
    return { capabilities: normalizeCapabilities(await fetcher()), source: 'server' };
  } catch (error) {
    if (isHttpError(error, 404)) {
      return { capabilities: fixtureCapabilities, source: 'fixture-fallback' };
    }
    throw error;
  }
}

export function canUseDeepIntelligence(capabilities: ProviderCapabilities): boolean {
  return capabilities.provider_mode === 'gemini'
    && capabilities.remote_processing
    && capabilities.features.intelligence
    && capabilities.intelligence.deep_available;
}

export function canUseDeepAsk(capabilities: ProviderCapabilities): boolean {
  return capabilities.provider_mode === 'gemini'
    && capabilities.remote_processing
    && capabilities.features.ask
    && capabilities.ask.deep_available;
}

export function isRemoteGemini(capabilities: ProviderCapabilities): boolean {
  return capabilities.provider_mode === 'gemini' && capabilities.remote_processing;
}

export function supportsEnglish(capabilities: ProviderCapabilities): boolean {
  return capabilities.allowed_languages.some((language) => /^en(?:-|$)/i.test(language));
}

export function resolveUploadLanguage(
  capabilities: ProviderCapabilities,
  requested: 'auto' | 'en',
): 'auto' | 'en' {
  if (isRemoteGemini(capabilities)) return 'en';
  return requested === 'en' && !supportsEnglish(capabilities) ? 'auto' : requested;
}

export function canUploadInConfiguredLanguage(capabilities: ProviderCapabilities): boolean {
  return !isRemoteGemini(capabilities)
    || (capabilities.features.transcript && supportsEnglish(capabilities));
}

export function isSyntheticApprovedOnly(capabilities: ProviderCapabilities): boolean {
  return capabilities.data_policy.trim().toLocaleLowerCase('en-US') === 'synthetic-approved-only';
}

export function requiresProviderDataApproval(capabilities: ProviderCapabilities): boolean {
  return isRemoteGemini(capabilities);
}

export function isProviderDataApprovalSatisfied(
  capabilities: ProviderCapabilities,
  approved: boolean,
): boolean {
  return !requiresProviderDataApproval(capabilities) || approved;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function stringList(value: unknown, fallback: string[]): string[] {
  if (!Array.isArray(value)) return [...fallback];
  const items = [...new Set(value.map(stringValue).filter((item): item is string => Boolean(item)))];
  return items;
}

function positiveNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback;
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function isHttpError(value: unknown, status: number): boolean {
  return Boolean(value && typeof value === 'object' && 'status' in value && value.status === status);
}
