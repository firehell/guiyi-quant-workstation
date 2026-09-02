import type { MarketFrequency } from '../types/market.ts'

export function marketHomeProductChartQuery(symbol: string) {
  return { symbol, series_kind: 'actual_dominant', frequency: '1d' as const }
}

export function marketHomeEventChartQuery(event: { symbol: string; frequency: MarketFrequency }) {
  return { symbol: event.symbol, series_kind: 'actual_dominant', frequency: event.frequency, overlay: 'htdy' as const }
}
