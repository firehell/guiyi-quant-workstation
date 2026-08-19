import type { Time } from 'lightweight-charts'
import type { BarData } from '@/types/market'

export type MainForceMirrorState = 'entry' | 'wash' | 'pull_up' | 'distribute' | 'exit' | 'lure'

export interface MainForceMirrorPoint {
  time: Time
  value: number | null
  state: MainForceMirrorState | null
  caution: boolean
  cautionLevel: number | null
}

export interface MainForceMirrorResult {
  points: MainForceMirrorPoint[]
}

export interface MainForceMirrorOptions {
  volumeWindow?: number
  flowEmaPeriod?: number
  rangeWindow?: number
  cautionHighWindow?: number
  cautionQuietWindow?: number
  flowClip?: number
  scoreScale?: number
  exitLureScale?: number
  cautionLevel?: number
}

const DEFAULTS = {
  volumeWindow: 20,
  flowEmaPeriod: 5,
  rangeWindow: 20,
  cautionHighWindow: 5,
  cautionQuietWindow: 10,
  flowClip: 3,
  scoreScale: 50,
  exitLureScale: 0.35,
  cautionLevel: 50,
} as const

/**
 * Designed six-state OHLCV observation proxy.
 * It does not measure real main-force fund flow or an outflow percentage.
 */
export function classifyMainForceMirrorState(
  rangePosition: number,
  flow: number,
  flowDelta: number,
  priceDelta: number,
): MainForceMirrorState {
  if (![rangePosition, flow, flowDelta, priceDelta].every(Number.isFinite)) {
    throw new Error('classification inputs must be finite')
  }

  if (flow < 0) {
    if (rangePosition >= 0.5 && priceDelta > 0) return 'lure'
    return 'exit'
  }

  if (rangePosition < 0.45) {
    if (priceDelta < 0 || flowDelta < 0) return 'wash'
    return 'entry'
  }

  if (priceDelta >= 0 && flowDelta >= 0) return 'pull_up'
  return 'distribute'
}

/**
 * Browser observation mirror of the Python Indicator Kernel.
 * "小心" reproduces rising_edge(BARSLAST(HIGH = HHV(HIGH, 5)) < 10).
 */
export function calculateMainForceMirror(
  bars: BarData[],
  options: MainForceMirrorOptions = {},
): MainForceMirrorResult {
  const config = { ...DEFAULTS, ...options }
  requirePositiveInt(config.volumeWindow, 'volumeWindow')
  requirePositiveInt(config.flowEmaPeriod, 'flowEmaPeriod')
  requirePositiveInt(config.rangeWindow, 'rangeWindow')
  requirePositiveInt(config.cautionHighWindow, 'cautionHighWindow')
  requirePositiveInt(config.cautionQuietWindow, 'cautionQuietWindow')
  requirePositive(config.flowClip, 'flowClip')
  requirePositive(config.scoreScale, 'scoreScale')
  if (!Number.isFinite(config.exitLureScale) || config.exitLureScale <= 0 || config.exitLureScale > 1) {
    throw new Error('exitLureScale must be in (0, 1]')
  }
  requirePositive(config.cautionLevel, 'cautionLevel')

  const high = bars.map((bar) => bar.high)
  const low = bars.map((bar) => bar.low)
  const close = bars.map((bar) => bar.close)
  const volume = bars.map((bar) => bar.volume)

  const volumeMean = rollingMean(volume, config.volumeWindow)
  const volumeRatio = volume.map((value, index) => {
    const mean = volumeMean[index]
    if (!isFiniteNumber(value) || !isFiniteNumber(mean) || mean <= 0) return undefined
    return clamp(value / mean, 0, config.flowClip)
  })

  const rawFlow = bars.map((bar, index) => {
    const ratio = volumeRatio[index]
    if (!isFiniteNumber(ratio)) return undefined
    const range = bar.high - bar.low
    const clv = isFiniteNumber(range) && range > 0
      ? (2 * bar.close - bar.high - bar.low) / range
      : 0
    return clv * ratio
  })
  const flow = emaFinite(rawFlow, config.flowEmaPeriod)
  const rollingHigh = rollingExtreme(high, config.rangeWindow, Math.max)
  const rollingLow = rollingExtreme(low, config.rangeWindow, Math.min)
  const rangePosition = bars.map((bar, index) => {
    const upper = rollingHigh[index]
    const lower = rollingLow[index]
    if (!isFiniteNumber(upper) || !isFiniteNumber(lower) || upper <= lower) return undefined
    return clamp((bar.close - lower) / (upper - lower), 0, 1)
  })

  const shortHighEvent = rollingCurrentHighEvent(high, config.cautionHighWindow)
  const recentShortHigh = rollingAny(shortHighEvent, config.cautionQuietWindow)
  const caution = recentShortHigh.map((active, index) => active && !(recentShortHigh[index - 1] ?? false))

  const points: MainForceMirrorPoint[] = bars.map((bar, index) => {
    const currentFlow = flow[index]
    const previousFlow = flow[index - 1]
    const currentRangePosition = rangePosition[index]
    let value: number | null = null
    let state: MainForceMirrorState | null = null

    if (
      index > 0
      && isFiniteNumber(currentFlow)
      && isFiniteNumber(previousFlow)
      && isFiniteNumber(currentRangePosition)
      && isFiniteNumber(bar.close)
      && isFiniteNumber(bars[index - 1].close)
    ) {
      const flowDelta = currentFlow - previousFlow
      const priceDelta = bar.close - bars[index - 1].close
      state = classifyMainForceMirrorState(currentRangePosition, currentFlow, flowDelta, priceDelta)
      const strength = Math.min(Math.abs(currentFlow) * config.scoreScale, 100)
      if (state === 'entry' || state === 'wash') value = strength
      else if (state === 'pull_up' || state === 'distribute') value = -strength
      else if (state === 'exit') value = strength * config.exitLureScale
      else value = -strength * config.exitLureScale
      value = round(value)
    }

    return {
      time: bar.time as Time,
      value,
      state,
      caution: caution[index],
      cautionLevel: caution[index] ? config.cautionLevel : null,
    }
  })

  return { points }
}

function rollingCurrentHighEvent(values: number[], window: number): boolean[] {
  return values.map((value, index) => {
    if (index < window - 1 || !Number.isFinite(value)) return false
    const segment = values.slice(index - window + 1, index + 1)
    return segment.every(Number.isFinite) && value === Math.max(...segment)
  })
}

function rollingAny(values: boolean[], window: number): boolean[] {
  return values.map((_, index) => values.slice(Math.max(0, index - window + 1), index + 1).some(Boolean))
}

function rollingMean(values: number[], window: number): Array<number | undefined> {
  return values.map((_, index) => {
    if (index < window - 1) return undefined
    const segment = values.slice(index - window + 1, index + 1)
    if (!segment.every(Number.isFinite)) return undefined
    return segment.reduce((sum, value) => sum + value, 0) / window
  })
}

function rollingExtreme(
  values: number[],
  window: number,
  reducer: (...values: number[]) => number,
): Array<number | undefined> {
  return values.map((_, index) => {
    if (index < window - 1) return undefined
    const segment = values.slice(index - window + 1, index + 1)
    if (!segment.every(Number.isFinite)) return undefined
    return reducer(...segment)
  })
}

function emaFinite(values: Array<number | undefined>, period: number): Array<number | undefined> {
  const alpha = 2 / (period + 1)
  let previous: number | undefined
  return values.map((value) => {
    if (!isFiniteNumber(value)) return undefined
    previous = previous === undefined ? value : alpha * value + (1 - alpha) * previous
    return previous
  })
}

function requirePositiveInt(value: number, name: string) {
  if (!Number.isInteger(value) || value <= 0) throw new Error(`${name} must be a positive integer`)
}

function requirePositive(value: number, name: string) {
  if (!Number.isFinite(value) || value <= 0) throw new Error(`${name} must be positive and finite`)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function round(value: number) {
  return Number(value.toFixed(6))
}
