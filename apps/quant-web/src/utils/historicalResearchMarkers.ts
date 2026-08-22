import type {
  KlineMarker,
  SubingHistoricalSignalEvent,
} from '../types/market.ts'
import { ALERT_RULE_CODES } from './alertRules.ts'


export function subingMarkerDedupeKey(
  symbol: string,
  barEnd: string,
  frequency: '5m' | '15m',
  direction: 'buy' | 'sell',
): string {
  return `${ALERT_RULE_CODES.SUBING}:${symbol.trim().toLowerCase()}:${barEnd}:${frequency}:${direction}`
}

export function historicalResearchEventToMarker(
  symbol: string,
  event: SubingHistoricalSignalEvent,
): KlineMarker {
  const buy = event.direction === 'buy'
  const label = buy ? '买入信号' : '卖出信号'
  return {
    id: `historical:${event.event_id}`,
    dedupeKey: subingMarkerDedupeKey(
      symbol,
      event.bar_end,
      event.trigger_timeframe,
      event.direction,
    ),
    time: event.bar_end,
    label,
    tooltip: `历史因果重放 · SuBing · ${event.contract} · ${event.trigger_timeframe} · ${label} · 非成交回测`,
    tone: buy ? 'up' : 'down',
    position: buy ? 'belowBar' : 'aboveBar',
    shape: buy ? 'arrowUp' : 'arrowDown',
  }
}
