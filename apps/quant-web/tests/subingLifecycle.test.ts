import test from 'node:test'
import assert from 'node:assert/strict'
import { lifecycleSnapshotToMarkers } from '../src/utils/subingLifecycleMarkers.ts'
import {
  subingLifecycleProgressLabel,
  subingLifecycleStageLabel,
  type SubingLifecycleSnapshot,
} from '../src/types/market.ts'

const OPPORTUNITY_KEY = 'subing_lifecycle_v2_research_v1:JM:JM2609:2026-08-12:long:2026-08-13T02:00:00+00:00'

function lifecycle(overrides: Partial<SubingLifecycleSnapshot> = {}): SubingLifecycleSnapshot {
  return {
    formula_version: 'subing_lifecycle_v2', policy_id: 'subing_lifecycle_v2_research_v1', research_only: true,
    observed_at: '2026-08-13T02:15:00Z', anchor_bar_end: '2026-08-13T02:15:00Z',
    availability: 'ready', unavailable_reason: null, direction: 'long', stage: 'setup_armed', opportunity_key: OPPORTUNITY_KEY,
    entry_progress: 'waiting_trigger', trigger_kind: null, trigger_timeframe: null, triggered_at: null,
    confirmation_source: null, confirmed_at: null, hold_count: 0, hold_required: 3,
    bound_reference_pivot: null, rebreak_reference_price: null, retest_at: null, retest_rebreak_count: 0,
    volume_ratio_prev: null, open_interest_delta: null, current_risk_codes: [], risk_progress: null,
    lower_tf_risk_count: 0, last_confirmed_stage: 'setup_armed', last_confirmed_at: '2026-08-13T02:15:00Z',
    latest_transition: { transition_id: 'transition:setup', transition_at: '2026-08-13T02:15:00Z', from_stage: 'idle', to_stage: 'setup_armed', reason_codes: ['DIRECTION_CONTEXT'] },
    crossed_trading_day: false, boundary_reset: null, formal_v1_matched: false,
    ...overrides,
  }
}

test('maps current setup lifecycle facts to a neutral preparation marker', () => {
  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycle()), [{
    id: `lifecycle:${OPPORTUNITY_KEY}:transition:transition:setup`, time: '2026-08-13T02:15:00Z', label: '准备',
    tooltip: 'SuBing 生命周期研究 · 准备', tone: 'neutral', position: 'belowBar', shape: 'circle',
  }])
})

test('uses the exact transition identity for repeated exit-risk transitions', () => {
  const first = lifecycleSnapshotToMarkers(lifecycle({
    stage: 'exit_risk', entry_progress: null, confirmation_source: 'momentum_hold',
    confirmed_at: '2026-08-13T02:10:00Z', hold_count: 3, trigger_kind: 'macd_cross',
    trigger_timeframe: '5m', triggered_at: '2026-08-13T02:05:00Z',
    current_risk_codes: ['LOWER_TF_EMA21_BREACH'], lower_tf_risk_count: 2,
    latest_transition: { transition_id: 'risk:first', transition_at: '2026-08-13T02:15:00Z', from_stage: 'continuation', to_stage: 'exit_risk', reason_codes: ['LOWER_TF_EMA21_BREACH'] },
    last_confirmed_stage: 'exit_risk', last_confirmed_at: '2026-08-13T02:15:00Z',
  }))
  const second = lifecycleSnapshotToMarkers(lifecycle({
    stage: 'exit_risk', entry_progress: null, confirmation_source: 'momentum_hold',
    confirmed_at: '2026-08-13T02:10:00Z', hold_count: 3, trigger_kind: 'macd_cross',
    trigger_timeframe: '5m', triggered_at: '2026-08-13T02:05:00Z',
    observed_at: '2026-08-13T02:25:00Z', anchor_bar_end: '2026-08-13T02:15:00Z',
    current_risk_codes: ['LOWER_TF_EMA21_BREACH'], lower_tf_risk_count: 2,
    latest_transition: { transition_id: 'risk:second', transition_at: '2026-08-13T02:25:00Z', from_stage: 'continuation', to_stage: 'exit_risk', reason_codes: ['LOWER_TF_EMA21_BREACH'] },
    last_confirmed_stage: 'exit_risk', last_confirmed_at: '2026-08-13T02:25:00Z',
  }))

  assert.equal(first.at(-1)?.id, `lifecycle:${OPPORTUNITY_KEY}:transition:risk:first`)
  assert.equal(first.at(-1)?.time, '2026-08-13T02:15:00Z')
  assert.equal(second.at(-1)?.id, `lifecycle:${OPPORTUNITY_KEY}:transition:risk:second`)
  assert.equal(second.at(-1)?.time, '2026-08-13T02:25:00Z')
})

test('does not emit a transition marker when latest transition does not reach the current stage', () => {
  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycle({
    latest_transition: { transition_id: 'stale', transition_at: '2026-08-13T02:10:00Z', from_stage: 'idle', to_stage: 'entry_confirmed', reason_codes: ['STALE'] },
  })), [])
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

test('shows X/3 only while hold or retest confirmation is in progress', () => {
  assert.equal(subingLifecycleProgressLabel(lifecycle({
    entry_progress: 'hold_confirming', trigger_kind: 'macd_cross', trigger_timeframe: '5m',
    triggered_at: '2026-08-13T02:10:00Z', hold_count: 1,
  })), '1/3')
  assert.equal(subingLifecycleProgressLabel(lifecycle({ entry_progress: 'waiting_trigger' })), '—')
  assert.equal(subingLifecycleProgressLabel(lifecycle({
    direction: 'none', stage: 'idle', opportunity_key: null, entry_progress: null,
    last_confirmed_stage: 'idle', latest_transition: null,
  })), '—')
  assert.equal(subingLifecycleProgressLabel(lifecycle({
    stage: 'entry_confirmed', entry_progress: null, confirmation_source: 'formal_v1',
    confirmed_at: '2026-08-13T02:15:00Z',
    latest_transition: { transition_id: 'transition:direct-formal', transition_at: '2026-08-13T02:15:00Z', from_stage: 'idle', to_stage: 'entry_confirmed', reason_codes: ['FORMAL_V1'] },
    last_confirmed_stage: 'entry_confirmed', last_confirmed_at: '2026-08-13T02:15:00Z',
  })), '已研究确认')
})
