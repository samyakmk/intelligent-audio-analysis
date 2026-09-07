import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { SessionProvider } from '@/providers/SessionProvider';
import { CapabilitiesProvider } from '@/providers/CapabilitiesProvider';

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <CapabilitiesProvider>
        <SessionProvider>
          <StatusBar style="dark" />
          <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: '#F4F5EF' } }} />
        </SessionProvider>
      </CapabilitiesProvider>
    </SafeAreaProvider>
  );
}
