export type MarketHomeIconState = 'up' | 'aligned' | 'down' | 'neutral' | 'unavailable'
export type MarketHomeIconSize = 'legend' | 'table' | 'micro'

export const MARKET_HOME_ICON_SIZES = { legend: 40, table: 28, micro: 24 } as const

export const MARKET_HOME_STATE_META: Record<MarketHomeIconState, { color: string; label: string }> = {
  up: { color: '#E63935', label: '上行' },
  aligned: { color: '#FF9601', label: '周期同向' },
  down: { color: '#35C759', label: '下行' },
  neutral: { color: '#017AFF', label: '中性' },
  unavailable: { color: '#98A2B3', label: '数据不足' },
}

export const MARKET_HOME_ICON_GLYPHS = {
  up: 'M12 6.5 19 17.5H5Z',
  aligned: 'M6.5 12.3 10.2 16 17.8 8.3',
  down: 'M5 6.5h14L12 17.5Z',
  neutral: 'm7.2 7.2 9.6 9.6m0-9.6-9.6 9.6',
  unavailable: 'circle:12:12:2.2',
  microUp: 'M6 15.5 10 11.5 13 13.5 18 8.5',
  microArrow: 'M14.5 8.5H18v3.5',
} as const
