import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Chip, CitationChip, EmptyState, Input, Notice, SectionTitle } from '@/components/ui';
import { api } from '@/lib/api';
import { colors, font, radius, shadowNone, spacing } from '@/theme';
import type { AskMessage, AskSession, Citation, Recording } from '@/types/api';

export function RecordingAskPane({ recording, onEvidence }: { recording: Recording; onEvidence(citation: Citation): void }) {
  const [askSession, setAskSession] = useState<AskSession>();
  const [messages, setMessages] = useState<AskMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error>();

  if (!recording.readiness.indexed_ready) {
    return (
      <Card>
        <EmptyState
          icon="database-clock-outline"
          title="Ask is not ready"
          body="Questions become available after this recording's searchable evidence index is published."
        />
      </Card>
    );
  }

  const send = async () => {
    const question = draft.trim();
    if (!question || loading) return;
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
      const currentSession = askSession ?? await api.createAskSession({ type: 'recording', recording_id: recording.id });
      if (!askSession) setAskSession(currentSession);
      const reply = await api.ask(currentSession.id, question, false);
      setMessages((current) => [...current, reply.message]);
    } catch (caught) {
      setMessages((current) => current.filter((message) => message.id !== userMessage.id));
      setError(caught instanceof Error ? caught : new Error('Ask failed'));
      setDraft(question);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.stack}>
      <Card style={styles.scopeCard}>
        <View style={styles.scopeIcon}><MaterialCommunityIcons name="target" size={19} color={colors.pine} /></View>
        <View style={styles.scopeCopy}>
          <Text style={styles.scopeKicker}>ANSWER SCOPE</Text>
          <Text style={styles.scopeTitle}>This recording only</Text>
          <Text style={styles.scopeBody}>Answers are grounded in indexed transcript segments from “{recording.title}”.</Text>
        </View>
        <Chip label="$0.10 query ceiling" icon="shield-check-outline" />
      </Card>

      <Card style={styles.chatCard}>
        <View style={styles.chatHeader}>
          <SectionTitle title="Ask this recording" subtitle="Answers include the exact evidence range used to support them." />
        </View>

        {!messages.length ? (
          <View style={styles.welcome}>
            <View style={styles.askMark}><MaterialCommunityIcons name="message-processing-outline" size={30} color={colors.coralDark} /></View>
            <Text style={styles.welcomeTitle}>What do you want to know?</Text>
            <Text style={styles.welcomeBody}>Ask about decisions, owners, next steps, risks, or anything else supported by this recording.</Text>
            <View style={styles.suggestions}>
              {['What decisions were made?', 'Who owns the next steps?', 'What remains unresolved?'].map((suggestion) => (
                <Chip key={suggestion} label={suggestion} onPress={() => setDraft(suggestion)} />
              ))}
            </View>
          </View>
        ) : (
          <View style={styles.messages}>
            {messages.map((message) => (
              <View key={message.id} style={[styles.message, message.role === 'user' ? styles.userMessage : styles.assistantMessage]}>
                <View style={styles.messageHeader}>
                  <Text style={[styles.messageRole, message.role === 'user' && styles.userMessageRole]}>{message.role === 'user' ? 'YOU' : 'ANSWER'}</Text>
                  {message.status === 'abstained' ? <Chip label="Insufficient evidence" icon="shield-alert-outline" /> : null}
                </View>
                <Text style={[styles.messageText, message.role === 'user' && styles.userMessageText]}>{message.content}</Text>
                {message.citations?.length ? (
                  <View style={styles.citations}>
                    {message.citations.map((citation) => (
                      <CitationChip
                        key={`${citation.segment_id}-${citation.start_ms}-${citation.end_ms}`}
                        citation={citation}
                        onPress={() => onEvidence(citation)}
                      />
                    ))}
                  </View>
                ) : null}
                {message.abstention_reason ? <Text style={styles.abstention}>The indexed evidence was not sufficient to answer this question.</Text> : null}
              </View>
            ))}
            {loading ? (
              <View style={[styles.message, styles.assistantMessage, styles.validating]}>
                <ActivityIndicator color={colors.coral} />
                <View style={styles.validatingCopy}>
                  <Text style={styles.messageRole}>CHECKING EVIDENCE</Text>
                  <Text style={styles.validatingText}>Retrieving transcript spans and validating answer citations…</Text>
                </View>
              </View>
            ) : null}
          </View>
        )}

        {error ? <View style={styles.errorWrap}><Notice tone="error" title="Ask stopped">{error.message}</Notice></View> : null}
        <View style={styles.composer}>
          <Input
            accessibilityLabel="Ask a question about this recording"
            multiline
            placeholder="Ask a question about this recording…"
            value={draft}
            onChangeText={setDraft}
            style={styles.composerInput}
          />
          <View style={styles.composerFooter}>
            <Text style={styles.composerHint}>Unsupported answers abstain instead of guessing.</Text>
            <Button icon="send" disabled={!draft.trim()} loading={loading} onPress={send}>Ask</Button>
          </View>
        </View>
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  stack: { gap: spacing.lg },
  scopeCard: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: spacing.md, padding: spacing.lg, ...shadowNone },
  scopeIcon: { width: 42, height: 42, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.pineSoft },
  scopeCopy: { flex: 1, minWidth: 180, gap: 2 },
  scopeKicker: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  scopeTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 13 },
  scopeBody: { color: colors.inkMuted, fontSize: 10, lineHeight: 15 },
  chatCard: { minHeight: 520, padding: 0, overflow: 'hidden', ...shadowNone },
  chatHeader: { padding: spacing.xl, borderBottomWidth: 1, borderBottomColor: colors.border },
  welcome: { minHeight: 300, alignItems: 'center', justifyContent: 'center', gap: spacing.md, padding: spacing.xl },
  askMark: { width: 62, height: 62, borderRadius: 21, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.coralSoft },
  welcomeTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 20, textAlign: 'center' },
  welcomeBody: { maxWidth: 540, color: colors.inkMuted, fontSize: 12, lineHeight: 19, textAlign: 'center' },
  suggestions: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: 6 },
  messages: { minHeight: 280, padding: spacing.xl, gap: spacing.lg },
  message: { maxWidth: '88%', borderRadius: radius.lg, padding: spacing.lg, gap: spacing.sm },
  userMessage: { alignSelf: 'flex-end', backgroundColor: colors.pine, borderBottomRightRadius: 5 },
  assistantMessage: { alignSelf: 'flex-start', backgroundColor: colors.canvas, borderBottomLeftRadius: 5 },
  messageHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md },
  messageRole: { color: colors.coralDark, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  userMessageRole: { color: '#BFD7D0' },
  messageText: { color: colors.ink, fontSize: 14, lineHeight: 22 },
  userMessageText: { color: colors.white },
  citations: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  abstention: { color: colors.inkMuted, fontSize: 10, fontStyle: 'italic' },
  validating: { flexDirection: 'row', alignItems: 'center' },
  validatingCopy: { flex: 1, gap: 4 },
  validatingText: { color: colors.inkMuted, fontSize: 11, lineHeight: 16 },
  errorWrap: { paddingHorizontal: spacing.lg },
  composer: { marginTop: 'auto', borderTopWidth: 1, borderTopColor: colors.border, padding: spacing.lg, gap: spacing.md, backgroundColor: colors.surface },
  composerInput: { minHeight: 76, borderWidth: 0, paddingHorizontal: 0 },
  composerFooter: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md, flexWrap: 'wrap' },
  composerHint: { color: colors.inkFaint, fontSize: 9 },
});
