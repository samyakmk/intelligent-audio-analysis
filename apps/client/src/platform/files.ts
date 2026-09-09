import * as Crypto from 'expo-crypto';
import * as DocumentPicker from 'expo-document-picker';

import { recordingFilename } from './recordingFile';

export { recordingFilename } from './recordingFile';

export const audioMimeTypes = [
  'audio/mpeg',
  'audio/mp4',
  'audio/aac',
  'audio/wav',
  'audio/x-wav',
  'audio/flac',
  'audio/ogg',
  'audio/webm',
];

export interface PickedAudio {
  uri: string;
  name: string;
  size?: number;
  mimeType: string;
  file?: File;
}

export function fromWebFile(file: File): PickedAudio {
  return {
    uri: URL.createObjectURL(file),
    name: file.name,
    size: file.size,
    mimeType: file.type || 'application/octet-stream',
    file,
  };
}

function runtimePlatform(): 'web' | 'native' {
  return typeof window !== 'undefined' && typeof document !== 'undefined' ? 'web' : 'native';
}

export async function fromRecordedUri(uri: string, timestamp = Date.now()): Promise<PickedAudio> {
  const response = await fetch(uri);
  if (!response.ok) throw new Error('The new recording could not be read. Please record it again.');
  const blob = await response.blob();
  const web = runtimePlatform() === 'web';
  const mimeType = blob.type || (web ? 'audio/webm' : 'audio/mp4');
  const name = recordingFilename(timestamp, mimeType, web ? 'web' : 'native');
  const webFile = web && typeof File !== 'undefined'
    ? new File([blob], name, { type: mimeType })
    : undefined;
  return {
    uri,
    name,
    size: blob.size,
    mimeType,
    file: webFile,
  };
}

export async function pickAudio(): Promise<PickedAudio | undefined> {
  const result = await DocumentPicker.getDocumentAsync({
    type: ['audio/*', ...audioMimeTypes],
    multiple: false,
    copyToCacheDirectory: true,
    base64: false,
  });
  if (result.canceled) return undefined;
  const asset = result.assets[0];
  if (!asset) return undefined;
  return {
    uri: asset.uri,
    name: asset.name,
    size: asset.size,
    mimeType: asset.mimeType ?? 'application/octet-stream',
    file: asset.file,
  };
}

export async function readAudio(file: PickedAudio): Promise<ArrayBuffer> {
  if (file.file) return file.file.arrayBuffer();
  const response = await fetch(file.uri);
  if (!response.ok) throw new Error('The selected file could not be read. Please choose it again.');
  return response.arrayBuffer();
}

export async function sha256(data: ArrayBuffer): Promise<string> {
  const digest = await Crypto.digest(Crypto.CryptoDigestAlgorithm.SHA256, data);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}
