import type { Time } from 'lightweight-charts'
import type { BarData } from '@/types/market'

export interface IndicatorPoint {
  time: Time
  value: number
}

export interface MacdResult {
  dif: IndicatorPoint[]
  dea: IndicatorPoint[]
  histogram: IndicatorPoint[]
}

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

export interface HuoTianDaYouCandleSegment {
  kind: 'body' | 'wick'
  colorRole: 'white' | 'yellow'
  from: number
  to: number
}

export interface HuoTianDaYouCandleObservation {
  yellowCandle: boolean
  whiteCandle: boolean
  candleSegments: HuoTianDaYouCandleSegment[]
}

export interface HuoTianDaYouResult {
  points: HuoTianDaYouPoint[]
}

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

export function calculateHuoTianDaYou(bars: BarData[], period = 25): HuoTianDaYouResult {
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
      zk1: roundedFiniteOrNull(upper),
      zd1: roundedFiniteOrNull(lower),
      zd2: roundedFiniteOrNull(mid),
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

  // Preserve Tongdaxin STICKLINE source order: white first, yellow afterward.
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

function normalizeXmaPeriod(period: number): number {
  const value = Math.trunc(period)
  if (value <= 0) return 0
  return value % 2 === 0 ? value + 1 : value
}

function sliceLikeNumpy<T>(values: T[], start: number, end: number): T[] {
  const length = values.length
  const normalizedStart = start < 0 ? Math.max(length + start, 0) : Math.min(start, length)
  const normalizedEnd = end < 0 ? Math.max(length + end, 0) : Math.min(end, length)
  if (normalizedEnd <= normalizedStart) return []
  return values.slice(normalizedStart, normalizedEnd)
}

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

export function isNewThirdConsecutive(flags: boolean[], index: number): boolean {
  return Boolean(flags[index] && flags[index - 1] && flags[index - 2] && !flags[index - 3])
}

function roundedFiniteOrNull(value: number | undefined): number | null {
  return isFiniteNumber(value) ? round(value) : null
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
