import type { ProductResearchResponse } from '../types/market.ts'

export interface MarketBackgroundSummary {
  label: '同向偏多' | '同向偏空' | '中性' | '未共振' | '数据不足'
  tone: 'up' | 'down' | 'neutral' | 'warning'
}

export function summarizeMarketBackground(
  daily: ProductResearchResponse['daily_trend'],
  weekly: ProductResearchResponse['weekly_trend'],
): MarketBackgroundSummary {
  if (daily === 'unavailable' || weekly === 'unavailable') {
    return { label: '数据不足', tone: 'warning' }
  }
  if (daily === 'up' && weekly === 'up') return { label: '同向偏多', tone: 'up' }
  if (daily === 'down' && weekly === 'down') return { label: '同向偏空', tone: 'down' }
  if (daily === 'neutral' && weekly === 'neutral') return { label: '中性', tone: 'neutral' }
  return { label: '未共振', tone: 'warning' }
}
