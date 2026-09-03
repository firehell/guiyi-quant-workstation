import type { MarketFrequency, OptionalEmaIndicatorId, SeriesKind } from '../types/market.ts'
import { MARKET_DETAIL_VIEWS, type FlexibleViewRestore, type MarketDetailView } from '../types/marketDetail.ts'
import { normalizeOptionalEmaIndicators } from './mainIndicators.ts'

export const MARKET_DETAIL_PREFERENCES_KEY = 'guiyi.market.detail.preferences.v1'
const LEGACY_KEY = 'guiyi.market.chart.preferences.v9'
const FREQUENCIES = new Set<MarketFrequency>(['1m', '5m', '15m', '30m', '60m', '1d', '1w'])

export interface FlexibleDetailPreferences extends FlexibleViewRestore {
  optionalEmaIndicators: OptionalEmaIndicatorId[]
  showRangeDetector: boolean
}

export interface MarketDetailPreferences {
  version: 1
  lastView: MarketDetailView
  htdy: FlexibleDetailPreferences
  free: FlexibleDetailPreferences
}

export type DetailPreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>

export function defaultMarketDetailPreferences(): MarketDetailPreferences {
  return {
    version: 1,
    lastView: 'trend',
    htdy: defaultFlexiblePreferences(),
    free: defaultFlexiblePreferences(),
  }
}

export function loadMarketDetailPreferences(storage: Pick<DetailPreferenceStorage, 'getItem'> | null = browserStorage()): MarketDetailPreferences {
  if (!storage) return defaultMarketDetailPreferences()
  try {
    const current = storage.getItem(MARKET_DETAIL_PREFERENCES_KEY)
    if (current !== null) return normalizeCurrent(JSON.parse(current))
    const legacy = storage.getItem(LEGACY_KEY)
    return legacy === null ? defaultMarketDetailPreferences() : migrateLegacy(JSON.parse(legacy))
  } catch {
    return defaultMarketDetailPreferences()
  }
}

export function saveMarketDetailPreferences(
  value: MarketDetailPreferences,
  storage: Pick<DetailPreferenceStorage, 'setItem'> | null = browserStorage(),
): void {
  if (!storage) return
  try { storage.setItem(MARKET_DETAIL_PREFERENCES_KEY, JSON.stringify(normalizeCurrent(value))) } catch { /* unavailable storage is non-blocking */ }
}

export function replaceFreeDetailPreferences(
  current: MarketDetailPreferences,
  free: Omit<FlexibleDetailPreferences, 'seriesKind'> & { seriesKind: SeriesKind },
): MarketDetailPreferences {
  return { ...current, free: normalizeFlexible(free) }
}

function normalizeCurrent(value: unknown): MarketDetailPreferences {
  if (!isRecord(value) || value.version !== 1) return defaultMarketDetailPreferences()
  return {
    version: 1,
    lastView: isView(value.lastView) ? value.lastView : 'trend',
    htdy: normalizeFlexible(value.htdy),
    free: normalizeFlexible(value.free),
  }
}

function migrateLegacy(value: unknown): MarketDetailPreferences {
  if (!isRecord(value) || value.version !== 9) return defaultMarketDetailPreferences()
  return {
    ...defaultMarketDetailPreferences(),
    free: {
      seriesKind: 'actual_dominant',
      frequency: normalizeFrequency(value.period),
      optionalEmaIndicators: normalizeOptionalEmaIndicators(value.optionalEmaIndicators),
      showRangeDetector: value.showRangeDetector === true,
    },
  }
}

function defaultFlexiblePreferences(): FlexibleDetailPreferences {
  return { seriesKind: 'actual_dominant', frequency: '15m', optionalEmaIndicators: [], showRangeDetector: false }
}

function normalizeFlexible(value: unknown): FlexibleDetailPreferences {
  if (!isRecord(value)) return defaultFlexiblePreferences()
  return {
    seriesKind: value.seriesKind === 'continuous' ? 'continuous' : 'actual_dominant',
    frequency: normalizeFrequency(value.frequency),
    optionalEmaIndicators: normalizeOptionalEmaIndicators(value.optionalEmaIndicators),
    showRangeDetector: value.showRangeDetector === true,
  }
}

function normalizeFrequency(value: unknown): MarketFrequency {
  return typeof value === 'string' && FREQUENCIES.has(value as MarketFrequency) ? value as MarketFrequency : '15m'
}

function isView(value: unknown): value is MarketDetailView {
  return typeof value === 'string' && (MARKET_DETAIL_VIEWS as readonly string[]).includes(value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function browserStorage(): DetailPreferenceStorage | null {
  return typeof window === 'undefined' ? null : window.localStorage
}
