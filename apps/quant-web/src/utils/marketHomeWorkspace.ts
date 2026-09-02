import type { MarketHomeRow } from './marketHomeViewModel.ts'

export type MarketHomeLocalFilter = 'all' | 'up' | 'down' | 'aligned'
export type MarketHomeSort = 'default' | 'change' | 'volume' | 'oi' | 'event'
export type MarketHomeTrendFilter = 'all' | 'up' | 'down' | 'neutral' | 'unavailable'
export type MarketHomeAlignmentFilter = 'all' | 'aligned-up' | 'aligned-down' | 'neutral' | 'mixed' | 'unavailable'
export type MarketHomeEventFilter = 'all' | 'with-event' | 'without-event'
export type MarketHomeDataFilter = 'all' | 'available' | 'unavailable'

export function filterAndSortMarketHomeRows(
  rows: readonly MarketHomeRow[],
  options: { query: string; sector: string; filter: MarketHomeLocalFilter; sort: MarketHomeSort; daily?: MarketHomeTrendFilter; weekly?: MarketHomeTrendFilter; alignment?: MarketHomeAlignmentFilter; event?: MarketHomeEventFilter; data?: MarketHomeDataFilter },
): MarketHomeRow[] {
  const query = options.query.trim().toLowerCase()
  const filtered = rows.filter((row) => {
    const textMatches = !query || `${row.symbol} ${row.product_name}`.toLowerCase().includes(query)
    const sectorMatches = !options.sector || row.sector === options.sector
    return textMatches && sectorMatches && matchesSummaryFilter(row, options.filter)
      && matchesTrend(row.dailyState, options.daily ?? 'all')
      && matchesTrend(row.weeklyState, options.weekly ?? 'all')
      && ((options.alignment ?? 'all') === 'all' || row.alignment === options.alignment)
      && matchesEvent(row, options.event ?? 'all')
      && matchesData(row, options.data ?? 'all')
  })
  return [...filtered].sort((left, right) => compareRows(left, right, options.sort))
}

function matchesSummaryFilter(row: MarketHomeRow, filter: MarketHomeLocalFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'up') return (row.price_change_1d ?? 0) > 0
  if (filter === 'down') return (row.price_change_1d ?? 0) < 0
  return row.alignment === 'aligned-up' || row.alignment === 'aligned-down'
}

function matchesTrend(value: string, filter: MarketHomeTrendFilter): boolean { return filter === 'all' || value === filter }
function matchesEvent(row: MarketHomeRow, filter: MarketHomeEventFilter): boolean {
  return filter === 'all' || (filter === 'with-event' ? Boolean(row.event) : !row.event)
}
function matchesData(row: MarketHomeRow, filter: MarketHomeDataFilter): boolean {
  const available = row.dailyState !== 'unavailable' && row.weeklyState !== 'unavailable'
  return filter === 'all' || (filter === 'available' ? available : !available)
}

function compareRows(left: MarketHomeRow, right: MarketHomeRow, sort: MarketHomeSort): number {
  if (sort === 'change') return nullableNumber(right.price_change_1d) - nullableNumber(left.price_change_1d) || left.symbol.localeCompare(right.symbol)
  if (sort === 'volume') return nullableNumber(right.volume_ratio20) - nullableNumber(left.volume_ratio20) || left.symbol.localeCompare(right.symbol)
  if (sort === 'oi') return nullableNumber(right.oi_change_1d) - nullableNumber(left.oi_change_1d) || left.symbol.localeCompare(right.symbol)
  if (sort === 'event') return Number(Boolean(right.event)) - Number(Boolean(left.event)) || left.symbol.localeCompare(right.symbol)
  return 0
}

function nullableNumber(value: number | null): number { return value ?? Number.NEGATIVE_INFINITY }
