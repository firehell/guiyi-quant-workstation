import type { Time } from 'lightweight-charts'
import type { MarketIndicatorPoint, MarketMacdIndicatorResponse } from '@/types/market'
import type { IndicatorPoint, MacdResult } from './indicators'

/**
 * 将后端 MACD 覆盖响应转为前端指标计算结果格式。
 * 无覆盖数据时返回 null。
 */
export function macdOverrideToResult(override?: MarketMacdIndicatorResponse | null): MacdResult | null {
  if (!override) return null
  return {
    dif: normalizeMacdPoints(override.dif),
    dea: normalizeMacdPoints(override.dea),
    histogram: normalizeMacdPoints(override.histogram),
  }
}

/** 过滤并规范化 MACD 点列：仅保留 ready、valid 且数值有限的点 */
function normalizeMacdPoints(points: MarketIndicatorPoint[]): IndicatorPoint[] {
  return points
    .filter((point) => point.ready && point.valid && typeof point.value === 'number' && Number.isFinite(point.value) && !!point.time)
    .map((point) => ({ time: point.time as Time, value: point.value as number }))
}
