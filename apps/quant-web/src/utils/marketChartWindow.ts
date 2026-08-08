import type { BarData, MarketCoverageItem } from '@/types/market'
import { barTimeMs, barTimeMsForBar, normalizeBarTimeString } from './barTime.ts'

/** 合约视图：具体交割月 / 连续主力 */
export type ContractViewMode = 'actual' | 'continuous'

/** 单次 bars 请求最大条数 */
export const MAX_BARS_PER_REQUEST = 10000

/** 支持实时刷新的分钟级周期 */
export const LIVE_SUPPORTED_PERIODS = new Set(['1m', '5m', '15m', '30m', '60m'])

/** 日线、周线周期集合 */
export const DAILY_WEEKLY_PERIODS = new Set(['1d', '1w'])

/** 打开图表时周期优先级（有覆盖数据时按此顺序选择） */
export const CHART_PERIOD_OPEN_ORDER = ['15m', '5m', '1d', '1w', '1m', '30m', '60m'] as const

/**
 * 生成品种的连续主力合约代码（如 jm.MAIN）。
 */
export function continuousContractFor(product: string): string {
  return `${product.trim().toLowerCase()}.MAIN`
}

/** 合约代码大小写不敏感比较（Catalog 多为 JM.MAIN，前端可能写 jm.MAIN）。 */
export function contractsEqual(left?: string | null, right?: string | null): boolean {
  if (!left || !right) return false
  return left.trim().toUpperCase() === right.trim().toUpperCase()
}

/**
 * 按周期返回默认合约视图：日/周线用连续，分钟级用具体合约。
 */
export function defaultContractViewForPeriod(period: string): ContractViewMode {
  return DAILY_WEEKLY_PERIODS.has(period) ? 'continuous' : 'actual'
}

/**
 * 根据视图模式解析实际请求用的合约代码。
 */
export function resolveContractForView(
  product: string,
  actualContract: string,
  viewMode: ContractViewMode,
): string {
  if (viewMode === 'continuous') return continuousContractFor(product)
  return actualContract
}

/**
 * 判断周期是否支持实时行情刷新。
 */
export function isLivePeriodSupported(period: string): boolean {
  return LIVE_SUPPORTED_PERIODS.has(period)
}

/**
 * 从覆盖数据中按优先级选择默认可用周期。
 */
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

/**
 * 返回覆盖数据的完整时间范围（毫秒）。
 */
export function fullCoverageDateRangeMs(coverageStart: number, coverageEnd: number): [number, number] {
  return [coverageStart, coverageEnd]
}

/** bars 查询窗口：起止毫秒、条数限制、是否取尾部 */
export interface BarsQueryWindow {
  startMs: number
  endMs: number
  limit: number
  tail: boolean
}

/**
 * 根据覆盖项解析首次加载 bars 的查询窗口；数据不完整时返回 null。
 */
export function resolveInitialBarsQuery(
  coverageItem: Pick<MarketCoverageItem, 'start_time' | 'end_time' | 'row_count'> | null | undefined,
): BarsQueryWindow | null {
  if (!coverageItem?.start_time || !coverageItem?.end_time) return null
  const startMs = barTimeMs(coverageItem.start_time)
  const endMs = barTimeMs(coverageItem.end_time)
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return null
  return { startMs, endMs, limit: MAX_BARS_PER_REQUEST, tail: true }
}

export { BarMergeConflictError, barTimeMs, dedupeBarsByPeriod, mergeBarsByPeriod as mergeBarsByTime } from './barTime.ts'
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

/**
 * 计算 bars 数组的时间跨度（起止毫秒）。
 */
export function barsTimeExtent(
  bars: Pick<BarData, 'time' | 'trading_day'>[],
  period?: string | null,
): { startMs: number; endMs: number } | null {
  if (!bars.length) return null
  const times = bars.map((bar) => barTimeMsForBar(bar, period)).filter(Number.isFinite)
  if (!times.length) return null
  return { startMs: Math.min(...times), endMs: Math.max(...times) }
}

/**
 * 从已加载 bars 中取最新一根 bar 的时间字符串，用于 live 增量刷新起点。
 */
export function resolveLiveRefreshStart(
  bars: Pick<BarData, 'time' | 'trading_day'>[],
  period?: string | null,
): string | undefined {
  let latest: Pick<BarData, 'time' | 'trading_day'> | undefined
  let latestMs = Number.NEGATIVE_INFINITY
  for (const bar of bars) {
    const value = barTimeMsForBar(bar, period)
    if (!Number.isFinite(value) || value <= latestMs) continue
    latest = bar
    latestMs = value
  }
  return latest ? normalizeBarTimeString(latest.time) : undefined
}

/**
 * 将 bars 裁剪到 maxCount 条，以 keepCenterMs 为中心尽量保留视口附近数据。
 */
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

/** 视口懒加载请求的时间范围 */
export interface ViewportLoadRequest {
  startMs: number
  endMs: number
}

/**
 * 根据可见视口与已加载范围计算是否需要扩展加载。
 * 在可见区间两侧按 paddingRatio 加缓冲；已覆盖则返回 null。
 */
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

/**
 * 按周期返回默认展示窗口（毫秒区间），不超过覆盖范围上限。
 */
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

/**
 * 从覆盖数据中提取可用周期标签列表（按 CHART_PERIOD_OPEN_ORDER 排序）。
 */
export function formatAvailablePeriodTags(coverage: Record<string, { available?: boolean }>): string[] {
  const available = new Set(
    Object.entries(coverage)
      .filter(([, item]) => item.available)
      .map(([period]) => period),
  )
  return CHART_PERIOD_OPEN_ORDER.filter((period) => available.has(period))
}
