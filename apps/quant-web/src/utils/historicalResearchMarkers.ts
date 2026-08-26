import type {
  JdjStrategyHistoricalAction,
  KlineMarker,
  SubingStrategyAction,
  SubingStrategyEpisode,
} from '../types/market.ts'
import { subingStrategyExitReasonLabel } from './subingStrategyRecords.ts'

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
  const entry = episode?.entry_action ?? (open ? action : null)
  const referenceChange = episode?.reference_change_percent
    ?? episode?.current_reference_change_percent
  const reasons = action.reason_codes.map(subingStrategyExitReasonLabel)
  const context = entry?.direction_context_source_day
    && entry.direction_context_target_day
    ? `${entry.direction_context_source_day} → ${entry.direction_context_target_day}`
    : '不可用'
  const pivot = entry?.bound_reference_pivot
  const structureExit = pivot
    ? `${pivot.kind === 'low' ? '低点' : '高点'} Pivot ${pivot.price}`
    : '不可用'
  const fillBasis = action.fill_basis === 'segment_terminal_close'
    ? '旧段末最后一根 15m close'
    : '下一根同合约 15m open'
  return {
    id: `historical:${action.action_id}`,
    time: action.effective_bar_end,
    label,
    tooltip: [
      'SuBing Strategy V1 · 15m · 历史因果投影',
      '模拟动作·非实际成交',
      `合约 ${action.contract}`,
      `方向 Context ${context}`,
      `确认来源 ${entry?.confirmation_source ?? '不可用'}`,
      `Opportunity ${action.opportunity_id}`,
      `结构退出 ${structureExit}`,
      `持有 ${episode?.holding_bar_count ?? '—'} 根 15m Bar`,
      `生效口径 ${fillBasis}`,
      `决策 ${action.decision_at}`,
      `生效 ${action.effective_bar_end}`,
      `参考价 ${action.reference_price}`,
      ...(reasons.length ? [`原因 ${reasons.join('、')}`] : []),
      ...(referenceChange === null || referenceChange === undefined
        ? []
        : [`参考变动 ${referenceChange >= 0 ? '+' : ''}${referenceChange.toFixed(2)}%`]),
    ].join(' · '),
    tone: long ? 'up' : 'down',
    position: open
      ? long ? 'belowBar' : 'aboveBar'
      : long ? 'aboveBar' : 'belowBar',
    shape: open ? long ? 'arrowUp' : 'arrowDown' : 'square',
  }
}
