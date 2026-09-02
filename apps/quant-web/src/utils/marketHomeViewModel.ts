import type {
  AlertEvent,
  CurrentAlertEventsResponse,
  MarketHomeOverviewItem,
  MarketHomeOverviewResponse,
  MarketHomeTrend,
} from '../types/market.ts'
import { alertEventIdentityKey } from './alertRules.ts'

export type MarketHomeAlignment = 'aligned-up' | 'aligned-down' | 'neutral' | 'unavailable' | 'mixed'
export type MarketHomeAvailability = 'ready' | 'degraded' | 'unavailable' | 'empty'

export interface MarketHomeViewModelInput {
  overview: MarketHomeOverviewResponse | null
  overviewStale: boolean
  runtime: { status: string } | null
  runtimeStale: boolean
  events: CurrentAlertEventsResponse | null
  eventsStale: boolean
  eventsUnavailable?: boolean
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
  const eventAvailability: MarketHomeAvailability = input.eventsUnavailable || input.eventsStale
    ? 'unavailable'
    : !input.events
    ? 'unavailable'
    : input.events.status === 'unavailable'
      ? 'unavailable'
      : input.events.items.length ? 'ready' : 'empty'
  const latestEvents = eventAvailability === 'unavailable' ? new Map<string, AlertEvent>() : latestEventsBySymbol(input.events?.items ?? [])
  // A failed refresh preserves a cached snapshot, while a successful degraded
  // overview is current transport data whose market facts are explicitly stale.
  // Both must withhold colored trend facts, but only the former is cached stale.
  const staleOverviewFacts = Boolean(input.overviewStale || (input.overview && input.overview.freshness !== 'fresh'))
  const rows = (input.overview?.items ?? []).map((item) => ({
    ...item,
    alignment: staleOverviewFacts ? 'unavailable' : alignmentFor(item.daily_trend, item.weekly_trend),
    dailyState: staleOverviewFacts ? 'unavailable' : item.daily_trend,
    weeklyState: staleOverviewFacts ? 'unavailable' : item.weekly_trend,
    event: latestEvents.get(item.symbol) ?? null,
  }))

  return {
    overview: { availability: overviewAvailability, cachedStale: Boolean(input.overviewStale) },
    runtime: { availability: input.runtime ? 'ready' : 'unavailable', status: input.runtime?.status ?? null, cachedStale: Boolean(input.runtimeStale) },
    events: { availability: eventAvailability, cachedStale: Boolean(input.eventsStale), tradingDay: input.events?.trading_day ?? null },
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

function latestEventsBySymbol(events: AlertEvent[]): Map<string, AlertEvent> {
  const identities = new Set<string>()
  const latest = new Map<string, AlertEvent>()
  for (const event of events) {
    const identity = alertEventIdentityKey(event)
    if (identities.has(identity)) throw new Error('current Alert events contain conflicting identities')
    identities.add(identity)
    const previous = latest.get(event.symbol)
    if (!previous || compareEvent(event, previous) > 0) latest.set(event.symbol, event)
  }
  return latest
}

function compareEvent(left: AlertEvent, right: AlertEvent): number {
  const detectedDifference = Date.parse(left.detected_at) - Date.parse(right.detected_at)
  if (detectedDifference) return detectedDifference
  const barDifference = Date.parse(left.bar_end) - Date.parse(right.bar_end)
  return barDifference || left.id - right.id
}
