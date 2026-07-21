import type { GlobalThemeOverrides } from 'naive-ui'

/**
 * Naive UI 深色主题覆盖。
 * Naive 在 JS 中推导 alpha 变体，因此此处须使用具体色值；与 tokens.css 保持一致。
 */
// Naive UI derives alpha variants in JavaScript and therefore requires concrete
// color values here. Keep these values aligned with tokens.css.
const palette = {
  app: '#060a10',
  canvas: '#0a0f18',
  panel: '#0d1420',
  panelStrong: '#111a29',
  overlay: '#0d1420',
  hover: 'rgba(255, 255, 255, 0.04)',
  selected: 'rgba(20, 133, 238, 0.12)',
  border: '#202b3e',
  primaryText: '#e8edf5',
  secondaryText: '#aeb9c9',
  mutedText: '#8290a6',
  accent: '#1485ee',
  accentHover: '#34a0ff',
  accentPressed: '#0a6fd4',
} as const

/** 导出给 NConfigProvider 的全局 theme-overrides */
export const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: palette.accent,
    primaryColorHover: palette.accentHover,
    primaryColorPressed: palette.accentPressed,
    primaryColorSuppl: palette.accentHover,
    bodyColor: palette.app,
    cardColor: palette.panel,
    modalColor: palette.panel,
    popoverColor: palette.overlay,
    tableColor: palette.panel,
    inputColor: palette.panelStrong,
    actionColor: palette.panelStrong,
    borderColor: palette.border,
    dividerColor: palette.border,
    textColor1: palette.primaryText,
    textColor2: palette.secondaryText,
    textColor3: palette.mutedText,
    placeholderColor: palette.mutedText,
    fontFamily: "'PingFang SC', 'Microsoft YaHei', system-ui, -apple-system, sans-serif",
    fontFamilyMono: "'SFMono-Regular', 'SF Mono', 'Roboto Mono', Menlo, monospace",
    borderRadius: '8px',
    heightMedium: '34px',
    heightSmall: '30px',
  },
  Layout: {
    color: palette.app,
    siderColor: palette.canvas,
    headerColor: palette.canvas,
  },
  Menu: {
    color: 'transparent',
    groupTextColor: palette.mutedText,
    itemColorHover: palette.hover,
    itemColorActive: palette.selected,
    itemColorActiveHover: palette.selected,
    itemTextColor: palette.secondaryText,
    itemTextColorHover: palette.primaryText,
    itemTextColorActive: palette.accentHover,
    itemTextColorActiveHover: palette.accentHover,
    itemIconColor: palette.mutedText,
    itemIconColorHover: palette.primaryText,
    itemIconColorActive: palette.accentHover,
    itemHeight: '38px',
    itemBorderRadius: '5px',
  },
  Card: {
    color: palette.panel,
    borderColor: palette.border,
    borderRadius: '10px',
    paddingSmall: '14px',
  },
  DataTable: {
    thColor: '#121c2b',
    thColorHover: '#121c2b',
    tdColor: palette.panel,
    tdColorHover: palette.hover,
    borderColor: palette.border,
    thTextColor: palette.mutedText,
    tdTextColor: palette.secondaryText,
  },
  Drawer: {
    color: palette.panel,
  },
  Tabs: {
    tabTextColorLine: palette.mutedText,
    tabTextColorActiveLine: palette.accentHover,
    tabTextColorHoverLine: palette.primaryText,
    barColor: palette.accent,
  },
  Button: {
    borderRadiusSmall: '5px',
    borderRadiusMedium: '8px',
  },
}
