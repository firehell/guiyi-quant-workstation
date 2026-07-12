import type { BarData, MarketCoverageItem } from '@/types/market'
import { barTimeMs, barTimeMsForBar } from './barTime.ts'

export type ContractViewMode = 'actual' | 'continuous'

export const MAX_BARS_PER_REQUEST = 10000

export const LIVE_SUPPORTED_PERIODS = new Set(['1m', '5m', '15m', '30m', '60m'])

export const DAILY_WEEKLY_PERIODS = new Set(['1d', '1w'])

export const CHART_PERIOD_OPEN_ORDER = ['15m', '5m', '1d', '1w', '1m', '30m', '60m'] as const

export function continuousContractFor(product: string): string {
  return `${product.trim().toLowerCase()}.MAIN`
}

export function defaultContractViewForPeriod(period: string): ContractViewMode {
  return DAILY_WEEKLY_PERIODS.has(period) ? 'continuous' : 'actual'
}

export function resolveContractForView(
  product: string,
  actualContract: string,
  viewMode: ContractViewMode,
): string {
  if (viewMode === 'continuous') return continuousContractFor(product)
  return actualContract
}

export function isLivePeriodSupported(period: string): boolean {
  return LIVE_SUPPORTED_PERIODS.has(period)
}

export function preferredOpenPeriod(coverage: Record<string, { available?: boolean }>): string {
  const available = new Set(
    Object.entries(coverage)
      .filter(([, item]) => item.available)
      .map(([period]) => period),
  )
  for (const period of CHART_PERIOD_OPEN_ORDER) {
    if (available.has(period)) return period
  }
  return '15m'
}

export function fullCoverageDateRangeMs(coverageStart: number, coverageEnd: number): [number, number] {
  return [coverageStart, coverageEnd]
}

export interface BarsQueryWindow {
  startMs: number
  endMs: number
  limit: number
  tail: boolean
}

export function resolveInitialBarsQuery(
  coverageItem: Pick<MarketCoverageItem, 'start_time' | 'end_time' | 'row_count'> | null | undefined,
): BarsQueryWindow | null {
  if (!coverageItem?.start_time || !coverageItem?.end_time) return null
  const startMs = barTimeMs(coverageItem.start_time)
  const endMs = barTimeMs(coverageItem.end_time)
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return null
  return { startMs, endMs, limit: MAX_BARS_PER_REQUEST, tail: true }
}

export { barTimeMs, dedupeBarsByPeriod, mergeBarsByPeriod as mergeBarsByTime } from './barTime.ts'
export {
  canonicalBarTimeKey,
  chartTimeKey,
  coerceTradingDay,
  isDailyLikePeriod,
  lookupKeyFromChartTime,
  normalizePeriod,
  toChartTimeForPeriod,
  type ChartTimeValue,
} from './barTime.ts'

export function barsTimeExtent(
  bars: Pick<BarData, 'time' | 'trading_day'>[],
  period?: string | null,
): { startMs: number; endMs: number } | null {
  if (!bars.length) return null
  const times = bars.map((bar) => barTimeMsForBar(bar, period)).filter(Number.isFinite)
  if (!times.length) return null
  return { startMs: Math.min(...times), endMs: Math.max(...times) }
}

export function trimBarsToMaxCount<T extends Pick<BarData, 'time' | 'trading_day'>>(
  bars: T[],
  maxCount: number,
  keepCenterMs: number,
  period?: string | null,
): T[] {
  if (bars.length <= maxCount) return bars
  let centerIndex = 0
  let nearestDistance = Number.POSITIVE_INFINITY
  bars.forEach((bar, index) => {
    const distance = Math.abs(barTimeMsForBar(bar, period) - keepCenterMs)
    if (distance < nearestDistance) {
      centerIndex = index
      nearestDistance = distance
    }
  })
  const half = Math.floor(maxCount / 2)
  const start = Math.max(0, Math.min(centerIndex - half, bars.length - maxCount))
  return bars.slice(start, start + maxCount)
}

export interface ViewportLoadRequest {
  startMs: number
  endMs: number
}

export function computeViewportLoadRequest(options: {
  visibleFromMs: number
  visibleToMs: number
  loadedStartMs: number
  loadedEndMs: number
  coverageStartMs: number
  coverageEndMs: number
  paddingRatio?: number
}): ViewportLoadRequest | null {
  const paddingRatio = options.paddingRatio ?? 0.2
  const visibleSpan = Math.max(1, options.visibleToMs - options.visibleFromMs)
  const paddingMs = visibleSpan * paddingRatio
  const needStart = Math.max(options.coverageStartMs, options.visibleFromMs - paddingMs)
  const needEnd = Math.min(options.coverageEndMs, options.visibleToMs + paddingMs)
  if (needStart >= options.loadedStartMs && needEnd <= options.loadedEndMs) return null
  return { startMs: needStart, endMs: needEnd }
}

export function defaultDateRangeMs(
  period: string,
  coverageStart: number,
  coverageEnd: number,
): [number, number] {
  const day = 24 * 60 * 60 * 1000
  const end = coverageEnd
  let windowDays: number
  switch (period) {
    case '1m':
      windowDays = 7
      break
    case '5m':
      windowDays = 30
      break
    case '15m':
      windowDays = 60
      break
    case '30m':
    case '60m':
      windowDays = 90
      break
    case '1d':
      windowDays = 365 * 3
      break
    case '1w':
      windowDays = 365 * 5
      break
    default:
      windowDays = 90
  }
  const start = Math.max(coverageStart, end - windowDays * day)
  return [start, end]
}

export function formatAvailablePeriodTags(coverage: Record<string, { available?: boolean }>): string[] {
  const available = new Set(
    Object.entries(coverage)
      .filter(([, item]) => item.available)
      .map(([period]) => period),
  )
  return CHART_PERIOD_OPEN_ORDER.filter((period) => available.has(period))
}
