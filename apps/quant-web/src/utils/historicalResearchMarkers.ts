import type {
  KlineMarker,
  SubingStrategyAction,
  SubingStrategyEpisode,
} from '../types/market.ts'
import { subingStrategyExitReasonLabel } from './subingStrategyRecords.ts'

export function formatSubingMarkerPrice(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return trimmed
  const numeric = Number(trimmed)
  if (!Number.isFinite(numeric)) return trimmed
  if (Number.isInteger(numeric)) return String(numeric)
  return trimmed
    .replace(/(\.\d*?[1-9])0+$/, '$1')
    .replace(/\.0+$/, '')
}

export function formatSubingMarkerPercent(value: string): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return value
  return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(2)}%`
}

export function subingStrategyResultTone(
  percent: string | null | undefined,
): 'profit' | 'loss' | null {
  if (percent === null || percent === undefined || percent === '') return null
  const numeric = Number(percent)
  if (!Number.isFinite(numeric)) return null
  return numeric >= 0 ? 'profit' : 'loss'
}

export function subingStrategyActionToMarker(
  action: SubingStrategyAction,
  episodeById: ReadonlyMap<string, SubingStrategyEpisode>,
): KlineMarker {
  const long = action.kind.endsWith('_long')
  const open = action.kind.startsWith('open_')
  const episode = episodeById.get(action.episode_id)
  const entry = episode?.entry_action ?? (open ? action : null)
  const price = formatSubingMarkerPrice(action.reference_price)
  const percentRaw = open ? null : episode?.reference_change_percent ?? null
  const percentLabel = percentRaw === null || percentRaw === undefined
    ? null
    : formatSubingMarkerPercent(percentRaw)
  const kindLabel = open
    ? long ? '建多' : '建空'
    : long ? '清多' : '清空'
  const label = open
    ? `${kindLabel} ${price}`
    : percentLabel
      ? `${kindLabel} ${price}(${percentLabel})`
      : `${kindLabel} ${price}`
  const resultTone = open ? null : subingStrategyResultTone(percentRaw)
  const reasons = action.reason_codes.map(subingStrategyExitReasonLabel)
  const context = entry?.direction_context_source_day
    && entry.direction_context_target_day
    ? `${entry.direction_context_source_day} → ${entry.direction_context_target_day}`
    : '不可用'
  const pivot = entry?.bound_reference_pivot
  const structureExit = pivot
    ? `${pivot.kind === 'low' ? '低点' : '高点'} Pivot ${pivot.price}`
    : '不可用'
  const fillBasisLabel = (fillBasis: SubingStrategyAction['fill_basis']) => (
    fillBasis === 'segment_terminal_close'
      ? '旧段末最后一根 15m close'
      : '下一根同合约 15m open'
  )
  const actionFacts = open
    ? [
        `生效口径 ${fillBasisLabel(action.fill_basis)}`,
        `决策 ${action.decision_at}`,
        `生效 ${action.effective_bar_end}`,
        `参考价 ${action.reference_price}`,
      ]
    : [
        ...(entry
          ? [
              `入场决策 ${entry.decision_at}`,
              `入场生效 ${entry.effective_bar_end}`,
              `入场参考价 ${entry.reference_price}`,
              `入场生效口径 ${fillBasisLabel(entry.fill_basis)}`,
            ]
          : ['入场事实 不可用']),
        `平仓决策 ${action.decision_at}`,
        `平仓生效 ${action.effective_bar_end}`,
        `平仓参考价 ${action.reference_price}`,
        `平仓生效口径 ${fillBasisLabel(action.fill_basis)}`,
        `持有 ${episode?.holding_bar_count ?? '—'} 根 15m Bar`,
        ...(reasons.length ? [`原因 ${reasons.join('、')}`] : []),
        ...(episode?.reference_change_percent === null
          || episode?.reference_change_percent === undefined
          ? []
          : [
              `参考变动 ${Number(episode.reference_change_percent) >= 0 ? '+' : ''}`
                + `${Number(episode.reference_change_percent).toFixed(2)}%`,
            ]),
      ]
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
      ...actionFacts,
    ].join(' · '),
    tone: long ? 'up' : 'down',
    resultTone,
    position: open
      ? long ? 'belowBar' : 'aboveBar'
      : long ? 'aboveBar' : 'belowBar',
    shape: open ? long ? 'arrowUp' : 'arrowDown' : 'square',
  }
}
