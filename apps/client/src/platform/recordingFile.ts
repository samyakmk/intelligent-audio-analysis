export function recordingFilename(timestamp: number, mimeType: string, platform: string): string {
  const extension = platform === 'web' || mimeType.includes('webm') ? 'webm' : 'm4a';
  return `demo-recording-${new Date(timestamp).toISOString().replace(/[:.]/g, '-')}.${extension}`;
}
