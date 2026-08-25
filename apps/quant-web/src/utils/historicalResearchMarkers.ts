import type {
  JdjStrategyHistoricalAction,
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

const JDJ_STRATEGY_FILL_KINDS = new Set(['entry', 'add', 'reduce', 'exit'])

export function jdjStrategyActionToMarker(
  action: JdjStrategyHistoricalAction,
): KlineMarker | null {
  if (
    !JDJ_STRATEGY_FILL_KINDS.has(action.kind)
    || action.effective_bar_end === null
    || action.reference_price === null
    || action.direction === null
  ) return null

  const long = action.direction === 'long'
  const label = action.kind === 'entry'
    ? long ? '▲' : '▼'
    : action.kind === 'add'
      ? '＋'
      : action.kind === 'reduce'
        ? '－'
        : '×'
  const shape = action.kind === 'entry'
    ? long ? 'arrowUp' as const : 'arrowDown' as const
    : action.kind === 'exit'
      ? 'square' as const
      : 'circle' as const
  const value = (candidate: string | null) => candidate ?? '—'
  return {
    id: `historical:${action.event_id}`,
    time: action.effective_bar_end,
    label,
    tooltip: [
      '参考回放 · 日进斗金策略',
      `主设置 ${value(action.primary_setup)}`,
      `辅助设置 ${action.supporting_setups.join(', ') || '—'}`,
      `合约 ${action.contract}`,
      `决策时间 ${action.decision_at}`,
      `生效时间 ${action.effective_bar_end}`,
      `数量 ${action.quantity}`,
      `止损 ${value(action.stop_price)}`,
      `目标 ${value(action.target_price)}`,
      `R:R ${value(action.reward_risk)}`,
      `原因 ${action.reason}`,
    ].join(' · '),
    tone: long ? 'up' : 'down',
    position: long ? 'belowBar' : 'aboveBar',
    shape,
  }
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
