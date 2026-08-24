import type { LocationQuery } from 'vue-router'

export interface SubingDailyWatchChartEntry {
  symbol: string
  seriesKind: 'actual_dominant'
  frequency: '15m'
  overlay: 'subing'
}

export function resolveSubingDailyWatchChartEntry(
  query: LocationQuery,
): SubingDailyWatchChartEntry | null {
  if (query.entry !== 'subing-daily-watch'
    || query.overlay !== 'subing'
    || query.series_kind !== 'actual_dominant'
    || query.frequency !== '15m'
    || (query.contract !== undefined && query.contract !== null && query.contract !== '')
    || typeof query.symbol !== 'string') return null

  const symbol = query.symbol.trim().toLowerCase()
  if (!/^[a-z]+$/.test(symbol)) return null

  return {
    symbol,
    seriesKind: 'actual_dominant',
    frequency: '15m',
    overlay: 'subing',
  }
}
