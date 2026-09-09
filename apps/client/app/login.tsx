import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BrandMark, Button, Notice } from '@/components/ui';
import { useSession } from '@/providers/SessionProvider';
import { colors, font, radius, shadow, spacing } from '@/theme';

const identity = { id: 'test-account' };

export default function LoginScreen() {
  const { session, loading, error: sessionError, login } = useSession();
  const router = useRouter();
  const { height, width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const [error, setError] = useState<Error>();
  const narrow = width < 720;

  const submit = async () => {
    setError(undefined);
    if (session) {
      router.replace('/');
      return;
    }
    try {
      await login(identity.id);
      router.replace('/');
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('Demo login failed'));
    }
  };

  return (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={[
        styles.root,
        narrow && styles.rootNarrow,
        {
          minHeight: height,
          paddingTop: Math.max(insets.top, narrow ? 20 : 16),
          paddingBottom: Math.max(insets.bottom, narrow ? 24 : 16),
        },
      ]}
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.brand}><BrandMark /></View>
      <View style={[styles.layout, narrow && styles.layoutNarrow]}>
        <View style={styles.story}>
          <Text style={styles.kicker}>MULTI-STAGE PROMPT ARCHITECTURE</Text>
          <Text accessibilityRole="header" style={[styles.hero, narrow && styles.heroNarrow]}>Do less model work. Keep the useful output.</Text>
          <Text style={styles.heroBody}>A focused demo of an audio pipeline that uses cheap, bounded prompts by default and pays for stronger reasoning only when validation finds a real problem.</Text>
          <View style={styles.flowRow}>
            {[
              ['microphone-outline', 'Audio'],
              ['transit-connection-variant', 'Prompt stages'],
              ['chart-waterfall', 'Cost trace'],
            ].map(([icon, label], index, all) => (
              <View key={label} style={styles.flowUnit}>
                <View style={styles.flowPill}>
                  <MaterialCommunityIcons name={icon as 'microphone-outline'} size={17} color={colors.pine} />
                  <Text style={styles.flowText}>{label}</Text>
                </View>
                {index < all.length - 1 ? <MaterialCommunityIcons name="arrow-right" size={15} color={colors.borderStrong} /> : null}
              </View>
            ))}
          </View>
        </View>

        <View style={[styles.accessCard, narrow && styles.accessCardNarrow]}>
          <View style={styles.accessIcon}><MaterialCommunityIcons name="play" size={24} color={colors.white} /></View>
          <Text style={styles.accessTitle}>Open the local demo</Text>
          <Text style={styles.accessBody}>Record or upload audio, inspect the staged output, then see exactly how the prompt flow saves cost.</Text>
          {(error ?? sessionError) ? <Notice tone="error" title="Could not open the demo">{(error ?? sessionError)?.message}</Notice> : null}
          <Button size="lg" icon="arrow-right" loading={loading} onPress={submit}>Enter demo</Button>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: colors.canvas },
  root: { flexGrow: 1, paddingHorizontal: spacing.xxxl },
  rootNarrow: { paddingHorizontal: spacing.lg },
  brand: { width: '100%', maxWidth: 1120, alignSelf: 'center', paddingTop: spacing.sm },
  layout: { flex: 1, width: '100%', maxWidth: 1120, alignSelf: 'center', flexDirection: 'row', alignItems: 'center', gap: spacing.xxxl, paddingVertical: spacing.xl },
  layoutNarrow: { flexDirection: 'column', alignItems: 'stretch', gap: spacing.xxl },
  story: { flex: 1.25, gap: spacing.xl },
  kicker: { color: colors.coralDark, fontFamily: font.medium, fontSize: 9, letterSpacing: 1.4 },
  hero: { maxWidth: 650, color: colors.ink, fontFamily: font.medium, fontSize: 54, lineHeight: 59, letterSpacing: -2 },
  heroNarrow: { fontSize: 39, lineHeight: 45, letterSpacing: -1.2 },
  heroBody: { maxWidth: 620, color: colors.inkMuted, fontSize: 16, lineHeight: 25 },
  flowRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: spacing.sm },
  flowUnit: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  flowPill: { minHeight: 40, flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingHorizontal: spacing.md, borderRadius: radius.pill, backgroundColor: colors.pineSoft },
  flowText: { color: colors.pine, fontFamily: font.medium, fontSize: 11 },
  accessCard: { flex: 0.75, maxWidth: 390, padding: spacing.xxl, borderWidth: 1, borderColor: colors.border, borderRadius: radius.xl, backgroundColor: colors.surface, gap: spacing.lg, ...shadow },
  accessCardNarrow: { width: '100%', maxWidth: '100%' },
  accessIcon: { width: 52, height: 52, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.coral },
  accessTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 24, letterSpacing: -0.5 },
  accessBody: { color: colors.inkMuted, fontSize: 13, lineHeight: 20 },
});
