import type { GlobalThemeOverrides } from 'naive-ui'

export const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#3b82f6',
    primaryColorHover: '#2563eb',
    primaryColorPressed: '#1d4ed8',
    bodyColor: '#0b0f14',
    cardColor: '#11151c',
    modalColor: '#11151c',
    popoverColor: '#1a2030',
    tableColor: '#11151c',
    inputColor: '#1a2030',
    borderColor: '#2a3344',
    dividerColor: '#2a3344',
    textColor1: '#e2e8f0',
    textColor2: '#cbd5e1',
    textColor3: '#94a3b8',
  },
  Layout: {
    color: '#0b0f14',
    siderColor: '#11151c',
    headerColor: '#11151c',
  },
  Menu: {
    itemColorActive: '#1a2030',
    itemColorActiveHover: '#1a2030',
    itemTextColorActive: '#3b82f6',
    itemTextColorActiveHover: '#60a5fa',
  },
  Card: {
    color: '#11151c',
    borderColor: '#2a3344',
  },
  DataTable: {
    thColor: '#1a2030',
    tdColor: '#11151c',
    borderColor: '#2a3344',
  },
}
