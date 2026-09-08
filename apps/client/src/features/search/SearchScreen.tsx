import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import {
  Button,
  Card,
  Chip,
  CitationChip,
  EmptyState,
  Field,
  Input,
  Notice,
  PageTitle,
  Segmented,
  uiStyles,
} from '@/components/ui';
import { useResource } from '@/hooks/useResource';
import { api, unwrapItems } from '@/lib/api';
import { formatDuration } from '@/lib/format';
import { RequestGeneration } from '@/lib/requestGeneration';
import { useSession } from '@/providers/SessionProvider';
import { colors, font, radius, shadowNone, spacing } from '@/theme';
import type { SearchFilters, SearchResponse } from '@/types/api';

const suggestions = ['What was decided?', 'owner:unresolved', 'deadlines next week'];

export default function SearchScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const { session } = useSession();
  const recordingsResource = useResource(() => api.recordings(), [session?.workspace.id]);
  const recordings = recordingsResource.data ? unwrapItems(recordingsResource.data) : [];
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<SearchFilters['mode']>('exact');
  const [recordingId, setRecordingId] = useState<string>();
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [speaker, setSpeaker] = useState('');
  const [topic, setTopic] = useState('');
  const [actionState, setActionState] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [result, setResult] = useState<SearchResponse>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error>();
  const [hasSearched, setHasSearched] = useState(false);
  const searchRequests = useRef(new RequestGeneration());
  useEffect(() => () => searchRequests.current.invalidate(), []);

  const filterCount = useMemo(
    () => [recordingId, dateFrom, dateTo, speaker, topic, actionState].filter(Boolean).length,
    [recordingId, dateFrom, dateTo, speaker, topic, actionState],
  );

  const search = async (term = query) => {
    const cleaned = term.trim();
    if (!cleaned) return;
    setQuery(cleaned);
    setLoading(true);
    setError(undefined);
    setHasSearched(true);
    const request = searchRequests.current.begin();
    try {
      const response = await api.search(cleaned, {
        mode,
        recording_id: recordingId,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        speaker: speaker || undefined,
        topic: topic || undefined,
        action_state: actionState || undefined,
      });
      if (searchRequests.current.isCurrent(request)) setResult(response);
    } catch (caught) {
      if (searchRequests.current.isCurrent(request)) {
        setResult(undefined);
        setError(caught instanceof Error ? caught : new Error('Search failed'));
      }
    } finally {
      if (searchRequests.current.isCurrent(request)) setLoading(false);
    }
  };

  const clearFilters = () => {
    setRecordingId(undefined); setDateFrom(''); setDateTo(''); setSpeaker(''); setTopic(''); setActionState('');
  };

  return (
    <AppShell>
      <PageTitle
        title="Search the evidence"
        subtitle="The fixture build uses permission-filtered lexical retrieval. Every result resolves to an authoritative transcript span; semantic retrieval stays visible as a gated extension."
      />
      <Card style={styles.searchCard}>
        <View style={styles.searchBar}>
          <MaterialCommunityIcons name="magnify" size={24} color={colors.inkFaint} />
          <Input
            accessibilityLabel="Search recordings"
            placeholder="Search a phrase, person, decision, or task…"
            value={query}
            onChangeText={setQuery}
            onSubmitEditing={() => search()}
            returnKeyType="search"
            style={styles.searchInput}
          />
          <Button loading={loading} onPress={() => search()}>Search</Button>
        </View>
        <View style={styles.searchOptions}>
          <Segmented<SearchFilters['mode']>
            value={mode}
            onChange={setMode}
            options={[
              { value: 'exact', label: 'Exact', description: 'Words and SQL facts' },
              { value: 'mixed', label: 'Mixed', description: 'Embedding adapter required', disabled: true },
              { value: 'semantic', label: 'Semantic', description: 'Embedding adapter required', disabled: true },
            ]}
          />
          <Button variant="ghost" icon={showFilters ? 'tune-variant' : 'tune'} onPress={() => setShowFilters((value) => !value)}>
            Filters{filterCount ? ` (${filterCount})` : ''}
          </Button>
        </View>
        {showFilters ? (
          <View style={styles.filterPanel}>
            <Field label="Recording">
              <View style={styles.chipWrap}>
                <Chip label="Any recording" selected={!recordingId} onPress={() => setRecordingId(undefined)} />
                {recordings.map((recording) => (
                  <Chip key={recording.id} label={recording.title} selected={recordingId === recording.id} onPress={() => setRecordingId(recording.id)} />
                ))}
              </View>
            </Field>
            <View style={styles.filterGrid}>
              <Field label="From date"><Input placeholder="YYYY-MM-DD" value={dateFrom} onChangeText={setDateFrom} /></Field>
              <Field label="To date"><Input placeholder="YYYY-MM-DD" value={dateTo} onChangeText={setDateTo} /></Field>
              <Field label="Speaker"><Input placeholder="Name or label" value={speaker} onChangeText={setSpeaker} /></Field>
              <Field label="Topic"><Input placeholder="Topic" value={topic} onChangeText={setTopic} /></Field>
              <Field label="Action state"><Input placeholder="open, done, unresolved" value={actionState} onChangeText={setActionState} /></Field>
            </View>
            <Button size="sm" variant="ghost" onPress={clearFilters}>Clear filters</Button>
          </View>
        ) : null}
      </Card>

      {!hasSearched ? (
        <Card style={styles.discoveryCard}>
          <View style={styles.discoveryIcon}><MaterialCommunityIcons name="text-search" size={29} color={colors.pine} /></View>
          <Text style={styles.discoveryTitle}>Find the moment, not just the file</Text>
          <Text style={styles.discoveryBody}>Try an exact phrase, a concept, or a structured question about owners, deadlines, dates, status, or counts.</Text>
          <View style={styles.suggestions}>
            {suggestions.map((item) => <Chip key={item} label={item} icon="arrow-top-right" onPress={() => search(item)} />)}
          </View>
        </Card>
      ) : null}
      {error ? <Notice tone="error" title="Search failed">{error.message}</Notice> : null}
      {result && (result.semantic_available === false || result.effective_mode === 'lexical') && mode !== 'exact' ? (
        <Notice tone="warning" title="Semantic retrieval is not configured">
          {result.retrieval_note ?? 'The API used permission-filtered lexical retrieval for this request. Results are not being represented as embedding-based semantic matches.'}
        </Notice>
      ) : null}
      {hasSearched && !loading && !error && result ? (
        <View style={styles.resultsArea}>
          <View style={uiStyles.rowBetween}>
            <Text style={styles.resultsTitle}>{result.total ?? result.items.length} results</Text>
            <Text style={styles.resultsMeta}>{result.mode ?? mode}{result.took_ms !== undefined ? ` · ${result.took_ms} ms` : ''}</Text>
          </View>
          {!result.items.length ? (
            <Card><EmptyState icon="magnify-close" title="No accessible evidence matched" body="Try fewer filters or a different phrase. Search does not reveal recordings outside this workspace scope." /></Card>
          ) : (
            <View style={[styles.resultsGrid, width < 840 && styles.resultsGridNarrow]}>
              {result.items.map((item) => (
                <Pressable
                  key={item.id}
                  accessibilityRole="button"
                  accessibilityLabel={`Open ${item.recording_title} at ${formatDuration(item.start_ms)}`}
                  onPress={() => router.push(`/recordings/${item.recording_id}?seek=${item.start_ms}`)}
                  style={({ pressed }) => [styles.resultCard, width < 840 && styles.resultCardNarrow, pressed && styles.resultCardActive]}
                >
                  <View style={uiStyles.rowBetween}>
                    <Chip label={item.kind.replace('_', ' ')} />
                    {item.score !== undefined ? <Text style={styles.score}>rank {item.score.toFixed(2)}</Text> : null}
                  </View>
                  <Text style={styles.resultTitle}>{item.recording_title}</Text>
                  <Text numberOfLines={4} style={styles.snippet}>{item.snippet}</Text>
                  <View style={styles.resultMetaRow}>
                    {item.speaker ? <Text style={styles.sourceMeta}>{item.speaker}</Text> : null}
                    {item.topic ? <Text style={styles.sourceMeta}>#{item.topic}</Text> : null}
                  </View>
                  <CitationChip citation={item.citation} />
                </Pressable>
              ))}
            </View>
          )}
        </View>
      ) : null}
    </AppShell>
  );
}

const styles = StyleSheet.create({
  searchCard: { gap: spacing.lg },
  searchBar: { minHeight: 58, paddingLeft: spacing.lg, gap: spacing.sm, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.borderStrong, flexDirection: 'row', alignItems: 'center' },
  searchInput: { flex: 1, borderWidth: 0, backgroundColor: 'transparent', minWidth: 80 },
  searchOptions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.lg, flexWrap: 'wrap' },
  filterPanel: { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.lg, gap: spacing.lg },
  filterGrid: { flexDirection: 'row', gap: spacing.md, flexWrap: 'wrap' },
  chipWrap: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  discoveryCard: { minHeight: 300, alignItems: 'center', justifyContent: 'center', gap: spacing.md, ...shadowNone },
  discoveryIcon: { width: 64, height: 64, borderRadius: 22, backgroundColor: colors.pineSoft, alignItems: 'center', justifyContent: 'center' },
  discoveryTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 20, textAlign: 'center' },
  discoveryBody: { maxWidth: 560, color: colors.inkMuted, fontSize: 13, lineHeight: 20, textAlign: 'center' },
  suggestions: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap', justifyContent: 'center', marginTop: spacing.sm },
  resultsArea: { gap: spacing.lg },
  resultsTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 16 },
  resultsMeta: { color: colors.inkFaint, fontFamily: font.mono, fontSize: 10 },
  resultsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.lg },
  resultsGridNarrow: { flexDirection: 'column' },
  resultCard: { flex: 1, minWidth: 330, maxWidth: '49%', minHeight: 230, padding: spacing.xl, gap: spacing.md, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  resultCardNarrow: { width: '100%', minWidth: 0, maxWidth: '100%' },
  resultCardActive: { borderColor: colors.pine, transform: [{ translateY: -2 }] },
  resultTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 14 },
  snippet: { color: colors.inkMuted, fontSize: 14, lineHeight: 22 },
  resultMetaRow: { flexDirection: 'row', gap: spacing.sm },
  sourceMeta: { color: colors.coralDark, fontSize: 10 },
  score: { color: colors.inkFaint, fontFamily: font.mono, fontSize: 9 },
});
