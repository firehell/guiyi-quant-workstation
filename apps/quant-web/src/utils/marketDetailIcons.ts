export const MARKET_DETAIL_ICON_NAMES = [
  'back', 'chevron-down', 'chevron-right', 'history', 'alert', 'more',
  'fullscreen', 'settings', 'warning', 'info', 'data', 'close',
  'refresh', 'contract-switch',
] as const

export type MarketDetailIconName = (typeof MARKET_DETAIL_ICON_NAMES)[number]

export interface MarketDetailIconDefinition {
  name: MarketDetailIconName
  label: string
  mode: 'stroke' | 'fill'
  paths: readonly string[]
  circles: readonly { cx: number; cy: number; r: number }[]
  referenceRole: 'navigation' | 'action' | 'disclosure' | 'status' | 'chart'
}

const MARKET_DETAIL_ICON_DEFINITIONS: Record<MarketDetailIconName, MarketDetailIconDefinition> = {
  back: {
    name: 'back', label: '返回', mode: 'stroke', paths: ['M15.5 5 8.5 12l7 7'], circles: [], referenceRole: 'navigation',
  },
  'chevron-down': {
    name: 'chevron-down', label: '展开', mode: 'stroke', paths: ['M7 9.5 12 14.5 17 9.5'], circles: [], referenceRole: 'disclosure',
  },
  'chevron-right': {
    name: 'chevron-right', label: '进入', mode: 'stroke', paths: ['M9.5 7 14.5 12 9.5 17'], circles: [], referenceRole: 'disclosure',
  },
  history: {
    name: 'history', label: '历史记录', mode: 'stroke', paths: ['M4 5v5h5', 'M4.7 9.5A8 8 0 1 0 7 5.3', 'M12 8v4l3 2'], circles: [], referenceRole: 'action',
  },
  alert: {
    name: 'alert', label: '预警', mode: 'stroke', paths: ['M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9', 'M10 20h4'], circles: [], referenceRole: 'action',
  },
  more: {
    name: 'more', label: '更多操作', mode: 'fill', paths: [], circles: [{ cx: 6, cy: 12, r: 1.5 }, { cx: 12, cy: 12, r: 1.5 }, { cx: 18, cy: 12, r: 1.5 }], referenceRole: 'action',
  },
  fullscreen: {
    name: 'fullscreen', label: '全屏', mode: 'stroke', paths: ['M8 3H3v5', 'M16 3h5v5', 'M21 16v5h-5', 'M8 21H3v-5'], circles: [], referenceRole: 'chart',
  },
  settings: {
    name: 'settings', label: '设置', mode: 'stroke', paths: ['M4 7h10', 'M18 7h2', 'M4 17h2', 'M10 17h10'], circles: [{ cx: 16, cy: 7, r: 2 }, { cx: 8, cy: 17, r: 2 }], referenceRole: 'action',
  },
  warning: {
    name: 'warning', label: '警示', mode: 'stroke', paths: ['M12 3 22 20H2Z', 'M12 8v5', 'M12 17h.01'], circles: [], referenceRole: 'status',
  },
  info: {
    name: 'info', label: '信息', mode: 'stroke', paths: ['M12 10v6', 'M12 7h.01'], circles: [{ cx: 12, cy: 12, r: 9 }], referenceRole: 'status',
  },
  data: {
    name: 'data', label: '数据', mode: 'stroke', paths: ['M4 6c0-2 16-2 16 0s-16 2-16 0', 'M4 6v6c0 2 16 2 16 0V6', 'M4 12v6c0 2 16 2 16 0v-6'], circles: [], referenceRole: 'status',
  },
  close: {
    name: 'close', label: '关闭', mode: 'stroke', paths: ['M6 6l12 12', 'M18 6 6 18'], circles: [], referenceRole: 'action',
  },
  refresh: {
    name: 'refresh', label: '刷新', mode: 'stroke', paths: ['M20 11a8 8 0 1 0-2.3 5.7', 'M20 4v7h-7'], circles: [], referenceRole: 'action',
  },
  'contract-switch': {
    name: 'contract-switch', label: '切换合约', mode: 'stroke', paths: ['M5 7h12', 'M14 4l3 3-3 3', 'M19 17H7', 'M10 14l-3 3 3 3'], circles: [], referenceRole: 'navigation',
  },
}

export function marketDetailIconDefinition(name: MarketDetailIconName): MarketDetailIconDefinition {
  return MARKET_DETAIL_ICON_DEFINITIONS[name]
}
