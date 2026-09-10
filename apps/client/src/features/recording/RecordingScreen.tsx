import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import { RecordingAudioPlayer, type RecordingAudioPlayerHandle } from '@/components/AudioPlayer';
import { Button, Card, Chip, CitationChip, EmptyState, ErrorState, LoadingState, Notice, SectionTitle, StatusBadge } from '@/components/ui';
import { RecordingAskPane } from '@/features/ask/RecordingAskPane';
import { useResource } from '@/hooks/useResource';
import { api } from '@/lib/api';
import { isValidEvidenceRange, type EvidenceRange } from '@/lib/evidence';
import { formatBytes, formatDate, formatDuration, formatMoney, isActiveState } from '@/lib/format';
import { colors, font, shadowNone, spacing } from '@/theme';
import type { Citation, CostSummary, EvidenceItem, Recording, RecordingIntelligence, Transcript, TranscriptSegment } from '@/types/api';

type DetailTab = 'overview' | 'transcript' | 'cost' | 'ask';

interface RecordingBundle {
  recording: Recording;
  transcript?: Transcript;
  intelligence?: RecordingIntelligence;
  transcriptError?: Error;
  intelligenceError?: Error;
}

const configuredPollMs = Number(process.env.EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS ?? '4000');
const statusPollMs = Math.max(1_000, Number.isFinite(configuredPollMs) ? configuredPollMs : 4_000);

export default function RecordingScreen() {
  const params = useLocalSearchParams<{ id: string; seek?: string; start?: string; end?: string }>();
  const router = useRouter();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;
  const routeSeek = Array.isArray(params.seek) ? params.seek[0] : params.seek;
  const routeStart = Array.isArray(params.start) ? params.start[0] : params.start;
  const routeEnd = Array.isArray(params.end) ? params.end[0] : params.end;
  const playerRef = useRef<RecordingAudioPlayerHandle>(null);
  const [tab, setTab] = useState<DetailTab>('overview');
  const [actionError, setActionError] = useState<Error>();
  const [actionBusy, setActionBusy] = useState<string>();

  const playEvidence = (range: EvidenceRange) => {
    if (isValidEvidenceRange(range)) playerRef.current?.playRangeMs(range.start_ms, range.end_ms);
  };

  const resource = useResource<RecordingBundle>(async () => {
    if (!id) throw new Error('Recording ID is missing');
    const recording = await api.recording(id);
    const [transcriptResult, intelligenceResult] = await Promise.allSettled([
      recording.readiness.transcript_ready ? api.transcript(id) : Promise.resolve(undefined),
      recording.readiness.intelligence_ready ? api.intelligence(id) : Promise.resolve(undefined),
    ]);
    return {
      recording,
      transcript: transcriptResult.status === 'fulfilled' ? transcriptResult.value : undefined,
      intelligence: intelligenceResult.status === 'fulfilled' ? intelligenceResult.value : undefined,
      transcriptError: transcriptResult.status === 'rejected' ? asError(transcriptResult.reason) : undefined,
      intelligenceError: intelligenceResult.status === 'rejected' ? asError(intelligenceResult.reason) : undefined,
    };
  }, [id]);

  const activeState = resource.data?.recording.state;
  const originalReady = resource.data?.recording.readiness.original_ready;
  const reload = resource.reload;
  useEffect(() => {
    if (!originalReady) return;
    const range = { start_ms: Number(routeStart), end_ms: Number(routeEnd) };
    if (isValidEvidenceRange(range)) {
      playerRef.current?.playRangeMs(range.start_ms, range.end_ms);
      return;
    }
    const ms = Number(routeSeek);
    if (Number.isFinite(ms) && ms >= 0) playerRef.current?.seekToMs(ms, true);
  }, [originalReady, routeEnd, routeSeek, routeStart]);

  useEffect(() => {
    if (!activeState || !isActiveState(activeState)) return;
    const timer = setInterval(() => void reload(), statusPollMs);
    return () => clearInterval(timer);
  }, [activeState, reload]);

  const run = async (name: string, operation: () => Promise<unknown>) => {
    setActionError(undefined);
    setActionBusy(name);
    try {
      await operation();
      await resource.reload();
    } catch (caught) {
      setActionError(asError(caught));
    } finally {
      setActionBusy(undefined);
    }
  };

  if (resource.loading) return <AppShell><LoadingState label="Loading run…" /></AppShell>;
  if (resource.error || !resource.data) return <AppShell><ErrorState error={resource.error ?? new Error('Run not found')} onRetry={resource.reload} /></AppShell>;

  const { recording, transcript, intelligence, transcriptError, intelligenceError } = resource.data;
  return (
    <AppShell>
      <View style={styles.header}>
        <View style={styles.headerCopy}>
          <Button size="sm" variant="ghost" icon="arrow-left" onPress={() => router.push('/results')}>All runs</Button>
          <View style={styles.titleLine}>
            <Text accessibilityRole="header" style={styles.title}>{recording.is_fixture ? 'Complete pipeline example' : recording.title}</Text>
            <StatusBadge state={recording.state} />
          </View>
          <Text style={styles.meta}>{formatDuration(recording.duration_ms)} · {formatBytes(recording.size_bytes)} · {formatDate(recording.created_at, true)}</Text>
        </View>
        {isActiveState(recording.state) && recording.state !== 'deleting' ? (
          <Button size="sm" variant="secondary" icon="stop-circle-outline" loading={actionBusy === 'cancel'} onPress={() => run('cancel', () => api.cancel(recording.id))}>Stop processing</Button>
        ) : recording.state === 'failed_retryable' || recording.state === 'cancelled' || recording.state === 'partial' ? (
          <Button size="sm" variant="secondary" icon="refresh" loading={actionBusy === 'retry'} onPress={() => run('retry', () => api.retry(recording.id))}>Retry</Button>
        ) : null}
      </View>

      <ReadinessPanel recording={recording} />
      {recording.readiness.original_ready ? <RecordingAudioPlayer ref={playerRef} recordingId={recording.id} /> : null}
      {actionError ? <Notice tone="error" title="Could not complete the action">{actionError.message}</Notice> : null}

      <View style={styles.tabs} accessibilityRole="tablist">
        {(['overview', 'transcript', 'cost', 'ask'] as DetailTab[]).map((item) => (
          <Pressable
            key={item}
            accessibilityRole="tab"
            accessibilityState={{ selected: tab === item }}
            onPress={() => setTab(item)}
            style={[styles.tab, tab === item && styles.tabActive]}
          >
            <Text style={[styles.tabText, tab === item && styles.tabTextActive]}>{item === 'overview' ? 'Grounded output' : item === 'cost' ? 'Cost trace' : item === 'ask' ? 'Ask' : 'Transcript'}</Text>
          </Pressable>
        ))}
      </View>

      {tab === 'overview' ? <OverviewPane recording={recording} intelligence={intelligence} error={intelligenceError} onSeek={playEvidence} /> : null}
      {tab === 'transcript' ? <TranscriptPane recording={recording} transcript={transcript} error={transcriptError} onSeek={playEvidence} /> : null}
      {tab === 'cost' ? <RecordingCostPane recordingId={recording.id} /> : null}
      {tab === 'ask' ? <RecordingAskPane key={recording.id} recording={recording} onEvidence={playEvidence} /> : null}
    </AppShell>
  );
}

function ReadinessPanel({ recording }: { recording: Recording }) {
  const items = [
    ['Source audio', 'original_ready', 'file-music-outline'],
    ['Transcript', 'transcript_ready', 'text-box-check-outline'],
    ['Grounded output', 'intelligence_ready', 'lightbulb-on-outline'],
    ['Search index', 'indexed_ready', 'database-search-outline'],
  ] as const;
  const issue = recording.issues?.[0];
  return (
    <Card style={styles.readinessCard}>
      <Text style={styles.readinessLabel}>PUBLISHED BACKEND STAGES</Text>
      <View style={styles.assetGrid}>
        {items.map(([label, key, icon], index) => {
          const ready = recording.readiness[key];
          const stageName = key === 'transcript_ready'
            ? 'transcribing'
            : key === 'intelligence_ready'
              ? 'extracting_intelligence'
              : key === 'indexed_ready'
                ? 'indexing'
                : undefined;
          const stage = stageName
            ? recording.stages?.find((candidate) => candidate.stage === stageName)
            : recording.stages?.find((candidate) => candidate.stage === 'uploading' || candidate.stage === 'verifying');
          const active = stage?.status === 'active' || (key === 'original_ready' && (recording.state === 'uploading' || recording.state === 'verifying'));
          return (
            <View key={key} style={styles.asset}>
              <View style={[styles.assetIcon, ready && styles.assetIconReady, active && styles.assetIconActive]}>
                <MaterialCommunityIcons name={ready ? 'check' : active ? 'progress-clock' : icon} size={18} color={ready ? colors.white : active ? colors.blue : colors.inkFaint} />
              </View>
              <View style={styles.assetCopy}>
                <Text style={styles.assetTitle}>{label}</Text>
                <Text style={[styles.assetState, ready && styles.assetStateReady, active && styles.assetStateActive]}>{ready ? 'Ready' : active ? 'Running' : stage?.status === 'failed' ? 'Failed' : 'Waiting'}</Text>
              </View>
              {index < items.length - 1 ? <MaterialCommunityIcons name="chevron-right" size={16} color={ready ? colors.green : colors.borderStrong} /> : null}
            </View>
          );
        })}
      </View>
      {issue ? <Notice tone={issue.retryable ? 'warning' : 'error'} title={issue.message}>{issue.action}</Notice> : null}
    </Card>
  );
}

function OverviewPane({ recording, intelligence, error, onSeek }: { recording: Recording; intelligence?: RecordingIntelligence; error?: Error; onSeek(range: EvidenceRange): void }) {
  if (!recording.readiness.intelligence_ready) {
    return <Card><EmptyState icon="lightbulb-off-outline" title="Grounded output is not ready" body="This section appears after the transcript, schema, and citation checks pass." /></Card>;
  }
  if (error) return <Card><ErrorState error={error} /></Card>;
  if (!intelligence) return <Card><EmptyState icon="file-question-outline" title="Output unavailable" body="Refresh this run to load the published result." /></Card>;
  return (
    <View style={styles.paneStack}>
      <Card style={styles.paneCard}>
        <SectionTitle title="Summary" subtitle={`Published output · v${intelligence.version}`} />
        <Text style={styles.summary}>{intelligence.summary.short}</Text>
        <CitationRow citations={intelligence.summary.evidence} onSeek={onSeek} />
      </Card>
      <View style={styles.outputGrid}>
        <Card style={[styles.paneCard, styles.outputCard]}>
          <SectionTitle title="Decisions" />
          <EvidenceList items={intelligence.decisions} empty="No cited decisions found." onSeek={onSeek} />
        </Card>
        <Card style={[styles.paneCard, styles.outputCard]}>
          <SectionTitle title="Next actions" />
          <EvidenceList items={intelligence.actions} empty="No cited actions found." onSeek={onSeek} kind="action" />
        </Card>
      </View>
    </View>
  );
}

function TranscriptPane({ recording, transcript, error, onSeek }: { recording: Recording; transcript?: Transcript; error?: Error; onSeek(range: EvidenceRange): void }) {
  if (!recording.readiness.transcript_ready) return <Card><EmptyState icon="text-box-remove-outline" title="Transcript is not ready" body="Transcription must finish before downstream stages can run." /></Card>;
  if (error) return <Card><ErrorState error={error} /></Card>;
  if (!transcript) return <Card><EmptyState icon="file-question-outline" title="Transcript unavailable" body="Refresh this run to load the published transcript." /></Card>;
  return (
    <Card style={styles.paneCard}>
      <SectionTitle title="Timestamped transcript" subtitle={`${transcript.segments.length} segments · version ${transcript.version}`} />
      <View style={styles.transcriptList}>
        {transcript.segments.map((segment) => (
          <View key={segment.id} style={styles.segment}>
            <Pressable accessibilityRole="button" accessibilityLabel={`Play from ${formatDuration(segment.start_ms)} to ${formatDuration(segment.end_ms)}`} onPress={() => onSeek(segment)} style={styles.timestampButton}>
              <MaterialCommunityIcons name="play" size={13} color={colors.blue} />
              <Text style={styles.timestamp}>{formatDuration(segment.start_ms)}–{formatDuration(segment.end_ms)}</Text>
            </Pressable>
            <View style={styles.segmentBody}>
              <Text style={styles.speakerName}>{segment.speaker_name ?? labelSpeaker(segment)}</Text>
              <Text style={styles.segmentText}>{segment.text}</Text>
            </View>
          </View>
        ))}
      </View>
    </Card>
  );
}

function EvidenceList({ items, empty, onSeek, kind }: { items: EvidenceItem[]; empty: string; onSeek(range: EvidenceRange): void; kind?: 'action' }) {
  if (!items.length) return <Text style={styles.emptyInline}>{empty}</Text>;
  return (
    <View style={styles.evidenceList}>
      {items.map((item, index) => {
        const text = item.claim ?? item.decision ?? item.task ?? item.question ?? item.text ?? 'Unresolved item';
        return (
          <View key={item.id ?? `${text}-${index}`} style={styles.evidenceItem}>
            <View style={[styles.evidenceNumber, kind === 'action' && styles.evidenceNumberAction]}><Text style={styles.evidenceNumberText}>{index + 1}</Text></View>
            <View style={styles.evidenceCopy}>
              <Text style={styles.evidenceText}>{text}</Text>
              {kind === 'action' ? (
                <View style={styles.chipWrap}>
                  <Chip label={item.owner_text ? `Owner: ${item.owner_text}` : 'Owner unresolved'} />
                  {item.due_text ? <Chip label={`Due: ${item.due_text}`} /> : null}
                </View>
              ) : null}
              <CitationRow citations={item.evidence} onSeek={onSeek} />
            </View>
          </View>
        );
      })}
    </View>
  );
}

function CitationRow({ citations, onSeek }: { citations: Citation[]; onSeek(range: EvidenceRange): void }) {
  return (
    <View style={styles.chipWrap}>
      {citations.map((citation) => <CitationChip key={`${citation.segment_id}-${citation.start_ms}-${citation.end_ms}`} citation={citation} onPress={() => onSeek(citation)} />)}
    </View>
  );
}

function RecordingCostPane({ recordingId }: { recordingId: string }) {
  const resource = useResource(() => api.costs(recordingId), [recordingId]);
  if (resource.loading) return <Card><LoadingState label="Loading cost trace…" /></Card>;
  if (resource.error || !resource.data) return <Card><ErrorState error={resource.error ?? new Error('Cost data is unavailable')} onRetry={resource.reload} /></Card>;
  const costs: CostSummary = resource.data;
  return (
    <View style={styles.paneStack}>
      <View style={styles.costMetrics}>
        <Metric label="Run cost" value={formatMoney(costs.estimated_incurred_usd)} />
        <Metric label="Baseline estimate" value={formatMoney(costs.baseline_estimate_usd)} />
        <Metric label="Modeled difference" value={formatMoney(costs.modeled_delta_usd)} accent />
      </View>
      <Card style={styles.paneCard}>
        <SectionTitle title="Model-call trace" subtitle={`${costs.events.length} model operations`} />
        {costs.events.map((event) => (
          <View key={event.id} style={styles.costEvent}>
            <View style={styles.costRoute}>
              <Text style={styles.routeAlias}>{event.model_alias}</Text>
              <Text style={styles.routeStage}>{event.stage.replace(/_/g, ' ')}{event.escalation_reason ? ` · ${event.escalation_reason.replace(/_/g, ' ')}` : ''}</Text>
            </View>
            {event.cached || event.reused ? <Chip label={event.reused ? 'Reused' : 'Cache hit'} /> : null}
            <Text style={styles.eventCost}>{formatMoney(event.reconciled_cost_usd ?? event.estimated_cost_usd)}</Text>
          </View>
        ))}
        {!costs.events.length ? <Text style={styles.emptyInline}>No model calls were needed for this run.</Text> : null}
      </Card>
    </View>
  );
}

function Metric({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <Card style={[styles.costMetric, accent && styles.costMetricAccent]}><Text style={styles.costMetricLabel}>{label}</Text><Text style={[styles.costMetricValue, accent && styles.costMetricValueAccent]}>{value}</Text></Card>;
}

function labelSpeaker(segment: TranscriptSegment) {
  const cluster = segment.speaker_cluster_id;
  if (!cluster) return 'Speaker';
  const anonymousLabel = /^speaker[-_\s]+(.+)$/i.exec(cluster)?.[1];
  return anonymousLabel ? `Speaker ${anonymousLabel.toUpperCase()}` : `Speaker ${cluster}`;
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error('Something went wrong');
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: spacing.xl, flexWrap: 'wrap' },
  headerCopy: { flex: 1, minWidth: 260, gap: spacing.sm },
  titleLine: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flexWrap: 'wrap' },
  title: { color: colors.ink, fontFamily: font.medium, fontSize: 31, lineHeight: 37, letterSpacing: -0.9 },
  meta: { color: colors.inkMuted, fontSize: 11 },
  readinessCard: { gap: spacing.lg, ...shadowNone },
  readinessLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  assetGrid: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  asset: { flex: 1, minWidth: 150, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  assetIcon: { width: 36, height: 36, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.surfaceMuted },
  assetIconReady: { backgroundColor: colors.green },
  assetIconActive: { backgroundColor: colors.blueSoft },
  assetCopy: { flex: 1, gap: 2 },
  assetTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 11 },
  assetState: { color: colors.inkFaint, fontSize: 9 },
  assetStateReady: { color: colors.green },
  assetStateActive: { color: colors.blue },
  tabs: { flexDirection: 'row', columnGap: spacing.xl, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: { paddingHorizontal: 2, paddingVertical: 13, borderBottomWidth: 2, borderBottomColor: 'transparent' },
  tabActive: { borderBottomColor: colors.coral },
  tabText: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 13 },
  tabTextActive: { color: colors.ink },
  paneStack: { gap: spacing.xl },
  paneCard: { gap: spacing.xl },
  outputGrid: { flexDirection: 'row', alignItems: 'flex-start', flexWrap: 'wrap', gap: spacing.xl },
  outputCard: { flex: 1, minWidth: 300 },
  summary: { color: colors.ink, fontFamily: font.medium, fontSize: 19, lineHeight: 29 },
  evidenceList: { gap: spacing.lg },
  evidenceItem: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md },
  evidenceNumber: { width: 26, height: 26, borderRadius: 9, backgroundColor: colors.pineSoft, alignItems: 'center', justifyContent: 'center' },
  evidenceNumberAction: { backgroundColor: colors.coralSoft },
  evidenceNumberText: { color: colors.pine, fontFamily: font.medium, fontSize: 10 },
  evidenceCopy: { flex: 1, gap: spacing.sm },
  evidenceText: { color: colors.ink, fontSize: 14, lineHeight: 21 },
  chipWrap: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  emptyInline: { color: colors.inkFaint, fontSize: 13, fontStyle: 'italic', paddingVertical: spacing.lg },
  transcriptList: { gap: 0 },
  segment: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md, paddingVertical: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  timestampButton: { width: 106, paddingTop: 2, flexDirection: 'row', alignItems: 'center', gap: 3 },
  timestamp: { color: colors.blue, fontFamily: font.mono, fontSize: 10 },
  segmentBody: { flex: 1, gap: spacing.sm },
  speakerName: { color: colors.coralDark, fontFamily: font.medium, fontSize: 11 },
  segmentText: { color: colors.ink, fontSize: 15, lineHeight: 24 },
  costMetrics: { flexDirection: 'row', gap: spacing.lg, flexWrap: 'wrap' },
  costMetric: { flex: 1, minWidth: 190, gap: spacing.sm, ...shadowNone },
  costMetricAccent: { backgroundColor: colors.greenSoft, borderColor: colors.green },
  costMetricLabel: { color: colors.inkMuted, fontSize: 11 },
  costMetricValue: { color: colors.ink, fontFamily: font.medium, fontSize: 25 },
  costMetricValueAccent: { color: colors.green },
  costEvent: { minHeight: 66, flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  costRoute: { flex: 1, minWidth: 150, gap: 3 },
  routeAlias: { color: colors.ink, fontFamily: font.mono, fontSize: 11 },
  routeStage: { color: colors.inkMuted, fontSize: 10, textTransform: 'capitalize' },
  eventCost: { width: 70, color: colors.ink, fontFamily: font.medium, fontSize: 12, textAlign: 'right' },
});
