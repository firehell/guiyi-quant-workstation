import test from 'node:test'
import assert from 'node:assert/strict'
import { lifecycleSnapshotToMarkers } from '../src/utils/subingLifecycleMarkers.ts'
import {
  subingLifecycleProgressLabel,
  subingLifecycleStageLabel,
  type SubingLifecycleSnapshot,
} from '../src/types/market.ts'

const OPPORTUNITY_KEY = 'subing_lifecycle_v2_research_v1:JM:JM2609:2026-08-12:long:2026-08-13T02:00:00+00:00'
const SETUP_TRANSITION_ID = `${OPPORTUNITY_KEY}:2026-08-13T02:00:00+00:00:setup_armed`

function transitionId(transitionAt: string, toStage: SubingLifecycleSnapshot['stage']): string {
  return `${OPPORTUNITY_KEY}:${transitionAt.replace('Z', '+00:00')}:${toStage}`
}

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
    latest_transition: { transition_id: SETUP_TRANSITION_ID, transition_at: '2026-08-13T02:00:00Z', from_stage: 'idle', to_stage: 'setup_armed', reason_codes: ['DIRECTION_CONTEXT_ALIGNED'] },
    crossed_trading_day: false, boundary_reset: null, formal_v1_matched: false,
    ...overrides,
  }
}

test('maps current setup lifecycle facts to a neutral preparation marker', () => {
  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycle()), [{
    id: `lifecycle:${OPPORTUNITY_KEY}:transition:${SETUP_TRANSITION_ID}`, time: '2026-08-13T02:00:00Z', label: '准备',
    tooltip: 'SuBing 生命周期研究 · 准备', tone: 'neutral', position: 'belowBar', shape: 'circle',
  }])
})

test('uses the exact transition identity for repeated exit-risk transitions', () => {
  const first = lifecycleSnapshotToMarkers(lifecycle({
    stage: 'exit_risk', entry_progress: null, confirmation_source: 'formal_v1',
    confirmed_at: '2026-08-13T02:00:00Z', hold_count: 0,
    current_risk_codes: ['LOWER_TF_EMA21_BREACH'], lower_tf_risk_count: 2,
    latest_transition: { transition_id: transitionId('2026-08-13T02:15:00Z', 'exit_risk'), transition_at: '2026-08-13T02:15:00Z', from_stage: 'continuation', to_stage: 'exit_risk', reason_codes: ['LOWER_TF_EMA21_BREACH'] },
    last_confirmed_stage: 'exit_risk', last_confirmed_at: '2026-08-13T02:15:00Z',
  }))
  const second = lifecycleSnapshotToMarkers(lifecycle({
    stage: 'exit_risk', entry_progress: null, confirmation_source: 'formal_v1',
    confirmed_at: '2026-08-13T02:00:00Z', hold_count: 0,
    observed_at: '2026-08-13T02:25:00Z', anchor_bar_end: '2026-08-13T02:15:00Z',
    current_risk_codes: ['LOWER_TF_EMA21_BREACH'], lower_tf_risk_count: 2,
    latest_transition: { transition_id: transitionId('2026-08-13T02:25:00Z', 'exit_risk'), transition_at: '2026-08-13T02:25:00Z', from_stage: 'continuation', to_stage: 'exit_risk', reason_codes: ['LOWER_TF_EMA21_BREACH'] },
    last_confirmed_stage: 'exit_risk', last_confirmed_at: '2026-08-13T02:25:00Z',
  }))

  assert.equal(first.at(-1)?.id, `lifecycle:${OPPORTUNITY_KEY}:transition:${transitionId('2026-08-13T02:15:00Z', 'exit_risk')}`)
  assert.equal(first.at(-1)?.time, '2026-08-13T02:15:00Z')
  assert.equal(second.at(-1)?.id, `lifecycle:${OPPORTUNITY_KEY}:transition:${transitionId('2026-08-13T02:25:00Z', 'exit_risk')}`)
  assert.equal(second.at(-1)?.time, '2026-08-13T02:25:00Z')
})

test('does not emit a transition marker when latest transition does not reach the current stage', () => {
  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycle({
    latest_transition: { transition_id: transitionId('2026-08-13T02:10:00Z', 'entry_confirmed'), transition_at: '2026-08-13T02:10:00Z', from_stage: 'idle', to_stage: 'entry_confirmed', reason_codes: ['STALE'] },
  })), [])
})

test('does not invent a lifecycle marker when the current snapshot is unavailable', () => {
  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycle({
    availability: 'unavailable', unavailable_reason: 'SUBING_LIFECYCLE_INTRADAY_ONLY',
    observed_at: null, anchor_bar_end: null, direction: 'none', stage: 'idle', opportunity_key: null,
    entry_progress: null, last_confirmed_stage: 'idle', last_confirmed_at: null, latest_transition: null,
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
    latest_transition: { transition_id: transitionId('2026-08-13T02:15:00Z', 'entry_confirmed'), transition_at: '2026-08-13T02:15:00Z', from_stage: 'setup_armed', to_stage: 'entry_confirmed', reason_codes: ['FORMAL_V1_MATCHED'] },
    last_confirmed_stage: 'entry_confirmed', last_confirmed_at: '2026-08-13T02:15:00Z',
    formal_v1_matched: true,
  })), '已研究确认')
})

test('uses retest rebreak progress instead of the frozen breakout hold count', () => {
  const pivot = {
    pivot_id: 'JM2609:2026-08-12:5m:high:2026-08-13T01:45:00+00:00',
    kind: 'high' as const, timeframe: '5m' as const, pivot_time: '2026-08-13T01:45:00Z',
    confirmed_at: '2026-08-13T02:05:00Z', price: 104.5, contract: 'JM2609',
    segment_start_trading_day: '2026-08-12',
  }
  const retestBar = lifecycle({
    entry_progress: 'retest_confirming', trigger_kind: 'pivot_break', trigger_timeframe: '5m',
    triggered_at: '2026-08-13T02:10:00Z', hold_count: 1, bound_reference_pivot: pivot,
    rebreak_reference_price: 104.5, retest_at: '2026-08-13T02:15:00Z', retest_rebreak_count: 0,
    latest_transition: { transition_id: transitionId('2026-08-13T02:00:00Z', 'setup_armed'), transition_at: '2026-08-13T02:00:00Z', from_stage: 'idle', to_stage: 'setup_armed', reason_codes: ['DIRECTION_CONTEXT_ALIGNED'] },
  })
  const nextBar = lifecycle({
    ...retestBar, observed_at: '2026-08-13T02:20:00Z', last_confirmed_at: '2026-08-13T02:20:00Z',
    retest_rebreak_count: 1,
  })

  assert.equal(subingLifecycleProgressLabel(retestBar), '0/3')
  assert.equal(subingLifecycleProgressLabel(nextBar), '1/3')
})
