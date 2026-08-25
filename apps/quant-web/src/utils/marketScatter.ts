import type { MarketRadarItem } from '../types/market.ts'

export type MarketQuadrantKey =
  | 'down_increase'
  | 'up_increase'
  | 'down_decrease'
  | 'up_decrease'
  | 'neutral'

export interface MarketQuadrant {
  key: MarketQuadrantKey
  label: string
  items: MarketRadarItem[]
}

const QUADRANTS: Array<Pick<MarketQuadrant, 'key' | 'label'>> = [
  { key: 'down_increase', label: '下跌 + 增仓' },
  { key: 'up_increase', label: '上涨 + 增仓' },
  { key: 'down_decrease', label: '下跌 + 减仓' },
  { key: 'up_decrease', label: '上涨 + 减仓' },
  { key: 'neutral', label: '方向未定' },
]

export function groupMarketScatterItems(items: readonly MarketRadarItem[]): MarketQuadrant[] {
  const grouped = new Map<MarketQuadrantKey, MarketRadarItem[]>(
    QUADRANTS.map((quadrant) => [quadrant.key, []]),
  )

  items.forEach((item) => {
    if (item.price_change_1d === null || item.oi_change_1d === null) return
    grouped.get(quadrantKey(item))?.push(item)
  })

  return QUADRANTS.map((quadrant) => ({
    ...quadrant,
    items: grouped.get(quadrant.key)!.sort(compareImpact),
  }))
}

function quadrantKey(item: MarketRadarItem): MarketQuadrantKey {
  const price = item.price_change_1d!
  const openInterest = item.oi_change_1d!
  if (price === 0 || openInterest === 0) return 'neutral'
  if (price < 0) return openInterest > 0 ? 'down_increase' : 'down_decrease'
  return openInterest > 0 ? 'up_increase' : 'up_decrease'
}

function compareImpact(left: MarketRadarItem, right: MarketRadarItem): number {
  const leftImpact = Math.abs(left.price_change_1d!) + Math.abs(left.oi_change_1d!)
  const rightImpact = Math.abs(right.price_change_1d!) + Math.abs(right.oi_change_1d!)
  return rightImpact - leftImpact || left.symbol.localeCompare(right.symbol)
}
