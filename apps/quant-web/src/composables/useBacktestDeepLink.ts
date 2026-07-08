import type { BacktestTrade } from '@/types/backtest'
import type { KlineMarker } from '@/types/market'
import { formatTradeMarkerText } from '@/utils/tradeMarker'

export function tradeToKlineMarkers(trade: BacktestTrade): KlineMarker[] {
  const markers: KlineMarker[] = []
  if (trade.open_time) {
    markers.push({
      id: `${trade.id}-open`,
      time: trade.open_time,
      label: trade.direction === 'long' || trade.direction === '多' ? 'B' : 'S',
      tooltip: formatTradeMarkerText(trade, 'open'),
      color: '#3b82f6',
      position: 'belowBar',
      shape: 'arrowUp',
    })
  }
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
