import assert from 'node:assert/strict'
import test from 'node:test'
import { summarizeFormalEvent, summarizeMarketBackground } from '../src/utils/productCheck.ts'
import type { EventState } from '../src/types/executionReview.ts'
import type { AlertEvent } from '../src/types/market.ts'

const event: AlertEvent = {
  id: 17,
  rule_code: 'subing_entry_signal_v1',
  symbol: 'ag',
  contract: 'AG2601',
  trading_day: '2026-08-21',
  frequency: '15m',
  bar_end: '2026-08-21T02:30:00Z',
  result_codes: ['buy'],
  lower_tf_confirmation: true,
  detected_at: '2026-08-21T02:31:00Z',
  notification_attempted_at: null,
}

test('market background keeps aligned and conflict semantics explicit', () => {
  assert.deepEqual(summarizeMarketBackground('up', 'up'), { label: '同向偏多', tone: 'up' })
  assert.deepEqual(summarizeMarketBackground('down', 'down'), { label: '同向偏空', tone: 'down' })
  assert.deepEqual(summarizeMarketBackground('neutral', 'neutral'), { label: '中性', tone: 'neutral' })
  assert.deepEqual(summarizeMarketBackground('up', 'neutral'), { label: '未共振', tone: 'warning' })
  assert.deepEqual(summarizeMarketBackground('unavailable', 'up'), { label: '数据不足', tone: 'warning' })
})

test('formal event summary uses EventState and never invents one', () => {
  assert.equal(summarizeFormalEvent([event], {})?.actionLabel, null)
  assert.equal(summarizeFormalEvent([event], {
    17: { event_id: 17, state: 'pending_decision', decision_id: null, episode_id: null },
  })?.actionLabel, '记录执行')
})

test('formal event summary chooses the latest recorded event and preserves its state', () => {
  const latest = { ...event, id: 18, rule_code: 'htdy_original_15m', bar_end: '2026-08-21T03:00:00Z' }
  const latestState: EventState = {
    event_id: 18,
    state: 'done',
    decision_id: 23,
    episode_id: null,
  }

  assert.deepEqual(summarizeFormalEvent([latest, event], { 18: latestState }), {
    event: latest,
    state: latestState,
    headline: '火天大有 · 买入观察',
    actionLabel: '查看记录',
  })
  assert.equal(summarizeFormalEvent([], {}), null)
})
