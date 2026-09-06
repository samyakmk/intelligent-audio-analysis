import { Platform } from 'react-native';

function absoluteUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  const base = (process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/\/$/, '');
  return `${base}${url.startsWith('/') ? '' : '/'}${url}`;
}

export async function downloadUrl(url: string, filename: string): Promise<void> {
  const resolved = absoluteUrl(url);
  if (Platform.OS === 'web') {
    const response = await fetch(resolved, { credentials: 'include' });
    if (!response.ok) throw new Error(`Download failed (${response.status})`);
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(objectUrl);
    return;
  }
  const FileSystem = await import('expo-file-system/legacy');
  const Sharing = await import('expo-sharing');
  const target = `${FileSystem.cacheDirectory}${filename.replace(/[^a-zA-Z0-9._-]/g, '_')}`;
  const result = await FileSystem.downloadAsync(resolved, target, { headers: {} });
  if (!(await Sharing.isAvailableAsync())) throw new Error('Sharing is not available on this device.');
  await Sharing.shareAsync(result.uri);
}

export async function downloadText(content: string, filename: string, mimeType: string): Promise<void> {
  if (Platform.OS === 'web') {
    const objectUrl = URL.createObjectURL(new Blob([content], { type: mimeType }));
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(objectUrl);
    return;
  }
  const FileSystem = await import('expo-file-system/legacy');
  const Sharing = await import('expo-sharing');
  const target = `${FileSystem.cacheDirectory}${filename.replace(/[^a-zA-Z0-9._-]/g, '_')}`;
  await FileSystem.writeAsStringAsync(target, content);
  if (!(await Sharing.isAvailableAsync())) throw new Error('Sharing is not available on this device.');
  await Sharing.shareAsync(target, { mimeType });
}
