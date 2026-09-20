import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { type ComponentProps, type ReactNode, useState } from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import { Button, Card, PageTitle } from '@/components/ui';
import { colors, font, radius, shadowNone, spacing } from '@/theme';

type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];
type NodeTone = 'neutral' | 'strong' | 'cheap' | 'code' | 'output';
type ApproachKey = 'naive' | 'middle' | 'optimized';
type WorkflowKey = 'recording' | 'continuous';

const mobileApproaches: { key: ApproachKey; label: string; cost: string }[] = [
  { key: 'naive', label: 'Naive', cost: 'HIGH' },
  { key: 'middle', label: 'Middle', cost: 'MED–HIGH' },
  { key: 'optimized', label: 'Our design', cost: 'LOW' },
];

export default function PromptFlowScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const stacked = width < 1040;
  const phone = width < 680;
  const [mobileApproach, setMobileApproach] = useState<ApproachKey>('optimized');
  const [workflow, setWorkflow] = useState<WorkflowKey>('recording');

  return (
    <AppShell>
      <View style={styles.intro}>
        <Text style={styles.eyebrow}>PROMPT FLOW &amp; SYSTEM DESIGN</Text>
        <PageTitle
          title={workflow === 'recording' ? 'Single-recording workflow' : 'Continuous-day workflow'}
          subtitle={workflow === 'recording' ? 'Compare what each approach sends to a model, how much work it repeats, and where stronger reasoning is actually used.' : 'See exactly how each arriving batch is filtered, reconciled, folded into temporal memory, and exposed to Ask.'}
          action={<Button icon="play" onPress={() => router.push('/')}>Try it</Button>}
        />
      </View>

      <View style={styles.workflowPicker} accessibilityRole="tablist">
        {([
          ['recording', 'Single recording', 'One bounded meeting or clip'],
          ['continuous', 'Continuous day', 'Sequential batches + evolving memory'],
        ] as const).map(([key, label, detail]) => {
          const selected = workflow === key;
          return (
            <Pressable key={key} accessibilityRole="tab" accessibilityState={{ selected }} onPress={() => setWorkflow(key)} style={[styles.workflowTab, selected && styles.workflowTabSelected]}>
              <Text style={[styles.workflowLabel, selected && styles.workflowLabelSelected]}>{label}</Text>
              <Text style={[styles.workflowDetail, selected && styles.workflowDetailSelected]}>{detail}</Text>
            </Pressable>
          );
        })}
      </View>

      {workflow === 'recording' ? <>
      {phone ? (
        <View style={styles.mobilePicker}>
          <View style={styles.mobilePickerHeader}>
            <Text style={styles.mobilePickerKicker}>COMPARE APPROACHES</Text>
            <Text style={styles.mobilePickerHint}>Tap each option to inspect its architecture.</Text>
          </View>
          <View style={styles.mobileTabs} accessibilityRole="tablist">
            {mobileApproaches.map((approach) => {
              const selected = mobileApproach === approach.key;
              return (
                <Pressable
                  key={approach.key}
                  accessibilityRole="tab"
                  accessibilityState={{ selected }}
                  onPress={() => setMobileApproach(approach.key)}
                  style={({ pressed }) => [
                    styles.mobileTab,
                    selected && styles.mobileTabSelected,
                    selected && approach.key === 'optimized' && styles.mobileTabOptimized,
                    pressed && styles.mobileTabPressed,
                  ]}
                >
                  <Text numberOfLines={1} style={[styles.mobileTabLabel, selected && styles.mobileTabLabelSelected]}>{approach.label}</Text>
                  <Text style={[styles.mobileTabCost, selected && styles.mobileTabCostSelected]}>{approach.cost}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      ) : null}

      <View style={[styles.comparisonGrid, stacked && styles.comparisonGridStacked, phone && styles.comparisonGridPhone]}>
        {!phone || mobileApproach === 'naive' ? <ApproachCard
          label="NAIVE APPROACH"
          title="One massive call"
          subtitle="Ask one strong model to understand everything and produce every artifact at once."
          badge="Highest model load"
          badgeTone="strong"
          cost={100}
          costLevel="High"
          costLabel="Full transcript processed once"
          tradeoffs={['Simple to prototype', 'Hard to validate or retry', 'One failure reruns everything']}
          compact={phone}
        >
          <PipelineNode icon="file-document-outline" title="Full transcript" detail="Every word + all instructions" tone="neutral" compact={phone} />
          <Connector compact={phone} />
          <PipelineNode icon="brain" title="One massive LLM call" detail="Strong model reasons, extracts, writes, and formats" tone="strong" featured compact={phone} />
          <Connector compact={phone} />
          <OutputCluster compact={phone} />
        </ApproachCard> : null}

        {!phone || mobileApproach === 'middle' ? <ApproachCard
          label="MIDDLE APPROACH"
          title="Split by output"
          subtitle="Use focused prompts, but send the full transcript to each model job."
          badge="Less coupled"
          badgeTone="cheap"
          cost={72}
          costLevel="Medium–high"
          costLabel="Full transcript processed repeatedly"
          tradeoffs={['Easier prompts to tune', 'Failures retry independently', 'Input tokens are duplicated']}
          compact={phone}
        >
          <PipelineNode icon="file-document-outline" title="Full transcript" detail="Shared source for every prompt" tone="neutral" compact={phone} />
          <Connector compact={phone} />
          <View style={[styles.parallelBox, phone && styles.parallelBoxCompact]}>
            <Text style={styles.parallelLabel}>SPECIALIZED MODEL CALLS</Text>
            <View style={styles.parallelGrid}>
              {[
                ['text-box-outline', 'Summary'],
                ['checkbox-marked-circle-outline', 'Actions'],
                ['source-branch', 'Decisions'],
                ['tag-multiple-outline', 'Topics'],
              ].map(([icon, label]) => (
                <View key={label} style={styles.parallelJob}>
                  <MaterialCommunityIcons name={icon as IconName} size={17} color={colors.blue} />
                  <Text style={styles.parallelJobText}>{label}</Text>
                </View>
              ))}
            </View>
            <Text style={styles.repeatNote}>The full transcript enters all four calls</Text>
          </View>
          <Connector compact={phone} />
          <PipelineNode icon="view-dashboard-outline" title="Combined output" detail="Independent results assembled at the end" tone="output" compact={phone} />
        </ApproachCard> : null}

        {!phone || mobileApproach === 'optimized' ? <ApproachCard
          label="OUR COST-SAVING APPROACH"
          title="Route only what is needed"
          subtitle="Shrink context early, validate with code, and reserve strong reasoning for isolated failures."
          badge="Lowest model load"
          badgeTone="code"
          cost={26}
          costLevel="Low"
          costLabel="Small windows + compact evidence"
          tradeoffs={['Context is bounded', 'Evidence is checked before publish', 'Only failed units escalate']}
          emphasized
          compact={phone}
        >
          <PipelineNode icon="file-document-outline" title="Transcript" detail="Authoritative source with timestamps" tone="neutral" compact={phone} />
          <Connector compact={phone} />
          <PipelineNode icon="code-braces" title="Gate + split in code" detail="Reject bad input and create topic-sized windows" tone="code" compact={phone} />
          <Connector compact={phone} />
          <PipelineNode icon="filter-variant" title="Cheap extraction" detail="Typed candidates + exact evidence only" tone="cheap" compact={phone} />
          <Connector compact={phone} />
          <PipelineNode icon="source-merge" title="Merge + validate in code" detail="Resolve, deduplicate, and flag contradictions" tone="code" compact={phone} />
          <Connector compact={phone} />
          <View style={styles.routedFinish}>
            <PipelineNode icon="text-box-check-outline" title="Compact synthesis" detail="Write from merged facts, not the transcript" tone="cheap" compact={phone} />
            <View style={[styles.repairBranch, phone && styles.repairBranchCompact]}>
              <MaterialCommunityIcons name="arrow-up-right" size={16} color={colors.coralDark} />
              <Text style={styles.repairText}>Strong repair sees only the failed unit</Text>
            </View>
          </View>
        </ApproachCard> : null}
      </View>

      <Card style={[styles.takeawayCard, phone && styles.takeawayCardPhone]}>
        <View style={styles.takeawayIcon}><MaterialCommunityIcons name="lightning-bolt-outline" size={24} color={colors.white} /></View>
        <View style={styles.takeawayCopy}>
          <Text style={styles.takeawayKicker}>THE KEY DIFFERENCE</Text>
          <Text style={styles.takeawayTitle}>Sophistication comes from routing and verification, not from making the first prompt bigger.</Text>
          <Text style={styles.takeawayBody}>The optimized pipeline pays for broad context once, keeps deterministic work in code, and buys stronger reasoning only for the small fraction of output that fails validation.</Text>
        </View>
      </Card>
      </> : <ContinuousDayFlow phone={phone} />}
    </AppShell>
  );
}

function ContinuousDayFlow({ phone }: { phone: boolean }) {
  const stages: { icon: IconName; title: string; detail: string; tone: NodeTone; side?: string }[] = [
    { icon: 'clock-fast', title: 'One immutable batch arrives', detail: 'Only the current slice is visible. Future audio cannot leak backward.', tone: 'neutral', side: 'watermark advances only after publish' },
    { icon: 'waveform', title: 'Conservative audio activity gate', detail: 'Local PCM analysis skips only clear near-silence. Ambiguous sound passes.', tone: 'code', side: 'saves speech calls without risking quiet speech' },
    { icon: 'text-box-outline', title: 'Gemini transcription', detail: 'The arriving batch becomes a full timestamped transcript; raw text is retained.', tone: 'cheap', side: 'one metered call for this batch only' },
    { icon: 'filter-variant', title: 'High-recall Gemini triage', detail: 'Keep decisions, tasks, corrections, risks, metrics, questions, and uncertain context.', tone: 'cheap', side: 'drop only obvious filler or unrelated chatter' },
    { icon: 'vector-link', title: 'Reconcile with prior tail', detail: 'Carry speaker and boundary context; retain exact source IDs and timestamps.', tone: 'code', side: 'future batches may revise, never rewrite evidence' },
    { icon: 'source-merge', title: 'Cumulative memory synthesis', detail: 'Send previously kept evidence plus this batch’s kept segments, not the whole day.', tone: 'strong', side: 'add, supersede, and resolve temporal facts' },
    { icon: 'database-check-outline', title: 'Atomic snapshot publish', detail: 'Transcript, index, memory, revision log, and Ask watermark become visible together.', tone: 'output', side: 'historical batch snapshots remain selectable' },
  ];
  return (
    <View style={styles.dayFlow}>
      <Card style={styles.dayDiagramCard}>
        <View style={styles.dayHeader}>
          <View style={styles.dayHeaderCopy}><Text style={styles.dayKicker}>PER-BATCH CRITICAL PATH</Text><Text style={styles.dayTitle}>Process completely before the next batch arrives</Text></View>
          <View style={styles.highRecallBadge}><MaterialCommunityIcons name="shield-check-outline" size={15} color={colors.green} /><Text style={styles.highRecallText}>FALSE-NEGATIVE AVERSE</Text></View>
        </View>
        <View style={styles.dayPipeline}>
          {stages.map((stage, index) => (
            <View key={stage.title}>
              <View style={[styles.dayStageRow, phone && styles.dayStageRowPhone]}>
                <View style={styles.dayStageNumber}><Text style={styles.dayStageNumberText}>{index + 1}</Text></View>
                <View style={styles.dayStageNode}><PipelineNode icon={stage.icon} title={stage.title} detail={stage.detail} tone={stage.tone} compact /></View>
                <Text style={[styles.dayStageSide, phone && styles.dayStageSidePhone]}>{stage.side}</Text>
              </View>
              {index < stages.length - 1 ? <View style={styles.dayConnector}><View style={styles.dayConnectorLine} /><MaterialCommunityIcons name="arrow-down" size={15} color={colors.borderStrong} /></View> : null}
            </View>
          ))}
        </View>
      </Card>

      <View style={[styles.decisionGrid, phone && styles.decisionGridPhone]}>
        <DecisionCard icon="archive-lock-outline" title="Keep the source" body="Filtering never deletes audio or transcript. Ask can retrieve omitted text when a later question makes it relevant." />
        <DecisionCard icon="timeline-clock-outline" title="Fence by watermark" body="Every snapshot and Ask answer sees only published batches through the selected point in time." />
        <DecisionCard icon="refresh-circle" title="Let the future revise" body="Later evidence can supersede provisional decisions while the revision log preserves what changed and why." />
        <DecisionCard icon="cash-check" title="Meter every remote step" body="Speech, triage, synthesis, and Ask each use stable attempts, budget reservations, provenance, and stale-generation checks." />
      </View>

      <Card style={styles.askArchitecture}>
        <View style={styles.askArchitectureIcon}><MaterialCommunityIcons name="message-question-outline" size={24} color={colors.white} /></View>
        <View style={styles.takeawayCopy}><Text style={styles.takeawayKicker}>ASK IS A SEPARATE RETRIEVAL PATH</Text><Text style={styles.takeawayTitle}>Memory stays compact; questions can still reach the full retained transcript.</Text><Text style={styles.takeawayBody}>Ask ranks matching text across every published segment, including content excluded from recurring synthesis, then adds recent high-salience evidence and sends a bounded, cited context to Gemini.</Text></View>
      </Card>
    </View>
  );
}

function DecisionCard({ icon, title, body }: { icon: IconName; title: string; body: string }) {
  return <Card style={styles.decisionCard}><View style={styles.decisionIcon}><MaterialCommunityIcons name={icon} size={20} color={colors.pine} /></View><View style={styles.decisionCopy}><Text style={styles.decisionTitle}>{title}</Text><Text style={styles.decisionBody}>{body}</Text></View></Card>;
}

function ApproachCard({
  label,
  title,
  subtitle,
  badge,
  badgeTone,
  cost,
  costLevel,
  costLabel,
  tradeoffs,
  emphasized = false,
  compact = false,
  children,
}: {
  label: string;
  title: string;
  subtitle: string;
  badge: string;
  badgeTone: 'strong' | 'cheap' | 'code';
  cost: number;
  costLevel: string;
  costLabel: string;
  tradeoffs: string[];
  emphasized?: boolean;
  compact?: boolean;
  children: ReactNode;
}) {
  return (
    <Card style={[styles.approachCard, compact && styles.approachCardCompact, emphasized && styles.approachCardEmphasized]}>
      <View style={[styles.approachHeader, compact && styles.approachHeaderCompact]}>
        <View style={styles.approachLabelRow}>
          <Text style={[styles.approachLabel, emphasized && styles.approachLabelEmphasized]}>{label}</Text>
          <View style={[styles.badge, styles[`badge_${badgeTone}`]]}>
            <Text style={[styles.badgeText, styles[`badgeText_${badgeTone}`]]}>{badge}</Text>
          </View>
        </View>
        <Text style={styles.approachTitle}>{title}</Text>
        <Text style={styles.approachSubtitle}>{subtitle}</Text>
      </View>

      <View style={[styles.diagram, compact && styles.diagramCompact]}>{children}</View>

      <View style={styles.costBlock}>
        <View style={styles.costTop}>
          <Text style={styles.costTitle}>ILLUSTRATIVE MODEL WORK</Text>
          <Text style={styles.costValue}>{costLevel}</Text>
        </View>
        <View style={styles.costTrack}>
          <View style={[
            styles.costFill,
            { width: `${cost}%` },
            badgeTone === 'strong' ? styles.costFillStrong : badgeTone === 'cheap' ? styles.costFillCheap : styles.costFillCode,
          ]} />
        </View>
        <Text style={styles.costLabel}>{costLabel}</Text>
      </View>

      <View style={styles.tradeoffList}>
        {tradeoffs.map((tradeoff, index) => (
          <View key={tradeoff} style={styles.tradeoffRow}>
            <MaterialCommunityIcons
              name={index === 0 ? 'check-circle-outline' : 'circle-small'}
              size={index === 0 ? 16 : 18}
              color={index === 0 ? colors.green : colors.inkFaint}
            />
            <Text style={styles.tradeoffText}>{tradeoff}</Text>
          </View>
        ))}
      </View>
    </Card>
  );
}

function PipelineNode({ icon, title, detail, tone, featured = false, compact = false }: { icon: IconName; title: string; detail: string; tone: NodeTone; featured?: boolean; compact?: boolean }) {
  const foreground = tone === 'strong'
    ? colors.coralDark
    : tone === 'cheap'
      ? colors.blue
      : tone === 'code'
        ? colors.green
        : colors.pine;
  return (
    <View style={[styles.pipelineNode, compact && styles.pipelineNodeCompact, styles[`pipelineNode_${tone}`], featured && styles.pipelineNodeFeatured, featured && compact && styles.pipelineNodeFeaturedCompact]}>
      <View style={[styles.nodeIcon, compact && styles.nodeIconCompact, styles[`nodeIcon_${tone}`]]}>
        <MaterialCommunityIcons name={icon} size={19} color={foreground} />
      </View>
      <View style={styles.nodeCopy}>
        <Text style={styles.nodeTitle}>{title}</Text>
        <Text style={styles.nodeDetail}>{detail}</Text>
      </View>
    </View>
  );
}

function Connector({ compact = false }: { compact?: boolean }) {
  return (
    <View style={[styles.connector, compact && styles.connectorCompact]}>
      <View style={styles.connectorLine} />
      <MaterialCommunityIcons name="arrow-down" size={16} color={colors.borderStrong} />
    </View>
  );
}

function OutputCluster({ compact = false }: { compact?: boolean }) {
  return (
    <View style={[styles.outputCluster, compact && styles.outputClusterCompact]}>
      <Text style={styles.outputLabel}>ALL OUTPUTS AT ONCE</Text>
      <View style={styles.outputGrid}>
        {['Summary', 'Actions', 'Decisions', 'Topics'].map((label) => (
          <View key={label} style={styles.outputChip}><Text style={styles.outputChipText}>{label}</Text></View>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  intro: { gap: spacing.sm },
  eyebrow: { color: colors.coralDark, fontFamily: font.medium, fontSize: 9, letterSpacing: 1.2 },
  workflowPicker: { flexDirection: 'row', alignSelf: 'stretch', flexWrap: 'wrap', gap: spacing.xs, padding: spacing.xs, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, backgroundColor: colors.surfaceMuted },
  workflowTab: { flexGrow: 1, minWidth: 150, gap: 2, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderRadius: radius.md },
  workflowTabSelected: { backgroundColor: colors.pine },
  workflowLabel: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 11 },
  workflowLabelSelected: { color: colors.white },
  workflowDetail: { color: colors.inkFaint, fontSize: 8 },
  workflowDetailSelected: { color: '#C8DDD6' },
  dayFlow: { gap: spacing.lg },
  dayDiagramCard: { gap: spacing.xl, padding: spacing.xl, ...shadowNone },
  dayHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.lg, flexWrap: 'wrap' },
  dayHeaderCopy: { flex: 1, minWidth: 220, gap: 3 },
  dayKicker: { color: colors.coralDark, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  dayTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 18 },
  highRecallBadge: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, borderRadius: radius.pill, backgroundColor: colors.greenSoft },
  highRecallText: { color: colors.green, fontFamily: font.mono, fontSize: 7, letterSpacing: 0.5 },
  dayPipeline: { maxWidth: 860, width: '100%', alignSelf: 'center' },
  dayStageRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  dayStageRowPhone: { alignItems: 'flex-start', flexWrap: 'wrap' },
  dayStageNumber: { width: 28, height: 28, alignItems: 'center', justifyContent: 'center', borderRadius: 14, backgroundColor: colors.pine },
  dayStageNumberText: { color: colors.white, fontFamily: font.mono, fontSize: 9 },
  dayStageNode: { flex: 1, minWidth: 240 },
  dayStageSide: { width: 190, color: colors.inkMuted, fontSize: 8, lineHeight: 12 },
  dayStageSidePhone: { width: '100%', paddingLeft: 44 },
  dayConnector: { height: 22, marginLeft: 13, alignItems: 'flex-start', justifyContent: 'center' },
  dayConnectorLine: { position: 'absolute', left: 0, top: 0, bottom: 5, width: 1, backgroundColor: colors.borderStrong },
  decisionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  decisionGridPhone: { flexDirection: 'column' },
  decisionCard: { width: '48%', flexGrow: 1, minWidth: 260, flexDirection: 'row', gap: spacing.md, padding: spacing.lg, ...shadowNone },
  decisionIcon: { width: 38, height: 38, alignItems: 'center', justifyContent: 'center', borderRadius: 12, backgroundColor: colors.pineSoft },
  decisionCopy: { flex: 1, gap: 4 },
  decisionTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 11 },
  decisionBody: { color: colors.inkMuted, fontSize: 9, lineHeight: 14 },
  askArchitecture: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg, backgroundColor: colors.pine, borderColor: colors.pine, ...shadowNone },
  askArchitectureIcon: { width: 48, height: 48, alignItems: 'center', justifyContent: 'center', borderRadius: 16, backgroundColor: 'rgba(255,255,255,0.12)' },
  comparisonGrid: { flexDirection: 'row', alignItems: 'stretch', gap: spacing.lg },
  comparisonGridStacked: { flexDirection: 'column' },
  comparisonGridPhone: { gap: 0 },
  mobilePicker: { gap: spacing.sm, padding: spacing.sm, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, backgroundColor: colors.surface },
  mobilePickerHeader: { paddingHorizontal: spacing.xs, paddingTop: spacing.xs, gap: 2 },
  mobilePickerKicker: { color: colors.ink, fontFamily: font.medium, fontSize: 10, letterSpacing: 0.8 },
  mobilePickerHint: { color: colors.inkMuted, fontSize: 10, lineHeight: 15 },
  mobileTabs: { flexDirection: 'row', gap: spacing.xs },
  mobileTab: { flex: 1, minWidth: 0, minHeight: 58, alignItems: 'center', justifyContent: 'center', gap: 3, paddingHorizontal: spacing.xs, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.canvas },
  mobileTabSelected: { borderColor: colors.pine, backgroundColor: colors.pine },
  mobileTabOptimized: { borderColor: colors.green, backgroundColor: colors.green },
  mobileTabPressed: { opacity: 0.78 },
  mobileTabLabel: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 10 },
  mobileTabLabelSelected: { color: colors.white },
  mobileTabCost: { color: colors.inkFaint, fontFamily: font.mono, fontSize: 7, letterSpacing: 0.5 },
  mobileTabCostSelected: { color: '#D8E9E3' },
  approachCard: { flex: 1, minWidth: 0, padding: spacing.lg, gap: spacing.lg, ...shadowNone },
  approachCardCompact: { flexGrow: 0, flexShrink: 1, flexBasis: 'auto', padding: spacing.lg, gap: spacing.md },
  approachCardEmphasized: { borderWidth: 2, borderColor: colors.green, backgroundColor: '#FBFEFC' },
  approachHeader: { minHeight: 130, gap: spacing.sm },
  approachHeaderCompact: { minHeight: 0 },
  approachLabelRow: { minHeight: 24, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm, flexWrap: 'wrap' },
  approachLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 0.9 },
  approachLabelEmphasized: { color: colors.green },
  approachTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 21, letterSpacing: -0.35 },
  approachSubtitle: { color: colors.inkMuted, fontSize: 11, lineHeight: 17 },
  badge: { paddingHorizontal: 8, paddingVertical: 5, borderRadius: radius.pill },
  badge_strong: { backgroundColor: colors.coralSoft },
  badge_cheap: { backgroundColor: colors.blueSoft },
  badge_code: { backgroundColor: colors.greenSoft },
  badgeText: { fontFamily: font.medium, fontSize: 7 },
  badgeText_strong: { color: colors.coralDark },
  badgeText_cheap: { color: colors.blue },
  badgeText_code: { color: colors.green },
  diagram: { flex: 1, minHeight: 420, padding: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, backgroundColor: colors.canvas, justifyContent: 'flex-start' },
  diagramCompact: { flexGrow: 0, flexShrink: 1, flexBasis: 'auto', minHeight: 0, padding: spacing.sm },
  pipelineNode: { minHeight: 68, flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderRadius: radius.md },
  pipelineNodeCompact: { minHeight: 58, padding: spacing.sm },
  pipelineNode_neutral: { borderColor: colors.borderStrong, backgroundColor: colors.surface },
  pipelineNode_strong: { borderColor: colors.coral, backgroundColor: colors.coralSoft },
  pipelineNode_cheap: { borderColor: '#AFCBDA', backgroundColor: colors.blueSoft },
  pipelineNode_code: { borderColor: '#AED0C3', backgroundColor: colors.greenSoft },
  pipelineNode_output: { borderColor: colors.pine, backgroundColor: colors.pineSoft },
  pipelineNodeFeatured: { minHeight: 92 },
  pipelineNodeFeaturedCompact: { minHeight: 68 },
  nodeIcon: { width: 36, height: 36, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  nodeIconCompact: { width: 32, height: 32, borderRadius: 10 },
  nodeIcon_neutral: { backgroundColor: colors.surfaceMuted },
  nodeIcon_strong: { backgroundColor: '#F9CDC4' },
  nodeIcon_cheap: { backgroundColor: '#CFE2EC' },
  nodeIcon_code: { backgroundColor: '#CBE4D9' },
  nodeIcon_output: { backgroundColor: '#C9DFD6' },
  nodeCopy: { flex: 1, minWidth: 0, gap: 3 },
  nodeTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 11 },
  nodeDetail: { color: colors.inkMuted, fontSize: 8, lineHeight: 12 },
  connector: { height: 30, alignItems: 'center', justifyContent: 'center' },
  connectorCompact: { height: 22 },
  connectorLine: { position: 'absolute', top: 0, bottom: 8, width: 1, backgroundColor: colors.borderStrong },
  outputCluster: { gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderColor: colors.pine, borderRadius: radius.md, backgroundColor: colors.pineSoft },
  outputClusterCompact: { padding: spacing.sm },
  outputLabel: { color: colors.pine, fontFamily: font.medium, fontSize: 7, letterSpacing: 0.8, textAlign: 'center' },
  outputGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  outputChip: { width: '48%', paddingVertical: 7, paddingHorizontal: spacing.xs, borderRadius: radius.sm, backgroundColor: colors.surface },
  outputChipText: { color: colors.ink, fontFamily: font.medium, fontSize: 8, textAlign: 'center' },
  parallelBox: { gap: spacing.md, padding: spacing.md, borderWidth: 1, borderColor: '#AFCBDA', borderRadius: radius.md, backgroundColor: colors.blueSoft },
  parallelBoxCompact: { gap: spacing.sm, padding: spacing.sm },
  parallelLabel: { color: colors.blue, fontFamily: font.medium, fontSize: 7, letterSpacing: 0.8, textAlign: 'center' },
  parallelGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  parallelJob: { width: '48%', minHeight: 58, alignItems: 'center', justifyContent: 'center', gap: 4, padding: spacing.xs, borderRadius: radius.sm, backgroundColor: colors.surface },
  parallelJobText: { color: colors.ink, fontFamily: font.medium, fontSize: 8 },
  repeatNote: { color: colors.blue, fontSize: 8, lineHeight: 12, textAlign: 'center' },
  routedFinish: { gap: spacing.sm },
  repairBranch: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.xs, padding: spacing.sm, borderWidth: 1, borderStyle: 'dashed', borderColor: colors.coral, borderRadius: radius.sm, backgroundColor: colors.coralSoft },
  repairBranchCompact: { alignItems: 'flex-start', justifyContent: 'flex-start' },
  repairText: { color: colors.coralDark, fontFamily: font.medium, fontSize: 8 },
  costBlock: { gap: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  costTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  costTitle: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 7, letterSpacing: 0.8 },
  costValue: { color: colors.ink, fontFamily: font.mono, fontSize: 10 },
  costTrack: { height: 7, borderRadius: 4, backgroundColor: colors.surfaceMuted, overflow: 'hidden' },
  costFill: { height: 7, borderRadius: 4 },
  costFillStrong: { backgroundColor: colors.coral },
  costFillCheap: { backgroundColor: colors.blue },
  costFillCode: { backgroundColor: colors.green },
  costLabel: { color: colors.inkMuted, fontSize: 8 },
  tradeoffList: { gap: spacing.xs },
  tradeoffRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  tradeoffText: { flex: 1, color: colors.inkMuted, fontSize: 9 },
  takeawayCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg, backgroundColor: colors.pine, borderColor: colors.pine, ...shadowNone },
  takeawayCardPhone: { alignItems: 'flex-start', padding: spacing.lg },
  takeawayIcon: { width: 48, height: 48, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.12)' },
  takeawayCopy: { flex: 1, gap: 4 },
  takeawayKicker: { color: '#A9CCC0', fontFamily: font.medium, fontSize: 8, letterSpacing: 0.9 },
  takeawayTitle: { color: colors.white, fontFamily: font.medium, fontSize: 14, lineHeight: 20 },
  takeawayBody: { color: '#C8DDD6', fontSize: 10, lineHeight: 15 },
});
