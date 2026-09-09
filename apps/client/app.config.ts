import type { ExpoConfig } from 'expo/config';

const easProjectId = process.env.EAS_PROJECT_ID;

const config: ExpoConfig = {
  name: process.env.EXPO_APP_NAME ?? 'Intelligent Audio Analysis',
  slug: process.env.EXPO_APP_SLUG ?? 'intelligent-audio-analysis',
  version: '0.1.0',
  orientation: 'default',
  scheme: process.env.EXPO_APP_SCHEME ?? 'intelligentaudioanalysis',
  userInterfaceStyle: 'light',
  ios: {
    supportsTablet: true,
    bundleIdentifier: process.env.IOS_BUNDLE_IDENTIFIER ?? 'com.intelligentaudioanalysis.app',
  },
  android: {
    package: process.env.ANDROID_PACKAGE_NAME ?? 'com.intelligentaudioanalysis.app',
    adaptiveIcon: {
      backgroundColor: '#123b37',
    },
  },
  web: {
    bundler: 'metro',
    output: 'static',
  },
  plugins: [
    'expo-router',
    [
      'expo-audio',
      {
        microphonePermission: 'Allow Intelligent Audio Analysis to record audio for this demo.',
        recordAudioAndroid: true,
        enableBackgroundPlayback: false,
      },
    ],
    'expo-document-picker',
  ],
  experiments: {
    typedRoutes: false,
  },
  extra: {
    apiUrl: process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000',
    demoMode: process.env.EXPO_PUBLIC_DEMO_MODE ?? 'true',
    ...(easProjectId && !easProjectId.startsWith('replace-me')
      ? { eas: { projectId: easProjectId } }
      : {}),
  },
};

export default config;
