import { describe, expect, it } from 'vitest';

import type { Citation, Topic } from '@/types/api';

import { buildMindMap, mindMapToMarkdown, type MindMapNode } from './projection';

const citation = (segment: string, start_ms: number): Citation => ({
  recording_id: 'recording-1',
  transcript_version: 1,
  segment_id: segment,
  start_ms,
  end_ms: start_ms + 1_000,
});

const topic = (label: string, parent?: string, start = 0): Topic => ({
  label,
  parent,
  intervals: [{ start_ms: start, end_ms: start + 2_000 }],
  evidence: [citation(`segment-${start}`, start)],
});

describe('deterministic mind map projection', () => {
  it('creates a stable hierarchy independent of topic input order', () => {
    const topics = [topic('API', 'Architecture', 4_000), topic('Architecture', undefined, 0), topic('Upload', undefined, 8_000)];
    const forward = buildMindMap('Design review', topics);
    const reverse = buildMindMap('Design review', [...topics].reverse());

    expect(reverse).toEqual(forward);
    expect(forward.nodeCount).toBe(3);
    expect(forward.children.map((node) => node.label)).toEqual(['Architecture', 'Upload']);
    expect(forward.children[0]?.children.map((node) => node.label)).toEqual(['API']);
  });

  it('merges repeated topic windows and deduplicates their evidence', () => {
    const repeated = topic(' Browser   upload ', undefined, 2_000);
    const map = buildMindMap('  Intelligent Audio Analysis   demo  ', [repeated, repeated, topic('browser upload', undefined, 6_000)]);
    const reversed = buildMindMap('  Intelligent Audio Analysis   demo  ', [topic('browser upload', undefined, 6_000), repeated]);

    expect(map.title).toBe('Intelligent Audio Analysis demo');
    expect(reversed).toEqual(map);
    expect(map.nodeCount).toBe(1);
    expect(map.children[0]?.label).toBe('Browser upload');
    expect(map.children[0]?.evidence.map((item) => item.start_ms)).toEqual([2_000, 6_000]);
    expect(map.children[0]?.intervals.map((item) => item.start_ms)).toEqual([2_000, 6_000]);
  });

  it('keeps orphaned and cyclic topics visible without recursion', () => {
    const map = buildMindMap('Review', [
      topic('Orphan', 'Missing'),
      topic('A', 'B'),
      topic('B', 'A'),
    ]);
    const flattened = flatten(map.children);

    expect(flattened).toHaveLength(3);
    expect(new Set(flattened.map((node) => node.label))).toEqual(new Set(['A', 'B', 'Orphan']));
  });

  it('exports the projection as nested Markdown with source timestamps', () => {
    const map = buildMindMap('Design review', [topic('Architecture'), topic('API', 'Architecture', 65_000)]);

    expect(mindMapToMarkdown(map)).toBe(
      '# Design review\n\n_2 topics projected from canonical intelligence._\n\n- Architecture — source 0:00\n  - API — source 1:05\n',
    );
  });
});

function flatten(nodes: MindMapNode[]): MindMapNode[] {
  return nodes.flatMap((node) => [node, ...flatten(node.children)]);
}
