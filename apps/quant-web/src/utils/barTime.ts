import type { BarData } from '@/types/market'
import { TickMarkType, type Time } from 'lightweight-charts'

/** 日线、周线类周期集合 */
const DAILY_WEEKLY_PERIODS = new Set(['1d', '1w'])
const INTRADAY_KLINE_PERIOD_SECONDS: Readonly<Record<string, number>> = {
  '1m': 60,
  '5m': 5 * 60,
  '15m': 15 * 60,
  '30m': 30 * 60,
  '60m': 60 * 60,
}
const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'

/** Lightweight Charts 业务日时间（无时分秒） */
export type ChartBusinessDay = { year: number; month: number; day: number }
/** 图表时间：业务日对象或 Unix 秒级时间戳 */
export type ChartTimeValue = ChartBusinessDay | number

type BarTimeInput = Pick<BarData, 'time' | 'trading_day'>

function isBusinessDay(time: Time): time is ChartBusinessDay {
  return typeof time === 'object' && time !== null && 'year' in time
}

function pad(value: string | number): string {
  return String(value).padStart(2, '0')
}

function datePartsInShanghai(date: Date) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: SHANGHAI_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)
  return Object.fromEntries(parts.map((part) => [part.type, part.value]))
}

function formatBusinessDay(time: ChartBusinessDay): string {
  return `${time.year}-${pad(time.month)}-${pad(time.day)}`
}

function parseChartInstant(time: Time): Date | null {
  if (typeof time === 'number') {
    const instant = new Date(time * 1000)
    return Number.isFinite(instant.getTime()) ? instant : null
  }
  if (typeof time === 'string') {
    const instant = new Date(time)
    return Number.isFinite(instant.getTime()) ? instant : null
  }
  return null
}

/**
 * 将横轴刻度格式化为北京时间，并按 LWC TickMarkType 分级缩短文案
 *（对齐参考图：日刻度用「13日」、分钟刻度用「HH:mm」）。
 */
export function formatChartAxisTimeInShanghai(
  time: Time,
  tickMarkType: TickMarkType = TickMarkType.Time,
): string {
  if (isBusinessDay(time)) {
    if (tickMarkType === TickMarkType.Year) return String(time.year)
    if (tickMarkType === TickMarkType.Month) return `${time.month}月`
    return `${time.day}日`
  }
  const instant = parseChartInstant(time)
  if (!instant) return ''
  const parts = datePartsInShanghai(instant)
  switch (tickMarkType) {
    case TickMarkType.Year:
      return parts.year ?? ''
    case TickMarkType.Month:
      return `${Number(parts.month)}月`
    case TickMarkType.DayOfMonth:
      return `${Number(parts.day)}日`
    case TickMarkType.TimeWithSeconds:
      return `${parts.hour}:${parts.minute}:00`
    case TickMarkType.Time:
    default:
      return `${parts.hour}:${parts.minute}`
  }
}

/** 将 crosshair 时间格式化为完整北京时间；交易日保持日期语义。 */
export function formatChartTimeInShanghai(time: Time): string {
  if (isBusinessDay(time)) return formatBusinessDay(time)
  const instant = parseChartInstant(time)
  if (!instant) return ''
  const parts = datePartsInShanghai(instant)
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`
}

/**
 * 规范化周期字符串：去空白、转小写；空值返回 null。
 */
export function normalizePeriod(period?: string | null): string | null {
  if (!period) return null
  const normalized = period.trim().toLowerCase()
  return normalized || null
}

/**
 * 判断是否为日线/周线类周期（1d、1w）。
 */
export function isDailyLikePeriod(period?: string | null): boolean {
  const normalized = normalizePeriod(period)
  return Boolean(normalized && DAILY_WEEKLY_PERIODS.has(normalized))
}

/**
 * 去除 bar 时间字符串末尾的时区后缀（Z 或 ±HH:MM）。
 */
export function normalizeBarTimeString(value: string): string {
  return String(value).replace(/(?:Z|[+-]\d{2}:\d{2})$/, '')
}

/**
 * 将 bar 时间字符串解析为本地 Date；无效时返回 null。
 */
export function parseBarLocalDate(value: string): Date | null {
  const normalized = normalizeBarTimeString(value)
  const date = new Date(normalized)
  return Number.isFinite(date.getTime()) ? date : null
}

/**
 * 将任意值强制转换为 YYYY-MM-DD 交易日字符串。
 * 已是日期格式则截取前 10 位，否则尝试解析后格式化。
 */
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

/**
 * 从 bar 提取交易日：优先 trading_day，其次 time 字段。
 */
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

/**
 * 生成 bar 去重/合并用的规范时间键。
 * 日线/周线用交易日，分钟级用规范化后的 time 字符串。
 */
export function canonicalBarTimeKey(bar: BarTimeInput, period?: string | null): string {
  if (isDailyLikePeriod(period)) {
    return tradingDayFromBar(bar) || normalizeBarTimeString(bar.time)
  }
  return normalizeBarTimeString(bar.time)
}

/**
 * 将 bar 时间转为毫秒时间戳；日线/周线以交易日零点为准。
 */
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

/**
 * 将 bar 时间字符串转为毫秒时间戳。
 */
export function barTimeMs(time: string): number {
  return parseBarLocalDate(time)?.getTime() ?? Number.NaN
}

/**
 * 按周期将 bar 转为 Lightweight Charts 可接受的时间格式。
 * 日线/周线返回 BusinessDay，分钟级返回 Unix 秒级时间戳。
 */
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

/**
 * K 线在主图上的展示坐标：分钟周期以区间开端定位，日/周保持交易日语义。
 * 原始 ``bar.time`` 始终是 Canonical/Live 的正式 ``bar_end``，不得在此改写。
 */
export function toKlineDisplayTimeForPeriod(
  bar: BarTimeInput,
  period?: string | null,
): ChartTimeValue {
  if (isDailyLikePeriod(period)) return toChartTimeForPeriod(bar, period)
  const instant = Date.parse(bar.time)
  if (!Number.isFinite(instant)) return 0
  const offset = INTRADAY_KLINE_PERIOD_SECONDS[normalizePeriod(period) ?? ''] ?? 0
  return Math.floor(instant / 1000) - offset
}

/**
 * 将 ChartTimeValue 转为可比较的字符串键。
 */
export function chartTimeKey(time: ChartTimeValue): string {
  if (typeof time === 'number') return String(time)
  return `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}`
}

/**
 * 从图表库 Time 或 ChartTimeValue 得到 bar 查找键。
 */
export function lookupKeyFromChartTime(time: Time | ChartTimeValue): string {
  if (typeof time === 'string') return normalizeBarTimeString(time)
  if (typeof time === 'object' && time !== null && 'year' in time) {
    return chartTimeKey(time)
  }
  return String(time)
}

/**
 * 生成 bar 在图表上的查找键（与 toChartTimeForPeriod 一致）。
 */
export function chartLookupKeyForBar(bar: BarTimeInput, period?: string | null): string {
  return chartTimeKey(toChartTimeForPeriod(bar, period))
}

/**
 * 从时间字符串生成图表查找键。
 */
export function chartLookupKeyForTimeString(value: string, period?: string | null): string {
  return chartLookupKeyForBar({ time: value }, period)
}

/**
 * 按周期对 bars 去重（内部调用 mergeBarsByPeriod，第二组为空）。
 */
export function dedupeBarsByPeriod<T extends BarTimeInput>(bars: T[], period?: string | null): T[] {
  return mergeBarsByPeriod(bars, [], period)
}

const OHLCV_FIELDS = ['open', 'high', 'low', 'close', 'volume'] as const

/** bar 合并时 OHLCV 字段冲突详情 */
export interface BarMergeConflict {
  key: string
  period: string | null
  fields: string[]
}

/** 合并 bars 时检测到不可调和的 OHLCV 冲突时抛出 */
export class BarMergeConflictError extends Error {
  readonly conflicts: BarMergeConflict[]

  constructor(conflicts: BarMergeConflict[]) {
    super('conflicting duplicate bars cannot be merged')
    this.name = 'BarMergeConflictError'
    this.conflicts = conflicts
  }
}

/** 比较两根 bar 的 OHLCV 字段，返回发生冲突的字段名列表 */
function conflictingOhlcvFields<T extends BarTimeInput>(existing: T, incoming: T): string[] {
  const fields: string[] = []
  for (const field of OHLCV_FIELDS) {
    if (field in existing && field in incoming) {
      const a = (existing as Record<string, unknown>)[field]
      const b = (incoming as Record<string, unknown>)[field]
      if (a != null && b != null && a !== b) fields.push(field)
    }
  }
  return fields
}

/**
 * 按周期合并两组 bars：同键保留后者，OHLCV 冲突则抛 BarMergeConflictError。
 * 结果按时间升序排列。
 */
export function mergeBarsByPeriod<T extends BarTimeInput>(first: T[], second: T[], period?: string | null): T[] {
  const byKey = new Map<string, T>()
  const conflicts: BarMergeConflict[] = []
  const addBar = (bar: T) => {
    const key = canonicalBarTimeKey(bar, period)
    const existing = byKey.get(key)
    const fields = existing ? conflictingOhlcvFields(existing, bar) : []
    if (fields.length) {
      conflicts.push({ key, period: normalizePeriod(period), fields })
      return
    }
    byKey.set(key, bar)
  }
  first.forEach((bar) => {
    addBar(bar)
  })
  second.forEach((bar) => {
    addBar(bar)
  })
  if (conflicts.length) throw new BarMergeConflictError(conflicts)
  return [...byKey.values()].sort((left, right) => barTimeMsForBar(left, period) - barTimeMsForBar(right, period))
}
