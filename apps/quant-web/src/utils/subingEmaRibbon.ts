import type { BarData } from '../types/market.ts'
import { calculateEMA } from './indicators.ts'

interface EmaPoint {
  time: string
  value: number
}

export const SUBING_EMA_RIBBON_STYLE = {
  bull: { fill: 'rgba(245, 197, 66, 0.30)', stroke: '#E8B923' },
  bear: { fill: 'rgba(125, 211, 252, 0.32)', stroke: '#38BDF8' },
} as const

export type SubingEmaRibbonTone = 'bull' | 'bear'

export interface SubingEmaRibbonAlignedPoint {
  time: string
  ema10: number
  ema21: number
}

export interface SubingEmaRibbonBand {
  left: SubingEmaRibbonAlignedPoint
  right: SubingEmaRibbonAlignedPoint
  leftTone: SubingEmaRibbonTone
  rightTone: SubingEmaRibbonTone
  splitT: number | null
}

export interface SubingEmaRibbon {
  ema10: EmaPoint[]
  ema21: EmaPoint[]
  bands: SubingEmaRibbonBand[]
}

export function buildSubingEmaRibbon(bars: BarData[]): SubingEmaRibbon {
  const ema10 = calculateEMA(bars, 10).map(toKlinePoint)
  const ema21 = calculateEMA(bars, 21).map(toKlinePoint)
  return {
    ema10,
    ema21,
    bands: segmentSubingEmaRibbon(ema10, ema21),
  }
}

export function segmentSubingEmaRibbon(
  fast: readonly EmaPoint[],
  slow: readonly EmaPoint[],
): SubingEmaRibbonBand[] {
  const aligned = alignEmaPoints(fast, slow)
  const bands: SubingEmaRibbonBand[] = []
  let inherited: SubingEmaRibbonTone | null = null

  for (let index = 0; index < aligned.length - 1; index += 1) {
    const left = aligned[index]
    const right = aligned[index + 1]
    const observedLeft = toneOf(left)
    const observedRight = toneOf(right)
    const resolvedLeft: SubingEmaRibbonTone | null = observedLeft ?? inherited ?? observedRight
    const resolvedRight: SubingEmaRibbonTone | null = observedRight ?? resolvedLeft
    if (!resolvedLeft || !resolvedRight) continue
    inherited = resolvedRight
    bands.push({
      left,
      right,
      leftTone: resolvedLeft,
      rightTone: resolvedRight,
      splitT: resolvedLeft === resolvedRight ? null : crossingSplitT(left, right),
    })
  }

  return bands
}

export function crossingSplitT(
  left: Pick<SubingEmaRibbonAlignedPoint, 'ema10' | 'ema21'>,
  right: Pick<SubingEmaRibbonAlignedPoint, 'ema10' | 'ema21'>,
): number {
  const previousDiff = left.ema10 - left.ema21
  const nextDiff = right.ema10 - right.ema21
  const denominator = previousDiff - nextDiff
  return denominator === 0 ? 0.5 : clamp01(previousDiff / denominator)
}

export function splitRibbonCoordinates(
  left: { x: number; y10: number; y21: number },
  right: { x: number; y10: number; y21: number },
  splitT: number,
): { x: number; y10: number; y21: number } {
  const t = clamp01(splitT)
  return {
    x: left.x + t * (right.x - left.x),
    y10: left.y10 + t * (right.y10 - left.y10),
    y21: left.y21 + t * (right.y21 - left.y21),
  }
}

function alignEmaPoints(
  fast: readonly EmaPoint[],
  slow: readonly EmaPoint[],
): SubingEmaRibbonAlignedPoint[] {
  const slowByTime = new Map(slow.map((point) => [point.time, point.value]))
  return fast.flatMap((point) => {
    const ema21 = slowByTime.get(point.time)
    return ema21 === undefined
      ? []
      : [{ time: point.time, ema10: point.value, ema21 }]
  })
}

function toneOf(point: SubingEmaRibbonAlignedPoint): SubingEmaRibbonTone | null {
  if (point.ema10 > point.ema21) return 'bull'
  if (point.ema10 < point.ema21) return 'bear'
  return null
}

function clamp01(value: number): number {
  if (value <= 0) return 0
  if (value >= 1) return 1
  return value
}

function toKlinePoint(point: { time: unknown; value: number }): EmaPoint {
  return { time: String(point.time), value: point.value }
}
