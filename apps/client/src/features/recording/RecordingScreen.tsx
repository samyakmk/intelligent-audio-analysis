import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import { RecordingAudioPlayer, type RecordingAudioPlayerHandle } from '@/components/AudioPlayer';
import {
  Button,
  Card,
  Chip,
  CitationChip,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingState,
  Notice,
  SectionTitle,
  Segmented,
  StatusBadge,
  uiStyles,
} from '@/components/ui';
import { useResource } from '@/hooks/useResource';
import { api, unwrapItems } from '@/lib/api';
import { downloadText, downloadUrl } from '@/platform/download';
import { formatBytes, formatDate, formatDuration, formatMoney, isActiveState } from '@/lib/format';
import { colors, font, radius, spacing } from '@/theme';
import type {
  Citation,
  CostSummary,
  EvidenceItem,
  Recording,
  RecordingIntelligence,
  Speaker,
  SummaryStyle,
  Transcript,
  TranscriptSegment,
} from '@/types/api';

type DetailTab = 'overview' | 'transcript' | 'intelligence' | 'cost';

interface RecordingBundle {
  recording: Recording;
  transcript?: Transcript;
  intelligence?: RecordingIntelligence;
  summaryStyles: SummaryStyle[];
  transcriptError?: Error;
  intelligenceError?: Error;
}

const defaultSummaryStyles: SummaryStyle[] = [
  { id: 'standard', name: 'Standard', description: 'A balanced cited overview' },
  { id: 'brief', name: 'Brief', description: 'A short, decision-first overview' },
  { id: 'detailed', name: 'Detailed', description: 'A fuller cited narrative' },
  { id: 'action_focused', name: 'Action focused', description: 'Decisions, owners, and next steps' },
];

const configuredPollMs = Number(process.env.EXPO_PUBLIC_STATUS_POLL_INTERVAL_MS ?? '4000');
const statusPollMs = Math.max(1_000, Number.isFinite(configuredPollMs) ? configuredPollMs : 4_000);

export default function RecordingScreen() {
  const params = useLocalSearchParams<{ id: string; seek?: string }>();
  const router = useRouter();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;
  const routeSeek = Array.isArray(params.seek) ? params.seek[0] : params.seek;
  const playerRef = useRef<RecordingAudioPlayerHandle>(null);
  const [tab, setTab] = useState<DetailTab>('overview');
  const [actionError, setActionError] = useState<Error>();
  const [notice, setNotice] = useState<string>();
  const [deleting, setDeleting] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [actionBusy, setActionBusy] = useState<string>();

  const seekToEvidence = (ms: number) => {
    playerRef.current?.seekToMs(ms, true);
  };

  useEffect(() => {
    const ms = Number(routeSeek);
    if (Number.isFinite(ms) && ms >= 0) playerRef.current?.seekToMs(ms, true);
  }, [routeSeek]);

  const resource = useResource<RecordingBundle>(async () => {
    if (!id) throw new Error('Recording ID is missing');
    const recording = await api.recording(id);
    const [transcriptResult, intelligenceResult, stylesResult] = await Promise.allSettled([
      recording.readiness.transcript_ready ? api.transcript(id) : Promise.resolve(undefined),
      recording.readiness.intelligence_ready ? api.intelligence(id) : Promise.resolve(undefined),
      api.summaryStyles(),
    ]);
    return {
      recording,
      transcript: transcriptResult.status === 'fulfilled' ? transcriptResult.value : undefined,
      intelligence: intelligenceResult.status === 'fulfilled' ? intelligenceResult.value : undefined,
      summaryStyles:
        stylesResult.status === 'fulfilled' ? unwrapItems(stylesResult.value) : defaultSummaryStyles,
      transcriptError: transcriptResult.status === 'rejected' ? asError(transcriptResult.reason) : undefined,
      intelligenceError: intelligenceResult.status === 'rejected' ? asError(intelligenceResult.reason) : undefined,
    };
  }, [id]);

  const activeRecording = resource.data?.recording;
  const activeState = activeRecording?.state;
  const reload = resource.reload;
  useEffect(() => {
    if (!activeState || !isActiveState(activeState)) return;
    const timer = setInterval(() => void reload(), statusPollMs);
    return () => clearInterval(timer);
  }, [activeState, reload]);

  const run = async (name: string, operation: () => Promise<unknown>, success: string) => {
    setActionError(undefined);
    setNotice(undefined);
    setActionBusy(name);
    try {
      await operation();
      setNotice(success);
      await resource.reload();
    } catch (caught) {
      setActionError(asError(caught));
    } finally {
      setActionBusy(undefined);
    }
  };

  const downloadOriginal = async () => {
    const current = resource.data?.recording;
    if (!current) return;
    await run('download', async () => {
      const grant = await api.mediaGrant(current.id, 'download');
      await downloadUrl(grant.url, current.filename);
    }, 'Original download prepared.');
  };

  const remove = async () => {
    const current = resource.data?.recording;
    if (!current) return;
    setDeleting(true);
    try {
      await api.deleteRecording(current.id);
      router.replace('/');
    } catch (caught) {
      setActionError(asError(caught));
      setDeleteOpen(false);
    } finally {
      setDeleting(false);
    }
  };

  if (resource.loading) return <AppShell><LoadingState label="Loading recording…" /></AppShell>;
  if (resource.error || !resource.data) return <AppShell><ErrorState error={resource.error ?? new Error('Recording not found')} onRetry={resource.reload} /></AppShell>;

  const { recording, transcript, intelligence, transcriptError, intelligenceError } = resource.data;
  return (
    <AppShell>
      <View style={styles.header}>
        <View style={styles.headerCopy}>
          <Button size="sm" variant="ghost" icon="arrow-left" onPress={() => router.back()}>Library</Button>
          <View style={styles.titleLine}>
            <Text accessibilityRole="header" style={styles.title}>{recording.title}</Text>
            <StatusBadge state={recording.state} />
          </View>
          <View style={styles.metadata}>
            <Text style={styles.meta}>{formatDuration(recording.duration_ms)}</Text><View style={styles.dot} />
            <Text style={styles.meta}>{formatBytes(recording.size_bytes)}</Text><View style={styles.dot} />
            <Text style={styles.meta}>{recording.language?.toUpperCase() ?? 'AUTO'}</Text><View style={styles.dot} />
            <Text style={styles.meta}>{formatDate(recording.created_at, true)}</Text>
          </View>
        </View>
        <View style={styles.headerActions}>
          {isActiveState(recording.state) && recording.state !== 'deleting' ? (
            <Button size="sm" variant="secondary" icon="stop-circle-outline" loading={actionBusy === 'cancel'} onPress={() => run('cancel', () => api.cancel(recording.id), 'Processing cancelled. Completed assets were preserved.')}>Cancel</Button>
          ) : null}
          {recording.state === 'failed_retryable' || recording.state === 'cancelled' || recording.state === 'partial' ? (
            <Button size="sm" variant="secondary" icon="refresh" loading={actionBusy === 'retry'} onPress={() => run('retry', () => api.retry(recording.id), 'Retry requested from the last valid artifact.')}>Retry</Button>
          ) : null}
          <Button size="sm" variant="secondary" icon="download-outline" disabled={!recording.readiness.original_ready} loading={actionBusy === 'download'} onPress={downloadOriginal}>Original</Button>
          <Button size="sm" variant="ghost" icon="delete-outline" onPress={() => setDeleteOpen(true)}>Delete</Button>
        </View>
      </View>

      <ReadinessPanel recording={recording} />
      {recording.readiness.original_ready ? <RecordingAudioPlayer ref={playerRef} recordingId={recording.id} /> : null}
      {notice ? <Notice tone="success" title="Done">{notice}</Notice> : null}
      {actionError ? <Notice tone="error" title="Action failed">{actionError.message}</Notice> : null}

      <View style={styles.tabs} accessibilityRole="tablist">
        {(['overview', 'transcript', 'intelligence', 'cost'] as DetailTab[]).map((item) => (
          <Pressable
            key={item}
            accessibilityRole="tab"
            accessibilityState={{ selected: tab === item }}
            onPress={() => setTab(item)}
            style={[styles.tab, tab === item && styles.tabActive]}
          >
            <Text style={[styles.tabText, tab === item && styles.tabTextActive]}>{item === 'cost' ? 'Cost & routes' : capitalize(item)}</Text>
          </Pressable>
        ))}
      </View>

      {tab === 'overview' ? (
        <OverviewPane
          recording={recording}
          intelligence={intelligence}
          intelligenceError={intelligenceError}
          summaryStyles={resource.data.summaryStyles}
          busy={actionBusy}
          onSeek={seekToEvidence}
          onRun={run}
        />
      ) : null}
      {tab === 'transcript' ? (
        <TranscriptPane
          recording={recording}
          transcript={transcript}
          error={transcriptError}
          busy={actionBusy}
          onSeek={seekToEvidence}
          onRun={run}
        />
      ) : null}
      {tab === 'intelligence' ? (
        <IntelligencePane recording={recording} intelligence={intelligence} error={intelligenceError} onSeek={seekToEvidence} />
      ) : null}
      {tab === 'cost' ? <RecordingCostPane recordingId={recording.id} /> : null}

      <ConfirmDialog
        visible={deleteOpen}
        title="Delete this recording?"
        body="Deletion immediately blocks new playback grants, Search, and Ask, then purges recording-scoped artifacts. Unused media grants are revoked when deletion commits; a response already in flight may finish first. Provider retention and backups are outside this demo's proof."
        confirmLabel="Delete recording"
        destructive
        loading={deleting}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={remove}
      />
    </AppShell>
  );
}

function ReadinessPanel({ recording }: { recording: Recording }) {
  const items = [
    ['Original', 'original_ready', 'file-music-outline'],
    ['Transcript', 'transcript_ready', 'text-box-check-outline'],
    ['Intelligence', 'intelligence_ready', 'lightbulb-on-outline'],
    ['Search index', 'indexed_ready', 'database-search-outline'],
  ] as const;
  const issue = recording.issues?.[0];
  return (
    <Card style={styles.readinessCard}>
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
          const originalActive = key === 'original_ready'
            && (recording.state === 'uploading' || recording.state === 'verifying');
          const active = stage?.status === 'active' || originalActive;
          return (
            <View key={key} style={styles.asset}>
              <View style={[styles.assetIcon, ready && styles.assetIconReady, active && styles.assetIconActive]}>
                <MaterialCommunityIcons name={ready ? 'check' : active ? 'progress-clock' : icon} size={18} color={ready ? colors.white : active ? colors.blue : colors.inkFaint} />
              </View>
              <View style={styles.assetCopy}>
                <Text style={styles.assetTitle}>{label}</Text>
                <Text style={[styles.assetState, ready && styles.assetStateReady, active && styles.assetStateActive]}>{ready ? 'Ready' : active ? 'In progress' : stage?.status === 'failed' ? 'Failed' : 'Waiting'}</Text>
              </View>
              {index < items.length - 1 ? <View style={[styles.assetConnector, ready && styles.assetConnectorReady]} /> : null}
            </View>
          );
        })}
      </View>
      {recording.sha256 ? (
        <View style={styles.checksumRow}>
          <MaterialCommunityIcons name="check-decagram-outline" size={16} color={colors.green} />
          <Text style={styles.checksumLabel}>VERIFIED SHA-256</Text>
          <Text selectable style={styles.checksumValue}>{recording.sha256}</Text>
        </View>
      ) : null}
      {issue ? (
        <Notice tone={issue.retryable ? 'warning' : 'error'} title={issue.code === 'speech_unconfigured' ? 'Speech provider is not configured' : issue.message}>
          {issue.code === 'speech_unconfigured'
            ? 'The byte-exact original is available, but the API correctly stopped before creating a transcript or plausible-looking intelligence. Configure an eligible speech route, then retry.'
            : issue.action ?? 'Completed assets remain available. Retry only if the issue is marked retryable.'}
        </Notice>
      ) : null}
    </Card>
  );
}

function OverviewPane({
  recording,
  intelligence,
  intelligenceError,
  summaryStyles,
  busy,
  onSeek,
  onRun,
}: {
  recording: Recording;
  intelligence?: RecordingIntelligence;
  intelligenceError?: Error;
  summaryStyles: SummaryStyle[];
  busy?: string;
  onSeek(ms: number): void;
  onRun(name: string, operation: () => Promise<unknown>, success: string): Promise<void>;
}) {
  const { width } = useWindowDimensions();
  const [title, setTitle] = useState(recording.title);
  const [tags, setTags] = useState((recording.tags ?? []).join(', '));
  const [folder, setFolder] = useState(recording.folder ?? '');
  const [style, setStyle] = useState(intelligence?.summary_style ?? summaryStyles[0]?.id ?? 'standard');
  const [mode, setMode] = useState<'standard' | 'deep'>('standard');
  const saveMetadata = () => onRun(
    'metadata',
    () => api.updateRecording(recording.id, {
      title: title.trim() || recording.title,
      tags: tags.split(',').map((item) => item.trim()).filter(Boolean),
      folder: folder.trim(),
    }, recording.version),
    'Recording details updated without rerunning AI.',
  );

  return (
    <View style={[styles.detailColumns, width < 980 && styles.detailColumnsNarrow]}>
      <View style={styles.primaryColumn}>
        {!recording.readiness.intelligence_ready ? (
          <Card>
            <EmptyState
              icon="lightbulb-off-outline"
              title={recording.readiness.transcript_ready ? 'Intelligence is not ready yet' : 'A transcript is required first'}
              body="The original and recording details remain independently useful. Intelligence will appear only after a schema- and citation-valid bundle is published."
            />
          </Card>
        ) : intelligenceError ? (
          <Card><ErrorState error={intelligenceError} /></Card>
        ) : !intelligence ? (
          <Card><EmptyState icon="file-question-outline" title="No current intelligence version" body="The API marked intelligence ready but did not return its canonical artifact." /></Card>
        ) : (
          <>
            <Card style={styles.paneCard}>
              <SectionTitle title="Overview" subtitle={`Canonical intelligence v${intelligence.version}`} />
              <Text style={styles.summary}>{intelligence.summary.short}</Text>
              {intelligence.summary.detailed ? <Text style={styles.bodyText}>{intelligence.summary.detailed}</Text> : null}
              <CitationRow citations={intelligence.summary.evidence} onSeek={onSeek} />
            </Card>
            <Card style={styles.paneCard}>
              <SectionTitle title="Decisions" subtitle="Each material decision links to source audio." />
              <EvidenceList items={intelligence.decisions} empty="No cited decisions were found." onSeek={onSeek} />
            </Card>
            <Card style={styles.paneCard}>
              <SectionTitle title="Next actions" />
              <EvidenceList items={intelligence.actions} empty="No cited actions were found." onSeek={onSeek} kind="action" />
            </Card>
          </>
        )}
      </View>
      <View style={styles.secondaryColumn}>
        <Card style={styles.paneCard}>
          <SectionTitle title="Recording details" subtitle="Edits do not rerun speech or base intelligence." />
          <Field label="Title"><Input value={title} onChangeText={setTitle} /></Field>
          <Field label="Folder"><Input value={folder} onChangeText={setFolder} placeholder="e.g. Customer research" /></Field>
          <Field label="Tags" hint="Comma-separated"><Input value={tags} onChangeText={setTags} placeholder="research, onboarding" /></Field>
          <Button variant="secondary" loading={busy === 'metadata'} onPress={saveMetadata}>Save details</Button>
        </Card>
        {intelligence ? <Card style={styles.paneCard}>
          <SectionTitle title="Regenerate downstream" subtitle="Reuses the transcript; speech is never rerun for style changes." />
          <View style={styles.chipWrap}>
            {summaryStyles.map((item) => <Chip key={item.id} label={item.name} selected={style === item.id} onPress={() => setStyle(item.id)} />)}
          </View>
          <Segmented<'standard' | 'deep'>
            value={mode}
            onChange={setMode}
            options={[
              { value: 'standard', label: 'Standard' },
              { value: 'deep', label: 'Deep', description: 'Remote adapter required', disabled: true },
            ]}
          />
          <Button
            icon="refresh"
            loading={busy === 'regenerate'}
            onPress={() => onRun('regenerate', () => api.regenerate(recording.id, style, mode), 'A new downstream intelligence version was requested.')}
          >
            Regenerate
          </Button>
        </Card> : null}
        {intelligence?.warnings.length ? (
          <Notice tone="warning" title="Unresolved intelligence">
            {intelligence.warnings.join(' ')}
          </Notice>
        ) : null}
      </View>
    </View>
  );
}

function TranscriptPane({
  recording,
  transcript,
  error,
  busy,
  onSeek,
  onRun,
}: {
  recording: Recording;
  transcript?: Transcript;
  error?: Error;
  busy?: string;
  onSeek(ms: number): void;
  onRun(name: string, operation: () => Promise<unknown>, success: string): Promise<void>;
}) {
  const { width } = useWindowDimensions();
  const [editing, setEditing] = useState<string>();
  const [draft, setDraft] = useState('');
  if (!recording.readiness.transcript_ready) {
    return <Card><EmptyState icon="text-box-remove-outline" title="No canonical transcript" body="The system will not publish a partial or invented transcript. Check the processing issue above, configure speech if needed, and retry." /></Card>;
  }
  if (error) return <Card><ErrorState error={error} /></Card>;
  if (!transcript) return <Card><EmptyState icon="file-question-outline" title="Transcript marked ready but unavailable" body="Refresh the recording or inspect the API response." /></Card>;

  const unreadable = transcript.intervals.filter((item) => item.state === 'unreadable');
  return (
    <View style={[styles.detailColumns, width < 980 && styles.detailColumnsNarrow]}>
      <Card style={[styles.paneCard, styles.primaryColumn]}>
        <SectionTitle title="Transcript" subtitle={`Version ${transcript.version} · ${transcript.segments.length} timestamped segments`} />
        {unreadable.length ? <Notice tone="warning" title={`${unreadable.length} unreadable timeline ${unreadable.length === 1 ? 'interval' : 'intervals'}`}>Every source interval is still accounted for; unreadable audio is not replaced with guessed words.</Notice> : null}
        <View style={styles.transcriptList}>
          {transcript.segments.map((segment) => {
            const isEditing = editing === segment.id;
            return (
              <View key={segment.id} style={styles.segment}>
                <Pressable accessibilityRole="button" accessibilityLabel={`Play at ${formatDuration(segment.start_ms)}`} onPress={() => onSeek(segment.start_ms)} style={styles.timestampButton}>
                  <MaterialCommunityIcons name="play" size={13} color={colors.blue} />
                  <Text style={styles.timestamp}>{formatDuration(segment.start_ms)}</Text>
                </Pressable>
                <View style={styles.segmentBody}>
                  <View style={styles.segmentHeader}>
                    <Text style={styles.speakerName}>{segment.speaker_name ?? labelSpeaker(segment)}</Text>
                    {segment.overlap_group_id ? <Chip label="Overlapping speech" /> : null}
                    {segment.confidence !== undefined && segment.confidence < 0.7 ? <Chip label="Low confidence" /> : null}
                  </View>
                  {isEditing ? (
                    <View style={styles.editArea}>
                      <Input multiline value={draft} onChangeText={setDraft} />
                      <View style={styles.editActions}>
                        <Button size="sm" variant="ghost" onPress={() => setEditing(undefined)}>Cancel</Button>
                        <Button
                          size="sm"
                          loading={busy === `segment-${segment.id}`}
                          onPress={async () => {
                            await onRun(`segment-${segment.id}`, () => api.correctTranscript(recording.id, segment.id, draft, Number(transcript.version)), 'Correction saved. Downstream artifacts were invalidated and will rebuild without rerunning speech.');
                            setEditing(undefined);
                          }}
                        >
                          Save correction
                        </Button>
                      </View>
                    </View>
                  ) : (
                    <Pressable accessibilityRole="button" accessibilityLabel="Edit transcript segment" onPress={() => { setEditing(segment.id); setDraft(segment.text); }}>
                      <Text style={styles.segmentText}>{segment.text}</Text>
                    </Pressable>
                  )}
                </View>
              </View>
            );
          })}
        </View>
      </Card>
      <View style={styles.secondaryColumn}>
        <Card style={styles.paneCard}>
          <SectionTitle title="Speaker labels" subtitle="Anonymous clusters are canonical until you name or merge them." />
          {transcript.speakers.length ? transcript.speakers.map((speaker) => (
            <SpeakerEditor
              key={speaker.id}
              speaker={speaker}
              speakers={transcript.speakers}
              busy={busy === `speaker-${speaker.id}`}
              onSave={(name, mergeInto) => onRun(`speaker-${speaker.id}`, () => api.updateSpeaker(recording.id, speaker.id, name, mergeInto, Number(transcript.version)), 'Speaker labels updated; affected downstream artifacts will rebuild.')}
            />
          )) : <Text style={styles.bodyText}>No speaker clusters were returned.</Text>}
        </Card>
        <Notice tone="info" title="Corrections are versioned">
          Editing text or speakers creates a new transcript version and invalidates dependent intelligence, indexes, rollups, and cached answers. It does not rerun ASR.
        </Notice>
      </View>
    </View>
  );
}

function SpeakerEditor({ speaker, speakers, busy, onSave }: { speaker: Speaker; speakers: Speaker[]; busy: boolean; onSave(name: string, mergeInto?: string): Promise<void> }) {
  const [name, setName] = useState(speaker.display_name ?? speaker.label);
  const [mergeInto, setMergeInto] = useState<string>();
  return (
    <View style={styles.speakerEditor}>
      <View style={uiStyles.rowBetween}>
        <Text style={styles.speakerEditorLabel}>{speaker.label}</Text>
        <Text style={styles.segmentCount}>{speaker.segment_count ?? 0} segments</Text>
      </View>
      <Input value={name} onChangeText={setName} placeholder="Display name" />
      {speakers.length > 1 ? (
        <View style={styles.chipWrap}>
          <Chip label="Keep separate" selected={!mergeInto} onPress={() => setMergeInto(undefined)} />
          {speakers.filter((item) => item.id !== speaker.id).map((item) => (
            <Chip key={item.id} label={`Merge into ${item.display_name ?? item.label}`} selected={mergeInto === item.id} onPress={() => setMergeInto(item.id)} />
          ))}
        </View>
      ) : null}
      <Button size="sm" variant="secondary" loading={busy} onPress={() => onSave(name.trim() || speaker.label, mergeInto)}>Save speaker</Button>
    </View>
  );
}

function IntelligencePane({ recording, intelligence, error, onSeek }: { recording: Recording; intelligence?: RecordingIntelligence; error?: Error; onSeek(ms: number): void }) {
  if (!recording.readiness.intelligence_ready) return <Card><EmptyState icon="lightbulb-off-outline" title="No published intelligence" body="Required fields and citations must validate before an intelligence bundle is shown." /></Card>;
  if (error) return <Card><ErrorState error={error} /></Card>;
  if (!intelligence) return null;
  return (
    <View style={styles.intelligenceGrid}>
      <Card style={styles.paneCard}><SectionTitle title="Facts" /><EvidenceList items={intelligence.facts} empty="No cited facts." onSeek={onSeek} /></Card>
      <Card style={styles.paneCard}><SectionTitle title="Decisions" /><EvidenceList items={intelligence.decisions} empty="No cited decisions." onSeek={onSeek} /></Card>
      <Card style={styles.paneCard}><SectionTitle title="Actions" /><EvidenceList items={intelligence.actions} empty="No cited actions." onSeek={onSeek} kind="action" /></Card>
      <Card style={styles.paneCard}><SectionTitle title="Open questions" /><EvidenceList items={intelligence.open_questions} empty="No cited open questions." onSeek={onSeek} /></Card>
      <Card style={[styles.paneCard, styles.fullCard]}>
        <SectionTitle title="Topics" subtitle="A deterministic projection of cited topic intervals." />
        <View style={styles.topicGrid}>
          {intelligence.topics.map((topic) => (
            <View key={`${topic.parent ?? 'root'}-${topic.label}`} style={styles.topicCard}>
              <MaterialCommunityIcons name="tag-outline" size={17} color={colors.coralDark} />
              <View style={styles.topicCopy}>
                <Text style={styles.topicLabel}>{topic.label}</Text>
                {topic.parent ? <Text style={styles.topicParent}>under {topic.parent}</Text> : null}
              </View>
              {topic.evidence[0] ? <CitationChip citation={topic.evidence[0]} onPress={(citation) => onSeek(citation.start_ms)} /> : null}
            </View>
          ))}
        </View>
      </Card>
    </View>
  );
}

function EvidenceList({ items, empty, onSeek, kind }: { items: EvidenceItem[]; empty: string; onSeek(ms: number): void; kind?: 'action' }) {
  if (!items.length) return <Text style={styles.emptyInline}>{empty}</Text>;
  return (
    <View style={styles.evidenceList}>
      {items.map((item, index) => {
        const text = item.claim ?? item.decision ?? item.task ?? item.question ?? item.text ?? 'Unresolved item';
        return (
          <View key={item.id ?? `${text}-${index}`} style={styles.evidenceItem}>
            <View style={[styles.evidenceNumber, kind === 'action' && styles.evidenceNumberAction]}>
              <Text style={styles.evidenceNumberText}>{index + 1}</Text>
            </View>
            <View style={styles.evidenceCopy}>
              <Text style={styles.evidenceText}>{text}</Text>
              {kind === 'action' ? (
                <View style={styles.chipWrap}>
                  <Chip label={item.owner_text ? `Owner: ${item.owner_text}` : 'Owner unresolved'} />
                  <Chip label={item.due_text ? `Due: ${item.due_text}` : 'Date unresolved'} />
                  {item.status ? <Chip label={capitalize(item.status)} /> : null}
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

function CitationRow({ citations, onSeek }: { citations: Citation[]; onSeek(ms: number): void }) {
  return (
    <View style={styles.chipWrap}>
      {citations.map((citation) => (
        <CitationChip key={`${citation.segment_id}-${citation.start_ms}`} citation={citation} onPress={() => onSeek(citation.start_ms)} />
      ))}
      {!citations.length ? <Chip label="Unresolved · no supporting evidence" icon="alert-outline" /> : null}
    </View>
  );
}

function RecordingCostPane({ recordingId }: { recordingId: string }) {
  const resource = useResource(() => api.costs(recordingId), [recordingId]);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<Error>();
  if (resource.loading) return <Card><LoadingState label="Loading route and cost events…" /></Card>;
  if (resource.error || !resource.data) return <Card><ErrorState error={resource.error ?? new Error('Cost data is unavailable')} onRetry={resource.reload} /></Card>;
  const costs: CostSummary = resource.data;
  const exportJson = async () => {
    setExporting(true); setError(undefined);
    try {
      const result = await api.createExport({ format: 'json', resource: 'recording', recording_id: recordingId });
      if (result.download_url) await downloadUrl(result.download_url, result.filename);
      else if (result.content !== undefined) await downloadText(result.content, result.filename, result.content_type);
      else throw new Error('The export completed without downloadable content.');
    } catch (caught) { setError(asError(caught)); } finally { setExporting(false); }
  };
  return (
    <View style={styles.primaryColumn}>
      {error ? <Notice tone="error" title="Export failed">{error.message}</Notice> : null}
      <View style={styles.costMetrics}>
        <Card style={styles.costMetric}><Text style={styles.costMetricLabel}>Estimated incurred</Text><Text style={styles.costMetricValue}>{formatMoney(costs.estimated_incurred_usd)}</Text></Card>
        <Card style={styles.costMetric}><Text style={styles.costMetricLabel}>Reconciled</Text><Text style={styles.costMetricValue}>{formatMoney(costs.reconciled_usd)}</Text></Card>
        <Card style={styles.costMetric}><Text style={styles.costMetricLabel}>Modeled scenario delta</Text><Text style={styles.costMetricValue}>{formatMoney(costs.modeled_delta_usd)}</Text></Card>
      </View>
      <Notice tone="info" title="A modeled delta is not incurred savings">
        The finite baseline must produce the same required assets and pass the same quality gate. Fixed platform cost remains separate.
      </Notice>
      <Card style={styles.paneCard}>
        <SectionTitle title="Attempt-level ledger" subtitle={`${costs.events.length} billed or reusable operations`} action={<Button size="sm" variant="secondary" icon="download-outline" loading={exporting} onPress={exportJson}>JSON</Button>} />
        {costs.events.map((event) => (
          <View key={event.id} style={styles.costEvent}>
            <View style={styles.costRoute}><Text style={styles.routeAlias}>{event.model_alias}</Text><Text style={styles.routeStage}>{event.stage}</Text></View>
            <View style={styles.eventFlags}>{event.cached || event.reused ? <Chip label={event.reused ? 'Reused' : 'Cache hit'} /> : null}</View>
            <Text style={styles.billedUnits}>{event.billed_units}</Text>
            <Text style={styles.eventCost}>{formatMoney(event.reconciled_cost_usd ?? event.estimated_cost_usd)}</Text>
          </View>
        ))}
        {!costs.events.length ? <Text style={styles.emptyInline}>No paid or reuse events have been recorded.</Text> : null}
      </Card>
    </View>
  );
}

function labelSpeaker(segment: TranscriptSegment) {
  const cluster = segment.speaker_cluster_id;
  if (!cluster) return 'Speaker unresolved';
  const anonymousLabel = /^speaker[-_\s]+(.+)$/i.exec(cluster)?.[1];
  return anonymousLabel ? `Speaker ${anonymousLabel.toUpperCase()}` : `Speaker ${cluster}`;
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error('Something went wrong');
}

function capitalize(value: string): string {
  return value.replace(/_/g, ' ').replace(/^./, (letter) => letter.toUpperCase());
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: spacing.xl, flexWrap: 'wrap' },
  headerCopy: { flex: 1, minWidth: 260, gap: spacing.sm },
  titleLine: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flexWrap: 'wrap' },
  title: { color: colors.ink, fontFamily: font.medium, fontSize: 31, lineHeight: 37, letterSpacing: -0.9 },
  metadata: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  meta: { color: colors.inkMuted, fontSize: 11 },
  dot: { width: 3, height: 3, borderRadius: 2, backgroundColor: colors.borderStrong },
  headerActions: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  readinessCard: { gap: spacing.lg, shadowOpacity: 0 },
  assetGrid: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  asset: { flex: 1, minWidth: 150, flexDirection: 'row', alignItems: 'center', gap: spacing.sm, position: 'relative' },
  assetIcon: { width: 36, height: 36, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.surfaceMuted },
  assetIconReady: { backgroundColor: colors.green },
  assetIconActive: { backgroundColor: colors.blueSoft },
  assetCopy: { flex: 1, gap: 2 },
  assetTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 11 },
  assetState: { color: colors.inkFaint, fontSize: 9 },
  assetStateReady: { color: colors.green },
  assetStateActive: { color: colors.blue },
  assetConnector: { position: 'absolute', height: 1, backgroundColor: colors.border, right: -4, width: 9 },
  assetConnectorReady: { backgroundColor: colors.green },
  checksumRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap', paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  checksumLabel: { color: colors.green, fontFamily: font.medium, fontSize: 8, letterSpacing: 0.8 },
  checksumValue: { flex: 1, minWidth: 180, color: colors.inkMuted, fontFamily: font.mono, fontSize: 9 },
  tabs: { flexDirection: 'row', flexWrap: 'wrap', columnGap: spacing.xl, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: { paddingHorizontal: 2, paddingVertical: 13, borderBottomWidth: 2, borderBottomColor: 'transparent' },
  tabActive: { borderBottomColor: colors.coral },
  tabText: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 13 },
  tabTextActive: { color: colors.ink },
  detailColumns: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xl },
  detailColumnsNarrow: { flexDirection: 'column' },
  primaryColumn: { flex: 1, width: '100%', minWidth: 0, gap: spacing.xl },
  secondaryColumn: { width: '100%', maxWidth: 360, gap: spacing.xl },
  paneCard: { gap: spacing.xl },
  summary: { color: colors.ink, fontFamily: font.medium, fontSize: 19, lineHeight: 29, letterSpacing: -0.25 },
  bodyText: { color: colors.inkMuted, fontSize: 14, lineHeight: 23 },
  chipWrap: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  evidenceList: { gap: spacing.lg },
  evidenceItem: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md },
  evidenceNumber: { width: 26, height: 26, borderRadius: 9, backgroundColor: colors.pineSoft, alignItems: 'center', justifyContent: 'center' },
  evidenceNumberAction: { backgroundColor: colors.coralSoft },
  evidenceNumberText: { color: colors.pine, fontFamily: font.medium, fontSize: 10 },
  evidenceCopy: { flex: 1, gap: spacing.sm },
  evidenceText: { color: colors.ink, fontSize: 14, lineHeight: 21 },
  emptyInline: { color: colors.inkFaint, fontSize: 13, fontStyle: 'italic', paddingVertical: spacing.lg },
  transcriptList: { gap: 0 },
  segment: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md, paddingVertical: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  timestampButton: { width: 62, paddingTop: 2, flexDirection: 'row', alignItems: 'center', gap: 3 },
  timestamp: { color: colors.blue, fontFamily: font.mono, fontSize: 10 },
  segmentBody: { flex: 1, gap: spacing.sm },
  segmentHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  speakerName: { color: colors.coralDark, fontFamily: font.medium, fontSize: 11 },
  segmentText: { color: colors.ink, fontSize: 15, lineHeight: 24 },
  editArea: { gap: spacing.sm },
  editActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
  speakerEditor: { gap: spacing.sm, paddingBottom: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  speakerEditorLabel: { color: colors.ink, fontFamily: font.medium, fontSize: 12 },
  segmentCount: { color: colors.inkFaint, fontSize: 9 },
  intelligenceGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xl },
  fullCard: { width: '100%' },
  topicGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  topicCard: { flex: 1, minWidth: 240, padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.canvas, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  topicCopy: { flex: 1, gap: 2 },
  topicLabel: { color: colors.ink, fontFamily: font.medium, fontSize: 12 },
  topicParent: { color: colors.inkFaint, fontSize: 9 },
  costMetrics: { flexDirection: 'row', gap: spacing.lg, flexWrap: 'wrap' },
  costMetric: { flex: 1, minWidth: 190, gap: spacing.sm, shadowOpacity: 0 },
  costMetricLabel: { color: colors.inkMuted, fontSize: 11 },
  costMetricValue: { color: colors.ink, fontFamily: font.medium, fontSize: 25, letterSpacing: -0.6 },
  costEvent: { minHeight: 62, flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, flexWrap: 'wrap' },
  costRoute: { flex: 1, minWidth: 150, gap: 3 },
  routeAlias: { color: colors.ink, fontFamily: font.mono, fontSize: 11 },
  routeStage: { color: colors.inkMuted, fontSize: 10 },
  eventFlags: { flexDirection: 'row', gap: 5 },
  billedUnits: { color: colors.inkMuted, fontFamily: font.mono, fontSize: 10 },
  eventCost: { width: 70, color: colors.ink, fontFamily: font.medium, fontSize: 12, textAlign: 'right' },
});
