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

export interface SubingEmaRibbonPoint {
  time: string
  ema10: number
  ema21: number
  tone: SubingEmaRibbonTone
}

export interface SubingEmaRibbon {
  ema10: EmaPoint[]
  ema21: EmaPoint[]
  points: SubingEmaRibbonPoint[]
}

export function buildSubingEmaRibbon(bars: BarData[]): SubingEmaRibbon {
  const ema10 = calculateEMA(bars, 10).map(toKlinePoint)
  const ema21 = calculateEMA(bars, 21).map(toKlinePoint)
  return {
    ema10,
    ema21,
    points: buildRibbonPoints(ema10, ema21),
  }
}

export function buildRibbonPoints(
  fast: readonly EmaPoint[],
  slow: readonly EmaPoint[],
): SubingEmaRibbonPoint[] {
  const slowByTime = new Map(slow.map((item) => [item.time, item.value]))
  const points: SubingEmaRibbonPoint[] = []
  let previousTone: SubingEmaRibbonTone | null = null

  for (const item of fast) {
    const ema21 = slowByTime.get(item.time)
    if (ema21 === undefined) continue

    const tone = item.value > ema21
      ? 'bull'
      : item.value < ema21
        ? 'bear'
        : previousTone

    if (!tone) continue
    previousTone = tone
    points.push({ time: item.time, ema10: item.value, ema21, tone })
  }

  return points
}

function toKlinePoint(point: { time: unknown; value: number }): EmaPoint {
  return { time: String(point.time), value: point.value }
}
