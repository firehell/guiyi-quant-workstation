import assert from 'node:assert/strict'
import test from 'node:test'

import {
  confirmValidityLabel,
  formatConfirmEffectiveTime,
  type ConfirmCurrentSnapshot,
} from '../src/utils/subingConfirmFacts.ts'

const action = {
  action_id: 'subing-action:open',
  opportunity_id: 'subing-opportunity:open',
}

function current(overrides: Partial<ConfirmCurrentSnapshot> = {}): ConfirmCurrentSnapshot {
  return {
    pending_action: null,
    current_episode: null,
    latest_completed_episode: null,
    ...overrides,
  }
}

test('confirm validity matches pending, open, closed, then unmatched in order', () => {
  assert.equal(confirmValidityLabel(action, null), '当前状态不可用')
  assert.equal(confirmValidityLabel(action, current({
    pending_action: { opportunity_id: action.opportunity_id },
  })), '待下一根开盘生效')
  assert.equal(confirmValidityLabel(action, current({
    current_episode: { entry_action: { action_id: action.action_id } },
  })), '仍持仓')
  assert.equal(confirmValidityLabel(action, current({
    latest_completed_episode: { exit_action: { action_id: action.action_id } },
  })), '已平仓')
  assert.equal(confirmValidityLabel(action, current()), '已不是当前仓位')
})

test('pending match wins over an open episode on a different action', () => {
  assert.equal(confirmValidityLabel(action, current({
    pending_action: { opportunity_id: action.opportunity_id },
    current_episode: { entry_action: { action_id: 'subing-action:other' } },
  })), '待下一根开盘生效')
})

test('formats effective time in Shanghai as month/day hour:minute', () => {
  const label = formatConfirmEffectiveTime('2026-01-12T02:30:00Z')
  assert.match(label, /10:30/)
  assert.match(label, /生效$/)
  assert.equal(formatConfirmEffectiveTime('not-a-time'), 'not-a-time 生效')
})
