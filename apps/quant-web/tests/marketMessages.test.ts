import assert from 'node:assert/strict'
import test from 'node:test'
import { useMarketMessages } from '../src/composables/useMarketMessages.ts'
import { normalizeAlertHistoryResponse } from '../src/utils/alertHistory.ts'

const event = (id: number, rule = 'htdy_original_15m') => ({
  id, rule_code: rule, symbol: 'ag', contract: 'AG2612', trading_day: '2026-09-13', frequency: '15m',
  bar_end: `2026-09-13T02:4${id}:00Z`, result_codes: ['buy'], detected_at: `2026-09-13T02:45:0${id}Z`, notification_attempted_at: null,
})

test('normalizes a bounded history page without inventing a total or delivery status', () => {
  const value = normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-07', end_day: '2026-09-13', symbol: null, rule_code: null, items: [event(1)], next_before: 'opaque' })
  assert.equal(value.items[0].id, 1)
  assert.equal(value.next_before, 'opaque')
  assert.equal('total' in value, false)
  assert.equal('delivered' in value.items[0], false)
})

test('rejects malformed history filters and cursors', () => {
  assert.throws(() => normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-14', end_day: '2026-09-13', symbol: null, rule_code: null, items: [], next_before: null }))
  assert.throws(() => normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-07', end_day: '2026-09-13', symbol: null, rule_code: null, items: [], next_before: '' }))
})

test('query changes abort and prevent an old message page from overwriting the new filter', async () => {
  const pending: Array<{ signal: AbortSignal; resolve: (value: ReturnType<typeof normalizeAlertHistoryResponse>) => void }> = []
  const messages = useMarketMessages({ fetchHistory: (_query, signal) => new Promise((resolve) => pending.push({ signal, resolve })) })
  const oldLoad = messages.load({ startDay: '2026-09-07', endDay: '2026-09-13', symbol: '', ruleCode: null })
  const newLoad = messages.load({ startDay: '2026-09-07', endDay: '2026-09-13', symbol: 'jm', ruleCode: null })
  assert.equal(pending[0].signal.aborted, true)
  pending[1].resolve(normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-07', end_day: '2026-09-13', symbol: 'jm', rule_code: null, items: [{ ...event(2), symbol: 'jm', contract: 'JM2609' }], next_before: null }))
  await newLoad
  pending[0].resolve(normalizeAlertHistoryResponse({ status: 'ready', start_day: '2026-09-07', end_day: '2026-09-13', symbol: null, rule_code: null, items: [event(1)], next_before: null }))
  await oldLoad
  assert.deepEqual(messages.items.value.map((item) => item.id), [2])
})

test('loads cursor pages once and appends immutable event identities', async () => {
  const calls: Array<string | null> = []
  const messages = useMarketMessages({ fetchHistory: async (query) => {
    calls.push(query.before ?? null)
    return normalizeAlertHistoryResponse({ status: 'ready', start_day: query.startDay, end_day: query.endDay, symbol: null, rule_code: null, items: [event(query.before ? 2 : 1)], next_before: query.before ? null : 'page-2' })
  } })
  const query = { startDay: '2026-09-07', endDay: '2026-09-13', symbol: '', ruleCode: null } as const
  await messages.load(query)
  await Promise.all([messages.loadMore(), messages.loadMore()])
  assert.deepEqual(calls, [null, 'page-2'])
  assert.deepEqual(messages.items.value.map((item) => item.id), [1, 2])
})
