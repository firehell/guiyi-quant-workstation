import type { BacktestTrade } from '@/types/backtest'
import type { KlineMarker } from '@/types/market'
import { formatTradeMarkerText } from '@/utils/tradeMarker'

/**
 * 将单笔回测成交转换为 K 线买卖点 marker。
 * 用于 deep-link 跳转行情页时在图表上标注开/平仓位置。
 */
export function tradeToKlineMarkers(trade: BacktestTrade): KlineMarker[] {
  const markers: KlineMarker[] = []
  if (trade.open_time) {
    markers.push({
      id: `${trade.id}-open`,
      time: trade.open_time,
      // 多/空方向决定买入(B)或卖出(S)标签
      label: trade.direction === 'long' || trade.direction === '多' ? 'B' : 'S',
      tooltip: formatTradeMarkerText(trade, 'open'),
      color: '#3b82f6',
      position: 'belowBar',
      shape: 'arrowUp',
    })
  }
  // 平仓 marker 独立于开仓，部分成交可能仅有开仓记录
  if (trade.close_time) {
    markers.push({
      id: `${trade.id}-close`,
      time: trade.close_time,
      label: 'X',
      tooltip: formatTradeMarkerText(trade, 'close'),
      color: '#f59e0b',
      position: 'aboveBar',
      shape: 'arrowDown',
    })
  }
  return markers
}
