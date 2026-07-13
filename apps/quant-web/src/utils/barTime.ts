import type { BarData } from '@/types/market'
import type { Time } from 'lightweight-charts'

const DAILY_WEEKLY_PERIODS = new Set(['1d', '1w'])

export type ChartBusinessDay = { year: number; month: number; day: number }
export type ChartTimeValue = ChartBusinessDay | number

type BarTimeInput = Pick<BarData, 'time' | 'trading_day'>

export function normalizePeriod(period?: string | null): string | null {
  if (!period) return null
  const normalized = period.trim().toLowerCase()
  return normalized || null
}

export function isDailyLikePeriod(period?: string | null): boolean {
  const normalized = normalizePeriod(period)
  return Boolean(normalized && DAILY_WEEKLY_PERIODS.has(normalized))
}

export function normalizeBarTimeString(value: string): string {
  return String(value).replace(/(?:Z|[+-]\d{2}:\d{2})$/, '')
}

export function parseBarLocalDate(value: string): Date | null {
  const normalized = normalizeBarTimeString(value)
  const date = new Date(normalized)
  return Number.isFinite(date.getTime()) ? date : null
}

export function coerceTradingDay(value: unknown): string | null {
  if (value === null || value === undefined) return null
  const text = String(value).trim()
  if (!text) return null
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10)
  const parsed = parseBarLocalDate(text)
  if (!parsed) return null
  const year = parsed.getFullYear()
  const month = String(parsed.getMonth() + 1).padStart(2, '0')
  const day = String(parsed.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function tradingDayFromBar(bar: BarTimeInput): string | null {
  const tradingDay = coerceTradingDay(bar.trading_day)
  if (tradingDay) return tradingDay
  const dateOnly = bar.time.trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateOnly)) return dateOnly
  const parsed = parseBarLocalDate(bar.time)
  if (!parsed) return null
  const year = parsed.getFullYear()
  const month = String(parsed.getMonth() + 1).padStart(2, '0')
  const day = String(parsed.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function canonicalBarTimeKey(bar: BarTimeInput, period?: string | null): string {
  if (isDailyLikePeriod(period)) {
    return tradingDayFromBar(bar) || normalizeBarTimeString(bar.time)
  }
  return normalizeBarTimeString(bar.time)
}

export function barTimeMsForBar(bar: BarTimeInput, period?: string | null): number {
  if (isDailyLikePeriod(period)) {
    const tradingDay = tradingDayFromBar(bar)
    if (tradingDay) {
      const parsed = parseBarLocalDate(`${tradingDay}T00:00:00`)
      if (parsed) return parsed.getTime()
    }
  }
  return parseBarLocalDate(bar.time)?.getTime() ?? Number.NaN
}

export function barTimeMs(time: string): number {
  return parseBarLocalDate(time)?.getTime() ?? Number.NaN
}

export function toChartTimeForPeriod(bar: BarTimeInput, period?: string | null): ChartTimeValue {
  if (isDailyLikePeriod(period)) {
    const tradingDay = tradingDayFromBar(bar)
    if (tradingDay) {
      const [year, month, day] = tradingDay.split('-').map(Number)
      if (year && month && day) return { year, month, day }
    }
  }
  const parsed = parseBarLocalDate(bar.time)
  if (!parsed) return 0
  return Math.floor(parsed.getTime() / 1000)
}

export function chartTimeKey(time: ChartTimeValue): string {
  if (typeof time === 'number') return String(time)
  return `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}`
}

export function lookupKeyFromChartTime(time: Time | ChartTimeValue): string {
  if (typeof time === 'object' && time !== null && 'year' in time) {
    return chartTimeKey(time)
  }
  return String(time)
}

export function dedupeBarsByPeriod<T extends BarTimeInput>(bars: T[], period?: string | null): T[] {
  return mergeBarsByPeriod(bars, [], period)
}

const OHLCV_FIELDS = ['open', 'high', 'low', 'close', 'volume'] as const

function barsHaveOhlcvConflict<T extends BarTimeInput>(existing: T, incoming: T): boolean {
  for (const field of OHLCV_FIELDS) {
    if (field in existing && field in incoming) {
      const a = (existing as Record<string, unknown>)[field]
      const b = (incoming as Record<string, unknown>)[field]
      if (a != null && b != null && a !== b) return true
    }
  }
  return false
}

export function mergeBarsByPeriod<T extends BarTimeInput>(first: T[], second: T[], period?: string | null): T[] {
  const byKey = new Map<string, T>()
  first.forEach((bar) => {
    const key = canonicalBarTimeKey(bar, period)
    const existing = byKey.get(key)
    if (existing && barsHaveOhlcvConflict(existing, bar)) {
      console.warn(
        `[barTime] Duplicate key "${key}" with conflicting OHLCV values (period=${period || 'unknown'}). ` +
        `Existing bar will be replaced. This indicates a data-source conflict — please verify data integrity.`,
        { key, period, existing, incoming: bar },
      )
    }
    byKey.set(key, bar)
  })
  second.forEach((bar) => {
    const key = canonicalBarTimeKey(bar, period)
    const existing = byKey.get(key)
    if (existing && barsHaveOhlcvConflict(existing, bar)) {
      console.warn(
        `[barTime] Duplicate key "${key}" with conflicting OHLCV values (period=${period || 'unknown'}). ` +
        `Existing bar will be replaced. This indicates a data-source conflict — please verify data integrity.`,
        { key, period, existing, incoming: bar },
      )
    }
    byKey.set(key, bar)
  })
  return [...byKey.values()].sort((left, right) => barTimeMsForBar(left, period) - barTimeMsForBar(right, period))
}
