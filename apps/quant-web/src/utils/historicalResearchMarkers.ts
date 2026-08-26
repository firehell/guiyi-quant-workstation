import type {
  JdjStrategyHistoricalAction,
  KlineMarker,
  SubingStrategyAction,
  SubingStrategyEpisode,
} from '../types/market.ts'

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
      '日进斗金参考回放',
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

const SUBING_REASON_LABELS: Record<string, string> = {
  EMA21: 'EMA21 跌破',
  PREVIOUS_15M_EXTREME: '上一根 15m 极值突破',
  BOUND_PIVOT: '绑定 Pivot 突破',
  MACD_HIGH_DEAD_CROSS: 'MACD 高位死叉',
  MACD_LOW_GOLDEN_CROSS: 'MACD 低位金叉',
  CONTRACT_SEGMENT_END: '物理主力段末',
}

export function subingStrategyActionToMarker(
  action: SubingStrategyAction,
  episodeById: ReadonlyMap<string, SubingStrategyEpisode>,
): KlineMarker {
  const long = action.kind.endsWith('_long')
  const open = action.kind.startsWith('open_')
  const label = open
    ? long ? '▲ 建多' : '▼ 建空'
    : long ? '× 清多' : '× 清空'
  const episode = episodeById.get(action.episode_id)
  const referenceChange = episode?.reference_change_percent
    ?? episode?.current_reference_change_percent
  const reasons = action.reason_codes.map((reason) => SUBING_REASON_LABELS[reason] ?? reason)
  return {
    id: `historical:${action.action_id}`,
    time: action.effective_bar_end,
    label,
    tooltip: [
      'SuBing 历史因果投影',
      '模拟动作·非实际成交',
      `合约 ${action.contract}`,
      `决策 ${action.decision_at}`,
      `生效 ${action.effective_bar_end}`,
      `参考价 ${action.reference_price}`,
      ...(reasons.length ? [`原因 ${reasons.join('、')}`] : []),
      ...(referenceChange === null || referenceChange === undefined
        ? []
        : [`参考变动 ${referenceChange >= 0 ? '+' : ''}${referenceChange.toFixed(2)}%`]),
    ].join(' · '),
    tone: long ? 'up' : 'down',
    position: long ? 'belowBar' : 'aboveBar',
    shape: open ? long ? 'arrowUp' : 'arrowDown' : 'square',
  }
}
