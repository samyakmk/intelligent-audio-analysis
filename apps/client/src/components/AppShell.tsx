import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Redirect, usePathname, useRouter } from 'expo-router';
import { type ComponentProps, type ReactNode } from 'react';
import {
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { BrandMark, LoadingState } from '@/components/ui';
import { mobileContentPadding } from '@/lib/layout';
import { useSession } from '@/providers/SessionProvider';
import { colors, font, spacing } from '@/theme';

type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];

const navigation: { href: string; label: string; icon: IconName; matches?: string[] }[] = [
  { href: '/', label: 'Run demo', icon: 'microphone-outline', matches: ['/upload'] },
  { href: '/results', label: 'Results', icon: 'text-box-check-outline', matches: ['/recordings'] },
  { href: '/prompt-flow', label: 'Prompt flow', icon: 'transit-connection-variant' },
];

export function AppShell({ children, scroll = true }: { children: ReactNode; scroll?: boolean }) {
  const { session, loading } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const desktop = width >= 760;

  if (loading) return <View style={styles.loading}><LoadingState label="Opening the demo…" /></View>;
  if (!session) return <Redirect href="/login" />;

  const isActive = (item: (typeof navigation)[number]) => (
    item.href === '/'
      ? pathname === '/' || (item.matches ?? []).some((match) => pathname.startsWith(match))
      : pathname.startsWith(item.href) || (item.matches ?? []).some((match) => pathname.startsWith(match))
  );
  const page = (
    <View
      style={[
        styles.contentInner,
        !desktop && styles.contentInnerMobile,
        !desktop && mobileContentPadding(insets.top, insets.bottom),
      ]}
    >
      {children}
    </View>
  );

  return (
    <View style={styles.root}>
      <View style={[styles.header, { paddingTop: Math.max(insets.top, desktop ? 16 : 10) }]}>
        <BrandMark compact={!desktop} />
        {desktop ? (
          <View style={styles.nav} accessibilityRole="menu">
            {navigation.map((item) => {
              const active = isActive(item);
              return (
                <Pressable
                  key={item.href}
                  accessibilityRole="menuitem"
                  accessibilityState={{ selected: active }}
                  onPress={() => router.push(item.href as never)}
                  style={({ pressed }) => [styles.navItem, active && styles.navItemActive, pressed && styles.pressed]}
                >
                  <MaterialCommunityIcons name={item.icon} size={18} color={active ? colors.pine : colors.inkMuted} />
                  <Text style={[styles.navLabel, active && styles.navLabelActive]}>{item.label}</Text>
                </Pressable>
              );
            })}
          </View>
        ) : (
          <Text style={styles.demoLabel}>ARCHITECTURE DEMO</Text>
        )}
      </View>

      <View style={styles.main}>
        {scroll ? (
          <ScrollView
            style={styles.scroll}
            contentContainerStyle={styles.scrollContent}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={Platform.OS !== 'web'}
          >
            {page}
          </ScrollView>
        ) : page}
      </View>

      {!desktop ? (
        <View style={[styles.bottomNav, { paddingBottom: Math.max(insets.bottom, 8) }]} accessibilityRole="tablist">
          {navigation.map((item) => {
            const active = isActive(item);
            return (
              <Pressable
                key={item.href}
                accessibilityRole="tab"
                accessibilityLabel={item.label}
                accessibilityState={{ selected: active }}
                onPress={() => router.push(item.href as never)}
                style={styles.bottomNavItem}
              >
                <MaterialCommunityIcons name={item.icon} size={21} color={active ? colors.coral : colors.inkFaint} />
                <Text style={[styles.bottomNavLabel, active && styles.bottomNavLabelActive]}>{item.label}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.canvas },
  loading: { flex: 1, justifyContent: 'center', backgroundColor: colors.canvas },
  header: { zIndex: 10, minHeight: 74, paddingHorizontal: spacing.xxl, paddingBottom: 14, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.xl },
  nav: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  navItem: { minHeight: 42, paddingHorizontal: spacing.lg, borderRadius: 12, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  navItemActive: { backgroundColor: colors.pineSoft },
  navLabel: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 13 },
  navLabelActive: { color: colors.pine },
  pressed: { opacity: 0.7 },
  demoLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 1.1 },
  main: { flex: 1, minWidth: 0 },
  scroll: { flex: 1 },
  scrollContent: { flexGrow: 1, alignItems: 'center' },
  contentInner: { width: '100%', maxWidth: 1120, padding: spacing.xxxl, gap: spacing.xl },
  contentInnerMobile: { paddingHorizontal: spacing.lg },
  bottomNav: { position: 'absolute', zIndex: 10, left: 0, right: 0, bottom: 0, minHeight: 70, paddingTop: 8, paddingHorizontal: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface, flexDirection: 'row', alignItems: 'flex-start' },
  bottomNavItem: { flex: 1, minWidth: 0, gap: 3, alignItems: 'center' },
  bottomNavLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 9 },
  bottomNavLabelActive: { color: colors.coralDark },
});
