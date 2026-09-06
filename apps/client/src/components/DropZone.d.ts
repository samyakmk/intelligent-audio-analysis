import type { PickedAudio } from '@/platform/files';

export function DropZone(props: { onPick(file: PickedAudio): void; pick(): void }): React.JSX.Element;
