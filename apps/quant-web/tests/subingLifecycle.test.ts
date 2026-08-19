import test from 'node:test'
import assert from 'node:assert/strict'
import { lifecycleSnapshotToMarkers } from '../src/utils/subingLifecycleMarkers.ts'
import {
  subingLifecycleProgressLabel,
  subingLifecycleStageLabel,
  type SubingLifecycleSnapshot,
  type SubingResearchResponse,
} from '../src/types/market.ts'
import { cloneSubingLifecycleCase } from './fixtures/subingLifecycleCases.mjs'

function lifecycleCase(name: string): SubingLifecycleSnapshot {
  return (cloneSubingLifecycleCase(name) as SubingResearchResponse).lifecycle
}

test('maps a reducer-produced setup transition to a neutral preparation marker', () => {
  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycleCase('longSetup')), [{
    id: 'lifecycle:subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00:transition:subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:long:2026-01-12T01:30:00+00:00:2026-01-12T01:30:00+00:00:setup_armed',
    time: '2026-01-12T01:30:00Z', label: '准备',
    tooltip: 'SuBing 生命周期研究 · 准备', tone: 'neutral', position: 'belowBar', shape: 'circle',
  }])
})

test('uses exact reducer transition identity for repeated exit-risk transitions', () => {
  const first = lifecycleSnapshotToMarkers(lifecycleCase('shortExitRiskFirst')).at(-1)
  const second = lifecycleSnapshotToMarkers(lifecycleCase('shortExitRiskSecond')).at(-1)

  assert.equal(first?.id, 'lifecycle:subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:00:00+00:00:transition:subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:00:00+00:00:2026-01-12T02:10:00+00:00:exit_risk')
  assert.equal(first?.time, '2026-01-12T02:10:00Z')
  assert.equal(second?.id, 'lifecycle:subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:00:00+00:00:transition:subing_lifecycle_v2_research_v1:ag:AG2601:2026-01-12:short:2026-01-12T02:00:00+00:00:2026-01-12T02:25:00+00:00:exit_risk')
  assert.equal(second?.time, '2026-01-12T02:25:00Z')
})

test('does not emit a transition marker when latest transition does not reach the current stage', () => {
  const setup = lifecycleCase('longSetup')
  setup.latest_transition = {
    transition_id: `${setup.opportunity_key}:2026-01-12T01:35:00+00:00:entry_confirmed`,
    transition_at: '2026-01-12T01:35:00Z', from_stage: 'setup_armed', to_stage: 'entry_confirmed',
    reason_codes: ['FORMAL_V1_MATCHED'],
  }

  assert.deepEqual(lifecycleSnapshotToMarkers(setup), [])
})

test('does not invent a lifecycle marker when the API projects daily unavailable', () => {
  assert.deepEqual(lifecycleSnapshotToMarkers(lifecycleCase('dailyUnavailable')), [])
})

test('uses research stage labels with no instruction vocabulary', () => {
  const labels = ['idle', 'setup_armed', 'entry_confirmed', 'continuation', 'exit_risk', 'closed']
    .map((stage) => subingLifecycleStageLabel(stage as SubingLifecycleSnapshot['stage']))
  assert.deepEqual(labels, ['暂无机会', '准备中', '研究确认', '延续', '退出风险', '本轮结束'])
  assert.doesNotMatch(labels.join(' '), /买入|卖出|下单|加仓|平仓指令/i)
})

test('shows X/3 only for reducer-produced hold and retest progress', () => {
  assert.equal(subingLifecycleProgressLabel(lifecycleCase('longMomentumHold')), '1/3')
  assert.equal(subingLifecycleProgressLabel(lifecycleCase('longSetup')), '—')
  assert.equal(subingLifecycleProgressLabel(lifecycleCase('dailyUnavailable')), '—')
  assert.equal(subingLifecycleProgressLabel(lifecycleCase('formalDirectLong')), '已研究确认')
})

test('uses reducer retest count instead of the frozen breakout hold count', () => {
  const retestBar = lifecycleCase('pivotRetest0')
  const nextBar = lifecycleCase('pivotRetest1')

  assert.equal(retestBar.hold_count, 1)
  assert.equal(nextBar.hold_count, 1)
  assert.equal(subingLifecycleProgressLabel(retestBar), '0/3')
  assert.equal(subingLifecycleProgressLabel(nextBar), '1/3')
})
