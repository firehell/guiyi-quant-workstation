import assert from 'node:assert/strict'
import test from 'node:test'

import type { SubingStrategyEpisode } from '../src/types/market.ts'
import { buildSubingStrategyRecordRows } from '../src/utils/subingStrategyRecords.ts'


function episode(
  direction: 'long' | 'short',
  state: 'open' | 'closed',
): SubingStrategyEpisode {
  const openKind = direction === 'long' ? 'open_long' : 'open_short'
  const closeKind = direction === 'long' ? 'close_long' : 'close_short'
  const entry = {
    action_id: `subing-action:${direction}:entry`, episode_id: `subing-episode:${direction}`,
    strategy_id: 'subing_strategy_v1' as const,
    formula_version: 'subing_strategy_15m_v1' as const,
    kind: openKind, symbol: 'jm', contract: 'JM2609', trading_day: '2026-08-03',
    segment_start_trading_day: '2026-08-01', opportunity_id: 'subing-opportunity:one',
    decision_at: '2026-08-03T02:15:00Z', effective_bar_end: '2026-08-03T02:30:00Z',
    reference_price: '100.5', fill_basis: 'next_bar_open' as const,
    confirmation_source: 'formal_v1' as const, reason_codes: [],
    direction_context_source_day: '2026-07-31', direction_context_target_day: '2026-08-03',
    bound_reference_pivot: null,
  }
  const exit = {
    ...entry, action_id: `subing-action:${direction}:exit`, kind: closeKind,
    decision_at: '2026-08-07T02:15:00Z', effective_bar_end: '2026-08-07T02:30:00Z',
    reference_price: direction === 'long' ? '108.50985' : '92.49015',
    confirmation_source: null, reason_codes: [
      direction === 'long' ? 'EMA21_BREACH_LONG' : 'EMA21_BREACH_SHORT',
      direction === 'long' ? 'PREVIOUS_BAR_LOW_BREACH' : 'PREVIOUS_BAR_HIGH_BREACH',
      direction === 'long' ? 'BOUND_LOW_PIVOT_BREACH' : 'BOUND_HIGH_PIVOT_BREACH',
      direction === 'long' ? 'MACD_HIGH_DEAD_CROSS' : 'MACD_LOW_GOLDEN_CROSS',
      'CONTRACT_SEGMENT_END',
    ],
    direction_context_source_day: null, direction_context_target_day: null,
  }
  return {
    episode_id: entry.episode_id, direction, entry_action: entry,
    exit_action: state === 'closed' ? exit : null, state, holding_bar_count: 20,
    reference_change_percent: state === 'closed' ? '7.97' : null,
    current_reference_change_percent: state === 'open' ? '-1.25' : null,
    latest_reference_price: state === 'open' ? '101.75625' : null,
    exit_reason_codes: state === 'closed' ? [...exit.reason_codes] : [],
    structure_exit_available: false,
  }
}

test('formats a closed long Episode with reference change and every exit reason', () => {
  const [row] = buildSubingStrategyRecordRows([episode('long', 'closed')])

  assert.equal(row.directionLabel, '建多 → 清多')
  assert.equal(row.referenceChangeLabel, '参考变动 +7.97%')
  assert.deepEqual(row.exitReasonLabels, [
    'EMA21 跌破',
    '上一根 15m 低点跌破',
    '绑定低点 Pivot 跌破',
    'MACD 高位死叉',
    '物理主力段末',
  ])
  assert.equal(row.disclaimer, '历史因果投影 · 模拟动作 · 非实际成交')
})

test('formats an open short Episode as holding without completed-result language', () => {
  const [row] = buildSubingStrategyRecordRows([episode('short', 'open')])

  assert.equal(row.stateLabel, '持仓中')
  assert.match(row.referenceChangeLabel, /^当前参考变动 /)
  assert.doesNotMatch(row.referenceChangeLabel, /收益|盈亏/)
})

test('sorts records by entry effective time descending', () => {
  const older = episode('long', 'closed')
  const newer = episode('short', 'open')
  newer.entry_action.effective_bar_end = '2026-08-08T02:30:00Z'

  assert.deepEqual(
    buildSubingStrategyRecordRows([older, newer]).map((row) => row.episodeId),
    [newer.episode_id, older.episode_id],
  )
})
