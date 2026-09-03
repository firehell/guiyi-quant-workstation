import type { AlertEvent } from '../types/market.ts'
import { isHtdyAlertEvent } from './alertRules.ts'
import { marketDetailEventIdentity, serializeMarketDetailIdentity } from './marketDetailRoute.ts'

export function marketHomeProductChartQuery(symbol: string) {
  return { symbol, series_kind: 'actual_dominant', frequency: '1d' as const }
}

export function marketHomeEventChartQuery(event: AlertEvent) {
  if (isHtdyAlertEvent(event)) {
    return { symbol: event.symbol, series_kind: 'actual_dominant', frequency: event.frequency, overlay: 'htdy' as const }
  }
  return {
    symbol: event.symbol,
    series_kind: 'actual_dominant',
    frequency: '15m' as const,
    focus_bar_end: event.bar_end,
  }
}

export function marketHomeUnifiedProductChartQuery(symbol: string) {
  return serializeMarketDetailIdentity({
    view: 'trend', symbol, seriesKind: 'actual_dominant', frequency: '1d',
  })
}

export function marketHomeUnifiedEventChartQuery(event: AlertEvent) {
  return serializeMarketDetailIdentity(marketDetailEventIdentity(event))
}
