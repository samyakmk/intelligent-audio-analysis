import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import {
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  Input,
  Notice,
  PageTitle,
  ProgressBar,
  SectionTitle,
  StatusBadge,
  uiStyles,
} from '@/components/ui';
import { useResource } from '@/hooks/useResource';
import { api, unwrapItems } from '@/lib/api';
import { formatBytes, formatDate, formatDuration, isActiveState } from '@/lib/format';
import { useSession } from '@/providers/SessionProvider';
import { colors, font, radius, shadowNone, spacing } from '@/theme';
import type { Recording, RecordingState } from '@/types/api';

const filters: { label: string; value?: RecordingState }[] = [
  { label: 'All' },
  { label: 'Ready', value: 'ready' },
  { label: 'Processing', value: 'processing' },
  { label: 'Partial', value: 'partial' },
];

const configuredPollMs = Number(process.env.EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS ?? '4000');
const statusPollMs = Math.max(1_000, Number.isFinite(configuredPollMs) ? configuredPollMs : 4_000);

export default function LibraryScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const { session, sync: syncSession } = useSession();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<RecordingState>();
  const [retryingId, setRetryingId] = useState<string>();
  const [actionError, setActionError] = useState<Error>();
  const resource = useResource(() => api.recordings(), [session?.workspace.id]);
  useEffect(() => {
    void syncSession();
  }, [syncSession]);
  const recordings = useMemo(() => {
    const items = resource.data ? unwrapItems(resource.data) : [];
    const needle = query.trim().toLocaleLowerCase();
    return [...items]
      .filter((recording) => !filter || recording.state === filter || (filter === 'processing' && isActiveState(recording.state)))
      .filter((recording) => !needle || recording.title.toLocaleLowerCase().includes(needle) || recording.filename.toLocaleLowerCase().includes(needle))
      .sort((a, b) => Number(Boolean(b.is_fixture)) - Number(Boolean(a.is_fixture)) || Date.parse(b.created_at) - Date.parse(a.created_at));
  }, [resource.data, query, filter]);

  const anyActive = recordings.some((recording) => isActiveState(recording.state));
  const reload = resource.reload;
  useEffect(() => {
    if (!anyActive) return;
    const timer = setInterval(() => void reload(), statusPollMs);
    return () => clearInterval(timer);
  }, [anyActive, reload]);

  const workspace = session?.workspace;
  const bytesPercent = Math.min(100, ((workspace?.retained_bytes ?? 0) / (workspace?.byte_limit || 5 * 1024 ** 3)) * 100);
  const countPercent = Math.min(100, ((workspace?.retained_recordings ?? recordings.length) / (workspace?.recording_limit || 200)) * 100);
  const cardWidth = width >= 1320 ? '31.8%' : width >= 760 ? '48.6%' : '100%';
  const fixture = recordings.find((recording) => recording.is_fixture);

  const retry = async (recording: Recording) => {
    setActionError(undefined);
    setRetryingId(recording.id);
    try {
      await api.retry(recording.id);
      await resource.reload();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught : new Error('Retry failed'));
    } finally {
      setRetryingId(undefined);
    }
  };

  return (
    <AppShell>
      <PageTitle
        title="Your audio, made useful"
        subtitle="Canonical recordings stay separate from transcripts, intelligence, and search indexes—so a failure never erases work that is already ready."
        action={<Button icon="plus" onPress={() => router.push('/upload')}>Upload audio</Button>}
      />

      <View style={styles.metrics}>
        <Card style={styles.metricCard}>
          <View style={uiStyles.rowBetween}>
            <View style={styles.metricIcon}><MaterialCommunityIcons name="database-outline" size={20} color={colors.pine} /></View>
            <Text style={styles.metricValue}>{workspace?.retained_recordings ?? recordings.length}</Text>
          </View>
          <Text style={styles.metricLabel}>Retained recordings</Text>
          <ProgressBar value={countPercent} tone="pine" />
          <Text style={styles.metricHint}>{workspace?.recording_limit ?? 200} recording limit</Text>
        </Card>
        <Card style={styles.metricCard}>
          <View style={uiStyles.rowBetween}>
            <View style={[styles.metricIcon, styles.metricIconBlue]}><MaterialCommunityIcons name="harddisk" size={20} color={colors.blue} /></View>
            <Text style={styles.metricValue}>{formatBytes(workspace?.retained_bytes ?? 0)}</Text>
          </View>
          <Text style={styles.metricLabel}>Storage in use</Text>
          <ProgressBar value={bytesPercent} tone="pine" />
          <Text style={styles.metricHint}>{formatBytes(workspace?.byte_limit ?? 5 * 1024 ** 3)} workspace limit</Text>
        </Card>
        <Card style={[styles.metricCard, styles.retentionCard]}>
          <View style={uiStyles.rowBetween}>
            <View style={[styles.metricIcon, styles.metricIconCoral]}><MaterialCommunityIcons name="clock-outline" size={20} color={colors.coralDark} /></View>
            <Text style={styles.metricValue}>30 days</Text>
          </View>
          <Text style={styles.metricLabel}>Default retention</Text>
          <Text style={styles.retentionBody}>Worker and inline maintenance enforce the demo expiry target and retry object purge. Backups and external providers remain outside this proof.</Text>
        </Card>
      </View>

      {fixture ? (
        <Notice
          tone="info"
          title="A grounded fixture is ready to explore"
          action={<Button size="sm" variant="secondary" onPress={() => router.push(`/recordings/${fixture.id}`)}>Open fixture</Button>}
        >
          Arbitrary uploads stay partial when speech providers are unconfigured; this seeded recording demonstrates transcript, citations, Search, Ask, and costs without fabricating output.
        </Notice>
      ) : null}
      {actionError ? <Notice tone="error" title="Action failed">{actionError.message}</Notice> : null}

      <Card style={styles.libraryCard}>
        <SectionTitle
          title="Library"
          subtitle={`${recordings.length} ${recordings.length === 1 ? 'recording' : 'recordings'} in this view`}
          action={
            <Button
              size="sm"
              variant="ghost"
              icon="refresh"
              loading={resource.refreshing}
              onPress={() => void Promise.all([resource.reload(), syncSession()])}
            >
              Refresh
            </Button>
          }
        />
        <View style={styles.toolbar}>
          <View style={styles.searchWrap}>
            <MaterialCommunityIcons name="magnify" size={20} color={colors.inkFaint} />
            <Input
              accessibilityLabel="Filter recordings"
              placeholder="Filter by title or filename"
              value={query}
              onChangeText={setQuery}
              style={styles.searchInput}
            />
          </View>
          <View style={styles.filters}>
            {filters.map((item) => (
              <Chip key={item.label} label={item.label} selected={filter === item.value} onPress={() => setFilter(item.value)} />
            ))}
          </View>
        </View>

        {resource.loading ? (
          <View style={styles.skeletonGrid}>{[0, 1, 2].map((value) => <View key={value} style={[styles.skeletonCard, { width: cardWidth }]} />)}</View>
        ) : resource.error ? (
          <ErrorState error={resource.error} onRetry={resource.reload} />
        ) : recordings.length === 0 ? (
          <EmptyState
            icon="waveform"
            title={query || filter ? 'No recordings match' : 'Start with an audio file'}
            body={query || filter ? 'Clear your filters or choose a different processing state.' : 'Upload MP3, M4A/AAC, WAV, FLAC, OGG, or WebM up to 500 MiB and two hours.'}
            action={<Button icon="tray-arrow-up" onPress={() => router.push('/upload')}>Choose audio</Button>}
          />
        ) : (
          <View style={styles.recordingGrid}>
            {recordings.map((recording) => (
              <RecordingCard
                key={recording.id}
                recording={recording}
                width={cardWidth}
                retrying={retryingId === recording.id}
                onOpen={() => router.push(`/recordings/${recording.id}`)}
                onRetry={() => retry(recording)}
              />
            ))}
          </View>
        )}
      </Card>
    </AppShell>
  );
}

function RecordingCard({
  recording,
  width,
  retrying,
  onOpen,
  onRetry,
}: {
  recording: Recording;
  width: number | string;
  retrying: boolean;
  onOpen(): void;
  onRetry(): void;
}) {
  const activeStage = recording.stages?.find((stage) => stage.status === 'active');
  const readyCount = Object.values(recording.readiness).filter(Boolean).length;
  const issue = recording.issues?.[0];
  return (
    <View style={[styles.recordingCard, { width } as object]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Open ${recording.title}`}
        onPress={onOpen}
        style={({ pressed }) => [styles.recordingCardOpen, pressed && styles.recordingCardActive]}
      >
      <View style={uiStyles.rowBetween}>
        <StatusBadge state={recording.state} />
        {recording.is_fixture ? <Chip label="Fixture" icon="flask-outline" /> : <Text style={styles.date}>{formatDate(recording.created_at)}</Text>}
      </View>
      <View style={styles.recordingMain}>
        <View style={styles.fileIcon}><MaterialCommunityIcons name="waveform" size={24} color={colors.coralDark} /></View>
        <View style={styles.recordingCopy}>
          <Text numberOfLines={2} style={styles.recordingTitle}>{recording.title}</Text>
          <Text numberOfLines={1} style={styles.filename}>{recording.filename}</Text>
        </View>
      </View>
      <View style={styles.recordingMeta}>
        <Text style={styles.metaText}>{formatDuration(recording.duration_ms)}</Text>
        <View style={styles.metaDot} />
        <Text style={styles.metaText}>{recording.language?.toUpperCase() ?? 'AUTO'}</Text>
        <View style={styles.metaDot} />
        <Text style={styles.metaText}>{recording.mode === 'deep' ? 'Deep' : 'Standard'}</Text>
      </View>
      {activeStage ? (
        <View style={styles.stageArea}>
          <View style={styles.activeStageRow}>
            <ActivityIndicator size="small" color={colors.blue} />
            <Text style={styles.stageLabel}>{activeStage.message ?? activeStage.stage.replace('_', ' ')}</Text>
          </View>
          <View style={styles.readinessRow}>
            {(['original_ready', 'transcript_ready', 'intelligence_ready', 'indexed_ready'] as const).map((key) => (
              <View key={key} style={[styles.readinessDot, recording.readiness[key] && styles.readinessDotReady]} />
            ))}
            <Text style={styles.readinessText}>{readyCount}/4 assets committed</Text>
          </View>
        </View>
      ) : (
        <View style={styles.readinessRow}>
          {(['original_ready', 'transcript_ready', 'intelligence_ready', 'indexed_ready'] as const).map((key) => (
            <View key={key} style={[styles.readinessDot, recording.readiness[key] && styles.readinessDotReady]} />
          ))}
          <Text style={styles.readinessText}>{readyCount}/4 assets ready</Text>
        </View>
      )}
      {issue ? (
        <View style={styles.issueRow}>
          <MaterialCommunityIcons name={issue.retryable ? 'alert-outline' : 'information-outline'} size={16} color={colors.amber} />
          <Text numberOfLines={2} style={styles.issueText}>
            {issue.code === 'speech_unconfigured' ? 'Speech is not configured. The original is safe; no transcript was invented.' : issue.message}
          </Text>
        </View>
      ) : null}
      </Pressable>
      <View style={styles.cardFooter}>
        <Text style={styles.expiry}>Retention target {formatDate(recording.expires_at)}</Text>
        {recording.state === 'failed_retryable' || (recording.state === 'partial' && issue?.retryable) ? (
          <Button
            size="sm"
            variant="ghost"
            icon="refresh"
            loading={retrying}
            onPress={(event) => {
              onRetry();
            }}
          >
            Retry
          </Button>
        ) : (
          <MaterialCommunityIcons name="arrow-right" size={18} color={colors.inkFaint} />
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  metrics: { flexDirection: 'row', gap: spacing.lg, flexWrap: 'wrap' },
  metricCard: { flex: 1, minWidth: 220, gap: spacing.sm, padding: spacing.lg, ...shadowNone },
  retentionCard: { minWidth: 260 },
  metricIcon: { width: 34, height: 34, borderRadius: 11, backgroundColor: colors.pineSoft, alignItems: 'center', justifyContent: 'center' },
  metricIconBlue: { backgroundColor: colors.blueSoft },
  metricIconCoral: { backgroundColor: colors.coralSoft },
  metricValue: { color: colors.ink, fontFamily: font.medium, fontSize: 20, letterSpacing: -0.4 },
  metricLabel: { color: colors.inkMuted, fontSize: 12 },
  metricHint: { color: colors.inkFaint, fontSize: 9 },
  retentionBody: { color: colors.inkMuted, fontSize: 11, lineHeight: 16 },
  libraryCard: { gap: spacing.xl },
  toolbar: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.lg, flexWrap: 'wrap' },
  searchWrap: { flex: 1, minWidth: 220, maxWidth: 480, minHeight: 44, flexDirection: 'row', alignItems: 'center', paddingLeft: 13, borderWidth: 1, borderColor: colors.borderStrong, backgroundColor: colors.surface, borderRadius: radius.md },
  searchInput: { flex: 1, borderWidth: 0, backgroundColor: 'transparent' },
  filters: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  skeletonGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.lg },
  skeletonCard: { minHeight: 290, borderRadius: radius.lg, backgroundColor: colors.surfaceMuted },
  recordingGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.lg },
  recordingCard: { minWidth: 250, minHeight: 290, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, padding: spacing.lg, backgroundColor: colors.surface, gap: spacing.lg },
  recordingCardOpen: { flex: 1, gap: spacing.lg },
  recordingCardActive: { opacity: 0.78 },
  date: { color: colors.inkFaint, fontSize: 10 },
  recordingMain: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  fileIcon: { width: 47, height: 47, borderRadius: 15, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.coralSoft },
  recordingCopy: { flex: 1, gap: 4 },
  recordingTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 16, lineHeight: 21 },
  filename: { color: colors.inkFaint, fontSize: 10 },
  recordingMeta: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  metaText: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 10 },
  metaDot: { width: 3, height: 3, borderRadius: 2, backgroundColor: colors.borderStrong },
  stageArea: { gap: spacing.sm },
  activeStageRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  stageLabel: { color: colors.blue, fontFamily: font.medium, fontSize: 11, textTransform: 'capitalize' },
  readinessRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  readinessDot: { width: 22, height: 5, borderRadius: 3, backgroundColor: colors.surfaceMuted },
  readinessDotReady: { backgroundColor: colors.green },
  readinessText: { color: colors.inkMuted, fontSize: 10, marginLeft: 4 },
  issueRow: { flexDirection: 'row', alignItems: 'flex-start', gap: 7, padding: 10, backgroundColor: colors.amberSoft, borderRadius: radius.sm },
  issueText: { flex: 1, color: colors.amber, fontSize: 10, lineHeight: 14 },
  cardFooter: { marginTop: 'auto', paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.border, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  expiry: { color: colors.inkFaint, fontSize: 9 },
});
