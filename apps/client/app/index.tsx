import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Button, LoadingState, Notice } from '@/components/ui';
import UploadScreen from '@/features/upload/UploadScreen';
import { useSession } from '@/providers/SessionProvider';
import { colors, spacing } from '@/theme';

const identity = { id: 'test-account' };

export default function HomeScreen() {
  const { session, loading, error, login } = useSession();
  const [attempted, setAttempted] = useState(false);

  useEffect(() => {
    if (loading || session || attempted) return;
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setAttempted(true);
      await login(identity.id).catch(() => undefined);
    });
    return () => { active = false; };
  }, [attempted, loading, login, session]);

  if (session) return <UploadScreen />;

  return (
    <View style={styles.root}>
      {loading || !attempted ? <LoadingState label="Opening the demo…" /> : (
        <Notice
          tone="error"
          title="Could not open the demo"
          action={<Button size="sm" variant="secondary" onPress={() => setAttempted(false)}>Try again</Button>}
        >
          {error?.message ?? 'The local API is unavailable.'}
        </Notice>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: 'center', padding: spacing.xl, backgroundColor: colors.canvas },
});
