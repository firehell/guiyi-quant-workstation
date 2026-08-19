import test from 'node:test'
import assert from 'node:assert/strict'
import { lifecycleSnapshotToMarkers } from '../src/utils/subingLifecycleMarkers.ts'
import { subingLifecycleStageLabel, type SubingLifecycleSnapshot } from '../src/types/market.ts'

function lifecycle(overrides: Partial<SubingLifecycleSnapshot> = {}): SubingLifecycleSnapshot {
  return {
    formula_version: 'subing_lifecycle_v2', policy_id: 'subing_lifecycle_v2_research_v1', research_only: true,
    observed_at: '2026-08-13T02:15:00Z', anchor_bar_end: '2026-08-13T02:15:00Z',
    availability: 'ready', unavailable_reason: null, direction: 'long', stage: 'setup_armed', opportunity_key: 'key',
    entry_progress: 'waiting_trigger', trigger_kind: null, trigger_timeframe: null, triggered_at: null,
    confirmation_source: null, confirmed_at: null, hold_count: 0, hold_required: 3,
    bound_reference_pivot: null, rebreak_reference_price: null, retest_at: null, retest_rebreak_count: 0,
    volume_ratio_prev: null, open_interest_delta: null, current_risk_codes: [], risk_progress: null,
    lower_tf_risk_count: 0, last_confirmed_stage: 'idle', last_confirmed_at: null,
    latest_transition: { transition_id: 'transition:setup', transition_at: '2026-08-13T02:15:00Z', from_stage: 'idle', to_stage: 'setup_armed', reason_codes: ['DIRECTION_CONTEXT'] },
    crossed_trading_day: false, boundary_reset: null, formal_v1_matched: false,
    ...overrides,
  }
}

test('maps current setup lifecycle facts to a neutral preparation marker', () => {
  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycle()), [{
    id: 'lifecycle:key:setup', time: '2026-08-13T02:15:00Z', label: '准备',
    tooltip: 'SuBing 生命周期研究 · 准备', tone: 'neutral', position: 'belowBar', shape: 'circle',
  }])
})

test('does not invent a lifecycle marker when the current snapshot is unavailable', () => {
  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycle({
    availability: 'unavailable', unavailable_reason: 'SUBING_LIFECYCLE_INTRADAY_ONLY',
  })), [])
})

test('uses research stage labels with no instruction vocabulary', () => {
  const labels = ['idle', 'setup_armed', 'entry_confirmed', 'continuation', 'exit_risk', 'closed']
    .map((stage) => subingLifecycleStageLabel(stage as SubingLifecycleSnapshot['stage']))
  assert.deepEqual(labels, ['暂无机会', '准备中', '研究确认', '延续', '退出风险', '本轮结束'])
  assert.doesNotMatch(labels.join(' '), /买入|卖出|下单|加仓|平仓指令/i)
})
