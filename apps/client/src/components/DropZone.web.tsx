import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { useState, type CSSProperties, type DragEvent } from 'react';

import { Button } from '@/components/ui';
import { colors, radius } from '@/theme';
import { fromWebFile, type PickedAudio } from '@/platform/files';

export function DropZone({ onPick, pick }: { onPick(file: PickedAudio): void; pick(): void }) {
  const [active, setActive] = useState(false);
  const style: CSSProperties = {
    minHeight: 245,
    border: `1.5px dashed ${active ? colors.coral : colors.borderStrong}`,
    borderRadius: radius.lg,
    background: active ? colors.coralSoft : colors.canvas,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    padding: 28,
    transition: '160ms ease',
    textAlign: 'center',
  };
  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setActive(false);
    const file = event.dataTransfer.files[0];
    if (file) onPick(fromWebFile(file));
  };
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label="Drop an audio file or choose a file"
      style={style}
      onDragEnter={(event) => { event.preventDefault(); setActive(true); }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => setActive(false)}
      onDrop={handleDrop}
      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') pick(); }}
    >
      <div style={{ width: 64, height: 64, borderRadius: 22, display: 'flex', alignItems: 'center', justifyContent: 'center', background: colors.coralSoft }}>
        <MaterialCommunityIcons name="waveform" size={31} color={colors.coralDark} />
      </div>
      <div style={{ color: colors.ink, fontWeight: 650, fontSize: 18 }}>Drop an audio file here</div>
      <div style={{ color: colors.inkMuted, fontSize: 13, lineHeight: '19px' }}>MP3, M4A/AAC, WAV, FLAC, OGG, or WebM</div>
      <Button variant="secondary" icon="folder-open-outline" onPress={pick}>Choose audio file</Button>
    </div>
  );
}
