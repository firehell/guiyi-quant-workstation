import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'
import { projectNewowDailyQuote, useNewowDailyQuote } from '../src/composables/useNewowDailyQuote.ts'
const bar = (day, close) => ({ bar_end: `${day}T07:00:00Z`, trading_day: day, open: 99, high: 110, low: 90, close, volume: 1, turnover: null, open_interest: null })
const page = () => ({ request: { series_kind: 'actual_dominant', symbol: 'rb', frequency: '1d', limit: 2, before: null, contract: null }, bars: [bar('2026-09-02', 100), bar('2026-09-03', 105)], canonical_coverage: { start: '2026-09-02', end: '2026-09-03' }, page: { has_more_before: true, next_before: 'cursor' }, resolved_contract_segments: [{contract:'RB2605',start_trading_day:'2026-01-01',end_trading_day:'2026-12-31'}] })
test('bounded daily quote validates request, prices, order, coverage and unique ownership', () => {
  assert.equal(projectNewowDailyQuote(page(), 'rb', 'RB2605').pct, 5)
  for (const mutate of [p => p.request.frequency = '60m', p => p.request.limit = 3, p => p.bars.reverse(), p => p.bars[0].close = NaN, p => p.canonical_coverage.end = '2026-09-02', p => p.resolved_contract_segments.push({...p.resolved_contract_segments[0]})]) {
    const p = page(); mutate(p); assert.throws(() => projectNewowDailyQuote(p, 'rb', 'RB2605'))
  }
  assert.throws(() => projectNewowDailyQuote(page(), 'rb', 'RB2610'))
})
test('rollover keeps latest close but never computes a cross-contract change', () => {
  const p = page(); p.resolved_contract_segments = [{contract:'RB2601',start_trading_day:'2026-09-02',end_trading_day:'2026-09-02'}, {contract:'RB2605',start_trading_day:'2026-09-03',end_trading_day:'2026-09-03'}]
  assert.equal(projectNewowDailyQuote(p, 'rb', 'RB2605').pct, null)
})
test('product switch cancels pending quote and rejects late response; same product does not refetch', async () => {
  const symbol = ref('rb'); const contract = ref('RB2605'); const pending = []
  const q = useNewowDailyQuote({ symbol, contract, fetchPage: (request, signal) => new Promise(resolve => pending.push({request, signal, resolve})) })
  assert.equal(pending.length, 1)
  symbol.value = 'ag'; contract.value = 'AG2612'; await nextTick()
  assert.equal(pending[0].signal.aborted, true)
  pending[0].resolve(page()); await nextTick(); await nextTick()
  assert.equal(q.quote.value, null)
  symbol.value = 'ag'; await nextTick(); assert.equal(pending.length, 2)
  q.dispose(); assert.equal(pending[1].signal.aborted, true)
})
test('D1 timestamps must agree with Shanghai trading day and exact timestamp coverage', () => {
  const future = page(); future.bars[1].bar_end = '2099-09-03T07:00:00Z'
  assert.throws(() => projectNewowDailyQuote(future, 'rb', 'RB2605'))
  const outside = page(); outside.canonical_coverage = { start: '2026-09-02T07:00:00Z', end: '2026-09-03T06:59:00Z' }
  assert.throws(() => projectNewowDailyQuote(outside, 'rb', 'RB2605'))
  const valid = page(); valid.bars[1].bar_end = '2026-09-03T15:00:00+08:00'; valid.canonical_coverage = { start: '2026-09-02T07:00:00Z', end: '2026-09-03T07:00:00Z' }
  assert.equal(projectNewowDailyQuote(valid, 'rb', 'RB2605').close, 105)
  valid.bars[1].bar_end = '2026-09-03T15:15:00+08:00'; valid.canonical_coverage.end = '2026-09-03T07:15:00Z'
  assert.equal(projectNewowDailyQuote(valid, 'rb', 'RB2605').close, 105)
  const ambiguous = page(); ambiguous.bars[1].bar_end = '2026-09-03T15:00:00'
  assert.throws(() => projectNewowDailyQuote(ambiguous, 'rb', 'RB2605'))
})
