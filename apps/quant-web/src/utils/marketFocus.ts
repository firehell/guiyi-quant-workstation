import type { MarketRadarItem } from '@/types/market'

export type MarketFocusDirection = 'long' | 'short'

export interface MarketFocusItem {
  item: MarketRadarItem
  direction: MarketFocusDirection
  reasonLabels: string[]
  riskLabel: string | null
}

const MAX_FOCUS_ITEMS = 3
const LONG_PARTICIPATION = ['price_move_up', 'volume_expansion', 'oi_increase'] as const
const SHORT_PARTICIPATION = ['price_move_down', 'volume_expansion', 'oi_increase'] as const

const REASON_LABELS: Record<string, string> = {
  price_move_up: '价格上涨',
  price_move_down: '价格下跌',
  volume_expansion: '放量',
  oi_increase: '增仓',
  near_20d_high: '接近20日高位',
  near_20d_low: '接近20日低位',
}

function has(item: MarketRadarItem, code: string) {
  return item.reason_codes.includes(code)
}

function direction(item: MarketRadarItem): MarketFocusDirection | null {
  if (has(item, 'ema21_up') && LONG_PARTICIPATION.some((code) => has(item, code))) return 'long'
  if (has(item, 'ema21_down') && SHORT_PARTICIPATION.some((code) => has(item, code))) return 'short'
  return null
}

function directionalCodes(value: MarketFocusDirection) {
  return value === 'long' ? LONG_PARTICIPATION : SHORT_PARTICIPATION
}

function focusItem(item: MarketRadarItem, value: MarketFocusDirection): MarketFocusItem {
  const locationCode = value === 'long' ? 'near_20d_high' : 'near_20d_low'
  const reasonLabels = [...directionalCodes(value), locationCode]
    .filter((code) => has(item, code))
    .map((code) => REASON_LABELS[code])
    .slice(0, 3)

  return {
    item,
    direction: value,
    reasonLabels,
    riskLabel: has(item, 'oi_decrease') ? '减仓推动' : has(item, 'high_volatility') ? '高波动' : null,
  }
}

function supportCount(entry: MarketFocusItem) {
  return directionalCodes(entry.direction).filter((code) => has(entry.item, code)).length
}

export function selectMarketFocus(items: MarketRadarItem[]): MarketFocusItem[] {
  return items
    .flatMap((item) => {
      const value = direction(item)
      return value ? [focusItem(item, value)] : []
    })
    .sort((left, right) => {
      const support = supportCount(right) - supportCount(left)
      if (support) return support

      const oi = Number(has(right.item, 'oi_increase')) - Number(has(left.item, 'oi_increase'))
      if (oi) return oi

      const volume = Number(has(right.item, 'volume_expansion')) - Number(has(left.item, 'volume_expansion'))
      if (volume) return volume

      const leftPriceCode = left.direction === 'long' ? 'price_move_up' : 'price_move_down'
      const rightPriceCode = right.direction === 'long' ? 'price_move_up' : 'price_move_down'
      const price = Number(has(right.item, rightPriceCode)) - Number(has(left.item, leftPriceCode))
      if (price) return price

      const turnover = (right.item.turnover ?? Number.NEGATIVE_INFINITY)
        - (left.item.turnover ?? Number.NEGATIVE_INFINITY)
      if (turnover) return turnover

      return left.item.symbol.localeCompare(right.item.symbol)
    })
    .slice(0, MAX_FOCUS_ITEMS)
}
