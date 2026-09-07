import type { MarketFrequency } from '../types/market.ts'
import type { MarketHomeSort, MarketHomeSortDirection } from './marketHomeWorkspace.ts'

export interface MarketHomePreferences { version: 1; sector: string; sort: MarketHomeSort; sortDirection?: MarketHomeSortDirection; compactDensity: boolean; detailFrequency: MarketFrequency; focusRailCollapsed: boolean }
export type LoadedMarketHomePreferences = MarketHomePreferences & { sortDirection: MarketHomeSortDirection }
export const MARKET_HOME_PREFERENCES_KEY = 'guiyi.market-home.preferences.v1'
const SORTS: readonly MarketHomeSort[] = ['default', 'close', 'change', 'volume', 'oi', 'event']
const DIRECTIONS: readonly MarketHomeSortDirection[] = ['asc', 'desc']
const FREQUENCIES: readonly MarketFrequency[] = ['1m', '5m', '15m', '30m', '60m', '1d', '1w']
const DEFAULT: LoadedMarketHomePreferences = { version: 1, sector: '', sort: 'default', sortDirection: 'desc', compactDensity: false, detailFrequency: '1d', focusRailCollapsed: true }

export function loadMarketHomePreferences(): LoadedMarketHomePreferences {
  try {
    const raw = globalThis.localStorage.getItem(MARKET_HOME_PREFERENCES_KEY)
    if (!raw) return { ...DEFAULT }
    return normalizePreferences(JSON.parse(raw)) ?? { ...DEFAULT }
  } catch {
    return { ...DEFAULT }
  }
}

export function saveMarketHomePreferences(value: MarketHomePreferences): void {
  try {
    globalThis.localStorage.setItem(MARKET_HOME_PREFERENCES_KEY, JSON.stringify(normalizePreferences(value) ?? DEFAULT))
  } catch {}
}

function normalizePreferences(value: unknown): LoadedMarketHomePreferences | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Record<string, unknown>
  const direction = candidate.sortDirection === undefined ? 'desc' : candidate.sortDirection
  if (
    candidate.version !== 1
    || typeof candidate.sector !== 'string'
    || !SORTS.includes(candidate.sort as MarketHomeSort)
    || !DIRECTIONS.includes(direction as MarketHomeSortDirection)
    || typeof candidate.compactDensity !== 'boolean'
    || !FREQUENCIES.includes(candidate.detailFrequency as MarketFrequency)
    || typeof candidate.focusRailCollapsed !== 'boolean'
  ) return null
  return {
    version: 1,
    sector: candidate.sector,
    sort: candidate.sort as MarketHomeSort,
    sortDirection: direction as MarketHomeSortDirection,
    compactDensity: candidate.compactDensity,
    detailFrequency: candidate.detailFrequency as MarketFrequency,
    focusRailCollapsed: candidate.focusRailCollapsed,
  }
}
