import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { type ComponentProps, type ReactNode } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import { Button, Card, PageTitle } from '@/components/ui';
import { colors, font, radius, shadowNone, spacing } from '@/theme';

type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];
type NodeTone = 'neutral' | 'strong' | 'cheap' | 'code' | 'output';

export default function PromptFlowScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const stacked = width < 1040;

  return (
    <AppShell>
      <View style={styles.intro}>
        <Text style={styles.eyebrow}>ARCHITECTURE COMPARISON</Text>
        <PageTitle
          title="Three ways to turn audio into useful output"
          subtitle="Compare what each approach sends to a model, how much work it repeats, and where stronger reasoning is actually used."
          action={<Button icon="play" onPress={() => router.push('/')}>Try it</Button>}
        />
      </View>

      <View style={[styles.comparisonGrid, stacked && styles.comparisonGridStacked]}>
        <ApproachCard
          label="NAIVE APPROACH"
          title="One massive call"
          subtitle="Ask one strong model to understand everything and produce every artifact at once."
          badge="Highest model load"
          badgeTone="strong"
          cost={100}
          costLevel="High"
          costLabel="Full transcript processed once"
          tradeoffs={['Simple to prototype', 'Hard to validate or retry', 'One failure reruns everything']}
        >
          <PipelineNode icon="file-document-outline" title="Full transcript" detail="Every word + all instructions" tone="neutral" />
          <Connector />
          <PipelineNode icon="brain" title="One massive LLM call" detail="Strong model reasons, extracts, writes, and formats" tone="strong" featured />
          <Connector />
          <OutputCluster />
        </ApproachCard>

        <ApproachCard
          label="MIDDLE APPROACH"
          title="Split by output"
          subtitle="Use focused prompts, but send the full transcript to each model job."
          badge="Less coupled"
          badgeTone="cheap"
          cost={72}
          costLevel="Medium–high"
          costLabel="Full transcript processed repeatedly"
          tradeoffs={['Easier prompts to tune', 'Failures retry independently', 'Input tokens are duplicated']}
        >
          <PipelineNode icon="file-document-outline" title="Full transcript" detail="Shared source for every prompt" tone="neutral" />
          <Connector />
          <View style={styles.parallelBox}>
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
          <Connector />
          <PipelineNode icon="view-dashboard-outline" title="Combined output" detail="Independent results assembled at the end" tone="output" />
        </ApproachCard>

        <ApproachCard
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
        >
          <PipelineNode icon="file-document-outline" title="Transcript" detail="Authoritative source with timestamps" tone="neutral" />
          <Connector />
          <PipelineNode icon="code-braces" title="Gate + split in code" detail="Reject bad input and create topic-sized windows" tone="code" />
          <Connector />
          <PipelineNode icon="filter-variant" title="Cheap extraction" detail="Typed candidates + exact evidence only" tone="cheap" />
          <Connector />
          <PipelineNode icon="source-merge" title="Merge + validate in code" detail="Resolve, deduplicate, and flag contradictions" tone="code" />
          <Connector />
          <View style={styles.routedFinish}>
            <PipelineNode icon="text-box-check-outline" title="Compact synthesis" detail="Write from merged facts—not the transcript" tone="cheap" />
            <View style={styles.repairBranch}>
              <MaterialCommunityIcons name="arrow-up-right" size={16} color={colors.coralDark} />
              <Text style={styles.repairText}>Strong repair sees only the failed unit</Text>
            </View>
          </View>
        </ApproachCard>
      </View>

      <Card style={styles.takeawayCard}>
        <View style={styles.takeawayIcon}><MaterialCommunityIcons name="lightning-bolt-outline" size={24} color={colors.white} /></View>
        <View style={styles.takeawayCopy}>
          <Text style={styles.takeawayKicker}>THE KEY DIFFERENCE</Text>
          <Text style={styles.takeawayTitle}>Sophistication comes from routing and verification—not from making the first prompt bigger.</Text>
          <Text style={styles.takeawayBody}>The optimized pipeline pays for broad context once, keeps deterministic work in code, and buys stronger reasoning only for the small fraction of output that fails validation.</Text>
        </View>
      </Card>
    </AppShell>
  );
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
  children: ReactNode;
}) {
  return (
    <Card style={[styles.approachCard, emphasized && styles.approachCardEmphasized]}>
      <View style={styles.approachHeader}>
        <View style={styles.approachLabelRow}>
          <Text style={[styles.approachLabel, emphasized && styles.approachLabelEmphasized]}>{label}</Text>
          <View style={[styles.badge, styles[`badge_${badgeTone}`]]}>
            <Text style={[styles.badgeText, styles[`badgeText_${badgeTone}`]]}>{badge}</Text>
          </View>
        </View>
        <Text style={styles.approachTitle}>{title}</Text>
        <Text style={styles.approachSubtitle}>{subtitle}</Text>
      </View>

      <View style={styles.diagram}>{children}</View>

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

function PipelineNode({ icon, title, detail, tone, featured = false }: { icon: IconName; title: string; detail: string; tone: NodeTone; featured?: boolean }) {
  const foreground = tone === 'strong'
    ? colors.coralDark
    : tone === 'cheap'
      ? colors.blue
      : tone === 'code'
        ? colors.green
        : colors.pine;
  return (
    <View style={[styles.pipelineNode, styles[`pipelineNode_${tone}`], featured && styles.pipelineNodeFeatured]}>
      <View style={[styles.nodeIcon, styles[`nodeIcon_${tone}`]]}>
        <MaterialCommunityIcons name={icon} size={19} color={foreground} />
      </View>
      <View style={styles.nodeCopy}>
        <Text style={styles.nodeTitle}>{title}</Text>
        <Text style={styles.nodeDetail}>{detail}</Text>
      </View>
    </View>
  );
}

function Connector() {
  return (
    <View style={styles.connector}>
      <View style={styles.connectorLine} />
      <MaterialCommunityIcons name="arrow-down" size={16} color={colors.borderStrong} />
    </View>
  );
}

function OutputCluster() {
  return (
    <View style={styles.outputCluster}>
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
  comparisonGrid: { flexDirection: 'row', alignItems: 'stretch', gap: spacing.lg },
  comparisonGridStacked: { flexDirection: 'column' },
  approachCard: { flex: 1, minWidth: 0, padding: spacing.lg, gap: spacing.lg, ...shadowNone },
  approachCardEmphasized: { borderWidth: 2, borderColor: colors.green, backgroundColor: '#FBFEFC' },
  approachHeader: { minHeight: 130, gap: spacing.sm },
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
  pipelineNode: { minHeight: 68, flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderRadius: radius.md },
  pipelineNode_neutral: { borderColor: colors.borderStrong, backgroundColor: colors.surface },
  pipelineNode_strong: { borderColor: colors.coral, backgroundColor: colors.coralSoft },
  pipelineNode_cheap: { borderColor: '#AFCBDA', backgroundColor: colors.blueSoft },
  pipelineNode_code: { borderColor: '#AED0C3', backgroundColor: colors.greenSoft },
  pipelineNode_output: { borderColor: colors.pine, backgroundColor: colors.pineSoft },
  pipelineNodeFeatured: { minHeight: 92 },
  nodeIcon: { width: 36, height: 36, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  nodeIcon_neutral: { backgroundColor: colors.surfaceMuted },
  nodeIcon_strong: { backgroundColor: '#F9CDC4' },
  nodeIcon_cheap: { backgroundColor: '#CFE2EC' },
  nodeIcon_code: { backgroundColor: '#CBE4D9' },
  nodeIcon_output: { backgroundColor: '#C9DFD6' },
  nodeCopy: { flex: 1, minWidth: 0, gap: 3 },
  nodeTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 11 },
  nodeDetail: { color: colors.inkMuted, fontSize: 8, lineHeight: 12 },
  connector: { height: 30, alignItems: 'center', justifyContent: 'center' },
  connectorLine: { position: 'absolute', top: 0, bottom: 8, width: 1, backgroundColor: colors.borderStrong },
  outputCluster: { gap: spacing.sm, padding: spacing.md, borderWidth: 1, borderColor: colors.pine, borderRadius: radius.md, backgroundColor: colors.pineSoft },
  outputLabel: { color: colors.pine, fontFamily: font.medium, fontSize: 7, letterSpacing: 0.8, textAlign: 'center' },
  outputGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  outputChip: { width: '48%', paddingVertical: 7, paddingHorizontal: spacing.xs, borderRadius: radius.sm, backgroundColor: colors.surface },
  outputChipText: { color: colors.ink, fontFamily: font.medium, fontSize: 8, textAlign: 'center' },
  parallelBox: { gap: spacing.md, padding: spacing.md, borderWidth: 1, borderColor: '#AFCBDA', borderRadius: radius.md, backgroundColor: colors.blueSoft },
  parallelLabel: { color: colors.blue, fontFamily: font.medium, fontSize: 7, letterSpacing: 0.8, textAlign: 'center' },
  parallelGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  parallelJob: { width: '48%', minHeight: 58, alignItems: 'center', justifyContent: 'center', gap: 4, padding: spacing.xs, borderRadius: radius.sm, backgroundColor: colors.surface },
  parallelJobText: { color: colors.ink, fontFamily: font.medium, fontSize: 8 },
  repeatNote: { color: colors.blue, fontSize: 8, lineHeight: 12, textAlign: 'center' },
  routedFinish: { gap: spacing.sm },
  repairBranch: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.xs, padding: spacing.sm, borderWidth: 1, borderStyle: 'dashed', borderColor: colors.coral, borderRadius: radius.sm, backgroundColor: colors.coralSoft },
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
  takeawayIcon: { width: 48, height: 48, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(255,255,255,0.12)' },
  takeawayCopy: { flex: 1, gap: 4 },
  takeawayKicker: { color: '#A9CCC0', fontFamily: font.medium, fontSize: 8, letterSpacing: 0.9 },
  takeawayTitle: { color: colors.white, fontFamily: font.medium, fontSize: 14, lineHeight: 20 },
  takeawayBody: { color: '#C8DDD6', fontSize: 10, lineHeight: 15 },
});
