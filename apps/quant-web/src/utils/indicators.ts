/**
 * Market Web 观察镜像：算法权威在 packages/quant-core Indicator Kernel。
 * 本文件只服务浏览器 overlay / 前端测试，必须与 shared golden 对齐；不得另立业务口径。
 */
import type { Time } from 'lightweight-charts'
import type { BarData } from '@/types/market'
export { calculateRangeDetectorLux } from './rangeDetectorLux.ts'

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
 * 通达信 XMA（扩展移动平均）：对称窗口加权，周期自动归一化为奇数。
 */
export function tdxXma(values: Array<number | undefined>, period: number): Array<number | undefined> {
  const normalizedPeriod = normalizeXmaPeriod(period)
  if (normalizedPeriod <= 0) return values.map(() => undefined)
  const radius = (normalizedPeriod - 1) / 2
  return values.map((_, index) => {
    const window = values.slice(Math.max(0, index - radius), Math.min(values.length, index + radius + 1)).filter(isFiniteNumber)
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
