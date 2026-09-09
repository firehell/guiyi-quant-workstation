import type { AlertEvent } from '../types/market.ts'
import { isHtdyAlertEvent, isSubingThsAlertEvent } from './alertRules.ts'
import { marketDetailEventIdentity, serializeMarketDetailIdentity } from './marketDetailRoute.ts'

export function marketHomeEventChartQuery(event: AlertEvent) {
  if (!isHtdyAlertEvent(event) && !isSubingThsAlertEvent(event)) throw new Error('unsupported AlertEvent identity')
  return marketHomeUnifiedEventChartQuery(event)
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
