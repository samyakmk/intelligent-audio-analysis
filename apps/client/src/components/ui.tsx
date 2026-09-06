import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import {
  ActivityIndicator,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type PressableProps,
  type StyleProp,
  type TextInputProps,
  type ViewStyle,
} from 'react-native';
import { createContext, useContext, type ComponentProps, type ReactNode } from 'react';

import { colors, font, radius, shadow, spacing } from '@/theme';
import type { Citation, RecordingState } from '@/types/api';
import { citationLabel, stateLabel } from '@/lib/format';

type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];
const FieldLabelContext = createContext<string | undefined>(undefined);

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <View style={styles.brandRow} accessibilityLabel="Pocket Evidence Lab">
      <View style={styles.brandIcon}>
        <MaterialCommunityIcons name="bookmark-check" size={20} color={colors.white} />
      </View>
      {!compact ? (
        <View>
          <Text style={styles.brandName}>Pocket</Text>
          <Text style={styles.brandSub}>EVIDENCE LAB</Text>
        </View>
      ) : null}
    </View>
  );
}

interface ButtonProps extends Omit<PressableProps, 'children' | 'style'> {
  children: ReactNode;
  icon?: IconName;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  style?: StyleProp<ViewStyle>;
}

export function Button({
  children,
  icon,
  variant = 'primary',
  size = 'md',
  loading,
  disabled,
  style,
  ...props
}: ButtonProps) {
  const foreground = variant === 'primary' || variant === 'danger' ? colors.white : colors.ink;
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.button,
        styles[`button_${variant}`],
        styles[`button_${size}`],
        pressed && styles.buttonActive,
        (disabled || loading) && styles.disabled,
        style,
      ]}
      {...props}
    >
      {loading ? <ActivityIndicator size="small" color={foreground} /> : null}
      {icon && !loading ? <MaterialCommunityIcons name={icon} size={size === 'sm' ? 16 : 18} color={foreground} /> : null}
      <Text style={[styles.buttonLabel, { color: foreground }]}>{children}</Text>
    </Pressable>
  );
}

export function IconButton({ icon, label, ...props }: { icon: IconName; label: string } & Omit<ButtonProps, 'children' | 'icon'>) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => [styles.iconButton, pressed && styles.iconButtonActive]}
      {...props}
    >
      <MaterialCommunityIcons name={icon} size={20} color={colors.ink} />
    </Pressable>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return <Text style={styles.eyebrow}>{children}</Text>;
}

export function PageTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <View style={styles.pageTitleRow}>
      <View style={styles.pageTitleCopy}>
        <Text accessibilityRole="header" style={styles.pageTitle}>
          {title}
        </Text>
        {subtitle ? <Text style={styles.pageSubtitle}>{subtitle}</Text> : null}
      </View>
      {action}
    </View>
  );
}

export function SectionTitle({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <View style={styles.sectionTitleRow}>
      <View style={styles.sectionTitleCopy}>
        <Text style={styles.sectionTitle}>{title}</Text>
        {subtitle ? <Text style={styles.sectionSubtitle}>{subtitle}</Text> : null}
      </View>
      {action}
    </View>
  );
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <FieldLabelContext.Provider value={label}>{children}</FieldLabelContext.Provider>
      {error ? <Text style={styles.fieldError}>{error}</Text> : hint ? <Text style={styles.fieldHint}>{hint}</Text> : null}
    </View>
  );
}

export function Input({ style, ...props }: TextInputProps) {
  const fieldLabel = useContext(FieldLabelContext);
  return (
    <TextInput
      accessibilityLabel={props.accessibilityLabel ?? fieldLabel}
      placeholderTextColor={colors.inkFaint}
      selectionColor={colors.coral}
      style={[styles.input, props.multiline && styles.inputMultiline, style]}
      {...props}
    />
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string; description?: string; disabled?: boolean }[];
  onChange(value: T): void;
}) {
  return (
    <View style={styles.segmented} accessibilityRole="radiogroup">
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="radio"
            accessibilityState={{ checked: selected, disabled: option.disabled }}
            disabled={option.disabled}
            onPress={() => onChange(option.value)}
            style={({ pressed }) => [
              styles.segmentOption,
              selected && styles.segmentOptionSelected,
              option.disabled && styles.disabled,
              pressed && styles.pressed,
            ]}
          >
            <Text style={[styles.segmentLabel, selected && styles.segmentLabelSelected]}>{option.label}</Text>
            {option.description ? (
              <Text style={[styles.segmentDescription, selected && styles.segmentDescriptionSelected]}>{option.description}</Text>
            ) : null}
          </Pressable>
        );
      })}
    </View>
  );
}

export function Chip({
  label,
  selected,
  onPress,
  icon,
}: {
  label: string;
  selected?: boolean;
  onPress?: () => void;
  icon?: IconName;
}) {
  const content = (
    <>
      {icon ? <MaterialCommunityIcons name={icon} size={14} color={selected ? colors.white : colors.inkMuted} /> : null}
      <Text style={[styles.chipLabel, selected && styles.chipLabelSelected]}>{label}</Text>
    </>
  );
  if (!onPress) return <View style={[styles.chip, selected && styles.chipSelected]}>{content}</View>;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.chip, selected && styles.chipSelected, pressed && styles.pressed]}
    >
      {content}
    </Pressable>
  );
}

const stateTone: Record<RecordingState, 'green' | 'amber' | 'red' | 'blue' | 'neutral'> = {
  uploading: 'blue',
  verifying: 'blue',
  sealed: 'blue',
  processing: 'blue',
  ready: 'green',
  partial: 'amber',
  failed_retryable: 'red',
  failed_final: 'red',
  cancelled: 'neutral',
  deleting: 'red',
  deleted: 'neutral',
};

export function StatusBadge({ state }: { state: RecordingState }) {
  const tone = stateTone[state];
  return (
    <View style={[styles.badge, styles[`badge_${tone}`]]}>
      <View style={[styles.badgeDot, styles[`badgeDot_${tone}`]]} />
      <Text style={[styles.badgeText, styles[`badgeText_${tone}`]]}>{stateLabel(state)}</Text>
    </View>
  );
}

export function Notice({
  tone = 'info',
  title,
  children,
  action,
}: {
  tone?: 'info' | 'warning' | 'error' | 'success';
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const icon: Record<typeof tone, IconName> = {
    info: 'information-outline',
    warning: 'alert-outline',
    error: 'alert-circle-outline',
    success: 'check-circle-outline',
  };
  return (
    <View style={[styles.notice, styles[`notice_${tone}`]]}>
      <MaterialCommunityIcons name={icon[tone]} size={20} color={colors.ink} />
      <View style={styles.noticeCopy}>
        <Text style={styles.noticeTitle}>{title}</Text>
        {children ? <Text style={styles.noticeBody}>{children}</Text> : null}
      </View>
      {action}
    </View>
  );
}

export function ProgressBar({ value, tone = 'coral' }: { value: number; tone?: 'coral' | 'pine' }) {
  return (
    <View style={styles.progressTrack} accessibilityRole="progressbar" accessibilityValue={{ min: 0, max: 100, now: value }}>
      <View
        style={[
          styles.progressFill,
          { width: `${Math.max(0, Math.min(100, value))}%`, backgroundColor: tone === 'coral' ? colors.coral : colors.pine },
        ]}
      />
    </View>
  );
}

export function CitationChip({ citation, onPress }: { citation: Citation; onPress?: (citation: Citation) => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Open source at ${citationLabel(citation)}`}
      onPress={() => onPress?.(citation)}
      style={({ pressed }) => [styles.citation, pressed && styles.pressed]}
    >
      <MaterialCommunityIcons name="play-circle-outline" size={15} color={colors.blue} />
      <Text numberOfLines={1} style={styles.citationText}>
        {citationLabel(citation)}
      </Text>
    </Pressable>
  );
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <View style={styles.stateView}>
      <ActivityIndicator color={colors.coral} size="large" />
      <Text style={styles.stateTitle}>{label}</Text>
    </View>
  );
}

export function EmptyState({ icon = 'tray', title, body, action }: { icon?: IconName; title: string; body: string; action?: ReactNode }) {
  return (
    <View style={styles.stateView}>
      <View style={styles.stateIcon}>
        <MaterialCommunityIcons name={icon} size={27} color={colors.pine} />
      </View>
      <Text style={styles.stateTitle}>{title}</Text>
      <Text style={styles.stateBody}>{body}</Text>
      {action}
    </View>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <EmptyState
      icon="cloud-alert-outline"
      title="We couldn't load this"
      body={error.message}
      action={onRetry ? <Button variant="secondary" onPress={onRetry}>Try again</Button> : undefined}
    />
  );
}

export function ConfirmDialog({
  visible,
  title,
  body,
  confirmLabel,
  destructive,
  loading,
  onCancel,
  onConfirm,
}: {
  visible: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  destructive?: boolean;
  loading?: boolean;
  onCancel(): void;
  onConfirm(): void;
}) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard} accessibilityViewIsModal>
          <Text style={styles.modalTitle}>{title}</Text>
          <Text style={styles.modalBody}>{body}</Text>
          <View style={styles.modalActions}>
            <Button variant="ghost" onPress={onCancel}>Cancel</Button>
            <Button variant={destructive ? 'danger' : 'primary'} loading={loading} onPress={onConfirm}>
              {confirmLabel}
            </Button>
          </View>
        </View>
      </View>
    </Modal>
  );
}

export function Divider() {
  return <View style={styles.divider} />;
}

export const uiStyles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, flexWrap: 'wrap' },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md },
  stack: { gap: spacing.lg },
  muted: { color: colors.inkMuted, fontSize: 14, lineHeight: 21 },
  label: { color: colors.ink, fontFamily: font.medium, fontSize: 14 },
  heading: { color: colors.ink, fontFamily: font.medium, fontSize: 20, letterSpacing: -0.3 },
});

const styles = StyleSheet.create({
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: 11 },
  brandIcon: { width: 38, height: 38, borderRadius: 12, backgroundColor: colors.coral, alignItems: 'center', justifyContent: 'center' },
  brandName: { color: colors.ink, fontFamily: font.medium, fontSize: 18, letterSpacing: -0.3 },
  brandSub: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 8, letterSpacing: 1.3, marginTop: 1 },
  button: { borderRadius: radius.md, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.sm, borderWidth: 1 },
  button_sm: { minHeight: 36, paddingHorizontal: 12 },
  button_md: { minHeight: 44, paddingHorizontal: 16 },
  button_lg: { minHeight: 50, paddingHorizontal: 20 },
  button_primary: { backgroundColor: colors.pine, borderColor: colors.pine },
  button_secondary: { backgroundColor: colors.surface, borderColor: colors.borderStrong },
  button_ghost: { backgroundColor: 'transparent', borderColor: 'transparent' },
  button_danger: { backgroundColor: colors.red, borderColor: colors.red },
  buttonActive: { opacity: 0.82, transform: [{ scale: 0.99 }] },
  buttonLabel: { fontFamily: font.medium, fontSize: 14 },
  disabled: { opacity: 0.48 },
  pressed: { opacity: 0.7 },
  iconButton: { width: 42, height: 42, alignItems: 'center', justifyContent: 'center', borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  iconButtonActive: { backgroundColor: colors.surfaceMuted },
  card: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.lg, padding: spacing.xl, ...shadow },
  eyebrow: { color: colors.coralDark, fontFamily: font.medium, fontSize: 11, letterSpacing: 1.4 },
  pageTitleRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: spacing.xl, flexWrap: 'wrap' },
  pageTitleCopy: { gap: spacing.sm, maxWidth: 720, flexShrink: 1 },
  pageTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 34, lineHeight: 40, letterSpacing: -1 },
  pageSubtitle: { color: colors.inkMuted, fontSize: 15, lineHeight: 23 },
  sectionTitleRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: spacing.lg, flexWrap: 'wrap' },
  sectionTitleCopy: { gap: 4, flex: 1, minWidth: 160 },
  sectionTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 20, letterSpacing: -0.35 },
  sectionSubtitle: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  field: { gap: spacing.sm },
  fieldLabel: { color: colors.ink, fontFamily: font.medium, fontSize: 13 },
  fieldHint: { color: colors.inkMuted, fontSize: 12, lineHeight: 17 },
  fieldError: { color: colors.red, fontSize: 12, lineHeight: 17 },
  input: { minHeight: 46, borderRadius: radius.md, borderWidth: 1, borderColor: colors.borderStrong, backgroundColor: colors.surface, color: colors.ink, paddingHorizontal: 14, paddingVertical: 11, fontSize: 15 },
  inputMultiline: { minHeight: 100, textAlignVertical: 'top' },
  segmented: { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  segmentOption: { flex: 1, minWidth: 130, minHeight: 58, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, paddingHorizontal: 14, paddingVertical: 11, gap: 3 },
  segmentOptionSelected: { backgroundColor: colors.pine, borderColor: colors.pine },
  segmentLabel: { color: colors.ink, fontFamily: font.medium, fontSize: 14 },
  segmentLabelSelected: { color: colors.white },
  segmentDescription: { color: colors.inkMuted, fontSize: 11, lineHeight: 15 },
  segmentDescriptionSelected: { color: '#D5E7E2' },
  chip: { minHeight: 32, paddingHorizontal: 11, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, flexDirection: 'row', alignItems: 'center', gap: 5, backgroundColor: colors.surface },
  chipSelected: { backgroundColor: colors.pine, borderColor: colors.pine },
  chipLabel: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 12 },
  chipLabelSelected: { color: colors.white },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 6, minHeight: 28, paddingHorizontal: 10, borderRadius: radius.pill },
  badge_green: { backgroundColor: colors.greenSoft },
  badge_amber: { backgroundColor: colors.amberSoft },
  badge_red: { backgroundColor: colors.redSoft },
  badge_blue: { backgroundColor: colors.blueSoft },
  badge_neutral: { backgroundColor: colors.surfaceMuted },
  badgeDot: { width: 6, height: 6, borderRadius: 3 },
  badgeDot_green: { backgroundColor: colors.green },
  badgeDot_amber: { backgroundColor: colors.amber },
  badgeDot_red: { backgroundColor: colors.red },
  badgeDot_blue: { backgroundColor: colors.blue },
  badgeDot_neutral: { backgroundColor: colors.inkMuted },
  badgeText: { fontFamily: font.medium, fontSize: 11 },
  badgeText_green: { color: colors.green },
  badgeText_amber: { color: colors.amber },
  badgeText_red: { color: colors.red },
  badgeText_blue: { color: colors.blue },
  badgeText_neutral: { color: colors.inkMuted },
  notice: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md, borderRadius: radius.md, borderWidth: 1, padding: spacing.lg },
  notice_info: { backgroundColor: colors.blueSoft, borderColor: '#C8DFE9' },
  notice_warning: { backgroundColor: colors.amberSoft, borderColor: '#EAD7A5' },
  notice_error: { backgroundColor: colors.redSoft, borderColor: '#ECCBC6' },
  notice_success: { backgroundColor: colors.greenSoft, borderColor: '#C7E1D7' },
  noticeCopy: { flex: 1, gap: 3 },
  noticeTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 13 },
  noticeBody: { color: colors.inkMuted, fontSize: 12, lineHeight: 18 },
  progressTrack: { height: 6, borderRadius: radius.pill, backgroundColor: colors.surfaceMuted, overflow: 'hidden' },
  progressFill: { height: 6, borderRadius: radius.pill },
  citation: { maxWidth: 240, flexDirection: 'row', alignItems: 'center', gap: 5, backgroundColor: colors.blueSoft, borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 6 },
  citationText: { flexShrink: 1, color: colors.blue, fontFamily: font.medium, fontSize: 11 },
  stateView: { minHeight: 260, alignItems: 'center', justifyContent: 'center', gap: spacing.md, padding: spacing.xl },
  stateIcon: { width: 58, height: 58, borderRadius: 20, backgroundColor: colors.pineSoft, alignItems: 'center', justifyContent: 'center' },
  stateTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 17, textAlign: 'center' },
  stateBody: { maxWidth: 460, color: colors.inkMuted, fontSize: 14, lineHeight: 21, textAlign: 'center' },
  modalBackdrop: { flex: 1, backgroundColor: colors.overlay, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  modalCard: { width: '100%', maxWidth: 460, borderRadius: radius.xl, padding: spacing.xl, backgroundColor: colors.surface, gap: spacing.lg, ...shadow },
  modalTitle: { color: colors.ink, fontFamily: font.medium, fontSize: 22, letterSpacing: -0.4 },
  modalBody: { color: colors.inkMuted, fontSize: 14, lineHeight: 22 },
  modalActions: { flexDirection: 'row', justifyContent: 'flex-end', gap: spacing.sm },
  divider: { height: 1, backgroundColor: colors.border },
});
