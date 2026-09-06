import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import {
  Button,
  Card,
  Chip,
  EmptyState,
  ErrorState,
  LoadingState,
  Notice,
  PageTitle,
  ProgressBar,
  SectionTitle,
  uiStyles,
} from '@/components/ui';
import { useResource } from '@/hooks/useResource';
import { api, unwrapItems } from '@/lib/api';
import { formatDate, formatMoney } from '@/lib/format';
import { useSession } from '@/providers/SessionProvider';
import { colors, font, radius, spacing } from '@/theme';
import type { CostEvent } from '@/types/api';

export default function CostLabScreen() {
  const { width } = useWindowDimensions();
  const { session, sync: syncSession } = useSession();
  const [recordingId, setRecordingId] = useState<string>();
  const recordingsResource = useResource(() => api.recordings(), [session?.workspace.id]);
  const recordings = recordingsResource.data ? unwrapItems(recordingsResource.data) : [];
  const resource = useResource(() => api.costs(recordingId), [session?.workspace.id, recordingId]);
  useEffect(() => {
    void syncSession();
  }, [syncSession]);
  const costs = resource.data;
  const maxStage = useMemo(() => Math.max(0.000001, ...(costs?.by_stage.map((item) => item.amount_usd) ?? [0])), [costs]);
  const budgetUse = costs ? Math.min(100, (costs.estimated_incurred_usd / (costs.budget_usd || 50)) * 100) : 0;

  return (
    <AppShell>
      <PageTitle
        title="Cost lab"
        subtitle="Trace each billed attempt, cache reuse, and targeted escalation. Estimates remain distinct from reconciled spend and modeled scenarios."
        action={<Button size="sm" variant="secondary" icon="refresh" loading={resource.refreshing} onPress={resource.reload}>Refresh ledger</Button>}
      />
      <Card style={styles.filterCard}>
        <Text style={styles.filterLabel}>RECORDING SCOPE</Text>
        <View style={styles.filters}>
          <Chip label="Whole workspace" selected={!recordingId} onPress={() => setRecordingId(undefined)} />
          {recordings.map((recording) => <Chip key={recording.id} label={recording.title} selected={recording.id === recordingId} onPress={() => setRecordingId(recording.id)} />)}
        </View>
      </Card>

      {resource.loading ? <Card><LoadingState label="Reconciling cost view…" /></Card> : resource.error ? <Card><ErrorState error={resource.error} onRetry={resource.reload} /></Card> : !costs ? null : (
        <>
          <View style={styles.metrics}>
            <MetricCard icon="cash-clock" label="Estimated incurred" value={formatMoney(costs.estimated_incurred_usd)} hint="Before invoice reconciliation" tone="coral" />
            <MetricCard icon="check-decagram-outline" label="Reconciled" value={formatMoney(costs.reconciled_usd)} hint="Confirmed provider usage" tone="green" />
            <MetricCard icon="chart-waterfall" label="Modeled delta" value={formatMoney(costs.modeled_delta_usd)} hint="Baseline minus optimized" tone="blue" />
            <Card style={styles.metricCard}>
              <View style={uiStyles.rowBetween}><Text style={styles.metricLabel}>Budget</Text><Text style={styles.metricValue}>{formatMoney(costs.budget_usd, 0)}</Text></View>
              <ProgressBar value={budgetUse} />
              <Text style={styles.metricHint}>{budgetUse.toFixed(1)}% incurred · durable admission enabled for instrumented paths</Text>
            </Card>
          </View>

          <Notice tone={costs.quality_gate_passed ? 'success' : 'warning'} title={costs.quality_gate_passed ? 'Configured route passed the recorded quality gate' : 'No quality-gate pass is claimed'}>
            {costs.quality_gate_passed
              ? `The result applies to the recorded fixture corpus and baseline ${costs.baseline_version ?? 'version'}; it is not a production quality or savings claim.`
              : 'Modeled deltas must not be presented as savings until both routes produce the same required assets and the optimized route passes the fixture gate.'}
          </Notice>

          <View style={[styles.analysisGrid, width < 980 && styles.analysisGridNarrow]}>
            <Card style={styles.waterfallCard}>
              <SectionTitle title="Capability-equivalent scenario" subtitle={`Baseline ${costs.baseline_version ?? 'not versioned'}`} />
              <View style={styles.comparison}>
                <ComparisonBar label="Strong baseline" value={costs.baseline_estimate_usd} max={Math.max(costs.baseline_estimate_usd, costs.optimized_estimate_usd, 0.000001)} color={colors.inkMuted} />
                <ComparisonBar label="Optimized route" value={costs.optimized_estimate_usd} max={Math.max(costs.baseline_estimate_usd, costs.optimized_estimate_usd, 0.000001)} color={colors.coral} />
              </View>
              <View style={styles.deltaBox}>
                <View><Text style={styles.deltaKicker}>MODELED SCENARIO DELTA</Text><Text style={styles.deltaValue}>{formatMoney(costs.modeled_delta_usd)}</Text></View>
                <MaterialCommunityIcons name="minus-circle-outline" size={28} color={colors.green} />
              </View>
              <View style={styles.avoidedGrid}>
                <SmallMetric label="Audio seconds" value={(costs.avoided_audio_seconds ?? 0).toLocaleString()} />
                <SmallMetric label="Model calls" value={(costs.avoided_calls ?? 0).toLocaleString()} />
                <SmallMetric label="Tokens" value={(costs.avoided_tokens ?? 0).toLocaleString()} />
                <SmallMetric label="Cache hits" value={(costs.cache_hits ?? 0).toLocaleString()} />
              </View>
              <Text style={styles.disclaimer}>This is a finite modeled scenario—not Pocket{"'"}s current implementation, incurred savings, or a universal percentage. Skipped required output never counts.</Text>
            </Card>
            <Card style={styles.stageCard}>
              <SectionTitle title="Spend by stage" subtitle="Direct variable model cost only" />
              <View style={styles.stageList}>
                {costs.by_stage.map((stage) => (
                  <View key={stage.stage} style={styles.stageRow}>
                    <View style={uiStyles.rowBetween}>
                      <Text style={styles.stageName}>{stage.stage.replace(/_/g, ' ')}</Text>
                      <Text style={styles.stageAmount}>{formatMoney(stage.amount_usd)}</Text>
                    </View>
                    <View style={styles.stageTrack}><View style={[styles.stageFill, { width: `${(stage.amount_usd / maxStage) * 100}%` }]} /></View>
                  </View>
                ))}
                {!costs.by_stage.length ? <Text style={styles.emptyInline}>No stage costs in this scope.</Text> : null}
              </View>
              <Notice tone="info" title="Costs stay separated">Direct AI, object/egress, allocated fixed platform cost, and modeled avoided cost are not blended.</Notice>
            </Card>
          </View>

          <Card style={styles.ledgerCard}>
            <SectionTitle title="Attempt ledger" subtitle={`${costs.events.length} attempt-scoped events · ${costs.period}`} />
            {!costs.events.length ? (
              <EmptyState icon="receipt-text-outline" title="No cost events in this scope" body="Cache hits and reusable operations will still appear as zero-provider-cost events." />
            ) : (
              <View style={styles.ledger}>
                <View style={styles.tableHeader}>
                  <Text style={[styles.headerCell, styles.routeColumn]}>ROUTE / STAGE</Text>
                  {width >= 800 ? <Text style={[styles.headerCell, styles.recordingColumn]}>RECORDING</Text> : null}
                  {width >= 560 ? <Text style={[styles.headerCell, styles.unitsColumn]}>BILLED UNITS</Text> : null}
                  <Text style={[styles.headerCell, styles.costColumn]}>COST</Text>
                </View>
                {costs.events.map((event) => <CostRow key={event.id} event={event} wide={width >= 800} showUnits={width >= 560} />)}
              </View>
            )}
          </Card>
        </>
      )}
    </AppShell>
  );
}

function MetricCard({ icon, label, value, hint, tone }: { icon: 'cash-clock' | 'check-decagram-outline' | 'chart-waterfall'; label: string; value: string; hint: string; tone: 'coral' | 'green' | 'blue' }) {
  const toneColor = tone === 'coral' ? colors.coralDark : tone === 'green' ? colors.green : colors.blue;
  const background = tone === 'coral' ? colors.coralSoft : tone === 'green' ? colors.greenSoft : colors.blueSoft;
  return (
    <Card style={styles.metricCard}>
      <View style={uiStyles.rowBetween}>
        <View style={[styles.metricIcon, { backgroundColor: background }]}><MaterialCommunityIcons name={icon} size={19} color={toneColor} /></View>
        <Text style={styles.metricValue}>{value}</Text>
      </View>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={styles.metricHint}>{hint}</Text>
    </Card>
  );
}

function ComparisonBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  return (
    <View style={styles.comparisonRow}>
      <View style={uiStyles.rowBetween}><Text style={styles.comparisonLabel}>{label}</Text><Text style={styles.comparisonAmount}>{formatMoney(value)}</Text></View>
      <View style={styles.comparisonTrack}><View style={[styles.comparisonFill, { width: `${(value / max) * 100}%`, backgroundColor: color }]} /></View>
    </View>
  );
}

function SmallMetric({ label, value }: { label: string; value: string }) {
  return <View style={styles.smallMetric}><Text style={styles.smallValue}>{value}</Text><Text style={styles.smallLabel}>{label}</Text></View>;
}

function CostRow({ event, wide, showUnits }: { event: CostEvent; wide: boolean; showUnits: boolean }) {
  return (
    <View style={styles.costRow}>
      <View style={styles.routeColumn}>
        <Text style={styles.routeName}>{event.model_alias}</Text>
        <Text style={styles.routeDetail}>{event.stage} · {event.resolved_model ?? 'unresolved version'}</Text>
        <View style={styles.flags}>
          {event.cached ? <Chip label="Cache hit" /> : null}
          {event.reused ? <Chip label="Artifact reuse" /> : null}
          {event.escalation_reason ? <Chip label={`Escalated: ${event.escalation_reason}`} /> : null}
        </View>
      </View>
      {wide ? <View style={styles.recordingColumn}><Text numberOfLines={1} style={styles.recordingText}>{event.recording_title ?? 'Ask / workspace'}</Text><Text style={styles.eventDate}>{formatDate(event.created_at, true)}</Text></View> : null}
      {showUnits ? <Text numberOfLines={2} style={[styles.units, styles.unitsColumn]}>{event.billed_units}</Text> : null}
      <View style={styles.costColumn}>
        <Text style={styles.costText}>{formatMoney(event.reconciled_cost_usd ?? event.estimated_cost_usd)}</Text>
        <Text style={styles.costState}>{event.reconciled_cost_usd === undefined ? 'estimated' : 'reconciled'}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  filterCard: { padding: spacing.md, shadowOpacity: 0, gap: spacing.sm },
  filterLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  filters: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  metrics: { flexDirection: 'row', gap: spacing.lg, flexWrap: 'wrap' },
  metricCard: { flex: 1, minWidth: 200, gap: spacing.sm, shadowOpacity: 0 },
  metricIcon: { width: 34, height: 34, borderRadius: 11, alignItems: 'center', justifyContent: 'center' },
  metricValue: { color: colors.ink, fontFamily: font.medium, fontSize: 22, letterSpacing: -0.5 },
  metricLabel: { color: colors.inkMuted, fontSize: 11 },
  metricHint: { color: colors.inkFaint, fontSize: 9 },
  analysisGrid: { flexDirection: 'row', alignItems: 'stretch', gap: spacing.xl },
  analysisGridNarrow: { flexDirection: 'column' },
  waterfallCard: { flex: 1.15, gap: spacing.xl },
  stageCard: { flex: 0.85, gap: spacing.xl },
  comparison: { gap: spacing.lg },
  comparisonRow: { gap: spacing.sm },
  comparisonLabel: { color: colors.inkMuted, fontSize: 11 },
  comparisonAmount: { color: colors.ink, fontFamily: font.medium, fontSize: 12 },
  comparisonTrack: { height: 12, borderRadius: 6, backgroundColor: colors.surfaceMuted, overflow: 'hidden' },
  comparisonFill: { height: 12, borderRadius: 6 },
  deltaBox: { minHeight: 100, borderRadius: radius.lg, padding: spacing.lg, backgroundColor: colors.greenSoft, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  deltaKicker: { color: colors.green, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  deltaValue: { color: colors.ink, fontFamily: font.medium, fontSize: 30, letterSpacing: -0.8, marginTop: 4 },
  avoidedGrid: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  smallMetric: { flex: 1, minWidth: 100, padding: spacing.md, borderRadius: radius.md, backgroundColor: colors.canvas, gap: 3 },
  smallValue: { color: colors.ink, fontFamily: font.medium, fontSize: 17 },
  smallLabel: { color: colors.inkMuted, fontSize: 9 },
  disclaimer: { color: colors.inkFaint, fontSize: 9, lineHeight: 14 },
  stageList: { gap: spacing.lg },
  stageRow: { gap: spacing.sm },
  stageName: { color: colors.inkMuted, fontSize: 11, textTransform: 'capitalize' },
  stageAmount: { color: colors.ink, fontFamily: font.mono, fontSize: 10 },
  stageTrack: { height: 7, borderRadius: 4, backgroundColor: colors.surfaceMuted, overflow: 'hidden' },
  stageFill: { height: 7, borderRadius: 4, backgroundColor: colors.coral },
  emptyInline: { color: colors.inkFaint, fontSize: 11, fontStyle: 'italic' },
  ledgerCard: { gap: spacing.xl },
  ledger: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, overflow: 'hidden' },
  tableHeader: { minHeight: 38, paddingHorizontal: spacing.md, flexDirection: 'row', alignItems: 'center', gap: spacing.md, backgroundColor: colors.canvas },
  headerCell: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 0.8 },
  costRow: { minHeight: 90, padding: spacing.md, flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderTopWidth: 1, borderTopColor: colors.border },
  routeColumn: { flex: 1.4, minWidth: 130, gap: 3 },
  recordingColumn: { flex: 1, minWidth: 90, gap: 3 },
  unitsColumn: { flex: 0.8, minWidth: 70 },
  costColumn: { width: 78, alignItems: 'flex-end', gap: 3 },
  routeName: { color: colors.ink, fontFamily: font.mono, fontSize: 11 },
  routeDetail: { color: colors.inkMuted, fontSize: 9 },
  flags: { flexDirection: 'row', gap: 4, flexWrap: 'wrap', marginTop: 5 },
  recordingText: { color: colors.ink, fontSize: 10 },
  eventDate: { color: colors.inkFaint, fontSize: 8 },
  units: { color: colors.inkMuted, fontFamily: font.mono, fontSize: 9 },
  costText: { color: colors.ink, fontFamily: font.medium, fontSize: 11 },
  costState: { color: colors.inkFaint, fontSize: 8 },
});
