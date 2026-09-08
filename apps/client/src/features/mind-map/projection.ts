import type { Citation, Topic } from '@/types/api';

export interface MindMapNode {
  id: string;
  label: string;
  intervals: { start_ms: number; end_ms: number }[];
  evidence: Citation[];
  children: MindMapNode[];
}

export interface MindMapProjection {
  title: string;
  children: MindMapNode[];
  nodeCount: number;
}

interface MutableNode extends Omit<MindMapNode, 'children'> {
  key: string;
  parentLabel?: string;
  parent?: MutableNode;
  children: MutableNode[];
}

/**
 * Projects canonical topics into a stable tree without making another model call.
 * Repeated window-level topics are merged, missing parents attach to the root, and
 * malformed cycles are cut deterministically so the view can never recurse forever.
 */
export function buildMindMap(title: string, topics: Topic[]): MindMapProjection {
  const rootTitle = cleanLabel(title) || 'Recording topics';
  const grouped = new Map<string, { label: string; parentLabel?: string; topics: Topic[] }>();

  for (const topic of topics) {
    const label = cleanLabel(topic.label);
    if (!label) continue;
    const parentLabel = cleanLabel(topic.parent);
    const key = `${normalize(parentLabel)}\u0000${normalize(label)}`;
    const group = grouped.get(key);
    if (group) {
      group.topics.push(topic);
      group.label = preferredDisplayLabel(group.label, label);
      if (parentLabel) group.parentLabel = preferredDisplayLabel(group.parentLabel ?? parentLabel, parentLabel);
    }
    else grouped.set(key, { label, parentLabel: parentLabel || undefined, topics: [topic] });
  }

  const groups = [...grouped.entries()].sort(([keyA], [keyB]) => keyA.localeCompare(keyB));
  const nodes: MutableNode[] = groups.map(([key, group], index) => ({
    key,
    id: `mind-map-${slug(group.label)}-${index + 1}`,
    label: group.label,
    parentLabel: group.parentLabel,
    intervals: uniqueIntervals(group.topics.flatMap((topic) => topic.intervals ?? [])),
    evidence: uniqueCitations(group.topics.flatMap((topic) => topic.evidence ?? [])),
    children: [],
  }));

  const byLabel = new Map<string, MutableNode[]>();
  for (const node of nodes) {
    const matches = byLabel.get(normalize(node.label)) ?? [];
    matches.push(node);
    byLabel.set(normalize(node.label), matches);
  }

  for (const node of nodes) {
    if (!node.parentLabel || normalize(node.parentLabel) === normalize(node.label)) continue;
    const candidates = (byLabel.get(normalize(node.parentLabel)) ?? [])
      .filter((candidate) => candidate !== node)
      .sort(compareParentCandidates);
    node.parent = candidates[0];
  }

  // DFS follows parent pointers. Cutting the edge on the node that closes a cycle
  // is stable because nodes were created in a deterministic sort order.
  const state = new Map<string, 'visiting' | 'visited'>();
  const visit = (node: MutableNode) => {
    const current = state.get(node.key);
    if (current === 'visited') return;
    if (current === 'visiting') {
      node.parent = undefined;
      return;
    }
    state.set(node.key, 'visiting');
    if (node.parent) visit(node.parent);
    state.set(node.key, 'visited');
  };
  nodes.forEach(visit);

  for (const node of nodes) node.parent?.children.push(node);
  nodes.forEach((node) => node.children.sort(compareNodes));
  const roots = nodes.filter((node) => !node.parent).sort(compareNodes);

  return {
    title: rootTitle,
    children: roots.map(toPublicNode),
    nodeCount: nodes.length,
  };
}

export function mindMapToMarkdown(map: MindMapProjection): string {
  const lines = [`# ${map.title}`, '', `_${map.nodeCount} topic${map.nodeCount === 1 ? '' : 's'} projected from canonical intelligence._`, ''];
  const append = (node: MindMapNode, depth: number) => {
    const firstCitation = node.evidence[0];
    const source = firstCitation ? `; source ${formatTimestamp(firstCitation.start_ms)}` : '';
    lines.push(`${'  '.repeat(depth)}- ${node.label}${source}`);
    node.children.forEach((child) => append(child, depth + 1));
  };
  map.children.forEach((node) => append(node, 0));
  return `${lines.join('\n').trimEnd()}\n`;
}

function toPublicNode(node: MutableNode): MindMapNode {
  return {
    id: node.id,
    label: node.label,
    intervals: node.intervals,
    evidence: node.evidence,
    children: node.children.map(toPublicNode),
  };
}

function compareParentCandidates(a: MutableNode, b: MutableNode): number {
  const depthHint = Number(Boolean(a.parentLabel)) - Number(Boolean(b.parentLabel));
  return depthHint || compareNodes(a, b);
}

function compareNodes(a: Pick<MutableNode, 'label' | 'key'>, b: Pick<MutableNode, 'label' | 'key'>): number {
  return a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }) || a.key.localeCompare(b.key);
}

function uniqueIntervals(intervals: { start_ms: number; end_ms: number }[]) {
  const unique = new Map<string, { start_ms: number; end_ms: number }>();
  for (const interval of intervals) {
    if (!Number.isFinite(interval.start_ms) || !Number.isFinite(interval.end_ms)) continue;
    unique.set(`${interval.start_ms}:${interval.end_ms}`, interval);
  }
  return [...unique.values()].sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms);
}

function uniqueCitations(citations: Citation[]) {
  const unique = new Map<string, Citation>();
  for (const citation of citations) {
    const key = `${citation.recording_id}:${citation.transcript_version}:${citation.segment_id}:${citation.start_ms}:${citation.end_ms}`;
    if (!unique.has(key)) unique.set(key, citation);
  }
  return [...unique.values()].sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms || a.segment_id.localeCompare(b.segment_id));
}

function cleanLabel(value?: string | null): string {
  return value?.trim().replace(/\s+/g, ' ') ?? '';
}

function normalize(value?: string): string {
  return cleanLabel(value).toLocaleLowerCase('en-US');
}

function slug(value: string): string {
  return normalize(value).replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'topic';
}

function preferredDisplayLabel(a: string, b: string): string {
  return a < b ? a : b;
}

function formatTimestamp(milliseconds: number): string {
  const total = Math.max(0, Math.round(milliseconds / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`;
}
