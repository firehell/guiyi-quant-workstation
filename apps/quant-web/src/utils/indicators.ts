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

function average(values: number[]): number {
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function round(value: number): number {
  return Number(value.toFixed(6))
}
