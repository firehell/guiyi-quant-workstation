import type { AlertEvent } from '../types/market.ts'
import { isHtdyAlertEvent, isSubingThsAlertEvent } from './alertRules.ts'
import { marketDetailEventIdentity, serializeMarketDetailIdentity } from './marketDetailRoute.ts'

export function marketHomeProductChartQuery(symbol: string) {
  return { symbol, series_kind: 'actual_dominant', frequency: '1d' as const }
}

export function marketHomeEventChartQuery(event: AlertEvent) {
  if (isSubingThsAlertEvent(event)) return marketHomeUnifiedEventChartQuery(event)
  if (isHtdyAlertEvent(event)) {
    return { symbol: event.symbol, series_kind: 'actual_dominant', frequency: event.frequency, overlay: 'htdy' as const }
  }
  throw new Error('unsupported AlertEvent identity')
}

export function marketHomeUnifiedProductChartQuery(symbol: string) {
  return serializeMarketDetailIdentity({
    view: 'newow', symbol, strategy: 'trend', seriesKind: 'actual_dominant', frequency: '1d',
  })
}

export function marketHomeUnifiedEventChartQuery(event: AlertEvent) {
  return serializeMarketDetailIdentity(marketDetailEventIdentity(event))
}

export function marketHomeViewChartQuery(view: 'newow' | 'htdy' | 'subing' | 'free', symbol: string) {
  return serializeMarketDetailIdentity({
    view, symbol, ...(view === 'newow' ? { strategy: 'trend' as const } : {}),
    seriesKind: 'actual_dominant', frequency: view === 'subing' ? '15m' : '1d',
  })
}
