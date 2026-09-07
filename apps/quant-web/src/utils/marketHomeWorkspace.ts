import type { MarketHomeRow } from './marketHomeViewModel.ts'

export type MarketHomeLocalFilter = 'all' | 'up' | 'down' | 'flat' | 'aligned' | 'daily-up' | 'daily-down' | 'daily-neutral' | 'daily-unavailable' | 'with-event'
export type MarketHomeSort = 'default' | 'close' | 'change' | 'volume' | 'oi' | 'event'
export type MarketHomeSortDirection = 'asc' | 'desc'
export type MarketHomeTrendFilter = 'all' | 'up' | 'down' | 'neutral' | 'unavailable'
export type MarketHomeAlignmentFilter = 'all' | 'aligned-up' | 'aligned-down' | 'neutral' | 'mixed' | 'unavailable'
export type MarketHomeEventFilter = 'all' | 'with-event' | 'without-event'
export type MarketHomeDataFilter = 'all' | 'available' | 'unavailable'

export function nextMarketHomeSort(
  current: { sort: MarketHomeSort; sortDirection: MarketHomeSortDirection },
  column: MarketHomeSort,
): { sort: MarketHomeSort; sortDirection: MarketHomeSortDirection } {
  if (column === 'default') return { sort: 'default', sortDirection: 'desc' }
  if (current.sort !== column) return { sort: column, sortDirection: 'desc' }
  if (current.sortDirection === 'desc') return { sort: column, sortDirection: 'asc' }
  return { sort: 'default', sortDirection: 'desc' }
}

export function filterAndSortMarketHomeRows(
  rows: readonly MarketHomeRow[],
  options: { query: string; sector: string; filter: MarketHomeLocalFilter; sort: MarketHomeSort; sortDirection?: MarketHomeSortDirection; daily?: MarketHomeTrendFilter; weekly?: MarketHomeTrendFilter; alignment?: MarketHomeAlignmentFilter; event?: MarketHomeEventFilter; data?: MarketHomeDataFilter },
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
  const sort = options.sort
  if (sort === 'default') return filtered
  return [...filtered].sort((left, right) => compareRows(left, right, sort, options.sortDirection ?? 'desc'))
}

function matchesSummaryFilter(row: MarketHomeRow, filter: MarketHomeLocalFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'up') return (row.price_change_1d ?? 0) > 0
  if (filter === 'down') return (row.price_change_1d ?? 0) < 0
  if (filter === 'flat') return row.price_change_1d === 0
  if (filter === 'aligned') return row.alignment === 'aligned-up' || row.alignment === 'aligned-down'
  if (filter === 'daily-up') return row.dailyState === 'up'
  if (filter === 'daily-down') return row.dailyState === 'down'
  if (filter === 'daily-neutral') return row.dailyState === 'neutral'
  if (filter === 'daily-unavailable') return row.dailyState === 'unavailable'
  return Boolean(row.event)
}

function matchesTrend(value: string, filter: MarketHomeTrendFilter): boolean { return filter === 'all' || value === filter }
function matchesEvent(row: MarketHomeRow, filter: MarketHomeEventFilter): boolean {
  return filter === 'all' || (filter === 'with-event' ? Boolean(row.event) : !row.event)
}
function matchesData(row: MarketHomeRow, filter: MarketHomeDataFilter): boolean {
  const available = row.dailyState !== 'unavailable' && row.weeklyState !== 'unavailable'
  return filter === 'all' || (filter === 'available' ? available : !available)
}

function compareRows(left: MarketHomeRow, right: MarketHomeRow, sort: Exclude<MarketHomeSort, 'default'>, direction: MarketHomeSortDirection): number {
  if (sort === 'event') {
    const presence = Number(Boolean(right.event)) - Number(Boolean(left.event))
    if (presence) return presence
    if (!left.event || !right.event) return left.symbol.localeCompare(right.symbol)
    return latestEventFirst(left, right) || left.symbol.localeCompare(right.symbol)
  }

  const values: Record<Exclude<MarketHomeSort, 'default' | 'event'>, (row: MarketHomeRow) => number | null> = {
    close: (row) => row.close,
    change: (row) => row.price_change_1d,
    volume: (row) => row.volume_ratio20,
    oi: (row) => row.oi_change_1d,
  }
  return compareNumericRows(left, right, values[sort], direction)
}

function compareNumericRows(
  left: MarketHomeRow,
  right: MarketHomeRow,
  valueFor: (row: MarketHomeRow) => number | null,
  direction: MarketHomeSortDirection,
): number {
  const leftValue = valueFor(left)
  const rightValue = valueFor(right)
  const leftIsFinite = typeof leftValue === 'number' && Number.isFinite(leftValue)
  const rightIsFinite = typeof rightValue === 'number' && Number.isFinite(rightValue)
  if (!leftIsFinite && !rightIsFinite) return left.symbol.localeCompare(right.symbol)
  if (!leftIsFinite) return 1
  if (!rightIsFinite) return -1
  if (leftValue === rightValue) return left.symbol.localeCompare(right.symbol)
  if (direction === 'asc') return leftValue < rightValue ? -1 : 1
  return leftValue > rightValue ? -1 : 1
}

function latestEventFirst(left: MarketHomeRow, right: MarketHomeRow): number {
  const detected = Date.parse(right.event!.detected_at) - Date.parse(left.event!.detected_at)
  if (detected) return detected
  const barEnd = Date.parse(right.event!.bar_end) - Date.parse(left.event!.bar_end)
  return barEnd || right.event!.id - left.event!.id
}
