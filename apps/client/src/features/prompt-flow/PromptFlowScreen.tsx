import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import { Button, Card, PageTitle } from '@/components/ui';
import { colors, font, radius, shadowNone, spacing } from '@/theme';

const stages = [
  {
    number: '01',
    title: 'Gate the transcript',
    body: 'Validate the transcript and split it into topic-sized windows before any model call.',
    route: 'Code only',
    tone: 'free' as const,
    icon: 'shield-check-outline' as const,
  },
  {
    number: '02',
    title: 'Extract candidates',
    body: 'A small structured prompt extracts facts, decisions, actions, and exact evidence from each window.',
    route: 'Lower-cost model',
    tone: 'cheap' as const,
    icon: 'filter-variant' as const,
  },
  {
    number: '03',
    title: 'Normalize + merge',
    body: 'Code resolves dates and owners, deduplicates candidates, and flags contradictions.',
    route: 'Code only',
    tone: 'free' as const,
    icon: 'source-merge' as const,
  },
  {
    number: '04',
    title: 'Synthesize compactly',
    body: 'A small prompt writes the title and summary from merged candidates—not the transcript.',
    route: 'Lower-cost model',
    tone: 'cheap' as const,
    icon: 'text-box-edit-outline' as const,
  },
  {
    number: '05',
    title: 'Validate evidence',
    body: 'Schema and citation checks block unsupported output before publication.',
    route: 'Code only',
    tone: 'free' as const,
    icon: 'check-decagram-outline' as const,
  },
  {
    number: '06',
    title: 'Repair only failures',
    body: 'Retry only the failed unit. The strong model sees a small evidence slice, not the full transcript.',
    route: 'Strong model if needed',
    tone: 'strong' as const,
    icon: 'arrow-up-bold-circle-outline' as const,
  },
];

const prompts = [
  {
    label: 'SUB-PROMPT A',
    title: 'Window extraction',
    input: 'One topic window + timestamps',
    output: 'Typed candidates + exact citations',
  },
  {
    label: 'SUB-PROMPT B',
    title: 'Compact synthesis',
    input: 'Merged candidate bundle',
    output: 'Title + cited summary',
  },
  {
    label: 'SUB-PROMPT C',
    title: 'Targeted repair',
    input: 'Failed unit + nearby evidence',
    output: 'Valid repair or unresolved state',
  },
];

export default function PromptFlowScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const narrow = width < 1080;

  return (
    <AppShell>
      <View style={styles.intro}>
        <Text style={styles.eyebrow}>THE CORE IDEA</Text>
        <PageTitle
          title="Use expensive reasoning only when needed"
          subtitle="Run small, bounded prompts first. Deterministic checks isolate the few outputs that need a stronger model."
          action={<Button icon="play" onPress={() => router.push('/demo')}>Try it</Button>}
        />
      </View>

      <Card style={styles.principleCard}>
        <View style={styles.principleMark}><MaterialCommunityIcons name="transit-connection-variant" size={27} color={colors.white} /></View>
        <View style={styles.principleCopy}>
          <Text style={styles.principleKicker}>ONE TRANSCRIPT IN, GROUNDED OUTPUT OUT</Text>
          <Text style={styles.principleText}>Each downstream prompt sees only the context it needs, and every claim links back to evidence.</Text>
        </View>
      </Card>

      <View style={styles.legend}>
        <LegendDot color={colors.green} label="Code only" />
        <LegendDot color={colors.blue} label="Lower-cost model" />
        <LegendDot color={colors.coral} label="Strong model if needed" />
      </View>

      <View style={[styles.flow, narrow && styles.flowNarrow]}>
        {stages.map((stage, index) => (
          <View key={stage.number} style={[styles.flowUnit, narrow && styles.flowUnitNarrow]}>
            <Card style={[styles.stageCard, stage.tone === 'strong' && styles.stageCardStrong]}>
              <View style={styles.stageTop}>
                <Text style={styles.stageNumber}>{stage.number}</Text>
                <View style={[
                  styles.stageIcon,
                  stage.tone === 'free' ? styles.stageIconFree : stage.tone === 'cheap' ? styles.stageIconCheap : styles.stageIconStrong,
                ]}>
                  <MaterialCommunityIcons
                    name={stage.icon}
                    size={20}
                    color={stage.tone === 'free' ? colors.green : stage.tone === 'cheap' ? colors.blue : colors.coralDark}
                  />
                </View>
              </View>
              <Text style={styles.stageTitle}>{stage.title}</Text>
              <Text style={styles.stageBody}>{stage.body}</Text>
              <View style={[
                styles.routeBadge,
                stage.tone === 'free' ? styles.routeBadgeFree : stage.tone === 'cheap' ? styles.routeBadgeCheap : styles.routeBadgeStrong,
              ]}>
                <Text style={[
                  styles.routeText,
                  stage.tone === 'free' ? styles.routeTextFree : stage.tone === 'cheap' ? styles.routeTextCheap : styles.routeTextStrong,
                ]}>{stage.route}</Text>
              </View>
            </Card>
            {index < stages.length - 1 ? (
              <View style={[styles.connector, narrow && styles.connectorNarrow]}>
                <MaterialCommunityIcons name={narrow ? 'arrow-down' : 'arrow-right'} size={18} color={colors.borderStrong} />
              </View>
            ) : null}
          </View>
        ))}
      </View>

      <View style={[styles.detailGrid, narrow && styles.detailGridNarrow]}>
        <Card style={styles.promptCard}>
          <Text style={styles.cardEyebrow}>THE THREE MODEL JOBS</Text>
          <View style={styles.promptList}>
            {prompts.map((prompt) => (
              <View key={prompt.label} style={styles.promptRow}>
                <View style={styles.promptIndex}><Text style={styles.promptIndexText}>{prompt.label.slice(-1)}</Text></View>
                <View style={styles.promptCopy}>
                  <Text style={styles.promptLabel}>{prompt.label}</Text>
                  <Text style={styles.promptTitle}>{prompt.title}</Text>
                  <Text style={styles.promptIO}><Text style={styles.promptIOStrong}>In:</Text> {prompt.input}</Text>
                  <Text style={styles.promptIO}><Text style={styles.promptIOStrong}>Out:</Text> {prompt.output}</Text>
                </View>
              </View>
            ))}
          </View>
        </Card>

        <Card style={styles.savingsCard}>
          <Text style={styles.cardEyebrow}>WHY THE COST DROPS</Text>
          <View style={styles.comparisonBlock}>
            <Text style={styles.comparisonLabel}>MONOLITHIC BASELINE</Text>
            <Text style={styles.formula}>full transcript × several strong prompts</Text>
          </View>
          <View style={styles.vsLine}><View style={styles.vsRule} /><Text style={styles.vsText}>BECOMES</Text><View style={styles.vsRule} /></View>
          <View style={[styles.comparisonBlock, styles.comparisonOptimized]}>
            <Text style={[styles.comparisonLabel, styles.comparisonLabelOptimized]}>OPTIMIZED ROUTE</Text>
            <Text style={styles.formula}>lower-cost window extraction + compact synthesis</Text>
            <Text style={styles.formulaAccent}>+ escalation rate × targeted strong repair</Text>
          </View>
          <View style={styles.savingRules}>
            <SavingRule icon="cached" text="Reuse transcripts and extracted candidates" />
            <SavingRule icon="code-braces" text="Keep deterministic work out of LLMs" />
            <SavingRule icon="target" text="Use the strong model for failed units only" />
          </View>
        </Card>
      </View>
    </AppShell>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return <View style={styles.legendItem}><View style={[styles.legendDot, { backgroundColor: color }]} /><Text style={styles.legendText}>{label}</Text></View>;
}

function SavingRule({ icon, text }: { icon: 'cached' | 'code-braces' | 'target'; text: string }) {
  return (
    <View style={styles.savingRule}>
      <MaterialCommunityIcons name={icon} size={18} color={colors.green} />
      <Text style={styles.savingRuleText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  intro: { gap: spacing.sm },
  eyebrow: { color: colors.coralDark, fontFamily: font.medium, fontSize: 9, letterSpacing: 1.2 },
  principleCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg, backgroundColor: colors.pine, borderColor: colors.pine, ...shadowNone },
  principleMark: { width: 52, height: 52, borderRadius: 17, backgroundColor: 'rgba(255,255,255,0.12)', alignItems: 'center', justifyContent: 'center' },
  principleCopy: { flex: 1, gap: 5 },
  principleKicker: { color: '#A9CCC0', fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  principleText: { color: colors.white, fontFamily: font.medium, fontSize: 15, lineHeight: 23 },
  legend: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg, flexWrap: 'wrap' },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot: { width: 8, height: 8, borderRadius: 4 },
  legendText: { color: colors.inkMuted, fontSize: 10 },
  flow: { flexDirection: 'row', alignItems: 'stretch' },
  flowNarrow: { flexDirection: 'column' },
  flowUnit: { flex: 1, minWidth: 0, flexDirection: 'row', alignItems: 'center' },
  flowUnitNarrow: { flexDirection: 'column' },
  stageCard: { flex: 1, alignSelf: 'stretch', minHeight: 230, padding: spacing.lg, gap: spacing.sm, ...shadowNone },
  stageCardStrong: { borderColor: colors.coral },
  stageTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  stageNumber: { color: colors.inkFaint, fontFamily: font.mono, fontSize: 9 },
  stageIcon: { width: 36, height: 36, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  stageIconFree: { backgroundColor: colors.greenSoft },
  stageIconCheap: { backgroundColor: colors.blueSoft },
  stageIconStrong: { backgroundColor: colors.coralSoft },
  stageTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 13, lineHeight: 18 },
  stageBody: { flex: 1, color: colors.inkMuted, fontSize: 10, lineHeight: 16 },
  routeBadge: { alignSelf: 'flex-start', borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 5 },
  routeBadgeFree: { backgroundColor: colors.greenSoft },
  routeBadgeCheap: { backgroundColor: colors.blueSoft },
  routeBadgeStrong: { backgroundColor: colors.coralSoft },
  routeText: { fontFamily: font.medium, fontSize: 8 },
  routeTextFree: { color: colors.green },
  routeTextCheap: { color: colors.blue },
  routeTextStrong: { color: colors.coralDark },
  connector: { width: 22, alignItems: 'center', justifyContent: 'center' },
  connectorNarrow: { width: '100%', height: 28 },
  detailGrid: { flexDirection: 'row', alignItems: 'stretch', gap: spacing.xl },
  detailGridNarrow: { flexDirection: 'column' },
  promptCard: { flex: 1, gap: spacing.lg, ...shadowNone },
  savingsCard: { flex: 1, gap: spacing.lg, backgroundColor: colors.surface, ...shadowNone },
  cardEyebrow: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 9, letterSpacing: 1.1 },
  promptList: { gap: spacing.lg },
  promptRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md },
  promptIndex: { width: 32, height: 32, borderRadius: 11, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.blueSoft },
  promptIndexText: { color: colors.blue, fontFamily: font.medium, fontSize: 11 },
  promptCopy: { flex: 1, gap: 3 },
  promptLabel: { color: colors.blue, fontFamily: font.medium, fontSize: 7, letterSpacing: 0.8 },
  promptTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 13 },
  promptIO: { color: colors.inkMuted, fontSize: 10, lineHeight: 15 },
  promptIOStrong: { color: colors.ink, fontFamily: font.medium },
  comparisonBlock: { gap: spacing.sm, padding: spacing.lg, borderRadius: radius.md, backgroundColor: colors.surfaceMuted },
  comparisonOptimized: { backgroundColor: colors.greenSoft },
  comparisonLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 0.8 },
  comparisonLabelOptimized: { color: colors.green },
  formula: { color: colors.ink, fontFamily: font.mono, fontSize: 12, lineHeight: 18 },
  formulaAccent: { color: colors.green, fontFamily: font.mono, fontSize: 11, lineHeight: 17 },
  vsLine: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  vsRule: { flex: 1, height: 1, backgroundColor: colors.border },
  vsText: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 0.8 },
  savingRules: { gap: spacing.md },
  savingRule: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  savingRuleText: { flex: 1, color: colors.inkMuted, fontSize: 11 },
});
