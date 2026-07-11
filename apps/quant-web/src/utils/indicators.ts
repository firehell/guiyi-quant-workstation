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
    zk1[index] = round(highValue + width)
    zd1[index] = round(lowValue - width)
  }

  const zd2 = tdxEmaFinite(zd1, period)
  const yellowFlags: boolean[] = []
  const whiteFlags: boolean[] = []

  const points = bars.map((bar, index) => {
    const upper = zk1[index]
    const lower = zd1[index]
    const mid = zd2[index]
    const yellowCandle = isFiniteNumber(lower) && bar.low <= lower && bar.high >= lower
    const whiteCandle = isFiniteNumber(upper) && bar.high >= upper
    yellowFlags[index] = yellowCandle
    whiteFlags[index] = whiteCandle
    return {
      time: bar.time as Time,
      zk1: finiteOrNull(upper),
      zd1: finiteOrNull(lower),
      zd2: finiteOrNull(mid),
      yellowCandle,
      whiteCandle,
      buyObservation: isNewThirdConsecutive(yellowFlags, index),
      sellObservation: isNewThirdConsecutive(whiteFlags, index),
    }
  })

  return { points }
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
    return round(average(window))
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
    result[index] = round(previous)
  })
  return result
}

function isNewThirdConsecutive(flags: boolean[], index: number): boolean {
  return Boolean(flags[index] && flags[index - 1] && flags[index - 2] && !flags[index - 3])
}

function finiteOrNull(value: number | undefined): number | null {
  return isFiniteNumber(value) ? value : null
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
