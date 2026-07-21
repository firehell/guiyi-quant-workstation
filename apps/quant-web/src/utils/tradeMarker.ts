export type TradeMarkerType = 'open' | 'close'

interface TradeMarkerSource {
  direction?: string | null
}

/**
 * 根据交易方向与 marker 类型生成中文标注文本（开多/开空/平多/平空）。
 */
export function formatTradeMarkerText(trade: TradeMarkerSource, markerType: TradeMarkerType) {
  const isLong = tradeDirectionSide(trade.direction || '') === 'long'
  if (markerType === 'open') return isLong ? '开多' : '开空'
  return isLong ? '平多' : '平空'
}

/** 将多种方向表示统一为 long / short */
function tradeDirectionSide(direction: string) {
  const normalized = String(direction).trim().toLowerCase()
  if (['long', 'buy', '多'].includes(normalized)) return 'long'
  if (['short', 'sell', '空'].includes(normalized)) return 'short'
  return normalized.includes('空') || normalized.includes('short') || normalized.includes('sell') ? 'short' : 'long'
}
