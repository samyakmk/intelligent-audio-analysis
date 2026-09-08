import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import {
  Button,
  Card,
  Chip,
  CitationChip,
  ConfirmDialog,
  Field,
  Input,
  Notice,
  PageTitle,
  Segmented,
} from '@/components/ui';
import { useResource } from '@/hooks/useResource';
import { api, unwrapItems } from '@/lib/api';
import { canUseDeepAsk } from '@/features/capabilities/capabilities';
import { ProviderPolicyNotice } from '@/features/capabilities/ProviderPolicyNotice';
import { useSession } from '@/providers/SessionProvider';
import { useCapabilities } from '@/providers/CapabilitiesProvider';
import { colors, font, radius, shadowNone, spacing } from '@/theme';
import type { AskMessage, AskScope, AskSession } from '@/types/api';

type ScopeKind = AskScope['type'];

export default function AskScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const { session: authSession } = useSession();
  const { capabilities, loading: capabilitiesLoading } = useCapabilities();
  const deepAvailable = canUseDeepAsk(capabilities);
  const recordingsResource = useResource(() => api.recordings(), [authSession?.workspace.id]);
  const recordings = recordingsResource.data ? unwrapItems(recordingsResource.data).filter((item) => item.readiness.indexed_ready) : [];
  const [scopeKind, setScopeKind] = useState<ScopeKind>('library');
  const [recordingId, setRecordingId] = useState<string>();
  const [segmentIds, setSegmentIds] = useState('');
  const [askSession, setAskSession] = useState<AskSession>();
  const [messages, setMessages] = useState<AskMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error>();
  const [deepOpen, setDeepOpen] = useState(false);

  const scope = useMemo<AskScope | undefined>(() => {
    if (scopeKind === 'library') return { type: 'library' };
    if (!recordingId) return undefined;
    if (scopeKind === 'recording') return { type: 'recording', recording_id: recordingId };
    const ids = segmentIds.split(',').map((item) => item.trim()).filter(Boolean);
    return ids.length ? { type: 'selection', recording_id: recordingId, segment_ids: ids } : undefined;
  }, [scopeKind, recordingId, segmentIds]);

  const scopeLabel = scope?.type === 'library'
    ? `${authSession?.workspace.name ?? 'Current workspace'} library`
    : scope?.type === 'recording'
      ? recordings.find((item) => item.id === scope.recording_id)?.title ?? 'Selected recording'
      : scope?.type === 'selection'
        ? `${scope.segment_ids.length} selected transcript segments`
        : 'Choose a valid scope';

  const resetSession = () => {
    setAskSession(undefined);
    setMessages([]);
    setError(undefined);
  };

  const changeScope = (kind: ScopeKind) => {
    setScopeKind(kind);
    resetSession();
  };

  const send = async (deep = false) => {
    const question = draft.trim();
    if (!question || !scope || loading || (deep && !deepAvailable)) return;
    setError(undefined);
    setLoading(true);
    const userMessage: AskMessage = {
      id: `local-${Date.now()}`,
      role: 'user',
      content: question,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, userMessage]);
    setDraft('');
    try {
      const currentSession = askSession ?? await api.createAskSession(scope);
      if (!askSession) setAskSession(currentSession);
      const reply = await api.ask(currentSession.id, question, deep);
      setMessages((current) => [...current, reply.message]);
    } catch (caught) {
      setMessages((current) => current.filter((message) => message.id !== userMessage.id));
      setError(caught instanceof Error ? caught : new Error('Ask failed'));
      setDraft(question);
    } finally {
      setLoading(false);
      setDeepOpen(false);
    }
  };

  return (
    <AppShell>
      <PageTitle
        title="Ask Pocket"
        subtitle="Answers use a bounded, permission-filtered context pack. Returned citations must exactly match retrieved source spans."
      />
      <ProviderPolicyNotice />
      <View style={[styles.layout, width < 940 && styles.layoutNarrow]}>
        <View style={styles.chatColumn}>
          <Card style={styles.scopeBar}>
            <View style={styles.scopeIdentity}>
              <View style={styles.scopeIcon}><MaterialCommunityIcons name="target" size={18} color={colors.pine} /></View>
              <View style={styles.scopeCopy}>
                <Text style={styles.scopeKicker}>ANSWER SCOPE</Text>
                <Text numberOfLines={1} style={styles.scopeTitle}>{scopeLabel}</Text>
              </View>
            </View>
            <Text style={styles.scopeBudget}>$0.10 query ceiling</Text>
          </Card>

          <Card style={styles.chatCard}>
            {!messages.length ? (
              <View style={styles.welcome}>
                <View style={styles.askMark}><MaterialCommunityIcons name="message-processing-outline" size={31} color={colors.coralDark} /></View>
                <Text style={styles.welcomeTitle}>Ask only what the evidence can answer</Text>
                <Text style={styles.welcomeBody}>Pocket will cite the source moment—or explicitly abstain when accessible evidence is insufficient.</Text>
                <View style={styles.suggestions}>
                  {['What are the unresolved decisions?', 'Who owns the next steps?', 'Summarize risks with evidence'].map((item) => (
                    <Chip key={item} label={item} onPress={() => setDraft(item)} />
                  ))}
                </View>
              </View>
            ) : (
              <View style={styles.messages}>
                {messages.map((message) => (
                  <View key={message.id} style={[styles.message, message.role === 'user' ? styles.userMessage : styles.assistantMessage]}>
                    <View style={styles.messageHeader}>
                      <Text style={[styles.messageRole, message.role === 'user' && styles.userMessageRole]}>{message.role === 'user' ? 'YOU' : 'POCKET'}</Text>
                      {message.status === 'abstained' ? <Chip label="Abstained" icon="shield-alert-outline" /> : null}
                    </View>
                    <Text style={[styles.messageText, message.role === 'user' && styles.userMessageText]}>{message.content}</Text>
                    {message.abstention_reason ? (
                      <Notice tone="warning" title="Insufficient evidence">{message.abstention_reason}</Notice>
                    ) : null}
                    {message.provenance?.deep_requested === true && message.provenance?.deep_provider_configured === false ? (
                      <Notice tone="warning" title="Deep route was unavailable">
                        The API answered with its configured deterministic or standard path. No stronger model call or Deep capability is being claimed.
                      </Notice>
                    ) : null}
                    {message.citations?.length ? (
                      <View style={styles.citations}>
                        {message.citations.map((citation) => (
                          <CitationChip
                            key={`${citation.segment_id}-${citation.start_ms}`}
                            citation={citation}
                            onPress={() => router.push(`/recordings/${citation.recording_id}?seek=${citation.start_ms}`)}
                          />
                        ))}
                      </View>
                    ) : null}
                  </View>
                ))}
                {loading ? (
                  <View style={[styles.message, styles.assistantMessage, styles.validating]}>
                    <ActivityIndicator color={colors.coral} />
                    <View style={styles.validatingCopy}>
                      <Text style={styles.messageRole}>VALIDATING BEFORE DISPLAY</Text>
                      <Text style={styles.validatingText}>Retrieving authorized source spans and validating every returned citation…</Text>
                    </View>
                  </View>
                ) : null}
              </View>
            )}
            {error ? <Notice tone="error" title="Ask stopped">{error.message}</Notice> : null}
            <View style={styles.composer}>
              <Input
                accessibilityLabel="Ask a question"
                multiline
                placeholder="Ask a question about this scope…"
                value={draft}
                onChangeText={setDraft}
                style={styles.composerInput}
              />
              <View style={styles.composerActions}>
                <Text style={styles.composerHint}>No full-library prompt is sent to a model.</Text>
                <View style={styles.sendButtons}>
                  <Button
                    variant="secondary"
                    icon="creation-outline"
                    disabled={!draft.trim() || !scope || loading || !deepAvailable}
                    onPress={() => setDeepOpen(true)}
                  >
                    Deep
                  </Button>
                  <Button icon="send" disabled={!draft.trim() || !scope} loading={loading} onPress={() => send(false)}>Ask</Button>
                </View>
              </View>
            </View>
          </Card>
        </View>

        <Card style={styles.scopePanel}>
          <Text style={styles.panelTitle}>Choose evidence scope</Text>
          <Segmented
            value={scopeKind}
            onChange={changeScope}
            options={[
              { value: 'library', label: 'Library', description: 'Across accessible recordings' },
              { value: 'recording', label: 'Recording', description: 'One canonical source' },
              { value: 'selection', label: 'Selection', description: 'Specific transcript units' },
            ]}
          />
          {scopeKind !== 'library' ? (
            <Field label="Recording">
              <View style={styles.recordingChoices}>
                {recordings.map((recording) => (
                  <Chip
                    key={recording.id}
                    label={recording.title}
                    selected={recording.id === recordingId}
                    onPress={() => { setRecordingId(recording.id); resetSession(); }}
                  />
                ))}
                {!recordings.length ? <Text style={styles.noIndexed}>No recording has an accessible ready index.</Text> : null}
              </View>
            </Field>
          ) : null}
          {scopeKind === 'selection' ? (
            <Field label="Transcript segment IDs" hint="Comma-separated canonical segment IDs from a transcript selection.">
              <Input value={segmentIds} onChangeText={(value) => { setSegmentIds(value); resetSession(); }} placeholder="seg_01, seg_02" />
            </Field>
          ) : null}
          <View style={styles.scopeRules}>
            <Text style={styles.rulesTitle}>Grounding rules</Text>
            {[
              'Authorization is applied before retrieval; source validity is checked again before evidence returns.',
              'One bounded retrieval expansion is allowed; absent evidence causes abstention.',
              'Deep is only used with sufficient evidence and a separate confirmed budget.',
            ].map((rule) => (
              <View key={rule} style={styles.ruleRow}>
                <MaterialCommunityIcons name="check-circle-outline" size={16} color={colors.green} />
                <Text style={styles.ruleText}>{rule}</Text>
              </View>
            ))}
            <Text style={styles.deepState}>
              {deepAvailable
                ? 'Gemini Deep is available for a separately confirmed request.'
                : capabilitiesLoading
                  ? 'Checking whether Gemini Deep is available…'
                  : 'Deep remains disabled until the API confirms an active Gemini strong route.'}
            </Text>
          </View>
        </Card>
      </View>
      <ConfirmDialog
        visible={deepOpen && deepAvailable}
        title="Use a new Deep budget?"
        body="Deep requests the configured Gemini strong synthesis route over the same bounded cited evidence. It uses a separately confirmed budget without relaxing authorization, citation validation, or the active data policy."
        confirmLabel="Confirm Deep ask"
        loading={loading}
        onCancel={() => setDeepOpen(false)}
        onConfirm={() => send(true)}
      />
    </AppShell>
  );
}

const styles = StyleSheet.create({
  layout: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xl },
  layoutNarrow: { flexDirection: 'column' },
  chatColumn: { flex: 1, width: '100%', minWidth: 0, gap: spacing.lg },
  scopeBar: { padding: spacing.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md, ...shadowNone },
  scopeIdentity: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  scopeIcon: { width: 36, height: 36, borderRadius: 12, backgroundColor: colors.pineSoft, alignItems: 'center', justifyContent: 'center' },
  scopeCopy: { flex: 1, gap: 2 },
  scopeKicker: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  scopeTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 12 },
  scopeBudget: { color: colors.inkMuted, fontFamily: font.mono, fontSize: 9 },
  chatCard: { minHeight: 590, padding: 0, overflow: 'hidden' },
  welcome: { flex: 1, minHeight: 380, alignItems: 'center', justifyContent: 'center', gap: spacing.md, padding: spacing.xl },
  askMark: { width: 68, height: 68, borderRadius: 23, backgroundColor: colors.coralSoft, alignItems: 'center', justifyContent: 'center' },
  welcomeTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 21, textAlign: 'center' },
  welcomeBody: { maxWidth: 500, color: colors.inkMuted, fontSize: 13, lineHeight: 20, textAlign: 'center' },
  suggestions: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 6 },
  messages: { flex: 1, padding: spacing.xl, gap: spacing.lg },
  message: { maxWidth: '88%', borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm },
  userMessage: { alignSelf: 'flex-end', backgroundColor: colors.pine, borderBottomRightRadius: 5 },
  assistantMessage: { alignSelf: 'flex-start', backgroundColor: colors.canvas, borderBottomLeftRadius: 5 },
  messageHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md },
  messageRole: { color: colors.coralDark, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  userMessageRole: { color: '#BFD7D0' },
  messageText: { color: colors.ink, fontSize: 14, lineHeight: 22 },
  userMessageText: { color: colors.white },
  citations: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  validating: { flexDirection: 'row', alignItems: 'center' },
  validatingCopy: { flex: 1, gap: 4 },
  validatingText: { color: colors.inkMuted, fontSize: 11, lineHeight: 16 },
  composer: { borderTopWidth: 1, borderTopColor: colors.border, padding: spacing.lg, gap: spacing.md, backgroundColor: colors.surface },
  composerInput: { minHeight: 76, borderWidth: 0, paddingHorizontal: 0 },
  composerActions: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md, flexWrap: 'wrap' },
  composerHint: { color: colors.inkFaint, fontSize: 9 },
  sendButtons: { flexDirection: 'row', gap: spacing.sm },
  scopePanel: { width: '100%', maxWidth: 350, gap: spacing.xl, ...shadowNone },
  panelTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 17 },
  recordingChoices: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  noIndexed: { color: colors.inkFaint, fontSize: 11, fontStyle: 'italic' },
  scopeRules: { gap: spacing.md, paddingTop: spacing.lg, borderTopWidth: 1, borderTopColor: colors.border },
  rulesTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 12 },
  ruleRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm },
  ruleText: { flex: 1, color: colors.inkMuted, fontSize: 10, lineHeight: 15 },
  deepState: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 10, lineHeight: 16 },
});
