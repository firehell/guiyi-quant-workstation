import type {
  AlertEvent,
  MarketHomeOverviewItem,
  MarketHomeOverviewResponse,
  MarketHomeTrend,
} from '../types/market.ts'

export type MarketHomeAlignment = 'aligned-up' | 'aligned-down' | 'neutral' | 'unavailable' | 'mixed'
export type MarketHomeAvailability = 'ready' | 'degraded' | 'unavailable' | 'empty'

export interface MarketHomeViewModelInput {
  overview: MarketHomeOverviewResponse | null
  overviewStale: boolean
  runtime: { status: string } | null
  runtimeStale: boolean
}

export interface MarketHomeRow extends MarketHomeOverviewItem {
  alignment: MarketHomeAlignment
  dailyState: MarketHomeTrend
  weeklyState: MarketHomeTrend
  event: AlertEvent | null
}

export function buildMarketHomeViewModel(input: MarketHomeViewModelInput) {
  const overviewAvailability: Exclude<MarketHomeAvailability, 'empty'> = input.overview
    ? input.overview.status
    : 'unavailable'
  // A failed refresh preserves a cached snapshot, while a successful degraded
  // overview is current transport data whose market facts are explicitly stale.
  // Both must withhold colored trend facts, but only the former is cached stale.
  const staleOverviewFacts = Boolean(input.overviewStale || (input.overview && input.overview.freshness !== 'fresh'))
  const rows = (input.overview?.items ?? []).map((item) => ({
    ...item,
    alignment: staleOverviewFacts ? 'unavailable' : alignmentFor(item.daily_trend, item.weekly_trend),
    dailyState: staleOverviewFacts ? 'unavailable' : item.daily_trend,
    weeklyState: staleOverviewFacts ? 'unavailable' : item.weekly_trend,
    event: null,
  }))

  return {
    overview: { availability: overviewAvailability, cachedStale: Boolean(input.overviewStale) },
    runtime: { availability: input.runtime ? 'ready' : 'unavailable', status: input.runtime?.status ?? null, cachedStale: Boolean(input.runtimeStale) },
    rows,
  }
}

export function alignmentFor(daily: MarketHomeTrend, weekly: MarketHomeTrend): MarketHomeAlignment {
  if (daily === 'unavailable' || weekly === 'unavailable') return 'unavailable'
  if (daily === 'up' && weekly === 'up') return 'aligned-up'
  if (daily === 'down' && weekly === 'down') return 'aligned-down'
  if (daily === 'neutral' && weekly === 'neutral') return 'neutral'
  return 'mixed'
}

export function formatMarketHomeNumber(value: number | null, maximumFractionDigits = 2): string {
  return value === null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits }).format(value)
}
