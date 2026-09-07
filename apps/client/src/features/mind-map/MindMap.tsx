import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, CitationChip, Notice, SectionTitle } from '@/components/ui';
import { formatDuration } from '@/lib/format';
import { downloadText } from '@/platform/download';
import { colors, font, radius, spacing } from '@/theme';
import type { Topic } from '@/types/api';

import { buildMindMap, mindMapToMarkdown, type MindMapNode } from './projection';

export function MindMap({
  recordingTitle,
  intelligenceTitle,
  topics,
  onSeek,
}: {
  recordingTitle: string;
  intelligenceTitle: string;
  topics: Topic[];
  onSeek(ms: number): void;
}) {
  const map = useMemo(() => buildMindMap(intelligenceTitle || recordingTitle, topics), [intelligenceTitle, recordingTitle, topics]);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<Error>();

  const exportMarkdown = async () => {
    setExporting(true);
    setError(undefined);
    try {
      const safeName = recordingTitle.trim().replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-|-$/g, '') || 'recording';
      await downloadText(mindMapToMarkdown(map), `${safeName}-mind-map.md`, 'text/markdown;charset=utf-8');
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('The mind map could not be exported.'));
    } finally {
      setExporting(false);
    }
  };

  return (
    <Card style={styles.card}>
      <SectionTitle
        title="Topic mind map"
        subtitle="A deterministic projection of canonical topics—opening or exporting it never calls the LLM."
        action={map.nodeCount ? <Button size="sm" variant="secondary" icon="download-outline" loading={exporting} onPress={exportMarkdown}>Markdown</Button> : undefined}
      />
      {error ? <Notice tone="error" title="Mind map export failed">{error.message}</Notice> : null}
      {!map.nodeCount ? (
        <View style={styles.empty}>
          <MaterialCommunityIcons name="graph-outline" size={24} color={colors.inkFaint} />
          <Text style={styles.emptyTitle}>No cited topics were extracted</Text>
          <Text style={styles.emptyBody}>The canonical intelligence remains available; the map will appear when at least one topic is published.</Text>
        </View>
      ) : (
        <View accessibilityLabel={`Mind map for ${map.title}, ${map.nodeCount} topics`}>
          <View style={styles.rootWrap}>
            <View style={styles.rootNode}>
              <MaterialCommunityIcons name="hub-outline" size={19} color={colors.white} />
              <View style={styles.rootCopy}>
                <Text style={styles.rootEyebrow}>RECORDING</Text>
                <Text style={styles.rootLabel}>{map.title}</Text>
                <Text style={styles.rootCount}>{map.nodeCount} topic{map.nodeCount === 1 ? '' : 's'}</Text>
              </View>
            </View>
            <View style={styles.trunk} />
          </View>
          <View style={styles.branchGrid}>
            {map.children.map((node) => <Branch key={node.id} node={node} onSeek={onSeek} />)}
          </View>
        </View>
      )}
    </Card>
  );
}

function Branch({ node, onSeek, depth = 0 }: { node: MindMapNode; onSeek(ms: number): void; depth?: number }) {
  const citation = node.evidence[0];
  const firstInterval = node.intervals[0];

  return (
    <View style={[styles.branch, depth === 0 && styles.topBranch]}>
      <View style={styles.node}>
        {citation ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`${node.label}, play first supporting source at ${formatDuration(citation.start_ms)}`}
            onPress={() => onSeek(citation.start_ms)}
            style={({ pressed }) => [styles.nodeTarget, pressed && styles.nodeTargetPressed]}
          >
            <View style={[styles.nodeDot, depth > 0 && styles.nodeDotNested]} />
            <NodeCopy node={node} firstInterval={firstInterval} />
          </Pressable>
        ) : (
          <View style={styles.nodeTarget}>
            <View style={[styles.nodeDot, depth > 0 && styles.nodeDotNested]} />
            <NodeCopy node={node} firstInterval={firstInterval} />
          </View>
        )}
        {citation ? <CitationChip citation={citation} onPress={() => onSeek(citation.start_ms)} /> : null}
      </View>
      {node.children.length ? (
        <View style={styles.children}>
          {node.children.map((child) => <Branch key={child.id} node={child} onSeek={onSeek} depth={depth + 1} />)}
        </View>
      ) : null}
    </View>
  );
}

function NodeCopy({ node, firstInterval }: { node: MindMapNode; firstInterval?: { start_ms: number; end_ms: number } }) {
  return (
    <View style={styles.nodeCopy}>
      <Text style={styles.nodeLabel}>{node.label}</Text>
      <Text style={styles.nodeMeta}>
        {node.evidence.length} source{node.evidence.length === 1 ? '' : 's'}
        {firstInterval ? ` · ${formatDuration(firstInterval.start_ms)}–${formatDuration(firstInterval.end_ms)}` : ''}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { width: '100%', gap: spacing.xl },
  empty: { alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xxl },
  emptyTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 14 },
  emptyBody: { maxWidth: 520, color: colors.inkMuted, fontSize: 12, lineHeight: 19, textAlign: 'center' },
  rootWrap: { alignItems: 'center' },
  rootNode: { width: '100%', maxWidth: 480, minHeight: 82, padding: spacing.lg, borderRadius: radius.lg, backgroundColor: colors.pine, flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  rootCopy: { flex: 1, gap: 3 },
  rootEyebrow: { color: colors.pineSoft, fontFamily: font.medium, fontSize: 8, letterSpacing: 1.1 },
  rootLabel: { color: colors.white, fontFamily: font.medium, fontSize: 17, lineHeight: 23 },
  rootCount: { color: colors.pineSoft, fontSize: 10 },
  trunk: { width: 2, height: spacing.xl, backgroundColor: colors.borderStrong },
  branchGrid: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'center', gap: spacing.lg },
  topBranch: { flex: 1, minWidth: 240, maxWidth: 480 },
  branch: { gap: spacing.sm },
  node: { minHeight: 62, padding: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.canvas, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  nodeTarget: { flex: 1, minWidth: 0, minHeight: 36, borderRadius: radius.sm, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  nodeTargetPressed: { backgroundColor: colors.coralSoft },
  nodeDot: { width: 10, height: 10, borderRadius: radius.pill, backgroundColor: colors.coral },
  nodeDotNested: { width: 8, height: 8, backgroundColor: colors.blue },
  nodeCopy: { flex: 1, minWidth: 100, gap: 3 },
  nodeLabel: { color: colors.ink, fontFamily: font.medium, fontSize: 13, lineHeight: 18 },
  nodeMeta: { color: colors.inkMuted, fontSize: 9 },
  children: { marginLeft: spacing.lg, paddingLeft: spacing.md, borderLeftWidth: 2, borderLeftColor: colors.border, gap: spacing.sm },
});
