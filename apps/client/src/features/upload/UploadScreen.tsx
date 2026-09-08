import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import { DropZone } from '@/components/DropZone';
import {
  Button,
  Card,
  Field,
  Input,
  Notice,
  PageTitle,
  ProgressBar,
  Segmented,
  uiStyles,
} from '@/components/ui';
import { ApiError, api } from '@/lib/api';
import {
  canUseDeepIntelligence,
  canUploadInConfiguredLanguage,
  isProviderDataApprovalSatisfied,
  isRemoteGemini,
  isSyntheticApprovedOnly,
  requiresProviderDataApproval,
  resolveUploadLanguage,
  supportsEnglish,
} from '@/features/capabilities/capabilities';
import { ProviderPolicyNotice } from '@/features/capabilities/ProviderPolicyNotice';
import { formatBytes } from '@/lib/format';
import { pickAudio, readAudio, sha256, type PickedAudio } from '@/platform/files';
import { useSession } from '@/providers/SessionProvider';
import { useCapabilities } from '@/providers/CapabilitiesProvider';
import { colors, font, radius, shadowNone, spacing } from '@/theme';
import type { UploadSession } from '@/types/api';

const MAX_BYTES = 500 * 1024 * 1024;

type UploadStep = 'idle' | 'hashing' | 'reserving' | 'uploading' | 'verifying';

interface PendingUpload {
  fingerprint: string;
  session: UploadSession;
}

export default function UploadScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const { session } = useSession();
  const { capabilities, loading: capabilitiesLoading } = useCapabilities();
  const [file, setFile] = useState<PickedAudio>();
  const [language, setLanguage] = useState<'auto' | 'en'>('auto');
  const [mode, setMode] = useState<'standard' | 'deep'>('standard');
  const [vocabulary, setVocabulary] = useState('');
  const [step, setStep] = useState<UploadStep>('idle');
  const [error, setError] = useState<Error>();
  const [fileError, setFileError] = useState<string>();
  const [pendingUpload, setPendingUpload] = useState<PendingUpload>();
  const [providerDataApproved, setProviderDataApproved] = useState(false);

  const vocabItems = useMemo(
    () => vocabulary.split(/[,\n]/).map((item) => item.trim()).filter(Boolean).slice(0, 50),
    [vocabulary],
  );
  const isBusy = step !== 'idle';
  const deepAvailable = canUseDeepIntelligence(capabilities);
  const remoteGemini = isRemoteGemini(capabilities);
  const englishAvailable = supportsEnglish(capabilities);
  const uploadLanguageAvailable = canUploadInConfiguredLanguage(capabilities);
  const approvalRequired = requiresProviderDataApproval(capabilities);
  const approvalSatisfied = isProviderDataApprovalSatisfied(capabilities, providerDataApproved);
  const selectedMode = deepAvailable ? mode : 'standard';
  const selectedLanguage = resolveUploadLanguage(capabilities, language);
  const quotaRemaining = Math.max(0, (session?.workspace.byte_limit ?? 5 * 1024 ** 3) - (session?.workspace.retained_bytes ?? 0));

  const selectFile = (value: PickedAudio) => {
    setError(undefined);
    setPendingUpload(undefined);
    setProviderDataApproved(false);
    if (value.size === 0) {
      setFile(undefined);
      setFileError('This file is empty. Choose a recording with audio data.');
      return;
    }
    if (value.size !== undefined && value.size > MAX_BYTES) {
      setFile(undefined);
      setFileError(`This file is ${formatBytes(value.size)}. The demo accepts up to 500 MiB.`);
      return;
    }
    if (value.size !== undefined && value.size > quotaRemaining) {
      setFile(undefined);
      setFileError(`This workspace has ${formatBytes(quotaRemaining)} left. Delete an older recording or use a smaller file.`);
      return;
    }
    setFileError(undefined);
    setFile(value);
  };

  const browse = async () => {
    try {
      const value = await pickAudio();
      if (value) selectFile(value);
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('The file picker could not open'));
    }
  };

  const upload = async () => {
    if (!file || isBusy || capabilitiesLoading || !approvalSatisfied || !uploadLanguageAvailable) return;
    setError(undefined);
    try {
      setStep('hashing');
      const bytes = await readAudio(file);
      const actualSize = bytes.byteLength;
      if (actualSize === 0) {
        throw new Error('This file is empty. Choose a recording with audio data.');
      }
      if (actualSize > MAX_BYTES) {
        throw new Error(`This file is ${formatBytes(actualSize)}. The demo accepts up to 500 MiB.`);
      }
      if (actualSize > quotaRemaining) {
        throw new Error(`This workspace has ${formatBytes(quotaRemaining)} left. Delete an older recording or use a smaller file.`);
      }
      const digest = await sha256(bytes);
      const fingerprint = JSON.stringify([
        digest,
        file.name,
        actualSize,
        file.mimeType,
        selectedLanguage,
        selectedMode,
        providerDataApproved,
        vocabItems,
      ]);
      setStep('reserving');
      const uploadSession = pendingUpload?.fingerprint === fingerprint
        ? pendingUpload.session
        : await api.createUpload({
          filename: file.name,
          content_type: file.mimeType,
          size_bytes: actualSize,
          sha256: digest,
          language: selectedLanguage,
          vocabulary_hints: vocabItems,
          mode: selectedMode,
          provider_data_approved: providerDataApproved,
        });
      setPendingUpload({ fingerprint, session: uploadSession });
      setStep('uploading');
      await api.uploadBytes(uploadSession, bytes, file.mimeType);
      setStep('verifying');
      const recording = await api.completeUpload(uploadSession.recording_id, uploadSession.id, digest);
      setPendingUpload(undefined);
      router.replace(`/recordings/${recording.id}`);
    } catch (caught) {
      setStep('idle');
      if (caught instanceof ApiError && caught.status >= 400 && caught.status < 500) {
        setPendingUpload(undefined);
      }
      setError(caught instanceof Error ? caught : new Error('Upload failed'));
    }
  };

  const stepCopy: Record<Exclude<UploadStep, 'idle'>, string> = {
    hashing: 'Calculating a byte-exact SHA-256 checksum…',
    reserving: 'Checking storage quota and creating the upload session…',
    uploading: 'Uploading original bytes to quarantine…',
    verifying: 'Asking the API to verify and seal the original…',
  };

  return (
    <AppShell>
      <PageTitle title="Add a recording" subtitle="The original is verified and stored byte-for-byte before any transcript or intelligence work begins." />
      <ProviderPolicyNotice />
      <View style={[styles.columns, width < 940 && styles.columnsNarrow]}>
        <Card style={styles.uploadCard}>
          {!file ? (
            <DropZone onPick={selectFile} pick={browse} />
          ) : (
            <View style={styles.selectedFile}>
              <View style={styles.fileIcon}><MaterialCommunityIcons name="music-note" size={28} color={colors.coralDark} /></View>
              <View style={styles.fileCopy}>
                <Text numberOfLines={2} style={styles.fileName}>{file.name}</Text>
                <Text style={styles.fileMeta}>{file.size === undefined ? 'Size checked during upload' : formatBytes(file.size)} · {file.mimeType}</Text>
                <View style={styles.localCheck}>
                  <MaterialCommunityIcons name="check-circle" size={15} color={colors.green} />
                  <Text style={styles.localCheckText}>Client limits passed; content validation happens on the API</Text>
                </View>
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Remove selected file"
                disabled={isBusy}
                onPress={() => {
                  setFile(undefined);
                  setPendingUpload(undefined);
                  setProviderDataApproved(false);
                }}
                style={styles.removeFile}
              >
                <MaterialCommunityIcons name="close" size={20} color={colors.inkMuted} />
              </Pressable>
            </View>
          )}
          {fileError ? <Notice tone="error" title="Choose another file">{fileError}</Notice> : null}
          {error ? <Notice tone="error" title="Upload stopped">{error.message}</Notice> : null}
          {isBusy ? (
            <View style={styles.busyArea}>
              <View style={uiStyles.rowBetween}>
                <Text style={styles.busyTitle}>{stepCopy[step as Exclude<UploadStep, 'idle'>]}</Text>
                <Text style={styles.busyStep}>{['hashing', 'reserving', 'uploading', 'verifying'].indexOf(step) + 1}/4</Text>
              </View>
              <View style={styles.discreteSteps}>
                {(['hashing', 'reserving', 'uploading', 'verifying'] as const).map((item, index, all) => {
                  const activeIndex = all.indexOf(step as Exclude<UploadStep, 'idle'>);
                  const done = index < activeIndex;
                  const active = index === activeIndex;
                  return (
                    <View key={item} style={[styles.discreteStep, done && styles.discreteStepDone, active && styles.discreteStepActive]}>
                      {active ? <ActivityIndicator size="small" color={colors.blue} /> : done ? <MaterialCommunityIcons name="check" size={14} color={colors.white} /> : null}
                    </View>
                  );
                })}
              </View>
              <Text style={styles.busyNote}>These are discrete client stages, not a guessed provider percentage. Keep this screen open until sealing completes.</Text>
            </View>
          ) : null}

          <View style={styles.formSection}>
            <Field
              label="Transcript language"
              hint={remoteGemini
                ? 'The Gemini demo route is pinned to English; Auto-detect is unavailable.'
                : 'Auto-detect remains available for the local fixture route.'}
            >
              <Segmented<'auto' | 'en'>
                value={selectedLanguage}
                onChange={setLanguage}
                options={[
                  {
                    value: 'auto',
                    label: 'Auto-detect',
                    description: remoteGemini ? 'Unavailable for Gemini' : 'Route after validation',
                    disabled: remoteGemini,
                  },
                  { value: 'en', label: 'English', description: 'Quality-gated route', disabled: !englishAvailable },
                ]}
              />
            </Field>
            <Field label="Vocabulary hints" hint={`${vocabItems.length}/50 hints · Separate names, acronyms, or jargon with commas.`}>
              <Input
                value={vocabulary}
                onChangeText={setVocabulary}
                editable={!isBusy}
                placeholder="e.g. pgvector, Samyak, Acme Health"
              />
            </Field>
            <Field label="Processing mode">
              <Segmented<'standard' | 'deep'>
                value={selectedMode}
                onChange={setMode}
                options={[
                  { value: 'standard', label: 'Standard', description: 'Cost-first, targeted escalation' },
                  {
                    value: 'deep',
                    label: 'Deep',
                    description: deepAvailable ? 'Gemini strong-model synthesis' : capabilitiesLoading ? 'Checking Gemini capability' : 'Configured Gemini strong route required',
                    disabled: !deepAvailable,
                  },
                ]}
              />
            </Field>
          </View>
          {deepAvailable ? (
            <Notice tone="info" title="Gemini Deep is available">
              Deep requests the configured strong synthesis route under a separate recording budget. Speech and canonical citation validation remain unchanged.
            </Notice>
          ) : (
            <Notice tone="info" title="Deep is unavailable">
              The client enables Deep only when the API confirms an active Gemini strong route. Standard and fixture-safe processing remain available.
            </Notice>
          )}
          {!uploadLanguageAvailable ? (
            <Notice tone="error" title="English transcription is unavailable">
              The Gemini demo accepts uploads only after the API advertises an English transcription route.
            </Notice>
          ) : null}
          {approvalRequired ? (
            <Pressable
              accessibilityRole="checkbox"
              accessibilityState={{ checked: providerDataApproved, disabled: isBusy }}
              disabled={isBusy}
              onPress={() => setProviderDataApproved((current) => !current)}
              style={({ pressed }) => [
                styles.approvalRow,
                providerDataApproved && styles.approvalRowChecked,
                pressed && styles.approvalRowPressed,
              ]}
            >
              <View style={[styles.approvalBox, providerDataApproved && styles.approvalBoxChecked]}>
                {providerDataApproved ? <MaterialCommunityIcons name="check" size={15} color={colors.white} /> : null}
              </View>
              <Text style={styles.approvalText}>
                {isSyntheticApprovedOnly(capabilities)
                  ? 'I confirm this audio is synthetic or explicitly approved and contains no private, personal, confidential, or production data.'
                  : `I confirm this audio is approved for processing under the active “${capabilities.data_policy}” provider policy.`}
              </Text>
            </Pressable>
          ) : null}
          <View style={styles.submitRow}>
            <Button variant="ghost" disabled={isBusy} onPress={() => router.back()}>Cancel</Button>
            <Button size="lg" icon="tray-arrow-up" disabled={!file || capabilitiesLoading || !approvalSatisfied || !uploadLanguageAvailable} loading={isBusy} onPress={upload}>
              Verify & upload
            </Button>
          </View>
        </Card>

        <View style={styles.sidebar}>
          <Card style={styles.guardrailCard}>
            <Text style={styles.sideTitle}>Demo guardrails</Text>
            {[
              ['file-document-outline', '500 MiB maximum file size'],
              ['timer-sand', 'Two-hour maximum duration'],
              ['cash-lock', '$2 automatic AI cap per recording'],
              ['calendar-clock', '30-day retention with automatic demo sweep'],
            ].map(([icon, label]) => (
              <View key={label} style={styles.guardrailRow}>
                <View style={styles.guardrailIcon}><MaterialCommunityIcons name={icon as 'timer-sand'} size={17} color={colors.pine} /></View>
                <Text style={styles.guardrailText}>{label}</Text>
              </View>
            ))}
          </Card>
          <Card style={styles.quotaCard}>
            <Text style={styles.sideTitle}>Workspace capacity</Text>
            <View style={uiStyles.rowBetween}>
              <Text style={styles.quotaLabel}>Storage remaining</Text>
              <Text style={styles.quotaValue}>{formatBytes(quotaRemaining)}</Text>
            </View>
            <ProgressBar
              value={Math.min(100, ((session?.workspace.retained_bytes ?? 0) / (session?.workspace.byte_limit || 5 * 1024 ** 3)) * 100)}
              tone="pine"
            />
            <Text style={styles.sideBody}>Abandoned uploads and successful ephemeral media derivatives expire after 24 hours.</Text>
          </Card>
          <Notice tone="info" title="No invented intelligence">
            Empty, corrupt, partial, or unsupported media ends with an actionable error. When speech is not configured, the original remains available and processing is marked partial.
          </Notice>
        </View>
      </View>
    </AppShell>
  );
}

const styles = StyleSheet.create({
  columns: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xl },
  columnsNarrow: { flexDirection: 'column' },
  uploadCard: { flex: 1, width: '100%', minWidth: 0, gap: spacing.xl },
  selectedFile: { minHeight: 160, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, backgroundColor: colors.canvas, padding: spacing.xl, flexDirection: 'row', alignItems: 'center', gap: spacing.lg },
  fileIcon: { width: 62, height: 62, borderRadius: 21, backgroundColor: colors.coralSoft, alignItems: 'center', justifyContent: 'center' },
  fileCopy: { flex: 1, gap: 5 },
  fileName: { color: colors.ink, fontFamily: font.medium, fontSize: 17 },
  fileMeta: { color: colors.inkMuted, fontSize: 12 },
  localCheck: { flexDirection: 'row', gap: 6, alignItems: 'center', marginTop: 6 },
  localCheckText: { flex: 1, color: colors.green, fontSize: 10 },
  removeFile: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.surface },
  busyArea: { gap: spacing.sm, padding: spacing.lg, borderRadius: radius.md, backgroundColor: colors.blueSoft },
  busyTitle: { flex: 1, color: colors.blue, fontFamily: font.medium, fontSize: 12 },
  busyStep: { color: colors.blue, fontFamily: font.mono, fontSize: 10 },
  discreteSteps: { flexDirection: 'row', gap: 5 },
  discreteStep: { flex: 1, height: 7, borderRadius: 4, backgroundColor: colors.surface },
  discreteStepDone: { backgroundColor: colors.green, alignItems: 'center', justifyContent: 'center', height: 18 },
  discreteStepActive: { backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center', height: 18 },
  busyNote: { color: colors.inkMuted, fontSize: 10, lineHeight: 15 },
  formSection: { gap: spacing.xl },
  approvalRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md, padding: spacing.lg, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: radius.md, backgroundColor: colors.canvas },
  approvalRowChecked: { borderColor: colors.green, backgroundColor: colors.greenSoft },
  approvalRowPressed: { opacity: 0.8 },
  approvalBox: { width: 22, height: 22, borderWidth: 2, borderColor: colors.borderStrong, borderRadius: 6, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center' },
  approvalBoxChecked: { borderColor: colors.green, backgroundColor: colors.green },
  approvalText: { flex: 1, color: colors.ink, fontSize: 12, lineHeight: 19 },
  submitRow: { flexDirection: 'row', justifyContent: 'flex-end', alignItems: 'center', gap: spacing.sm, flexWrap: 'wrap' },
  sidebar: { width: '100%', maxWidth: 330, gap: spacing.lg },
  guardrailCard: { gap: spacing.lg, ...shadowNone },
  sideTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 16 },
  sideBody: { color: colors.inkMuted, fontSize: 11, lineHeight: 17 },
  guardrailRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  guardrailIcon: { width: 34, height: 34, borderRadius: 11, backgroundColor: colors.pineSoft, alignItems: 'center', justifyContent: 'center' },
  guardrailText: { color: colors.inkMuted, fontSize: 12 },
  quotaCard: { gap: spacing.md, ...shadowNone },
  quotaLabel: { color: colors.inkMuted, fontSize: 11 },
  quotaValue: { color: colors.ink, fontFamily: font.medium, fontSize: 12 },
});
