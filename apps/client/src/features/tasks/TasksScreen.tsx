import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import {
  Button,
  Card,
  Chip,
  CitationChip,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingState,
  Notice,
  PageTitle,
  Segmented,
  uiStyles,
} from '@/components/ui';
import { useResource } from '@/hooks/useResource';
import { api, unwrapItems } from '@/lib/api';
import { downloadText, downloadUrl } from '@/platform/download';
import { formatDate } from '@/lib/format';
import { useSession } from '@/providers/SessionProvider';
import { colors, font, radius, spacing } from '@/theme';
import type { ActionTask, ExportRequest, Recap, Topic } from '@/types/api';

type Tab = 'tasks' | 'insights';
type StatusFilter = 'all' | ActionTask['status'];

export default function TasksScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const { session } = useSession();
  const [tab, setTab] = useState<Tab>('tasks');
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<Error>();
  const [notice, setNotice] = useState<string>();
  const [recapKind, setRecapKind] = useState<'daily' | 'project'>('daily');
  const [project, setProject] = useState('');
  const [recap, setRecap] = useState<Recap>();
  const resource = useResource(() => api.tasks(), [session?.workspace.id]);
  const tasks = resource.data ? unwrapItems(resource.data) : [];
  const visibleTasks = filter === 'all' ? tasks : tasks.filter((task) => task.status === filter);

  const mutate = async (name: string, operation: () => Promise<unknown>, message: string) => {
    setBusy(name); setError(undefined); setNotice(undefined);
    try { await operation(); setNotice(message); await resource.reload(); }
    catch (caught) { setError(caught instanceof Error ? caught : new Error('Action failed')); }
    finally { setBusy(undefined); }
  };

  const generateRecap = async () => {
    setBusy('recap'); setError(undefined); setNotice(undefined);
    try {
      const value = await api.createRecap(recapKind, recapKind === 'project' ? project.trim() : undefined);
      setRecap(value);
      setNotice('Recap generated from current canonical versions.');
    } catch (caught) { setError(caught instanceof Error ? caught : new Error('Recap failed')); }
    finally { setBusy(undefined); }
  };

  const exportResource = async (format: ExportRequest['format'], resourceName: ExportRequest['resource']) => {
    const key = `export-${resourceName}-${format}`;
    setBusy(key); setError(undefined); setNotice(undefined);
    try {
      const result = await api.createExport({ format, resource: resourceName, recap_id: resourceName === 'recap' ? recap?.id : undefined });
      if (result.download_url) await downloadUrl(result.download_url, result.filename);
      else if (result.content !== undefined) await downloadText(result.content, result.filename, result.content_type);
      else throw new Error('The API returned no downloadable export.');
      setNotice(`${format.toUpperCase()} export prepared.`);
    } catch (caught) { setError(caught instanceof Error ? caught : new Error('Export failed')); }
    finally { setBusy(undefined); }
  };

  return (
    <AppShell>
      <PageTitle
        title="Tasks & insights"
        subtitle="Actions and topic views are deterministic projections of cited canonical intelligence. Recaps are generated only when requested."
        action={
          <View style={styles.pageTabs}>
            <Chip label="Tasks" selected={tab === 'tasks'} onPress={() => setTab('tasks')} />
            <Chip label="Insights" selected={tab === 'insights'} onPress={() => setTab('insights')} />
          </View>
        }
      />
      {notice ? <Notice tone="success" title="Done">{notice}</Notice> : null}
      {error ? <Notice tone="error" title="Action failed">{error.message}</Notice> : null}

      {tab === 'tasks' ? (
        <>
          <Card style={styles.toolbarCard}>
            <View style={styles.filters}>
              {(['all', 'open', 'in_progress', 'done', 'unresolved'] as StatusFilter[]).map((status) => (
                <Chip key={status} label={status.replace('_', ' ')} selected={filter === status} onPress={() => setFilter(status)} />
              ))}
            </View>
            <View style={styles.exportButtons}>
              {(['csv', 'ics', 'markdown', 'json'] as const).map((format) => (
                <Button key={format} size="sm" variant="ghost" icon="download-outline" loading={busy === `export-tasks-${format}`} onPress={() => exportResource(format, 'tasks')}>
                  {format.toUpperCase()}
                </Button>
              ))}
            </View>
          </Card>
          {resource.loading ? <Card><LoadingState label="Loading cited actions…" /></Card> : resource.error ? <Card><ErrorState error={resource.error} onRetry={resource.reload} /></Card> : !visibleTasks.length ? (
            <Card><EmptyState icon="checkbox-marked-circle-outline" title={filter === 'all' ? 'No cited tasks yet' : `No ${filter.replace('_', ' ')} tasks`} body="Tasks appear only after a grounded intelligence bundle publishes an action with evidence or an explicitly unresolved field." /></Card>
          ) : (
            <View style={styles.taskList}>
              {visibleTasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  narrow={width < 760}
                  busy={busy === task.id}
                  onStatus={(status) => mutate(task.id, () => api.updateTask(task.id, status, task.version), `Task marked ${status.replace('_', ' ')}.`)}
                  onSource={() => router.push(`/recordings/${task.recording_id}?seek=${task.evidence[0]?.start_ms ?? 0}`)}
                />
              ))}
            </View>
          )}
        </>
      ) : (
        <View style={[styles.insightsLayout, width < 940 && styles.insightsLayoutNarrow]}>
          <View style={styles.insightsMain}>
            {recap ? (
              <>
                <Card style={styles.recapCard}>
                  <View style={uiStyles.rowBetween}>
                    <View style={styles.recapTitleCopy}>
                      <Text style={styles.recapKicker}>{recap.period.toUpperCase()}</Text>
                      <Text style={styles.recapTitle}>{recap.title}</Text>
                      <Text style={styles.recapDate}>Generated {formatDate(recap.generated_at, true)}</Text>
                    </View>
                    <View style={styles.exportButtons}>
                      {(['markdown', 'json'] as const).map((format) => (
                        <Button key={format} size="sm" variant="secondary" icon="download-outline" loading={busy === `export-recap-${format}`} onPress={() => exportResource(format, 'recap')}>{format.toUpperCase()}</Button>
                      ))}
                    </View>
                  </View>
                  <Text style={styles.recapSummary}>{recap.summary}</Text>
                  <View style={styles.citations}>
                    {recap.citations.slice(0, 8).map((citation) => (
                      <CitationChip key={`${citation.segment_id}-${citation.start_ms}`} citation={citation} onPress={() => router.push(`/recordings/${citation.recording_id}?seek=${citation.start_ms}`)} />
                    ))}
                  </View>
                </Card>
                <Card style={styles.recapCard}>
                  <Text style={styles.sectionTitle}>Topic map</Text>
                  <TopicMap topics={recap.topics} onSource={(topic) => {
                    const citation = topic.evidence[0];
                    if (citation) router.push(`/recordings/${citation.recording_id}?seek=${citation.start_ms}`);
                  }} />
                </Card>
              </>
            ) : (
              <Card><EmptyState icon="chart-tree" title="Generate an on-demand recap" body="Daily and project recaps record their input versions and citations. Corrections, permission changes, and deletion invalidate them." /></Card>
            )}
          </View>
          <Card style={styles.recapControls}>
            <Text style={styles.panelTitle}>New recap</Text>
            <Segmented<'daily' | 'project'>
              value={recapKind}
              onChange={setRecapKind}
              options={[
                { value: 'daily', label: 'Daily', description: 'Recent accessible evidence' },
                { value: 'project', label: 'Project', description: 'Project-filtered evidence' },
              ]}
            />
            {recapKind === 'project' ? <Field label="Project or folder"><Input value={project} onChangeText={setProject} placeholder="Customer research" /></Field> : null}
            <Button icon="creation-outline" loading={busy === 'recap'} disabled={recapKind === 'project' && !project.trim()} onPress={generateRecap}>Generate cited recap</Button>
            <Notice tone="info" title="Generated only on demand">Scheduled insights are intentionally deferred until usage warrants the spend.</Notice>
          </Card>
        </View>
      )}
    </AppShell>
  );
}

function TaskRow({ task, narrow, busy, onStatus, onSource }: { task: ActionTask; narrow: boolean; busy: boolean; onStatus(status: ActionTask['status']): void; onSource(): void }) {
  return (
    <Card style={[styles.taskRow, narrow && styles.taskRowNarrow]}>
      <Pressable accessibilityRole="button" accessibilityLabel="Open source recording" onPress={onSource} style={styles.taskSourceIcon}>
        <MaterialCommunityIcons name="play-circle-outline" size={24} color={colors.coralDark} />
      </Pressable>
      <View style={styles.taskCopy}>
        <Text style={styles.taskText}>{task.task}</Text>
        <View style={styles.taskMeta}>
          <Text style={styles.recordingName}>{task.recording_title ?? 'Recording'}</Text>
          <Text style={styles.metaDot}>·</Text>
          <Text style={[styles.owner, !task.owner_text && styles.unresolved]}>{task.owner_text ?? 'Owner unresolved'}</Text>
          <Text style={styles.metaDot}>·</Text>
          <Text style={[styles.due, !task.due_at && styles.unresolved]}>{task.due_at ? formatDate(task.due_at) : task.due_text ?? 'Date unresolved'}</Text>
        </View>
        {task.ambiguities?.length ? <Text style={styles.ambiguity}>{task.ambiguities.join(' · ')}</Text> : null}
        <View style={styles.citations}>{task.evidence.map((citation) => <CitationChip key={`${citation.segment_id}-${citation.start_ms}`} citation={citation} onPress={onSource} />)}</View>
      </View>
      <View style={styles.statusChoices}>
        {(['open', 'in_progress', 'done', 'dismissed'] as const).map((status) => (
          <Chip key={status} label={status.replace('_', ' ')} selected={task.status === status} onPress={busy ? undefined : () => onStatus(status)} />
        ))}
      </View>
    </Card>
  );
}

function TopicMap({ topics, onSource }: { topics: Topic[]; onSource(topic: Topic): void }) {
  const roots = topics.filter((topic) => !topic.parent || !topics.some((candidate) => candidate.label === topic.parent));
  if (!topics.length) return <Text style={styles.emptyTopics}>No cited topics in this recap.</Text>;
  return (
    <View style={styles.topicMap}>
      {roots.map((root) => (
        <View key={root.label} style={styles.topicBranch}>
          <Pressable accessibilityRole="button" onPress={() => onSource(root)} style={styles.topicRoot}>
            <MaterialCommunityIcons name="circle-slice-8" size={17} color={colors.white} />
            <Text style={styles.topicRootText}>{root.label}</Text>
          </Pressable>
          <View style={styles.topicChildren}>
            {topics.filter((topic) => topic.parent === root.label).map((child) => (
              <Pressable key={child.label} accessibilityRole="button" onPress={() => onSource(child)} style={styles.topicChild}>
                <View style={styles.topicLine} />
                <Text style={styles.topicChildText}>{child.label}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  pageTabs: { flexDirection: 'row', gap: 6 },
  toolbarCard: { padding: spacing.md, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: spacing.md, flexWrap: 'wrap', shadowOpacity: 0 },
  filters: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  exportButtons: { flexDirection: 'row', gap: 4, flexWrap: 'wrap' },
  taskList: { gap: spacing.md },
  taskRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.lg, padding: spacing.lg, shadowOpacity: 0 },
  taskRowNarrow: { flexDirection: 'column' },
  taskSourceIcon: { width: 42, height: 42, borderRadius: 14, backgroundColor: colors.coralSoft, alignItems: 'center', justifyContent: 'center' },
  taskCopy: { flex: 1, gap: spacing.sm },
  taskText: { color: colors.ink, fontFamily: font.medium, fontSize: 14, lineHeight: 20 },
  taskMeta: { flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  recordingName: { color: colors.blue, fontSize: 10 },
  metaDot: { color: colors.borderStrong, fontSize: 10 },
  owner: { color: colors.inkMuted, fontSize: 10 },
  due: { color: colors.inkMuted, fontSize: 10 },
  unresolved: { color: colors.amber, fontStyle: 'italic' },
  ambiguity: { color: colors.amber, fontSize: 9 },
  citations: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  statusChoices: { maxWidth: 230, flexDirection: 'row', justifyContent: 'flex-end', gap: 5, flexWrap: 'wrap' },
  insightsLayout: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xl },
  insightsLayoutNarrow: { flexDirection: 'column' },
  insightsMain: { flex: 1, width: '100%', minWidth: 0, gap: spacing.xl },
  recapCard: { gap: spacing.xl },
  recapTitleCopy: { flex: 1, minWidth: 180, gap: 3 },
  recapKicker: { color: colors.coralDark, fontFamily: font.medium, fontSize: 9, letterSpacing: 1.2 },
  recapTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 23, letterSpacing: -0.5 },
  recapDate: { color: colors.inkFaint, fontSize: 9 },
  recapSummary: { color: colors.ink, fontSize: 16, lineHeight: 26 },
  recapControls: { width: '100%', maxWidth: 350, gap: spacing.xl, shadowOpacity: 0 },
  panelTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 17 },
  sectionTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 18 },
  topicMap: { gap: spacing.lg },
  topicBranch: { gap: spacing.sm },
  topicRoot: { alignSelf: 'flex-start', minHeight: 38, paddingHorizontal: 14, borderRadius: radius.pill, backgroundColor: colors.pine, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  topicRootText: { color: colors.white, fontFamily: font.medium, fontSize: 12 },
  topicChildren: { paddingLeft: spacing.xl, gap: spacing.sm },
  topicChild: { minHeight: 34, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  topicLine: { width: 22, height: 1, backgroundColor: colors.borderStrong },
  topicChildText: { color: colors.inkMuted, fontSize: 12 },
  emptyTopics: { color: colors.inkFaint, fontSize: 12, fontStyle: 'italic' },
});
