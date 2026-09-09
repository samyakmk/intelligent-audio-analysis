import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useEffect, useMemo } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import { Button, Card, EmptyState, ErrorState, PageTitle, StatusBadge } from '@/components/ui';
import { useResource } from '@/hooks/useResource';
import { api, unwrapItems } from '@/lib/api';
import { formatDate, formatDuration, isActiveState } from '@/lib/format';
import { useSession } from '@/providers/SessionProvider';
import { colors, font, radius, shadowNone, spacing } from '@/theme';
import type { Recording } from '@/types/api';

const configuredPollMs = Number(process.env.EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS ?? '4000');
const statusPollMs = Math.max(1_000, Number.isFinite(configuredPollMs) ? configuredPollMs : 4_000);

export default function LibraryScreen() {
  const router = useRouter();
  const { session } = useSession();
  const resource = useResource(() => api.recordings(), [session?.workspace.id]);
  const recordings = useMemo(() => {
    const items = resource.data ? unwrapItems(resource.data) : [];
    return [...items].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  }, [resource.data]);
  const fixture = recordings.find((recording) => recording.is_fixture);
  const runs = recordings.filter((recording) => !recording.is_fixture);
  const anyActive = recordings.some((recording) => isActiveState(recording.state));
  const reload = resource.reload;

  useEffect(() => {
    if (!anyActive) return;
    const timer = setInterval(() => void reload(), statusPollMs);
    return () => clearInterval(timer);
  }, [anyActive, reload]);

  return (
    <AppShell>
      <View style={styles.intro}>
        <Text style={styles.eyebrow}>RUN OUTPUT</Text>
        <PageTitle
          title="Inspect a run"
          subtitle="Open a run to review each published stage, its evidence, and model cost."
          action={<Button icon="plus" onPress={() => router.push('/')}>New run</Button>}
        />
      </View>

      {resource.loading ? (
        <View style={styles.loading}><ActivityIndicator color={colors.coral} /><Text style={styles.loadingText}>Loading runs…</Text></View>
      ) : resource.error ? (
        <Card><ErrorState error={resource.error} onRetry={resource.reload} /></Card>
      ) : (
        <>
          {fixture ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Open the complete example run"
              onPress={() => router.push(`/recordings/${fixture.id}`)}
              style={({ pressed }) => [styles.featured, pressed && styles.pressed]}
            >
              <View style={styles.featuredIcon}><MaterialCommunityIcons name="flask-outline" size={24} color={colors.white} /></View>
              <View style={styles.featuredCopy}>
                <Text style={styles.featuredKicker}>READY-MADE RUN</Text>
                <Text style={styles.featuredTitle}>Complete pipeline example</Text>
                <Text style={styles.featuredBody}>Explore the transcript, grounded output, and cost trace without recording anything first.</Text>
              </View>
              <MaterialCommunityIcons name="arrow-right" size={22} color={colors.pine} />
            </Pressable>
          ) : null}

          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Your runs</Text>
            <Text style={styles.sectionCount}>{runs.length}</Text>
          </View>

          {!runs.length ? (
            <Card>
              <EmptyState
                icon="microphone-outline"
                title="No runs yet"
                body="Record a short clip or choose an audio file to start."
                action={<Button icon="play" onPress={() => router.push('/')}>Start a run</Button>}
              />
            </Card>
          ) : (
            <View style={styles.runList}>
              {runs.map((recording) => <RunRow key={recording.id} recording={recording} onOpen={() => router.push(`/recordings/${recording.id}`)} />)}
            </View>
          )}
        </>
      )}
    </AppShell>
  );
}

function RunRow({ recording, onOpen }: { recording: Recording; onOpen(): void }) {
  const readyCount = Object.values(recording.readiness).filter(Boolean).length;
  const activeStage = recording.stages?.find((stage) => stage.status === 'active');
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Open ${recording.title}`}
      onPress={onOpen}
      style={({ pressed }) => [styles.runRow, pressed && styles.pressed]}
    >
      <View style={styles.runIcon}><MaterialCommunityIcons name="waveform" size={22} color={colors.coralDark} /></View>
      <View style={styles.runCopy}>
        <View style={styles.runTitleRow}>
          <Text numberOfLines={1} style={styles.runTitle}>{recording.title}</Text>
          <StatusBadge state={recording.state} />
        </View>
        <Text numberOfLines={1} style={styles.runMeta}>
          {[formatDuration(recording.duration_ms), formatDate(recording.created_at, true)].join(' · ')}
        </Text>
        <View style={styles.stageLine}>
          {(['original_ready', 'transcript_ready', 'intelligence_ready', 'indexed_ready'] as const).map((key) => (
            <View key={key} style={[styles.stageDot, recording.readiness[key] && styles.stageDotReady]} />
          ))}
          <Text style={styles.stageText}>{activeStage?.message ?? `${readyCount} of 4 outputs ready`}</Text>
        </View>
      </View>
      {activeStage ? <ActivityIndicator size="small" color={colors.blue} /> : <MaterialCommunityIcons name="chevron-right" size={23} color={colors.inkFaint} />}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  intro: { gap: spacing.sm },
  eyebrow: { color: colors.coralDark, fontFamily: font.medium, fontSize: 9, letterSpacing: 1.2 },
  loading: { minHeight: 260, alignItems: 'center', justifyContent: 'center', gap: spacing.md },
  loadingText: { color: colors.inkMuted, fontSize: 12 },
  featured: { minHeight: 128, flexDirection: 'row', alignItems: 'center', gap: spacing.lg, borderWidth: 1, borderColor: colors.pine, borderRadius: radius.lg, backgroundColor: colors.pineSoft, padding: spacing.xl },
  featuredIcon: { width: 48, height: 48, borderRadius: 16, backgroundColor: colors.pine, alignItems: 'center', justifyContent: 'center' },
  featuredCopy: { flex: 1, minWidth: 0, gap: 4 },
  featuredKicker: { color: colors.green, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  featuredTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 18 },
  featuredBody: { color: colors.inkMuted, fontSize: 11, lineHeight: 17 },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingTop: spacing.sm },
  sectionTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 18 },
  sectionCount: { minWidth: 24, height: 24, borderRadius: 12, textAlign: 'center', lineHeight: 24, backgroundColor: colors.surfaceMuted, color: colors.inkMuted, fontFamily: font.medium, fontSize: 10 },
  runList: { gap: spacing.md },
  runRow: { minHeight: 116, flexDirection: 'row', alignItems: 'center', gap: spacing.lg, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, padding: spacing.lg, backgroundColor: colors.surface, ...shadowNone },
  pressed: { opacity: 0.72 },
  runIcon: { width: 44, height: 44, borderRadius: 15, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.coralSoft },
  runCopy: { flex: 1, minWidth: 0, gap: spacing.sm },
  runTitleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  runTitle: { maxWidth: 500, color: colors.ink, fontFamily: font.medium, fontSize: 15 },
  runMeta: { color: colors.inkFaint, fontSize: 10 },
  stageLine: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  stageDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.surfaceMuted },
  stageDotReady: { backgroundColor: colors.green },
  stageText: { marginLeft: 4, color: colors.inkMuted, fontSize: 10 },
});
