import type { SubingStrategyEpisode } from '../types/market.ts'


const EXIT_REASON_LABELS: Record<string, string> = {
  EMA21_BREACH_LONG: 'EMA21 跌破',
  EMA21_BREACH_SHORT: 'EMA21 突破',
  PREVIOUS_BAR_LOW_BREACH: '上一根 15m 低点跌破',
  PREVIOUS_BAR_HIGH_BREACH: '上一根 15m 高点突破',
  BOUND_LOW_PIVOT_BREACH: '绑定低点 Pivot 跌破',
  BOUND_HIGH_PIVOT_BREACH: '绑定高点 Pivot 突破',
  MACD_HIGH_DEAD_CROSS: 'MACD 高位死叉',
  MACD_LOW_GOLDEN_CROSS: 'MACD 低位金叉',
  CONTRACT_SEGMENT_END: '物理主力段末',
}

export function subingStrategyExitReasonLabel(reason: string): string {
  return EXIT_REASON_LABELS[reason] ?? reason
}

export interface SubingStrategyRecordRow {
  episodeId: string
  contract: string
  frequencyLabel: '15m'
  directionLabel: string
  stateLabel: string
  entryTime: string
  entryReferencePrice: string
  exitTime: string | null
  exitReferencePrice: string | null
  holdingBarCount: number
  referenceChangeLabel: string
  exitReasonLabels: string[]
  structureExitLabel: string
  disclaimer: '历史因果投影 · 模拟动作 · 非实际成交'
}

function signedPercent(value: string): string {
  const displayed = Number(value)
  return `${displayed >= 0 ? '+' : ''}${displayed.toFixed(2)}%`
}

export function buildSubingStrategyRecordRows(
  episodes: readonly SubingStrategyEpisode[],
): SubingStrategyRecordRow[] {
  return [...episodes]
    .sort((left, right) => Date.parse(right.entry_action.effective_bar_end)
      - Date.parse(left.entry_action.effective_bar_end))
    .map((episode) => {
      const long = episode.direction === 'long'
      const closed = episode.state === 'closed'
      const referenceChange = closed
        ? episode.reference_change_percent
        : episode.current_reference_change_percent
      return {
        episodeId: episode.episode_id,
        contract: episode.entry_action.contract,
        frequencyLabel: '15m',
        directionLabel: closed
          ? long ? '建多 → 清多' : '建空 → 清空'
          : long ? '建多' : '建空',
        stateLabel: closed ? '已清仓' : '持仓中',
        entryTime: episode.entry_action.effective_bar_end,
        entryReferencePrice: String(episode.entry_action.reference_price),
        exitTime: episode.exit_action?.effective_bar_end ?? null,
        exitReferencePrice: episode.exit_action === null
          ? null : String(episode.exit_action.reference_price),
        holdingBarCount: episode.holding_bar_count,
        referenceChangeLabel: referenceChange === null
          ? '参考变动 —'
          : `${closed ? '参考变动' : '当前参考变动'} ${signedPercent(referenceChange)}`,
        exitReasonLabels: episode.exit_reason_codes.map(subingStrategyExitReasonLabel),
        structureExitLabel: episode.structure_exit_available
          ? '绑定 Pivot 退出可用' : '无绑定 Pivot 退出',
        disclaimer: '历史因果投影 · 模拟动作 · 非实际成交',
      }
    })
}
