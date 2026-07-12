import type { Time } from 'lightweight-charts'
import type { MarketIndicatorPoint, MarketMacdIndicatorResponse } from '@/types/market'
import type { IndicatorPoint, MacdResult } from './indicators'

export function macdOverrideToResult(override?: MarketMacdIndicatorResponse | null): MacdResult | null {
  if (!override) return null
  return {
    dif: normalizeMacdPoints(override.dif),
    dea: normalizeMacdPoints(override.dea),
    histogram: normalizeMacdPoints(override.histogram),
  }
}

function normalizeMacdPoints(points: MarketIndicatorPoint[]): IndicatorPoint[] {
  return points
    .filter((point) => point.ready && point.valid && typeof point.value === 'number' && Number.isFinite(point.value) && !!point.time)
    .map((point) => ({ time: point.time as Time, value: point.value as number }))
}
