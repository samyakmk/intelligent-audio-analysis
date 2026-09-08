import MaterialCommunityIcons from '@expo/vector-icons/MaterialCommunityIcons';
import { Redirect, usePathname, useRouter } from 'expo-router';
import { useState, type ComponentProps, type ReactNode } from 'react';
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
import { formatMoney, initials } from '@/lib/format';
import { mobileContentPadding } from '@/lib/layout';
import { useSession } from '@/providers/SessionProvider';
import { colors, font, menuShadow, radius, spacing } from '@/theme';

type IconName = ComponentProps<typeof MaterialCommunityIcons>['name'];

const navigation: { href: string; label: string; icon: IconName; match?: string }[] = [
  { href: '/', label: 'Library', icon: 'bookshelf', match: '/recordings' },
  { href: '/upload', label: 'Upload', icon: 'tray-arrow-up' },
  { href: '/search', label: 'Search', icon: 'magnify' },
  { href: '/ask', label: 'Ask Pocket', icon: 'message-processing-outline' },
  { href: '/tasks', label: 'Tasks & insights', icon: 'checkbox-marked-circle-outline' },
  { href: '/costs', label: 'Cost lab', icon: 'chart-waterfall' },
];

export function AppShell({ children, scroll = true }: { children: ReactNode; scroll?: boolean }) {
  const { session, loading, switchWorkspace, logout } = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const desktop = width >= 960;
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [switching, setSwitching] = useState(false);

  if (loading) return <View style={styles.loading}><LoadingState label="Opening your workspace…" /></View>;
  if (!session) return <Redirect href="/login" />;

  const go = (href: string) => router.push(href as never);
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
      {desktop ? (
        <View style={[styles.sidebar, { paddingTop: Math.max(insets.top, 24), paddingBottom: Math.max(insets.bottom, 24) }]}>
          <BrandMark />
          <View style={styles.workspaceArea}>
            <Text style={styles.workspaceLabel}>WORKSPACE</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Switch workspace"
              onPress={() => setWorkspaceOpen((value) => !value)}
              style={({ pressed }) => [styles.workspaceButton, pressed && styles.pressed]}
            >
              <View style={styles.workspaceMonogram}>
                <Text style={styles.workspaceMonogramText}>{initials(session.workspace.name)}</Text>
              </View>
              <View style={styles.workspaceCopy}>
                <Text numberOfLines={1} style={styles.workspaceName}>{session.workspace.name}</Text>
                <Text style={styles.workspaceRole}>{session.workspace.role ?? 'Member'}</Text>
              </View>
              <MaterialCommunityIcons name={workspaceOpen ? 'chevron-up' : 'chevron-down'} size={18} color={colors.inkMuted} />
            </Pressable>
            {workspaceOpen ? (
              <View style={styles.workspaceMenu}>
                {session.workspaces.map((workspace) => (
                  <Pressable
                    key={workspace.id}
                    accessibilityRole="menuitem"
                    onPress={async () => {
                      setSwitching(true);
                      try {
                        await switchWorkspace(workspace.id);
                      } catch {
                        // SessionProvider reconciles a potentially committed
                        // mutation before returning. Always leave scoped data.
                      } finally {
                        setWorkspaceOpen(false);
                        router.replace('/');
                        setSwitching(false);
                      }
                    }}
                    disabled={switching || workspace.id === session.workspace.id}
                    style={({ pressed }) => [styles.workspaceMenuItem, pressed && styles.pressed]}
                  >
                    <Text style={styles.workspaceMenuText}>{workspace.name}</Text>
                    {workspace.id === session.workspace.id ? (
                      <MaterialCommunityIcons name="check" size={17} color={colors.green} />
                    ) : null}
                  </Pressable>
                ))}
              </View>
            ) : null}
          </View>
          <View style={styles.nav} accessibilityRole="menu">
            {navigation.map((item) => {
              const active = item.href === '/' ? pathname === '/' || pathname.startsWith(item.match ?? '') : pathname.startsWith(item.href);
              return (
                <Pressable
                  key={item.href}
                  accessibilityRole="menuitem"
                  accessibilityState={{ selected: active }}
                  onPress={() => go(item.href)}
                  style={({ pressed }) => [
                    styles.navItem,
                    active && styles.navItemActive,
                    pressed && !active && styles.navItemHover,
                  ]}
                >
                  <MaterialCommunityIcons name={item.icon} size={20} color={active ? colors.pine : colors.inkMuted} />
                  <Text style={[styles.navLabel, active && styles.navLabelActive]}>{item.label}</Text>
                </Pressable>
              );
            })}
          </View>
          <View style={styles.sidebarFooter}>
            <View style={styles.budgetRow}>
              <Text style={styles.budgetLabel}>MONTHLY AI SPEND</Text>
              <Text style={styles.budgetValue}>
                {formatMoney(session.workspace.monthly_spend_usd ?? 0, 2)} / {formatMoney(session.workspace.monthly_budget_usd ?? 50, 0)}
              </Text>
            </View>
            <View style={styles.avatarRow}>
              <View style={styles.avatar}><Text style={styles.avatarText}>{initials(session.principal.name)}</Text></View>
              <View style={styles.userCopy}>
                <Text numberOfLines={1} style={styles.userName}>{session.principal.name}</Text>
                <Text numberOfLines={1} style={styles.userEmail}>{session.principal.email ?? 'Demo account'}</Text>
              </View>
              <Pressable accessibilityRole="button" accessibilityLabel="Sign out" onPress={logout} hitSlop={10}>
                <MaterialCommunityIcons name="logout" size={19} color={colors.inkMuted} />
              </Pressable>
            </View>
          </View>
        </View>
      ) : (
        <View style={[styles.mobileHeader, { paddingTop: Math.max(insets.top, 12) }]}>
          <BrandMark compact />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Current workspace: ${session.workspace.name}. Tap to switch.`}
            onPress={async () => {
              const currentIndex = session.workspaces.findIndex((item) => item.id === session.workspace.id);
              const next = session.workspaces[(currentIndex + 1) % session.workspaces.length];
              if (next) {
                try {
                  await switchWorkspace(next.id);
                } catch {
                  // The provider reconciles server state after a lost response.
                } finally {
                  router.replace('/');
                }
              }
            }}
            style={styles.mobileWorkspace}
          >
            <Text numberOfLines={1} style={styles.mobileWorkspaceText}>{session.workspace.name}</Text>
            <MaterialCommunityIcons name="swap-horizontal" size={17} color={colors.inkMuted} />
          </Pressable>
        </View>
      )}

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
            const active = item.href === '/' ? pathname === '/' || pathname.startsWith(item.match ?? '') : pathname.startsWith(item.href);
            return (
              <Pressable
                key={item.href}
                accessibilityRole="tab"
                accessibilityLabel={item.label}
                accessibilityState={{ selected: active }}
                onPress={() => go(item.href)}
                style={styles.bottomNavItem}
              >
                <MaterialCommunityIcons name={item.icon} size={21} color={active ? colors.coral : colors.inkFaint} />
                <Text numberOfLines={1} style={[styles.bottomNavLabel, active && styles.bottomNavLabelActive]}>
                  {item.label === 'Tasks & insights' ? 'Tasks' : item.label === 'Ask Pocket' ? 'Ask' : item.label === 'Cost lab' ? 'Costs' : item.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, flexDirection: 'row', backgroundColor: colors.canvas },
  loading: { flex: 1, justifyContent: 'center', backgroundColor: colors.canvas },
  sidebar: { width: 258, paddingHorizontal: 18, backgroundColor: colors.surface, borderRightWidth: 1, borderRightColor: colors.border, gap: spacing.xl },
  workspaceArea: { zIndex: 5, gap: 7 },
  workspaceLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 9, letterSpacing: 1.2, paddingHorizontal: 9 },
  workspaceButton: { minHeight: 56, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.canvas, paddingHorizontal: 10, flexDirection: 'row', alignItems: 'center', gap: 9 },
  workspaceMonogram: { width: 34, height: 34, borderRadius: 11, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.pine },
  workspaceMonogramText: { color: colors.white, fontFamily: font.medium, fontSize: 12 },
  workspaceCopy: { flex: 1, gap: 2 },
  workspaceName: { color: colors.ink, fontFamily: font.medium, fontSize: 13 },
  workspaceRole: { color: colors.inkMuted, fontSize: 10, textTransform: 'capitalize' },
  workspaceMenu: { position: 'absolute', top: 80, left: 0, right: 0, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: 6, backgroundColor: colors.surface, ...menuShadow },
  workspaceMenuItem: { minHeight: 42, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 10, borderRadius: radius.sm },
  workspaceMenuText: { color: colors.ink, fontSize: 13 },
  nav: { flex: 1, gap: 4 },
  navItem: { minHeight: 44, paddingHorizontal: 12, borderRadius: radius.md, flexDirection: 'row', alignItems: 'center', gap: 12 },
  navItemActive: { backgroundColor: colors.pineSoft },
  navItemHover: { backgroundColor: colors.canvas },
  navLabel: { color: colors.inkMuted, fontFamily: font.medium, fontSize: 13 },
  navLabelActive: { color: colors.pine },
  pressed: { opacity: 0.7 },
  sidebarFooter: { gap: spacing.lg },
  budgetRow: { gap: 4, paddingHorizontal: 4 },
  budgetLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 8, letterSpacing: 1 },
  budgetValue: { color: colors.inkMuted, fontSize: 11 },
  avatarRow: { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.lg, flexDirection: 'row', alignItems: 'center', gap: 10 },
  avatar: { width: 35, height: 35, borderRadius: 18, backgroundColor: colors.coralSoft, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: colors.coralDark, fontFamily: font.medium, fontSize: 12 },
  userCopy: { flex: 1, gap: 2 },
  userName: { color: colors.ink, fontFamily: font.medium, fontSize: 12 },
  userEmail: { color: colors.inkFaint, fontSize: 9 },
  main: { flex: 1, minWidth: 0 },
  scroll: { flex: 1 },
  scrollContent: { flexGrow: 1, alignItems: 'center' },
  contentInner: { width: '100%', maxWidth: 1320, padding: spacing.xxxl, gap: spacing.xl },
  contentInnerMobile: { paddingHorizontal: spacing.lg },
  mobileHeader: { position: 'absolute', zIndex: 10, top: 0, left: 0, right: 0, minHeight: 66, paddingHorizontal: spacing.lg, paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  mobileWorkspace: { maxWidth: 200, height: 38, paddingHorizontal: 11, borderRadius: radius.pill, flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: colors.canvas },
  mobileWorkspaceText: { maxWidth: 150, color: colors.ink, fontFamily: font.medium, fontSize: 11 },
  bottomNav: { position: 'absolute', zIndex: 10, left: 0, right: 0, bottom: 0, minHeight: 70, paddingTop: 8, paddingHorizontal: 4, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface, flexDirection: 'row', alignItems: 'flex-start' },
  bottomNavItem: { flex: 1, minWidth: 0, gap: 3, alignItems: 'center' },
  bottomNavLabel: { color: colors.inkFaint, fontFamily: font.medium, fontSize: 9 },
  bottomNavLabelActive: { color: colors.coralDark },
});
