import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

import { AppShell } from '@/components/AppShell';
import { LocalAudioPlayer } from '@/components/AudioPlayer';
import { DropZone } from '@/components/DropZone';
import { Button, Card, Notice, PageTitle } from '@/components/ui';
import {
  canUploadInConfiguredLanguage,
  isProviderDataApprovalSatisfied,
  requiresProviderDataApproval,
  resolveUploadLanguage,
} from '@/features/capabilities/capabilities';
import { ApiError, api } from '@/lib/api';
import { formatBytes, formatDuration } from '@/lib/format';
import { fromRecordedUri, pickAudio, readAudio, sha256, type PickedAudio } from '@/platform/files';
import { useCapabilities } from '@/providers/CapabilitiesProvider';
import { useSession } from '@/providers/SessionProvider';
import { colors, font, radius, spacing } from '@/theme';
import type { UploadSession } from '@/types/api';

import { demoAudioSamples, loadDemoAudioSample } from './demoSamples';

const MAX_BYTES = 500 * 1024 * 1024;

type UploadStep = 'idle' | 'hashing' | 'reserving' | 'uploading' | 'verifying';
type InputSource = 'upload' | 'recording' | 'sample';

interface PendingUpload {
  fingerprint: string;
  session: UploadSession;
}

export default function UploadScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const phone = width < 560;
  const { session } = useSession();
  const { capabilities, loading: capabilitiesLoading } = useCapabilities();
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorderState = useAudioRecorderState(recorder, 100);
  const [file, setFile] = useState<PickedAudio>();
  const [inputSource, setInputSource] = useState<InputSource>();
  const [selectedDuration, setSelectedDuration] = useState<number>();
  const [selectedLabel, setSelectedLabel] = useState<string>();
  const [sampleLoading, setSampleLoading] = useState<string>();
  const [recordingBusy, setRecordingBusy] = useState(false);
  const [step, setStep] = useState<UploadStep>('idle');
  const [error, setError] = useState<Error>();
  const [fileError, setFileError] = useState<string>();
  const [pendingUpload, setPendingUpload] = useState<PendingUpload>();
  const [providerDataApproved, setProviderDataApproved] = useState(false);

  const isBusy = step !== 'idle';
  const approvalRequired = requiresProviderDataApproval(capabilities);
  const approvalSatisfied = isProviderDataApprovalSatisfied(capabilities, providerDataApproved);
  const uploadLanguageAvailable = canUploadInConfiguredLanguage(capabilities);
  const selectedLanguage = resolveUploadLanguage(capabilities, 'auto');
  const quotaRemaining = Math.max(0, (session?.workspace.byte_limit ?? 5 * 1024 ** 3) - (session?.workspace.retained_bytes ?? 0));

  const clearFile = () => {
    setFile(undefined);
    setInputSource(undefined);
    setSelectedDuration(undefined);
    setSelectedLabel(undefined);
    setPendingUpload(undefined);
  };

  const selectFile = (value: PickedAudio, source: InputSource, duration?: number, label?: string) => {
    setError(undefined);
    setPendingUpload(undefined);
    setProviderDataApproved(false);
    if (value.size === 0) {
      clearFile();
      setFileError('No audio was captured. Try recording again.');
      return;
    }
    if (value.size !== undefined && value.size > MAX_BYTES) {
      clearFile();
      setFileError(`This audio is ${formatBytes(value.size)}. Use a file smaller than 500 MiB.`);
      return;
    }
    if (value.size !== undefined && value.size > quotaRemaining) {
      clearFile();
      setFileError(`This demo has ${formatBytes(quotaRemaining)} of storage left. Use a smaller file.`);
      return;
    }
    setFileError(undefined);
    setInputSource(source);
    setSelectedDuration(duration);
    setSelectedLabel(label);
    setFile(value);
  };

  const browse = async () => {
    try {
      const value = await pickAudio();
      if (value) selectFile(value, 'upload');
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('The file picker could not open'));
    }
  };

  const selectSample = async (sample: (typeof demoAudioSamples)[number]) => {
    if (sampleLoading || isBusy) return;
    setSampleLoading(sample.id);
    setError(undefined);
    try {
      const value = await loadDemoAudioSample(sample);
      selectFile(value, 'sample', sample.durationMs, sample.title);
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('The demo audio could not be loaded'));
    } finally {
      setSampleLoading(undefined);
    }
  };

  const startRecording = async () => {
    if (recordingBusy || isBusy) return;
    setRecordingBusy(true);
    setError(undefined);
    setFileError(undefined);
    clearFile();
    try {
      const permission = await requestRecordingPermissionsAsync();
      if (!permission.granted) throw new Error('Microphone access is needed to record a demo clip.');
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('Recording could not start'));
    } finally {
      setRecordingBusy(false);
    }
  };

  const stopRecording = async () => {
    if (!recorderState.isRecording || recordingBusy) return;
    setRecordingBusy(true);
    setError(undefined);
    const duration = recorderState.durationMillis;
    try {
      await recorder.stop();
      await setAudioModeAsync({ allowsRecording: false });
      if (!recorder.uri) throw new Error('The recording finished without an audio file.');
      selectFile(await fromRecordedUri(recorder.uri), 'recording', duration);
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('Recording could not be saved'));
    } finally {
      setRecordingBusy(false);
    }
  };

  const upload = async () => {
    if (!file || isBusy || capabilitiesLoading || !approvalSatisfied || !uploadLanguageAvailable) return;
    setError(undefined);
    try {
      setStep('hashing');
      const bytes = await readAudio(file);
      const actualSize = bytes.byteLength;
      if (actualSize === 0) throw new Error('No audio data was found. Choose or record another clip.');
      if (actualSize > MAX_BYTES) throw new Error(`This audio is ${formatBytes(actualSize)}. Use a file smaller than 500 MiB.`);
      if (actualSize > quotaRemaining) throw new Error(`This demo has ${formatBytes(quotaRemaining)} of storage left. Use a smaller file.`);
      const digest = await sha256(bytes);
      const fingerprint = JSON.stringify([digest, file.name, actualSize, file.mimeType, selectedLanguage]);
      setStep('reserving');
      const uploadSession = pendingUpload?.fingerprint === fingerprint
        ? pendingUpload.session
        : await api.createUpload({
          filename: file.name,
          content_type: file.mimeType,
          size_bytes: actualSize,
          sha256: digest,
          language: selectedLanguage,
          vocabulary_hints: [],
          mode: 'standard',
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
      if (caught instanceof ApiError && caught.status >= 400 && caught.status < 500) setPendingUpload(undefined);
      setError(caught instanceof Error ? caught : new Error('The demo run could not start'));
    }
  };

  const stepCopy: Record<Exclude<UploadStep, 'idle'>, string> = {
    hashing: 'Checking the audio',
    reserving: 'Preparing the run',
    uploading: 'Uploading the source audio',
    verifying: 'Starting the pipeline',
  };

  return (
    <AppShell>
      <View style={styles.intro}>
        <Text style={styles.eyebrow}>START A RUN</Text>
        <PageTitle title="Add a recording" subtitle="Upload audio, record a new clip, or choose a synthetic example. The backend publishes each stage as it completes." />
      </View>

      <View style={[styles.stepRail, phone && styles.stepRailPhone]}>
        {[
          ['1', 'Add audio', true],
          ['2', 'Process audio', Boolean(file)],
          ['3', 'Inspect output', false],
        ].map(([number, label, active]) => (
          <View key={String(number)} style={[styles.stepItem, phone && styles.stepItemPhone]}>
            <View style={[styles.stepNumber, active && styles.stepNumberActive]}><Text style={[styles.stepNumberText, active && styles.stepNumberTextActive]}>{number}</Text></View>
            <Text numberOfLines={1} style={[styles.stepLabel, phone && styles.stepLabelPhone, active && styles.stepLabelActive]}>{label}</Text>
          </View>
        ))}
      </View>

      <Card style={styles.inputCard}>
        {!file ? (
          <View style={[styles.sourceGrid, width < 1060 && styles.sourceGridNarrow]}>
            <View style={styles.sourceColumn}>
              <Text style={styles.sourceLabel}>UPLOAD</Text>
              <DropZone onPick={(value) => selectFile(value, 'upload')} pick={browse} />
            </View>
            <View style={styles.choiceDivider}><Text style={styles.choiceDividerText}>OR</Text></View>
            <View style={[styles.sourceColumn, styles.recorderCard, recorderState.isRecording && styles.recorderCardActive]}>
              <Text style={styles.sourceLabel}>RECORD NOW</Text>
              <View style={[styles.recordIcon, recorderState.isRecording && styles.recordIconActive]}>
                <MaterialCommunityIcons name={recorderState.isRecording ? 'waveform' : 'microphone-outline'} size={34} color={recorderState.isRecording ? colors.white : colors.pine} />
              </View>
              <Text style={styles.recordTitle}>{recorderState.isRecording ? 'Recording…' : 'Use your microphone'}</Text>
              <Text style={styles.recordBody}>{recorderState.isRecording ? formatDuration(recorderState.durationMillis) : 'Speak naturally, then stop when you are ready.'}</Text>
              {recorderState.isRecording ? (
                <View style={styles.levels} accessibilityLabel="Recording in progress">
                  {[12, 24, 17, 31, 20, 28, 14].map((height, index) => <View key={index} style={[styles.levelBar, { height }]} />)}
                </View>
              ) : null}
              <Button
                icon={recorderState.isRecording ? 'stop' : 'record-circle-outline'}
                variant={recorderState.isRecording ? 'danger' : 'primary'}
                loading={recordingBusy}
                onPress={recorderState.isRecording ? stopRecording : startRecording}
              >
                {recorderState.isRecording ? 'Stop recording' : 'Start recording'}
              </Button>
            </View>
            <View style={styles.choiceDivider}><Text style={styles.choiceDividerText}>OR</Text></View>
            <View style={styles.sourceColumn}>
              <Text style={styles.sourceLabel}>CHOOSE AN EXAMPLE</Text>
              <View style={styles.sampleCard} accessibilityRole="list">
                <View style={styles.sampleIntro}>
                  <View style={styles.sampleIcon}><MaterialCommunityIcons name="flask-outline" size={22} color={colors.blue} /></View>
                  <View style={styles.sampleIntroCopy}>
                    <Text style={styles.sampleTitle}>Synthetic recordings</Text>
                    <Text style={styles.sampleBody}>Pick a ready-made scenario to run through the pipeline.</Text>
                  </View>
                </View>
                <View style={styles.sampleList}>
                  {demoAudioSamples.map((sample) => (
                    <Pressable
                      key={sample.id}
                      accessibilityRole="button"
                      accessibilityLabel={`Choose ${sample.title}, ${formatDuration(sample.durationMs)}`}
                      disabled={Boolean(sampleLoading)}
                      onPress={() => void selectSample(sample)}
                      style={({ pressed }) => [styles.sampleOption, pressed && styles.sampleOptionPressed]}
                    >
                      <View style={styles.sampleOptionCopy}>
                        <Text style={styles.sampleOptionTitle}>{sample.title}</Text>
                        <Text numberOfLines={2} style={styles.sampleOptionBody}>{sample.description}</Text>
                        <Text style={styles.sampleMeta}>{formatDuration(sample.durationMs)} · {formatBytes(sample.size)}</Text>
                      </View>
                      {sampleLoading === sample.id
                        ? <ActivityIndicator size="small" color={colors.coral} />
                        : <MaterialCommunityIcons name="chevron-right" size={20} color={colors.inkFaint} />}
                    </Pressable>
                  ))}
                </View>
              </View>
            </View>
          </View>
        ) : (
          <View style={styles.selectedArea}>
            <View style={styles.selectedFile}>
              <View style={styles.fileIcon}>
                <MaterialCommunityIcons
                  name={inputSource === 'recording' ? 'microphone' : inputSource === 'sample' ? 'flask-outline' : 'music-note'}
                  size={27}
                  color={colors.coralDark}
                />
              </View>
              <View style={styles.fileCopy}>
                <Text style={styles.readyLabel}>READY TO PROCESS</Text>
                <Text numberOfLines={2} style={styles.fileName}>{inputSource === 'recording' ? 'New microphone recording' : selectedLabel ?? file.name}</Text>
                <Text style={styles.fileMeta}>
                  {[selectedDuration ? formatDuration(selectedDuration) : undefined, file.size === undefined ? undefined : formatBytes(file.size), file.mimeType].filter(Boolean).join(' · ')}
                </Text>
              </View>
              <Button
                size="sm"
                variant="ghost"
                icon={inputSource === 'recording' ? 'microphone-outline' : undefined}
                disabled={isBusy}
                onPress={clearFile}
              >
                {inputSource === 'recording' ? 'Re-record' : 'Replace'}
              </Button>
            </View>
            {inputSource === 'recording' ? <LocalAudioPlayer uri={file.uri} /> : null}
          </View>
        )}

        {fileError ? <Notice tone="error" title="Try another input">{fileError}</Notice> : null}
        {error ? <Notice tone="error" title="Could not continue">{error.message}</Notice> : null}

        {isBusy ? (
          <View style={styles.busyArea}>
            <ActivityIndicator size="small" color={colors.coral} />
            <View style={styles.busyCopy}>
              <Text style={styles.busyTitle}>{stepCopy[step as Exclude<UploadStep, 'idle'>]}</Text>
              <Text style={styles.busyBody}>The next screen updates as each backend stage is published.</Text>
            </View>
          </View>
        ) : null}

        {approvalRequired ? (
          <Pressable
            accessibilityRole="checkbox"
            accessibilityState={{ checked: providerDataApproved, disabled: isBusy }}
            disabled={isBusy}
            onPress={() => setProviderDataApproved((current) => !current)}
            style={styles.approvalRow}
          >
            <View style={[styles.approvalBox, providerDataApproved && styles.approvalBoxChecked]}>
              {providerDataApproved ? <MaterialCommunityIcons name="check" size={15} color={colors.white} /> : null}
            </View>
            <Text style={styles.approvalText}>This is synthetic or approved demo audio.</Text>
          </Pressable>
        ) : null}

        <View style={styles.runRow}>
          <View style={styles.runCopy}>
            <Text style={styles.runTitle}>Cost-optimized by default</Text>
            <Text style={styles.runBody}>Use the lower-cost model first; escalate only when validation fails.</Text>
          </View>
          <Button
            size="lg"
            icon="play"
            disabled={!file || capabilitiesLoading || !approvalSatisfied || !uploadLanguageAvailable || recorderState.isRecording}
            loading={isBusy}
            onPress={upload}
          >
            Run demo
          </Button>
        </View>
      </Card>

      <View style={styles.explainer}>
        <MaterialCommunityIcons name="information-outline" size={18} color={colors.blue} />
        <Text style={styles.explainerText}>Want to see how it works? <Text style={styles.explainerLink} onPress={() => router.push('/prompt-flow')}>Prompt flow</Text> maps each model call and the checks between them.</Text>
      </View>
    </AppShell>
  );
}

const styles = StyleSheet.create({
  intro: { gap: spacing.sm },
  eyebrow: { color: colors.coralDark, fontFamily: font.medium, fontSize: 9, letterSpacing: 1.2 },
  stepRail: { flexDirection: 'row', alignItems: 'center', gap: spacing.xl, paddingVertical: spacing.sm },
  stepRailPhone: { justifyContent: 'space-between', gap: 0 },
  stepItem: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  stepItemPhone: { flex: 1, flexDirection: 'column', gap: spacing.xs },
  stepNumber: { width: 24, height: 24, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.surfaceMuted },
  stepNumberActive: { backgroundColor: colors.pine },
  stepNumberText: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 10 },
  stepNumberTextActive: { color: colors.white },
  stepLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 11 },
  stepLabelPhone: { fontSize: 9, textAlign: 'center' },
  stepLabelActive: { color: colors.ink },
  inputCard: { gap: spacing.xl },
  sourceGrid: { flexDirection: 'row', alignItems: 'stretch', gap: spacing.xl },
  sourceGridNarrow: { flexDirection: 'column' },
  sourceColumn: { flex: 1, minWidth: 0, gap: spacing.md },
  sourceLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 9, letterSpacing: 1.1 },
  choiceDivider: { alignItems: 'center', justifyContent: 'center' },
  choiceDividerText: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 9 },
  recorderCard: { minHeight: 245, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, padding: spacing.xl, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.canvas, gap: spacing.md },
  recorderCardActive: { borderColor: colors.coral, backgroundColor: colors.coralSoft },
  recordIcon: { width: 68, height: 68, borderRadius: 24, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.pineSoft },
  recordIconActive: { backgroundColor: colors.coral },
  recordTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 18 },
  recordBody: { maxWidth: 280, color: colors.inkMuted, fontSize: 12, lineHeight: 18, textAlign: 'center' },
  levels: { height: 34, flexDirection: 'row', alignItems: 'center', gap: 4 },
  levelBar: { width: 4, borderRadius: 2, backgroundColor: colors.coral },
  sampleCard: { minHeight: 245, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, padding: spacing.md, backgroundColor: colors.canvas, gap: spacing.md },
  sampleIntro: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.xs },
  sampleIcon: { width: 38, height: 38, borderRadius: 12, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.blueSoft },
  sampleIntroCopy: { flex: 1, minWidth: 0, gap: 2 },
  sampleTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 13 },
  sampleBody: { color: colors.inkMuted, fontSize: 9, lineHeight: 13 },
  sampleList: { gap: spacing.sm },
  sampleOption: { minHeight: 58, flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.sm, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.surface },
  sampleOptionPressed: { borderColor: colors.coral, backgroundColor: colors.coralSoft },
  sampleOptionCopy: { flex: 1, minWidth: 0, gap: 2 },
  sampleOptionTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 10 },
  sampleOptionBody: { color: colors.inkMuted, fontSize: 8, lineHeight: 11 },
  sampleMeta: { color: colors.blue, fontFamily: font.mono, fontSize: 7 },
  selectedArea: { gap: spacing.md },
  selectedFile: { minHeight: 124, borderWidth: 1, borderColor: colors.green, borderRadius: radius.lg, backgroundColor: colors.greenSoft, padding: spacing.xl, flexDirection: 'row', alignItems: 'center', gap: spacing.lg },
  fileIcon: { width: 54, height: 54, borderRadius: 18, backgroundColor: colors.coralSoft, alignItems: 'center', justifyContent: 'center' },
  fileCopy: { flex: 1, minWidth: 0, gap: 4 },
  readyLabel: { color: colors.green, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  fileName: { color: colors.ink, fontFamily: font.medium, fontSize: 17 },
  fileMeta: { color: colors.inkMuted, fontSize: 11 },
  busyArea: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.lg, borderRadius: radius.md, backgroundColor: colors.blueSoft },
  busyCopy: { flex: 1, gap: 3 },
  busyTitle: { color: colors.blue, fontFamily: font.medium, fontSize: 12 },
  busyBody: { color: colors.inkMuted, fontSize: 10 },
  approvalRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, backgroundColor: colors.canvas },
  approvalBox: { width: 22, height: 22, borderWidth: 2, borderColor: colors.borderStrong, borderRadius: 6, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center' },
  approvalBoxChecked: { borderColor: colors.green, backgroundColor: colors.green },
  approvalText: { flex: 1, color: colors.ink, fontSize: 12 },
  runRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.xl, flexWrap: 'wrap', paddingTop: spacing.lg, borderTopWidth: 1, borderTopColor: colors.border },
  runCopy: { flex: 1, minWidth: 220, gap: 4 },
  runTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 13 },
  runBody: { color: colors.inkMuted, fontSize: 11 },
  explainer: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, paddingHorizontal: spacing.sm },
  explainerText: { flex: 1, color: colors.inkMuted, fontSize: 11, lineHeight: 17 },
  explainerLink: { color: colors.blue, fontFamily: font.medium },
});
