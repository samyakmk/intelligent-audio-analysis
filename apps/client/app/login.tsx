import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Redirect, useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BrandMark, Button, Notice } from '@/components/ui';
import { API_BASE_URL } from '@/lib/api';
import { useSession } from '@/providers/SessionProvider';
import { colors, font, radius, shadow, spacing } from '@/theme';

const identity = {
  id: 'test-account',
  name: 'Test Account',
  role: 'Workspace Owner',
  detail: 'Shared public demo access with upload, edit, export, deletion, and cost rights.',
  initials: 'TA',
};

export default function LoginScreen() {
  const { session, loading, error: sessionError, login } = useSession();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const [error, setError] = useState<Error>();
  const [browserWidth, setBrowserWidth] = useState<number>();

  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const updateBrowserWidth = () => setBrowserWidth(window.innerWidth);
    updateBrowserWidth();
    window.addEventListener('resize', updateBrowserWidth);
    return () => window.removeEventListener('resize', updateBrowserWidth);
  }, []);

  const responsiveWidth = Platform.OS === 'web' ? (browserWidth ?? Number.POSITIVE_INFINITY) : width;
  const isNarrow = responsiveWidth < 680;
  const isCompact = responsiveWidth < 1000;

  if (session) return <Redirect href="/" />;

  const submit = async () => {
    setError(undefined);
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
        {
          paddingTop: isNarrow ? Math.max(insets.top, 24) : insets.top,
          paddingBottom: isNarrow ? Math.max(insets.bottom, 24) : insets.bottom,
        },
      ]}
      keyboardShouldPersistTaps="handled"
      scrollEnabled={isNarrow}
      showsVerticalScrollIndicator={false}
    >
      <View style={[styles.layout, isCompact && styles.layoutCompact, isNarrow && styles.layoutNarrow]}>
        <View style={[styles.story, isCompact && styles.storyCompact]}>
          <BrandMark />
          <View style={styles.storyCopy}>
            <Text style={styles.kicker}>CANONICAL EVIDENCE · SELECTIVE AI · VISIBLE COST</Text>
            <Text accessibilityRole="header" style={[styles.hero, isCompact && styles.heroCompact, responsiveWidth < 540 && styles.heroSmall]}>
              Turn every recording into evidence you can trust.
            </Text>
            <Text style={styles.heroBody}>
              Upload audio once. Trace every summary, decision, and task back to the exact moment it came from—while seeing what each stage costs.
            </Text>
          </View>
          <View style={styles.promiseRow}>
            {[
              ['transcribe', 'Complete timelines'],
              ['text-box-search-outline', 'Cited intelligence'],
              ['chart-timeline-variant-shimmer', 'Auditable spend'],
            ].map(([icon, label]) => (
              <View key={label} style={styles.promise}>
                <MaterialCommunityIcons name={icon as 'transcribe'} size={19} color={colors.pine} />
                <Text style={styles.promiseText}>{label}</Text>
              </View>
            ))}
          </View>
        </View>

        <View style={[styles.loginCard, isNarrow && styles.loginCardNarrow]}>
          <View style={styles.cardTitleArea}>
            <Text style={styles.cardKicker}>DEMO ACCESS</Text>
            <Text style={styles.cardTitle}>Use the shared test account</Text>
            <Text style={styles.cardBody}>Everyone using this public account shares one owner-level workspace.</Text>
          </View>
          {(error ?? sessionError) ? (
            <Notice tone="error" title="Could not sign in">{(error ?? sessionError)?.message}</Notice>
          ) : null}
          <View style={styles.identityList}>
            <Pressable
              accessibilityRole="button"
              onPress={submit}
              style={({ pressed }) => [styles.identity, styles.identityActive, pressed && styles.pressed]}
            >
              <View style={[styles.identityAvatar, styles.identityAvatarActive]}>
                <Text style={[styles.identityInitials, styles.identityInitialsActive]}>{identity.initials}</Text>
              </View>
              <View style={styles.identityCopy}>
                <Text style={styles.identityName}>{identity.name}</Text>
                <Text style={styles.identityRole}>{identity.role}</Text>
                <Text style={styles.identityDetail}>{identity.detail}</Text>
              </View>
              <MaterialCommunityIcons name="account-arrow-right-outline" size={20} color={colors.coral} />
            </Pressable>
          </View>
          <Button size="lg" loading={loading} onPress={submit} icon="arrow-right">Enter evidence lab</Button>
          <Text style={styles.endpoint}>Connecting to {API_BASE_URL}</Text>
          <View style={styles.disclosure}>
            <MaterialCommunityIcons name="shield-check-outline" size={18} color={colors.green} />
            <Text style={styles.disclosureText}>Use synthetic or approved audio until provider terms are configured and accepted.</Text>
          </View>
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: colors.canvas },
  root: { flexGrow: 1, backgroundColor: colors.canvas, justifyContent: 'center', paddingHorizontal: spacing.xl },
  layout: { width: '100%', maxWidth: 1120, alignSelf: 'center', flexDirection: 'row', alignItems: 'center', gap: 56 },
  layoutCompact: { gap: spacing.xl },
  layoutNarrow: { flexDirection: 'column', gap: spacing.xxxl, paddingVertical: spacing.xxxl },
  story: { flex: 1, minWidth: 0, gap: 58 },
  storyCompact: { gap: spacing.xxl },
  storyCopy: { gap: spacing.lg },
  kicker: { color: colors.coralDark, fontFamily: font.medium, fontSize: 10, letterSpacing: 1.5 },
  hero: { maxWidth: 640, color: colors.ink, fontFamily: font.medium, fontSize: 52, lineHeight: 57, letterSpacing: -2.2 },
  heroCompact: { fontSize: 42, lineHeight: 47, letterSpacing: -1.7 },
  heroSmall: { fontSize: 38, lineHeight: 44 },
  heroBody: { maxWidth: 570, color: colors.inkMuted, fontSize: 17, lineHeight: 27 },
  promiseRow: { flexDirection: 'row', gap: spacing.xl, flexWrap: 'wrap' },
  promise: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  promiseText: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 12 },
  loginCard: { width: 430, maxWidth: '100%', flexShrink: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.xl, padding: spacing.xxl, gap: spacing.xl, ...shadow },
  loginCardNarrow: { width: '100%' },
  cardTitleArea: { gap: spacing.sm },
  cardKicker: { color: colors.coralDark, fontFamily: font.medium, fontSize: 10, letterSpacing: 1.4 },
  cardTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 26, letterSpacing: -0.7 },
  cardBody: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  identityList: { gap: spacing.sm },
  identity: { minHeight: 92, padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  identityActive: { borderColor: colors.pine, backgroundColor: colors.pineSoft },
  identityAvatar: { width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.surfaceMuted },
  identityAvatarActive: { backgroundColor: colors.pine },
  identityInitials: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 12 },
  identityInitialsActive: { color: colors.white },
  identityCopy: { flex: 1, gap: 2 },
  identityName: { color: colors.ink, fontFamily: font.medium, fontSize: 14 },
  identityRole: { color: colors.coralDark, fontSize: 11 },
  identityDetail: { color: colors.inkMuted, fontSize: 10, lineHeight: 14, marginTop: 2 },
  endpoint: { color: colors.inkFaint, fontFamily: font.mono, fontSize: 9, textAlign: 'center' },
  disclosure: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, paddingTop: spacing.lg, borderTopWidth: 1, borderTopColor: colors.border },
  disclosureText: { flex: 1, color: colors.inkMuted, fontSize: 10, lineHeight: 15 },
  pressed: { opacity: 0.72 },
});
