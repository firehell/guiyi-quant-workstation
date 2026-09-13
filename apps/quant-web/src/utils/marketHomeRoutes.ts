import type { AlertEvent } from '../types/market.ts'
import { isHtdyAlertEvent, isSubingThsAlertEvent } from './alertRules.ts'
import { marketDetailEventIdentity, serializeMarketDetailIdentity } from './marketDetailRoute.ts'
import type { NewowFrequency } from '../types/marketDetail.ts'

export function marketHomeEventChartQuery(event: AlertEvent) {
  if (!isHtdyAlertEvent(event) && !isSubingThsAlertEvent(event)) throw new Error('unsupported AlertEvent identity')
  return marketHomeUnifiedEventChartQuery(event)
}

export function marketHomeUnifiedProductChartQuery(symbol: string, frequency: NewowFrequency) {
  return serializeMarketDetailIdentity({
    view: 'newow', symbol, strategy: 'trend', seriesKind: 'actual_dominant', frequency,
  })
}

export function marketHomeUnifiedEventChartQuery(event: AlertEvent) {
  return serializeMarketDetailIdentity(marketDetailEventIdentity(event))
}

export function marketHomeViewChartQuery(view: 'newow' | 'htdy' | 'subing' | 'free', symbol: string, newowFrequency: NewowFrequency | null) {
  return serializeMarketDetailIdentity({
    view, symbol, ...(view === 'newow' ? { strategy: 'trend' as const } : {}),
    seriesKind: 'actual_dominant', frequency: view === 'newow' ? (newowFrequency ?? failMissingNewowFrequency()) : view === 'subing' ? '15m' : '1d',
  })
}

function failMissingNewowFrequency(): never {
  throw new Error('Newow frequency capability is required')
}
