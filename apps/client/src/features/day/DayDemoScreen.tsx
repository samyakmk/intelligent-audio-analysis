import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import type { ComponentProps, ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import { Button, Card, ErrorState, Input, Notice, ProgressBar } from '@/components/ui';
import { useResource } from '@/hooks/useResource';
import { api } from '@/lib/api';
import { formatBytes, formatDuration } from '@/lib/format';
import { colors, font, radius, spacing } from '@/theme';
import type { DayBatch, DayChange, DayMemory, DayMemoryItem } from '@/types/api';

import {
  asksThroughWatermark,
  changesThroughBatch,
  currentMemory,
  dayStageLabel,
  memorySummary,
  revisionVerb,
  snapshotMemory,
  snapshotWatermark,
  stageProgress,
  visibleBatch,
} from './presentation';

const AUTO_STEP_MS = 1_050;
type SnapshotTab = 'overview' | 'decisions' | 'todos' | 'mindmap';

export default function DayDemoScreen() {
  const params = useLocalSearchParams<{ id: string }>();
  const recordingId = Array.isArray(params.id) ? params.id[0] : params.id;
  const router = useRouter();
  const { width } = useWindowDimensions();
  const compact = width < 820;
  const resource = useResource(() => api.daySession(recordingId ?? ''), [recordingId]);
  const [autoRun, setAutoRun] = useState(true);
  const [advancing, setAdvancing] = useState(false);
  const [asking, setAsking] = useState(false);
  const [question, setQuestion] = useState('');
  const [actionError, setActionError] = useState<Error>();
  const [selectedBatchIndex, setSelectedBatchIndex] = useState<number | null>(null);
  const [snapshotTab, setSnapshotTab] = useState<SnapshotTab>('overview');
  const session = resource.data;

  const advance = useCallback(async () => {
    if (!session || advancing || session.status === 'complete' || session.status === 'failed') return;
    setAdvancing(true);
    setActionError(undefined);
    try {
      resource.setData(await api.advanceDay(session.recording_id, session.revision));
    } catch (caught) {
      setAutoRun(false);
      setActionError(caught instanceof Error ? caught : new Error('The next pipeline stage could not run'));
    } finally {
      setAdvancing(false);
    }
  }, [advancing, resource, session]);

  useEffect(() => {
    if (!autoRun || !session || advancing || session.status === 'complete' || session.status === 'failed') return;
    const timer = setTimeout(() => void advance(), AUTO_STEP_MS);
    return () => clearTimeout(timer);
  }, [advance, advancing, autoRun, session]);

  const ask = async (value = question) => {
    const trimmed = value.trim();
    if (!session || !trimmed || asking) return;
    setQuestion('');
    setAsking(true);
    setActionError(undefined);
    try {
      await api.askDay(
        session.recording_id,
        trimmed,
        selectedBatchIndex === null ? undefined : selectedBatchIndex,
      );
      // The pipeline may publish while Ask is running. Reload instead of
      // merging into a stale client snapshot so a newer watermark is never hidden.
      resource.setData(await api.daySession(session.recording_id));
    } catch (caught) {
      setActionError(caught instanceof Error ? caught : new Error('Ask could not answer this question'));
    } finally {
      setAsking(false);
    }
  };

  const restart = async () => {
    if (!session || advancing) return;
    setAdvancing(true);
    setActionError(undefined);
    try {
      resource.setData(await api.resetDay(session.recording_id, session.revision));
      setSelectedBatchIndex(null);
      setAutoRun(true);
    } catch (caught) {
      setActionError(caught instanceof Error ? caught : new Error('The simulation could not restart'));
    } finally {
      setAdvancing(false);
    }
  };

  if (resource.loading) {
    return <AppShell><View style={styles.loading}><ActivityIndicator size="large" color={colors.coral} /><Text style={styles.muted}>Preparing the day timeline…</Text></View></AppShell>;
  }
  if (resource.error || !session) {
    return <AppShell><Card><ErrorState error={resource.error ?? new Error('Day session not found')} onRetry={resource.reload} /></Card></AppShell>;
  }

  const active = visibleBatch(session);
  const selectedBatch = selectedBatchIndex === null
    ? undefined
    : session.batches.find((batch) => batch.index === selectedBatchIndex && batch.status === 'complete');
  const displayedBatch = selectedBatch ?? active;
  const displayedMemory = snapshotMemory(session, selectedBatch?.index ?? null);
  const displayedWatermark = snapshotWatermark(session, selectedBatch?.index ?? null);
  const displayedChanges = changesThroughBatch(session, selectedBatch?.index ?? null);
  const displayedAsks = asksThroughWatermark(session, displayedWatermark);
  const displayedBatchCount = selectedBatch ? selectedBatch.index + 1 : session.processed_batch_count;
  const historical = Boolean(selectedBatch);
  const complete = session.status === 'complete';

  return (
    <AppShell>
      <View style={styles.hero}>
        <View style={styles.heroCopy}>
          <Pressable accessibilityRole="link" onPress={() => router.push('/results')} style={styles.backLink}>
            <MaterialCommunityIcons name="arrow-left" size={15} color={colors.inkMuted} />
            <Text style={styles.backText}>All runs</Text>
          </Pressable>
          <Text style={styles.eyebrow}>CONTINUOUS DAY · ARCHITECTURE SIMULATION</Text>
          <Text accessibilityRole="header" style={styles.title}>{session.title}</Text>
          {session.description ? <Text style={styles.subtitle}>{session.description}</Text> : null}
        </View>
        <View style={styles.heroActions}>
          <Button
            variant={autoRun ? 'secondary' : 'primary'}
            icon={autoRun ? 'pause' : 'play'}
            disabled={complete || session.status === 'failed'}
            onPress={() => setAutoRun((value) => !value)}
          >
            {autoRun ? 'Pause simulation' : 'Resume simulation'}
          </Button>
          <Button variant="ghost" icon="restart" loading={advancing && !autoRun} onPress={() => void restart()}>Restart</Button>
        </View>
      </View>

      <Notice tone="info" title="How to read this demo">{session.notice ?? 'Each batch is processed without access to future batches. Published memory can be revised when later evidence arrives.'}</Notice>
      {actionError ? <Notice tone="error" title="Simulation paused">{actionError.message}</Notice> : null}
      {session.error ? <Notice tone="error" title="Pipeline stopped">{session.error.message}</Notice> : null}

      <Card style={styles.overview}>
        <View style={styles.metrics}>
          <Metric label={historical ? 'BATCHES IN SNAPSHOT' : 'BATCHES PUBLISHED'} value={`${displayedBatchCount} / ${session.batch_count}`} />
          <Metric label="ASK-READY THROUGH" value={formatDuration(displayedWatermark)} />
          <Metric label={historical ? 'VIEWING' : 'CURRENT REVISION'} value={historical ? `Batch ${selectedBatch!.number}` : `r${session.revision}`} />
          <Metric label="PIPELINE STATE" value={historical ? 'Historical snapshot' : dayStageLabel(session.current_stage)} accent />
        </View>
        <ProgressBar value={historical ? (displayedBatchCount / session.batch_count) * 100 : stageProgress(session)} tone="pine" />
        <Text style={styles.progressCaption}>
          {historical
            ? `Frozen at Batch ${selectedBatch!.number}. Processing ${complete ? 'is complete' : 'continues independently'}; this view will not drift.`
            : complete
              ? 'All batches are published. Click any batch to inspect its historical snapshot.'
              : `${autoRun ? 'Auto-running' : 'Paused'} · next stage advances independently, like the next worker checkpoint.`}
        </Text>
      </Card>

      <View style={styles.snapshotSelector}>
        <View style={styles.selectorHeading}>
          <View style={styles.selectorCopy}>
            <Text style={styles.sectionKicker}>TIME-TRAVEL SNAPSHOTS</Text>
            <Text style={styles.selectorTitle}>Choose a published batch</Text>
            <Text style={styles.selectorBody}>Everything below—overview, decisions, to-dos, map, history, memory, and Ask—rewinds to that publish point.</Text>
          </View>
          {historical ? <Button size="sm" icon="update" onPress={() => setSelectedBatchIndex(null)}>Follow latest</Button> : <Text style={styles.liveLabel}>● LIVE</Text>}
        </View>
        <View style={styles.batchRail} accessibilityRole="list">
          {session.batches.map((batch) => (
            <BatchCard
              key={batch.id}
              batch={batch}
              active={!historical && batch.id === active?.id}
              selected={batch.index === selectedBatch?.index}
              onSelect={() => setSelectedBatchIndex(batch.index)}
            />
          ))}
        </View>
      </View>

      <SnapshotExplorer
        batch={selectedBatch}
        batchCount={displayedBatchCount}
        memory={displayedMemory}
        tab={snapshotTab}
        watermarkMs={displayedWatermark}
        onTab={setSnapshotTab}
      />

      <View style={[styles.twoColumn, compact && styles.oneColumn]}>
        <View style={styles.primaryColumn}>
          <Card style={styles.pipelineCard}>
            <View style={styles.sectionHeading}>
              <View>
                <Text style={styles.sectionKicker}>LIVE PIPELINE OUTPUT</Text>
                <Text style={styles.sectionTitle}>{displayedBatch ? `Batch ${displayedBatch.number} · ${dayStageLabel(displayedBatch.stage)}` : 'Waiting for batch'}</Text>
              </View>
              {!historical && advancing ? <ActivityIndicator color={colors.coral} /> : !historical && !complete ? <Button size="sm" variant="secondary" icon="step-forward" disabled={advancing} onPress={() => void advance()}>Advance one stage</Button> : null}
            </View>
            {displayedBatch ? <BatchOutput batch={displayedBatch} /> : null}
          </Card>

          <Card style={styles.historyCard}>
            <View style={styles.sectionHeading}>
              <View>
                <Text style={styles.sectionKicker}>TEMPORAL CHANGE LOG</Text>
                <Text style={styles.sectionTitle}>What changed, and why</Text>
              </View>
              <Text style={styles.count}>{displayedChanges.length}</Text>
            </View>
            {!displayedChanges.length ? <Text style={styles.emptyCopy}>Changes appear only when a batch is published.</Text> : (
              <View style={styles.changeList}>
                {[...displayedChanges].reverse().map((change) => <ChangeRow key={`${change.id}-${change.batch_index}`} change={change} />)}
              </View>
            )}
          </Card>
        </View>

        <View style={styles.sideColumn}>
          <Card style={styles.askCard}>
            <View style={styles.askMark}><MaterialCommunityIcons name="comment-question-outline" size={22} color={colors.white} /></View>
            <View style={styles.askHeading}>
              <Text style={styles.askKicker}>{historical ? `ASK BATCH ${selectedBatch!.number} SNAPSHOT` : 'ASK THE DAY SO FAR'}</Text>
              <Text style={styles.askTitle}>Answers obey the watermark</Text>
              <Text style={styles.askBody}>{historical ? `Questions are answered only from evidence available through ${formatDuration(displayedWatermark)}.` : 'Ask never sees queued batches. Re-ask after a later publish to watch the answer and citations change.'}</Text>
            </View>
            <View style={styles.suggestions}>
              {session.suggested_questions.slice(0, 3).map((suggestion) => (
                <Pressable key={suggestion} accessibilityRole="button" onPress={() => void ask(suggestion)} style={({ pressed }) => [styles.suggestion, pressed && styles.pressed]}>
                  <Text style={styles.suggestionText}>{suggestion}</Text>
                  <MaterialCommunityIcons name="arrow-up-right" size={14} color={colors.pine} />
                </Pressable>
              ))}
            </View>
            <Input
              value={question}
              multiline
              placeholder={displayedWatermark ? `Ask about 0:00–${formatDuration(displayedWatermark)}…` : 'Ask now to see a grounded abstention…'}
              onChangeText={setQuestion}
              onSubmitEditing={() => void ask()}
            />
            <Button icon="send" loading={asking} disabled={!question.trim()} onPress={() => void ask()}>Ask current memory</Button>
            <View style={styles.answers}>
              {[...displayedAsks].reverse().map((message) => (
                <View key={message.id} style={styles.answer}>
                  <Text style={styles.answerQuestion}>{message.question}</Text>
                  <Text style={styles.answerText}>{message.answer}</Text>
                  <View style={styles.answerMeta}>
                    <Text style={[styles.provisional, !message.provisional && styles.final]}>● {message.abstained ? 'ABSTAINED' : message.provisional ? 'PROVISIONAL' : 'FINAL'}</Text>
                    <Text style={styles.watermark}>through {formatDuration(message.watermark_ms)}</Text>
                  </View>
                  {message.citations.map((citation) => (
                    <Text key={citation.segment_id} style={styles.citation}>↳ {formatDuration(citation.start_ms)}–{formatDuration(citation.end_ms)} · “{citation.quote}”</Text>
                  ))}
                </View>
              ))}
            </View>
          </Card>

          <MemoryCard memory={displayedMemory} label={historical ? `Batch ${selectedBatch!.number} memory` : 'Current day memory'} />
        </View>
      </View>
    </AppShell>
  );
}

function SnapshotExplorer({
  batch,
  batchCount,
  memory,
  tab,
  watermarkMs,
  onTab,
}: {
  batch?: DayBatch;
  batchCount: number;
  memory: DayMemory;
  tab: SnapshotTab;
  watermarkMs: number;
  onTab(tab: SnapshotTab): void;
}) {
  const current = currentMemory(memory);
  const decisions = current.filter((item) => item.kind === 'decision');
  const actions = current.filter((item) => item.kind === 'action');
  const facts = current.filter((item) => item.kind === 'fact');
  const questions = current.filter((item) => item.kind === 'open_question');
  const tabs: { id: SnapshotTab; label: string; icon: ComponentProps<typeof MaterialCommunityIcons>['name'] }[] = [
    { id: 'overview', label: 'Overview', icon: 'view-dashboard-outline' },
    { id: 'decisions', label: 'Decisions', icon: 'gavel' },
    { id: 'todos', label: "To-do's", icon: 'checkbox-marked-circle-outline' },
    { id: 'mindmap', label: 'Mind map', icon: 'graph-outline' },
  ];
  return (
    <Card style={styles.explorer}>
      <View style={styles.explorerHeading}>
        <View>
          <Text style={styles.sectionKicker}>PUBLISHED ARTIFACTS</Text>
          <Text style={styles.sectionTitle}>{batch ? `As of Batch ${batch.number}` : 'Latest published state'}</Text>
        </View>
        <Text style={styles.snapshotStamp}>{`${batchCount} ${batchCount === 1 ? 'batch' : 'batches'} · through ${formatDuration(watermarkMs)}`}</Text>
      </View>
      <View style={styles.snapshotTabs} accessibilityRole="tablist">
        {tabs.map((item) => (
          <Pressable
            key={item.id}
            accessibilityRole="tab"
            accessibilityState={{ selected: tab === item.id }}
            onPress={() => onTab(item.id)}
            style={[styles.snapshotTab, tab === item.id && styles.snapshotTabActive]}
          >
            <MaterialCommunityIcons name={item.icon} size={16} color={tab === item.id ? colors.pine : colors.inkMuted} />
            <Text style={[styles.snapshotTabText, tab === item.id && styles.snapshotTabTextActive]}>{item.label}</Text>
          </Pressable>
        ))}
      </View>
      {tab === 'overview' ? (
        <View style={styles.snapshotPane}>
          <Text style={styles.snapshotSummary}>{memorySummary(memory)}</Text>
          <View style={styles.snapshotStats}>
            <SnapshotStat label="Decisions" value={decisions.length} />
            <SnapshotStat label="To-do's" value={actions.length} />
            <SnapshotStat label="Facts" value={facts.length} />
            <SnapshotStat label="Questions" value={questions.length} />
          </View>
          <View style={styles.overviewColumns}>
            <SnapshotItemList title="Key decisions" items={decisions.slice(0, 3)} empty="No decisions yet." />
            <SnapshotItemList title="Active to-do's" items={actions.slice(0, 3)} empty="No to-do's yet." />
          </View>
        </View>
      ) : null}
      {tab === 'decisions' ? <SnapshotItemList title="Decisions at this point" items={decisions} empty="No decisions had been published by this batch." roomy /> : null}
      {tab === 'todos' ? <SnapshotItemList title="To-do's at this point" items={actions} empty="No to-do's had been published by this batch." roomy /> : null}
      {tab === 'mindmap' ? <SnapshotMindMap memory={memory} /> : null}
    </Card>
  );
}

function SnapshotStat({ label, value }: { label: string; value: number }) {
  return <View style={styles.snapshotStat}><Text style={styles.snapshotStatValue}>{value}</Text><Text style={styles.snapshotStatLabel}>{label}</Text></View>;
}

function SnapshotItemList({ title, items, empty, roomy = false }: { title: string; items: DayMemoryItem[]; empty: string; roomy?: boolean }) {
  return (
    <View style={[styles.snapshotList, roomy && styles.snapshotListRoomy]}>
      <Text style={styles.snapshotListTitle}>{title}</Text>
      {!items.length ? <Text style={styles.emptyCopy}>{empty}</Text> : items.map((item) => (
        <View key={item.id} style={styles.snapshotItem}>
          <View style={[styles.snapshotItemDot, item.status === 'resolved' && styles.snapshotItemDotResolved]} />
          <View style={styles.snapshotItemCopy}>
            <Text style={styles.snapshotItemMeta}>BATCH {item.effective_batch + 1} · {item.status}</Text>
            <Text style={styles.snapshotItemText}>{item.text}</Text>
            {item.owner ? <Text style={styles.ownerText}>Owner: {item.owner}{item.due ? ` · ${item.due}` : ''}</Text> : null}
            {item.evidence[0] ? <Text style={styles.snapshotEvidence}>Source {formatDuration(item.evidence[0].start_ms)}–{formatDuration(item.evidence[0].end_ms)}</Text> : null}
          </View>
        </View>
      ))}
    </View>
  );
}

function SnapshotMindMap({ memory }: { memory: DayMemory }) {
  const groups = [
    { label: 'Decisions', icon: 'gavel' as const, items: currentMemory(memory).filter((item) => item.kind === 'decision') },
    { label: "To-do's", icon: 'checkbox-marked-circle-outline' as const, items: currentMemory(memory).filter((item) => item.kind === 'action') },
    { label: 'Facts', icon: 'lightbulb-outline' as const, items: currentMemory(memory).filter((item) => item.kind === 'fact') },
    { label: 'Questions', icon: 'help-circle-outline' as const, items: currentMemory(memory).filter((item) => item.kind === 'open_question') },
  ].filter((group) => group.items.length);
  if (!groups.length) return <Text style={styles.emptyCopy}>The map appears after the first memory item is published.</Text>;
  return (
    <View style={styles.mapPane} accessibilityLabel={`Snapshot mind map with ${groups.length} branches`}>
      <View style={styles.mapRoot}>
        <MaterialCommunityIcons name="hub-outline" size={20} color={colors.white} />
        <View style={styles.mapRootCopy}><Text style={styles.mapRootLabel}>Day memory</Text><Text style={styles.mapRootSummary}>{memorySummary(memory)}</Text></View>
      </View>
      <View style={styles.mapTrunk} />
      <View style={styles.mapBranches}>
        {groups.map((group) => (
          <View key={group.label} style={styles.mapBranch}>
            <View style={styles.mapBranchTitle}><MaterialCommunityIcons name={group.icon} size={15} color={colors.pine} /><Text style={styles.mapBranchLabel}>{group.label}</Text></View>
            {group.items.map((item) => <View key={item.id} style={styles.mapLeaf}><View style={styles.mapLeafDot} /><Text style={styles.mapLeafText}>{item.text}</Text></View>)}
          </View>
        ))}
      </View>
    </View>
  );
}

function Metric({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <View style={styles.metric}><Text style={styles.metricLabel}>{label}</Text><Text style={[styles.metricValue, accent && styles.metricAccent]}>{value}</Text></View>;
}

function BatchCard({ batch, active, selected, onSelect }: { batch: DayBatch; active: boolean; selected: boolean; onSelect(): void }) {
  const queued = batch.status === 'queued';
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={queued ? `Batch ${batch.number} has not been published` : `View Batch ${batch.number} snapshot`}
      accessibilityState={{ disabled: queued, selected }}
      disabled={queued}
      onPress={onSelect}
      style={({ pressed }) => [styles.batchCard, active && styles.batchCardActive, batch.status === 'complete' && styles.batchCardComplete, selected && styles.batchCardSelected, pressed && styles.pressed]}
    >
      <View style={styles.batchTop}>
        <View style={[styles.batchNumber, batch.status === 'complete' && styles.batchNumberComplete]}>
          {batch.status === 'complete' ? <MaterialCommunityIcons name="check" size={14} color={colors.white} /> : <Text style={styles.batchNumberText}>{batch.number}</Text>}
        </View>
        <Text style={styles.batchTime}>{formatDuration(batch.start_ms)}–{formatDuration(batch.end_ms)}</Text>
      </View>
      <Text style={styles.batchState}>{selected ? 'Viewing snapshot' : queued ? 'Not arrived yet' : dayStageLabel(batch.stage)}</Text>
      <Text style={styles.batchSize}>{batch.size_bytes ? formatBytes(batch.size_bytes) : 'logical slice'}</Text>
    </Pressable>
  );
}

function BatchOutput({ batch }: { batch: DayBatch }) {
  const speechProvider = batch.provider?.speech;
  const intelligenceProvider = batch.provider?.intelligence;
  return (
    <View style={styles.outputStack}>
      {batch.transcript.length ? (
        <OutputBlock icon="text-box-outline" title="1 · Transcript" complete={batch.stage !== 'transcribing'}>
          {speechProvider ? <ProviderTrace label="Gemini speech" provenance={speechProvider} /> : null}
          {batch.transcript.map((segment) => (
            <View key={segment.id} style={styles.transcriptRow}>
              <Text style={styles.timecode}>{formatDuration(segment.start_ms)}</Text>
              <View style={styles.transcriptCopy}><Text style={styles.speaker}>{segment.speaker_name ?? segment.speaker_id ?? 'Speaker'}</Text><Text style={styles.transcriptText}>{segment.text}</Text></View>
            </View>
          ))}
        </OutputBlock>
      ) : <OutputBlock icon="text-box-outline" title="1 · Transcript"><Text style={styles.emptyCopy}>Waiting for this batch to arrive.</Text></OutputBlock>}

      {batch.reconciliation.boundary_revision ? (
        <OutputBlock icon="vector-link" title="2 · Boundary reconciliation" complete={batch.stage !== 'reconciling'}>
          <Text style={styles.outputText}>{batch.reconciliation.boundary_revision}</Text>
          <Text style={styles.outputMeta}>{batch.reconciliation.context_segments_used ?? 0} prior-tail segment · {(batch.reconciliation.speaker_clusters_carried ?? []).length} speaker identities carried</Text>
        </OutputBlock>
      ) : null}

      {batch.index_state.evidence_chunks !== undefined ? (
        <OutputBlock icon="database-search-outline" title="3 · Retrieval index" complete={batch.stage !== 'indexing'}>
          <View style={styles.indexGrid}>
            <MiniStat value={batch.index_state.evidence_chunks} label="evidence chunks" />
            <MiniStat value={batch.index_state.lexical_terms} label="lexical terms" />
            <MiniStat value={batch.index_state.vector_embeddings} label="embeddings" />
            <MiniStat value={batch.index_state.neighbor_links} label="neighbor links" />
          </View>
        </OutputBlock>
      ) : null}

      {batch.pending_changes.length ? (
        <OutputBlock icon="source-branch" title="4 · Proposed memory mutations" complete={batch.stage === 'published'}>
          {intelligenceProvider ? <ProviderTrace label="Gemini intelligence" provenance={intelligenceProvider} /> : null}
          {batch.pending_changes.map((change) => <ChangeRow key={change.id} change={change} preview />)}
        </OutputBlock>
      ) : null}

      {batch.status === 'complete' ? (
        <OutputBlock icon="check-decagram-outline" title="5 · Atomic publish" complete>
          <Text style={styles.outputText}>Transcript, retrieval evidence, current memory, and revision history became visible together.</Text>
        </OutputBlock>
      ) : null}
    </View>
  );
}

function ProviderTrace({ label, provenance }: { label: string; provenance: { provider?: string; model_alias?: string; resolved_model?: string } }) {
  return (
    <View style={styles.providerTrace}>
      <MaterialCommunityIcons name="creation-outline" size={14} color={colors.pine} />
      <Text style={styles.providerTraceText}>{label} · {provenance.resolved_model ?? provenance.model_alias ?? provenance.provider}</Text>
    </View>
  );
}

function OutputBlock({ icon, title, complete = false, children }: { icon: ComponentProps<typeof MaterialCommunityIcons>['name']; title: string; complete?: boolean; children: ReactNode }) {
  return (
    <View style={styles.outputBlock}>
      <View style={styles.outputHeader}>
        <MaterialCommunityIcons name={icon} size={17} color={complete ? colors.green : colors.coral} />
        <Text style={styles.outputTitle}>{title}</Text>
        <Text style={[styles.outputStatus, complete && styles.outputStatusComplete]}>{complete ? 'DONE' : 'ACTIVE'}</Text>
      </View>
      {children}
    </View>
  );
}

function MiniStat({ value, label }: { value?: number; label: string }) {
  return <View style={styles.miniStat}><Text style={styles.miniValue}>{value ?? 0}</Text><Text style={styles.miniLabel}>{label}</Text></View>;
}

function ChangeRow({ change, preview = false }: { change: DayChange; preview?: boolean }) {
  return (
    <View style={styles.changeRow}>
      <Text style={[styles.changeVerb, change.operation === 'supersede' && styles.changeVerbRevised]}>{preview ? 'PROPOSED' : revisionVerb(change.operation)}</Text>
      <View style={styles.changeCopy}>
        <Text style={styles.changeKind}>Batch {change.batch_index + 1} · {change.kind.replace('_', ' ')}</Text>
        {change.before ? <Text style={styles.beforeText}>{change.before}</Text> : null}
        <Text style={styles.afterText}>{change.after}</Text>
        {change.owner_before || change.owner_after ? <Text style={styles.ownerText}>Owner: {change.owner_before ?? 'unassigned'} → {change.owner_after ?? 'unassigned'}</Text> : null}
      </View>
    </View>
  );
}

function MemoryCard({ memory, label }: { memory: DayMemory; label: string }) {
  const items = useMemo(() => currentMemory(memory), [memory]);
  return (
    <Card style={styles.memoryCard}>
      <Text style={styles.sectionKicker}>{label.toUpperCase()}</Text>
      <Text style={styles.memorySummary}>{memorySummary(memory)}</Text>
      {!items.length ? <Text style={styles.emptyCopy}>The canonical memory is empty until the first batch publishes.</Text> : (
        <View style={styles.memoryList}>{items.map((item) => <MemoryRow key={item.id} item={item} />)}</View>
      )}
      <Text style={styles.memoryFootnote}>Superseded values stay in the change log but are excluded from current Ask context.</Text>
    </Card>
  );
}

function MemoryRow({ item }: { item: DayMemoryItem }) {
  return (
    <View style={styles.memoryRow}>
      <View style={styles.memoryIcon}><MaterialCommunityIcons name={item.kind === 'action' ? 'checkbox-marked-circle-outline' : item.kind === 'decision' ? 'gavel' : item.kind === 'open_question' ? 'help-circle-outline' : 'lightbulb-outline'} size={15} color={colors.pine} /></View>
      <View style={styles.memoryCopy}>
        <Text style={styles.memoryKind}>{item.kind.replace('_', ' ')} · BATCH {item.effective_batch + 1} · {item.status}</Text>
        <Text style={styles.memoryText}>{item.text}</Text>
        {item.owner ? <Text style={styles.ownerText}>Owner: {item.owner}{item.due ? ` · ${item.due}` : ''}</Text> : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  loading: { minHeight: 420, alignItems: 'center', justifyContent: 'center', gap: spacing.md },
  hero: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: spacing.xl, flexWrap: 'wrap' },
  heroCopy: { flex: 1, minWidth: 280, gap: spacing.sm },
  heroActions: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  backLink: { flexDirection: 'row', alignItems: 'center', gap: 4, alignSelf: 'flex-start' },
  backText: { color: colors.inkMuted, fontSize: 10 },
  eyebrow: { color: colors.coralDark, fontFamily: font.medium, fontSize: 9, letterSpacing: 1.2 },
  title: { color: colors.ink, fontFamily: font.medium, fontSize: 30, letterSpacing: -0.7 },
  subtitle: { maxWidth: 720, color: colors.inkMuted, fontSize: 12, lineHeight: 19 },
  muted: { color: colors.inkMuted, fontSize: 12 },
  overview: { gap: spacing.lg },
  metrics: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.lg },
  metric: { flex: 1, minWidth: 150, gap: 4 },
  metricLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 0.8 },
  metricValue: { color: colors.ink, fontFamily: font.mono, fontSize: 16 },
  metricAccent: { color: colors.coralDark },
  progressCaption: { color: colors.inkMuted, fontSize: 10 },
  snapshotSelector: { gap: spacing.md },
  selectorHeading: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: spacing.lg, flexWrap: 'wrap' },
  selectorCopy: { flex: 1, minWidth: 260, gap: 3 },
  selectorTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 18 },
  selectorBody: { maxWidth: 720, color: colors.inkMuted, fontSize: 10, lineHeight: 15 },
  liveLabel: { color: colors.green, fontFamily: font.mono, fontSize: 9, letterSpacing: 0.7 },
  batchRail: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  batchCard: { flex: 1, minWidth: 150, padding: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.surfaceMuted, gap: 5 },
  batchCardActive: { borderColor: colors.coral, backgroundColor: colors.coralSoft },
  batchCardComplete: { borderColor: colors.green, backgroundColor: colors.greenSoft },
  batchCardSelected: { borderWidth: 2, borderColor: colors.coral, backgroundColor: colors.coralSoft },
  batchTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  batchNumber: { width: 26, height: 26, borderRadius: 9, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.surface },
  batchNumberComplete: { backgroundColor: colors.green },
  batchNumberText: { color: colors.inkMuted, fontFamily: font.mono, fontSize: 10 },
  batchTime: { color: colors.inkMuted, fontFamily: font.mono, fontSize: 8 },
  batchState: { color: colors.ink, fontFamily: font.medium, fontSize: 10 },
  batchSize: { color: colors.inkFaint, fontSize: 8 },
  explorer: { gap: spacing.lg, borderColor: colors.borderStrong },
  explorerHeading: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between', gap: spacing.lg, flexWrap: 'wrap' },
  snapshotStamp: { color: colors.blue, fontFamily: font.mono, fontSize: 9 },
  snapshotTabs: { flexDirection: 'row', flexWrap: 'wrap', borderBottomWidth: 1, borderBottomColor: colors.border },
  snapshotTab: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: spacing.md, paddingVertical: spacing.md, borderBottomWidth: 2, borderBottomColor: 'transparent' },
  snapshotTabActive: { borderBottomColor: colors.coral },
  snapshotTabText: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 11 },
  snapshotTabTextActive: { color: colors.pine },
  snapshotPane: { gap: spacing.xl },
  snapshotSummary: { maxWidth: 820, color: colors.ink, fontFamily: font.medium, fontSize: 19, lineHeight: 28 },
  snapshotStats: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  snapshotStat: { flex: 1, minWidth: 110, padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.canvas, gap: 2 },
  snapshotStatValue: { color: colors.pine, fontFamily: font.mono, fontSize: 19 },
  snapshotStatLabel: { color: colors.inkMuted, fontSize: 9 },
  overviewColumns: { flexDirection: 'row', alignItems: 'flex-start', flexWrap: 'wrap', gap: spacing.xl },
  snapshotList: { flex: 1, minWidth: 260, gap: spacing.md },
  snapshotListRoomy: { width: '100%', maxWidth: 820, flex: 0 },
  snapshotListTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 13 },
  snapshotItem: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.canvas },
  snapshotItemDot: { width: 9, height: 9, marginTop: 4, borderRadius: radius.pill, backgroundColor: colors.coral },
  snapshotItemDotResolved: { backgroundColor: colors.green },
  snapshotItemCopy: { flex: 1, minWidth: 0, gap: 3 },
  snapshotItemMeta: { color: colors.inkFaint, fontFamily: font.mono, fontSize: 7, textTransform: 'uppercase' },
  snapshotItemText: { color: colors.ink, fontSize: 11, lineHeight: 17 },
  snapshotEvidence: { color: colors.blue, fontFamily: font.mono, fontSize: 7 },
  mapPane: { alignItems: 'center' },
  mapRoot: { width: '100%', maxWidth: 620, minHeight: 76, padding: spacing.lg, borderRadius: radius.lg, backgroundColor: colors.pine, flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  mapRootCopy: { flex: 1, gap: 3 },
  mapRootLabel: { color: colors.white, fontFamily: font.medium, fontSize: 14 },
  mapRootSummary: { color: colors.pineSoft, fontSize: 9, lineHeight: 14 },
  mapTrunk: { width: 2, height: spacing.xl, backgroundColor: colors.borderStrong },
  mapBranches: { width: '100%', flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'center', gap: spacing.md },
  mapBranch: { flex: 1, minWidth: 210, maxWidth: 400, padding: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.canvas, gap: spacing.sm },
  mapBranchTitle: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingBottom: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  mapBranchLabel: { color: colors.pine, fontFamily: font.medium, fontSize: 11 },
  mapLeaf: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  mapLeafDot: { width: 7, height: 7, marginTop: 4, borderRadius: radius.pill, backgroundColor: colors.coral },
  mapLeafText: { flex: 1, color: colors.ink, fontSize: 9, lineHeight: 14 },
  twoColumn: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xl },
  oneColumn: { flexDirection: 'column' },
  primaryColumn: { flex: 1.35, width: '100%', minWidth: 0, gap: spacing.xl },
  sideColumn: { flex: 1, width: '100%', minWidth: 0, gap: spacing.xl },
  pipelineCard: { gap: spacing.lg },
  historyCard: { gap: spacing.lg },
  sectionHeading: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md, flexWrap: 'wrap' },
  sectionKicker: { color: colors.coralDark, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  sectionTitle: { marginTop: 3, color: colors.ink, fontFamily: font.medium, fontSize: 17 },
  count: { minWidth: 28, height: 28, borderRadius: 14, textAlign: 'center', lineHeight: 28, backgroundColor: colors.surfaceMuted, color: colors.inkMuted, fontFamily: font.mono, fontSize: 10 },
  emptyCopy: { color: colors.inkMuted, fontSize: 10, lineHeight: 16 },
  outputStack: { gap: spacing.md },
  outputBlock: { padding: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.canvas, gap: spacing.md },
  providerTrace: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.sm, borderRadius: radius.sm, backgroundColor: colors.pineSoft },
  providerTraceText: { color: colors.pine, fontFamily: font.mono, fontSize: 8 },
  outputHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  outputTitle: { flex: 1, color: colors.ink, fontFamily: font.medium, fontSize: 11 },
  outputStatus: { color: colors.coralDark, fontFamily: font.mono, fontSize: 7 },
  outputStatusComplete: { color: colors.green },
  outputText: { color: colors.ink, fontSize: 10, lineHeight: 16 },
  outputMeta: { color: colors.inkMuted, fontFamily: font.mono, fontSize: 8 },
  transcriptRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  timecode: { width: 38, color: colors.blue, fontFamily: font.mono, fontSize: 8, paddingTop: 2 },
  transcriptCopy: { flex: 1, minWidth: 0, gap: 2 },
  speaker: { color: colors.coralDark, fontFamily: font.medium, fontSize: 8, textTransform: 'uppercase' },
  transcriptText: { color: colors.ink, fontSize: 10, lineHeight: 15 },
  indexGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  miniStat: { flex: 1, minWidth: 92, padding: spacing.sm, borderRadius: radius.sm, backgroundColor: colors.surface, gap: 2 },
  miniValue: { color: colors.pine, fontFamily: font.mono, fontSize: 15 },
  miniLabel: { color: colors.inkMuted, fontSize: 8 },
  changeList: { gap: spacing.sm },
  changeRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  changeVerb: { width: 58, color: colors.green, fontFamily: font.mono, fontSize: 7, paddingTop: 3 },
  changeVerbRevised: { color: colors.coralDark },
  changeCopy: { flex: 1, minWidth: 0, gap: 3 },
  changeKind: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, textTransform: 'uppercase' },
  beforeText: { color: colors.inkFaint, fontSize: 9, lineHeight: 14, textDecorationLine: 'line-through' },
  afterText: { color: colors.ink, fontSize: 10, lineHeight: 15 },
  ownerText: { color: colors.blue, fontSize: 8 },
  askCard: { gap: spacing.md, borderColor: colors.pine, backgroundColor: colors.pineSoft },
  askMark: { width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.pine },
  askHeading: { gap: 4 },
  askKicker: { color: colors.green, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  askTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 20 },
  askBody: { color: colors.inkMuted, fontSize: 10, lineHeight: 16 },
  suggestions: { gap: spacing.sm },
  suggestion: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.sm, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.sm, backgroundColor: colors.surface },
  suggestionText: { flex: 1, color: colors.pine, fontSize: 9, lineHeight: 13 },
  answers: { gap: spacing.md },
  answer: { paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.borderStrong, gap: spacing.sm },
  answerQuestion: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 9 },
  answerText: { color: colors.ink, fontSize: 11, lineHeight: 17 },
  answerMeta: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.sm },
  provisional: { color: colors.amber, fontFamily: font.mono, fontSize: 7 },
  final: { color: colors.green },
  watermark: { color: colors.inkFaint, fontFamily: font.mono, fontSize: 7 },
  citation: { color: colors.blue, fontSize: 8, lineHeight: 12 },
  memoryCard: { gap: spacing.md },
  memorySummary: { color: colors.ink, fontFamily: font.medium, fontSize: 13, lineHeight: 19 },
  memoryList: { gap: spacing.sm },
  memoryRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  memoryIcon: { width: 29, height: 29, borderRadius: 9, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.pineSoft },
  memoryCopy: { flex: 1, minWidth: 0, gap: 3 },
  memoryKind: { color: colors.inkFaint, fontFamily: font.mono, fontSize: 7, textTransform: 'uppercase' },
  memoryText: { color: colors.ink, fontSize: 10, lineHeight: 15 },
  memoryFootnote: { color: colors.inkFaint, fontSize: 8, lineHeight: 12 },
  pressed: { opacity: 0.7 },
});
