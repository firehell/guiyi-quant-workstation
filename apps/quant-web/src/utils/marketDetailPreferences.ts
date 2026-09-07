import type { MarketFrequency, OptionalEmaIndicatorId, SeriesKind } from '../types/market.ts'
import {
  MARKET_DETAIL_VIEWS,
  NEWOW_FREQUENCIES,
  NEWOW_STRATEGIES,
  type FlexibleViewRestore,
  type MarketDetailView,
  type NewowFrequency,
  type NewowStrategy,
} from '../types/marketDetail.ts'
import { normalizeOptionalEmaIndicators } from './mainIndicators.ts'

export const MARKET_DETAIL_PREFERENCES_KEY = 'guiyi.market.detail.preferences.v2'
const LEGACY_DETAIL_KEY = 'guiyi.market.detail.preferences.v1'
const LEGACY_CHART_KEY = 'guiyi.market.chart.preferences.v9'
const FREQUENCIES = new Set<MarketFrequency>(['1m', '5m', '15m', '30m', '60m', '1d', '1w'])
const NEWOW_FREQUENCY_SET = new Set<string>(NEWOW_FREQUENCIES)
const NEWOW_STRATEGY_SET = new Set<string>(NEWOW_STRATEGIES)

export interface FlexibleDetailPreferences extends FlexibleViewRestore {
  optionalEmaIndicators: OptionalEmaIndicatorId[]
  showRangeDetector: boolean
}

export interface MarketDetailPreferences {
  version: 2
  lastView: Exclude<MarketDetailView, 'trend'>
  newow: { strategy: NewowStrategy; frequency: NewowFrequency }
  htdy: FlexibleDetailPreferences
  free: FlexibleDetailPreferences
}

export type DetailPreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>

export function defaultMarketDetailPreferences(): MarketDetailPreferences {
  return {
    version: 2,
    lastView: 'newow',
    newow: { strategy: 'trend', frequency: '1d' },
    htdy: defaultFlexiblePreferences(),
    free: defaultFlexiblePreferences(),
  }
}

export function loadMarketDetailPreferences(storage: Pick<DetailPreferenceStorage, 'getItem'> | null = browserStorage()): MarketDetailPreferences {
  if (!storage) return defaultMarketDetailPreferences()
  try {
    const current = storage.getItem(MARKET_DETAIL_PREFERENCES_KEY)
    if (current !== null) return normalizeCurrent(JSON.parse(current))
    const legacyDetail = storage.getItem(LEGACY_DETAIL_KEY)
    if (legacyDetail !== null) return migrateDetailV1(JSON.parse(legacyDetail))
    const legacyChart = storage.getItem(LEGACY_CHART_KEY)
    return legacyChart === null ? defaultMarketDetailPreferences() : migrateChartV9(JSON.parse(legacyChart))
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

export function replaceHtdyDetailPreferences(
  current: MarketDetailPreferences,
  htdy: Omit<FlexibleDetailPreferences, 'seriesKind'> & { seriesKind: SeriesKind },
): MarketDetailPreferences {
  return { ...current, htdy: normalizeFlexible(htdy) }
}

export function replaceNewowDetailPreferences(
  current: MarketDetailPreferences,
  newow: { strategy: unknown; frequency: unknown },
): MarketDetailPreferences {
  return { ...current, newow: normalizeNewow(newow) }
}

function normalizeCurrent(value: unknown): MarketDetailPreferences {
  if (!isRecord(value) || value.version !== 2) return defaultMarketDetailPreferences()
  return {
    version: 2,
    lastView: isRestorableView(value.lastView) ? value.lastView : 'newow',
    newow: normalizeNewow(value.newow),
    htdy: normalizeFlexible(value.htdy),
    free: normalizeFlexible(value.free),
  }
}

function migrateDetailV1(value: unknown): MarketDetailPreferences {
  if (!isRecord(value) || value.version !== 1) return defaultMarketDetailPreferences()
  return {
    version: 2,
    lastView: value.lastView === 'trend'
      ? 'newow'
      : isRestorableView(value.lastView) ? value.lastView : 'newow',
    newow: { strategy: 'trend', frequency: '1d' },
    htdy: normalizeFlexible(value.htdy),
    free: normalizeFlexible(value.free),
  }
}

function migrateChartV9(value: unknown): MarketDetailPreferences {
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

function normalizeNewow(value: unknown): MarketDetailPreferences['newow'] {
  if (!isRecord(value)) return { strategy: 'trend', frequency: '1d' }
  return {
    strategy: typeof value.strategy === 'string' && NEWOW_STRATEGY_SET.has(value.strategy)
      ? value.strategy as NewowStrategy
      : 'trend',
    frequency: typeof value.frequency === 'string' && NEWOW_FREQUENCY_SET.has(value.frequency)
      ? value.frequency as NewowFrequency
      : '1d',
  }
}

function normalizeFrequency(value: unknown): MarketFrequency {
  return typeof value === 'string' && FREQUENCIES.has(value as MarketFrequency) ? value as MarketFrequency : '15m'
}

function isRestorableView(value: unknown): value is Exclude<MarketDetailView, 'trend'> {
  return typeof value === 'string' && value !== 'trend'
    && (MARKET_DETAIL_VIEWS as readonly string[]).includes(value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function browserStorage(): DetailPreferenceStorage | null {
  return typeof window === 'undefined' ? null : window.localStorage
}
