import type { Time } from 'lightweight-charts'
import type { BarData } from '@/types/market'

/** 指标序列单点：时间与数值 */
export interface IndicatorPoint {
  time: Time
  value: number
}

/** MACD 三线结果：DIF、DEA、柱状图 */
export interface MacdResult {
  dif: IndicatorPoint[]
  dea: IndicatorPoint[]
  histogram: IndicatorPoint[]
}

/** 火天大有指标单 bar 观察点 */
export interface HuoTianDaYouPoint {
  time: Time
  zk1: number | null
  zd1: number | null
  zd2: number | null
  yellowCandle: boolean
  whiteCandle: boolean
  buyObservation: boolean
  sellObservation: boolean
  xgObservation: boolean
  candleSegments: HuoTianDaYouCandleSegment[]
}

/** 火天大有 K 线着色片段（实体/影线） */
export interface HuoTianDaYouCandleSegment {
  kind: 'body' | 'wick'
  colorRole: 'white' | 'yellow'
  from: number
  to: number
}

/** 火天大有单 bar K 线着色观察结果 */
export interface HuoTianDaYouCandleObservation {
  yellowCandle: boolean
  whiteCandle: boolean
  candleSegments: HuoTianDaYouCandleSegment[]
}

/** 火天大有指标完整序列 */
export interface HuoTianDaYouResult {
  points: HuoTianDaYouPoint[]
}

/**
 * 计算指数移动平均线（EMA）。
 * 前 period 根用 SMA 初始化，之后按标准 EMA 递推。
 */
export function calculateEMA(bars: BarData[], period: number): IndicatorPoint[] {
  if (period <= 0 || bars.length < period) return []

  const multiplier = 2 / (period + 1)
  let previous = average(bars.slice(0, period).map((bar) => bar.close))
  const points: IndicatorPoint[] = [{ time: bars[period - 1].time as Time, value: round(previous) }]

  for (let index = period; index < bars.length; index += 1) {
    previous = (bars[index].close - previous) * multiplier + previous
    points.push({ time: bars[index].time as Time, value: round(previous) })
  }

  return points
}

/**
 * 计算火天大有（HTDY）观察指标，对齐通达信公式语义。
 * 含 zk1/zd1/zd2 通道、黄白 K 线着色及买卖观察信号。
 */
export function calculateHuoTianDaYou(bars: BarData[], period = 25, roundOutput = true): HuoTianDaYouResult {
  if (period <= 0 || bars.length === 0) return { points: [] }

  const high = bars.map((bar) => bar.high)
  const low = bars.map((bar) => bar.low)
  const xmaHigh = tdxXma(tdxXma(high, period), period)
  const xmaLow = tdxXma(tdxXma(low, period), period)
  const zk1: Array<number | undefined> = []
  const zd1: Array<number | undefined> = []

  for (let index = 0; index < bars.length; index += 1) {
    const highValue = xmaHigh[index]
    const lowValue = xmaLow[index]
    if (!isFiniteNumber(highValue) || !isFiniteNumber(lowValue)) {
      zk1[index] = undefined
      zd1[index] = undefined
      continue
    }
    const width = highValue - lowValue
    zk1[index] = highValue + width
    zd1[index] = lowValue - width
  }

  const zd2 = tdxEmaFinite(zd1, period)
  const close = bars.map((bar) => bar.close)
  const previousClose = referenceValues(close, 1)
  const delta = close.map((value, index) => subtractFinite(value, previousClose[index]))
  const absoluteDelta = delta.map((value) => (isFiniteNumber(value) ? Math.abs(value) : undefined))
  const var23Numerator = tdxXma(tdxXma(delta, 6), 6)
  const var23Denominator = tdxXma(tdxXma(absoluteDelta, 6), 6)
  const var23 = var23Numerator.map((value, index) => divideFinite(value, var23Denominator[index], 100))
  const var23Ma2 = movingAverageFinite(var23, 2)
  const var23Llv2 = lowestFinite(var23, 2)
  const var23Llv7 = lowestFinite(var23, 7)
  const negativeCount2 = countFlags(var23.map((value) => isFiniteNumber(value) && value < 0), 2)
  const callbackBuy = var23.map((value, index) =>
    isFiniteNumber(value) &&
    isFiniteNumber(var23Llv2[index]) &&
    isFiniteNumber(var23Llv7[index]) &&
    var23Llv2[index] === var23Llv7[index] &&
    negativeCount2[index] > 0 &&
    crossesAbove(var23, var23Ma2, index),
  )
  const yellowFlags: boolean[] = []
  const whiteFlags: boolean[] = []

  const points = bars.map((bar, index) => {
    const upper = zk1[index]
    const lower = zd1[index]
    const mid = zd2[index]
    const observation = resolveHuoTianDaYouCandleObservation(bar, upper, lower)
    const { yellowCandle, whiteCandle, candleSegments } = observation
    yellowFlags[index] = yellowCandle
    whiteFlags[index] = whiteCandle
    return {
      time: bar.time as Time,
      zk1: finiteOrNull(upper, roundOutput),
      zd1: finiteOrNull(lower, roundOutput),
      zd2: finiteOrNull(mid, roundOutput),
      yellowCandle,
      whiteCandle,
      buyObservation: isNewThirdConsecutive(yellowFlags, index),
      sellObservation: isNewThirdConsecutive(whiteFlags, index),
      xgObservation: Boolean(isFiniteNumber(lower) && lower > bar.high && callbackBuy[index] && bar.low <= lower),
      candleSegments,
    }
  })

  return { points }
}

/**
 * 解析单根 K 线的火天大有着色观察（黄/白 K 线及 STICKLINE 片段）。
 * 绘制顺序对齐通达信：白线优先，黄线在后。
 */
export function resolveHuoTianDaYouCandleObservation(
  bar: BarData,
  upper: number | undefined,
  lower: number | undefined,
): HuoTianDaYouCandleObservation {
  const bodyHigh = Math.max(bar.open, bar.close)
  const bodyLow = Math.min(bar.open, bar.close)
  const overLow = isFiniteNumber(upper) ? Math.max(bodyLow, upper) : undefined
  const yellowAcrossRange = isFiniteNumber(lower) && lower > bar.low && lower < bar.high
  const yellowInsideBody = isFiniteNumber(lower) && lower > bodyLow && lower < bodyHigh
  const yellowAboveHigh = isFiniteNumber(lower) && lower > bar.high
  const yellowCandle = yellowAcrossRange || yellowInsideBody || yellowAboveHigh
  const whiteCandle = isFiniteNumber(upper) && isFiniteNumber(overLow) && bodyHigh > upper && bodyHigh > overLow
  const candleSegments: HuoTianDaYouCandleSegment[] = []

  // 对齐通达信 STICKLINE 绘制顺序：先白后黄
  if (whiteCandle) {
    candleSegments.push({ kind: 'body', colorRole: 'white', from: round(bodyHigh), to: round(overLow) })
  }
  if (yellowAcrossRange && isFiniteNumber(lower)) {
    candleSegments.push({ kind: 'body', colorRole: 'yellow', from: round(lower), to: round(Math.min(bodyLow, lower)) })
  }
  if (yellowInsideBody && isFiniteNumber(lower)) {
    candleSegments.push({ kind: 'body', colorRole: 'yellow', from: round(lower), to: round(bodyLow) })
  }
  if (yellowAboveHigh) {
    candleSegments.push(
      { kind: 'body', colorRole: 'yellow', from: round(bar.open), to: round(bar.close) },
      { kind: 'wick', colorRole: 'yellow', from: round(bar.high), to: round(bar.low) },
    )
  }

  return { yellowCandle, whiteCandle, candleSegments }
}

/**
 * 计算 MACD 指标（DIF、DEA、柱状图）。
 * 柱状图值为 (DIF - DEA) * 2，与通达信惯例一致。
 */
export function calculateMACD(bars: BarData[], fast = 12, slow = 26, signal = 9): MacdResult {
  if (bars.length < slow + signal) {
    return { dif: [], dea: [], histogram: [] }
  }

  const fastSeries = emaValues(bars.map((bar) => bar.close), fast)
  const slowSeries = emaValues(bars.map((bar) => bar.close), slow)
  const difValues: Array<{ index: number; value: number }> = []

  for (let index = 0; index < bars.length; index += 1) {
    const fastValue = fastSeries[index]
    const slowValue = slowSeries[index]
    if (fastValue === undefined || slowValue === undefined) continue
    difValues.push({ index, value: fastValue - slowValue })
  }

  const deaValues = emaValues(
    difValues.map((point) => point.value),
    signal,
  )
  const dif: IndicatorPoint[] = []
  const dea: IndicatorPoint[] = []
  const histogram: IndicatorPoint[] = []

  deaValues.forEach((deaValue, localIndex) => {
    if (deaValue === undefined) return
    const difPoint = difValues[localIndex]
    dif.push({ time: bars[difPoint.index].time as Time, value: round(difPoint.value) })
    dea.push({ time: bars[difPoint.index].time as Time, value: round(deaValue) })
    histogram.push({ time: bars[difPoint.index].time as Time, value: round((difPoint.value - deaValue) * 2) })
  })

  return { dif, dea, histogram }
}

/**
 * 计算平均真实波幅（ATR），使用 Wilder 平滑。
 */
export function calculateATR(bars: BarData[], period = 14): IndicatorPoint[] {
  if (period <= 0 || bars.length < period) return []

  const trueRanges = bars.map((bar, index) => {
    if (index === 0) return bar.high - bar.low
    const previousClose = bars[index - 1].close
    return Math.max(bar.high - bar.low, Math.abs(bar.high - previousClose), Math.abs(bar.low - previousClose))
  })
  const points: IndicatorPoint[] = []
  let previous = average(trueRanges.slice(0, period))
  points.push({ time: bars[period - 1].time as Time, value: round(previous) })

  for (let index = period; index < trueRanges.length; index += 1) {
    previous = (previous * (period - 1) + trueRanges[index]) / period
    points.push({ time: bars[index].time as Time, value: round(previous) })
  }

  return points
}

function emaValues(values: number[], period: number): Array<number | undefined> {
  const result: Array<number | undefined> = Array.from({ length: values.length }, () => undefined)
  if (period <= 0 || values.length < period) return result

  const multiplier = 2 / (period + 1)
  let previous = average(values.slice(0, period))
  result[period - 1] = previous
  for (let index = period; index < values.length; index += 1) {
    previous = (values[index] - previous) * multiplier + previous
    result[index] = previous
  }
  return result
}

/**
 * 通达信 XMA（扩展移动平均）：对称窗口加权，周期自动归一化为奇数。
 */
export function tdxXma(values: Array<number | undefined>, period: number): Array<number | undefined> {
  const normalizedPeriod = normalizeXmaPeriod(period)
  const p = (normalizedPeriod - 1) / 2
  return values.map((_, index) => {
    const start = index - p - 1
    const end = index + (normalizedPeriod - p) - 1
    const window = sliceLikeNumpy(values, start, end).filter(isFiniteNumber)
    if (window.length === 0) return undefined
    return average(window)
  })
}

/** XMA 周期须为正奇数，偶数时 +1 */
function normalizeXmaPeriod(period: number): number {
  const value = Math.trunc(period)
  if (value <= 0) return 0
  return value % 2 === 0 ? value + 1 : value
}

/** 模拟 numpy 负索引切片语义 */
function sliceLikeNumpy<T>(values: T[], start: number, end: number): T[] {
  const length = values.length
  const normalizedStart = start < 0 ? Math.max(length + start, 0) : Math.min(start, length)
  const normalizedEnd = end < 0 ? Math.max(length + end, 0) : Math.min(end, length)
  if (normalizedEnd <= normalizedStart) return []
  return values.slice(normalizedStart, normalizedEnd)
}

/** 通达信 EMA：跳过非有限值，首个有效值作为种子 */
function tdxEmaFinite(values: Array<number | undefined>, period: number): Array<number | undefined> {
  const result: Array<number | undefined> = Array.from({ length: values.length }, () => undefined)
  if (period <= 0) return result
  const multiplier = 2 / (period + 1)
  let previous: number | undefined
  values.forEach((value, index) => {
    if (!isFiniteNumber(value)) return
    previous = previous === undefined ? value : (value - previous) * multiplier + previous
    result[index] = previous
  })
  return result
}

function referenceValues(values: number[], periods: number): Array<number | undefined> {
  return values.map((_, index) => (index >= periods ? values[index - periods] : undefined))
}

function subtractFinite(left: number | undefined, right: number | undefined): number | undefined {
  return isFiniteNumber(left) && isFiniteNumber(right) ? left - right : undefined
}

function divideFinite(
  numerator: number | undefined,
  denominator: number | undefined,
  scale = 1,
): number | undefined {
  return isFiniteNumber(numerator) && isFiniteNumber(denominator) && denominator !== 0
    ? (numerator / denominator) * scale
    : undefined
}

function movingAverageFinite(values: Array<number | undefined>, period: number): Array<number | undefined> {
  return values.map((_, index) => {
    if (index < period - 1) return undefined
    const window = values.slice(index - period + 1, index + 1)
    return window.every(isFiniteNumber) ? average(window) : undefined
  })
}

function lowestFinite(values: Array<number | undefined>, period: number): Array<number | undefined> {
  return values.map((_, index) => {
    const window = values.slice(Math.max(0, index - period + 1), index + 1).filter(isFiniteNumber)
    return window.length > 0 ? Math.min(...window) : undefined
  })
}

function countFlags(flags: boolean[], period: number): number[] {
  return flags.map((_, index) => flags.slice(Math.max(0, index - period + 1), index + 1).filter(Boolean).length)
}

/** 判断 index 处 left 是否上穿 right（前一根 ≤，当前根 >） */
function crossesAbove(
  left: Array<number | undefined>,
  right: Array<number | undefined>,
  index: number,
): boolean {
  if (index <= 0) return false
  const previousLeft = left[index - 1]
  const previousRight = right[index - 1]
  const currentLeft = left[index]
  const currentRight = right[index]
  return Boolean(
    isFiniteNumber(previousLeft) &&
    isFiniteNumber(previousRight) &&
    isFiniteNumber(currentLeft) &&
    isFiniteNumber(currentRight) &&
    previousLeft <= previousRight &&
    currentLeft > currentRight,
  )
}

/**
 * 判断 flags 在 index 处是否为「连续第三根为真且第四根为假」的新信号点。
 */
export function isNewThirdConsecutive(flags: boolean[], index: number): boolean {
  return Boolean(flags[index] && flags[index - 1] && flags[index - 2] && !flags[index - 3])
}

function finiteOrNull(value: number | undefined, roundOutput: boolean): number | null {
  if (!isFiniteNumber(value)) return null
  return roundOutput ? round(value) : value
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function average(values: number[]): number {
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function round(value: number): number {
  return Number(value.toFixed(6))
}
