import { Platform } from 'react-native';

export const colors = {
  canvas: '#F4F5EF',
  surface: '#FFFFFF',
  surfaceMuted: '#EBEEE7',
  ink: '#172523',
  inkMuted: '#64706C',
  inkFaint: '#8B9591',
  border: '#D9DED7',
  borderStrong: '#BCC6BE',
  pine: '#123B37',
  pineSoft: '#DDEBE5',
  coral: '#E45745',
  coralDark: '#BA3E30',
  coralSoft: '#FCE7E1',
  blue: '#356C8C',
  blueSoft: '#E2EEF4',
  amber: '#9A6814',
  amberSoft: '#FFF0CC',
  red: '#B8403A',
  redSoft: '#FBE5E2',
  green: '#27705A',
  greenSoft: '#DFF0E8',
  white: '#FFFFFF',
  black: '#000000',
  overlay: 'rgba(15, 29, 27, 0.48)',
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 18,
  xl: 26,
  pill: 999,
} as const;

export const shadow = Platform.select({
  web: {
    boxShadow: '0 12px 32px rgba(28, 51, 46, 0.08)',
  } as object,
  default: {
    shadowColor: colors.black,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.08,
    shadowRadius: 20,
    elevation: 3,
  },
});

export const font = {
  regular: Platform.select({ ios: 'System', android: 'sans-serif', default: 'system-ui' }),
  medium: Platform.select({ ios: 'System', android: 'sans-serif-medium', default: 'system-ui' }),
  mono: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'ui-monospace' }),
};
