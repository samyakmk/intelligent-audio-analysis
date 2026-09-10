import { Asset } from 'expo-asset';

import type { PickedAudio } from '@/platform/files';

export interface DemoAudioSample {
  id: string;
  title: string;
  description: string;
  durationMs: number;
  size: number;
  filename: string;
  assetModule: number;
}

export const demoAudioSamples: DemoAudioSample[] = [
  {
    id: 'project-lantern-baseline',
    title: 'Project Lantern update',
    description: 'A concise project status meeting with decisions and owners.',
    durationMs: 27_572,
    size: 886_392,
    filename: 'project-lantern-baseline.wav',
    assetModule: require('../../../assets/demo-audio/project-lantern-baseline.wav'),
  },
  {
    id: 'decision-reversal',
    title: 'Decision reversal',
    description: 'A two-speaker discussion where an earlier decision changes.',
    durationMs: 37_911,
    size: 1_213_210,
    filename: 'decision-reversal.wav',
    assetModule: require('../../../assets/demo-audio/decision-reversal.wav'),
  },
  {
    id: 'unresolved-vendor',
    title: 'Unresolved vendor choice',
    description: 'A three-speaker debate that ends without a final decision.',
    durationMs: 28_466,
    size: 910_968,
    filename: 'unresolved-vendor.wav',
    assetModule: require('../../../assets/demo-audio/unresolved-vendor.wav'),
  },
];

export async function loadDemoAudioSample(sample: DemoAudioSample): Promise<PickedAudio> {
  const asset = Asset.fromModule(sample.assetModule);
  if (!asset.localUri) await asset.downloadAsync();
  const uri = asset.localUri ?? asset.uri;
  if (!uri) throw new Error('The selected demo audio could not be loaded.');
  return {
    uri,
    name: sample.filename,
    size: sample.size,
    mimeType: 'audio/wav',
  };
}
