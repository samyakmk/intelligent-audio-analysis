import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/ui';
import { colors, font, radius, spacing } from '@/theme';
import type { PickedAudio } from '@/platform/files';

export function DropZone({ pick }: { onPick(file: PickedAudio): void; pick(): void }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel="Choose an audio file" onPress={pick} style={({ pressed }) => [styles.root, pressed && styles.pressed]}>
      <View style={styles.icon}><MaterialCommunityIcons name="waveform" size={31} color={colors.coralDark} /></View>
      <Text style={styles.title}>Choose a recording</Text>
      <Text style={styles.body}>MP3, M4A/AAC, WAV, FLAC, OGG, or WebM</Text>
      <Button variant="secondary" icon="folder-open-outline" onPress={pick}>Browse files</Button>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { minHeight: 245, padding: spacing.xl, borderRadius: radius.lg, borderWidth: 1.5, borderStyle: 'dashed', borderColor: colors.borderStrong, backgroundColor: colors.canvas, alignItems: 'center', justifyContent: 'center', gap: spacing.md },
  pressed: { opacity: 0.75 },
  icon: { width: 64, height: 64, borderRadius: 22, backgroundColor: colors.coralSoft, alignItems: 'center', justifyContent: 'center' },
  title: { color: colors.ink, fontFamily: font.medium, fontSize: 18 },
  body: { color: colors.inkMuted, fontSize: 13, textAlign: 'center' },
});
