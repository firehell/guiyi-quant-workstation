import assert from 'node:assert/strict'
import test from 'node:test'
import { summarizeFormalEvent, summarizeMarketBackground } from '../src/utils/productCheck.ts'
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

test('formal event summary chooses the latest immutable Alert Event', () => {
  const latest = { ...event, id: 18, rule_code: 'htdy_original_15m', bar_end: '2026-08-21T03:00:00Z' }

  assert.deepEqual(summarizeFormalEvent([latest, event]), {
    event: latest,
    headline: '火天大有 · 买入观察',
  })
  assert.equal(summarizeFormalEvent([]), null)
})
