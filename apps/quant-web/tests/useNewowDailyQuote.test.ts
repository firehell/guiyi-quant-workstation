import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, ref } from 'vue'
import { projectNewowDailyQuote, useNewowDailyQuote } from '../src/composables/useNewowDailyQuote.ts'
import { normalizeMarketBarsPageResponse } from '../src/api/marketWire.ts'
const bar = (day, close) => ({ bar_end: `${day}T07:00:00Z`, trading_day: day, open: 99, high: 110, low: 90, close, volume: 1, turnover: null, open_interest: null })
const page = () => ({ request: { series_kind: 'actual_dominant', symbol: 'rb', frequency: '1d', limit: 2, before: null, contract: null }, bars: [bar('2026-09-02', 100), bar('2026-09-03', 105)], canonical_coverage: { start: '2026-09-02', end: '2026-09-03' }, page: { has_more_before: true, next_before: 'cursor' }, resolved_contract_segments: [{contract:'RB2605',start_trading_day:'2026-01-01',end_trading_day:'2026-12-31'}] })
test('bounded daily quote validates request, prices, order, coverage and unique ownership', () => {
  assert.equal(projectNewowDailyQuote(page(), 'rb', 'RB2605').pct, 5)
  for (const mutate of [p => p.request.frequency = '60m', p => p.request.limit = 3, p => p.bars.reverse(), p => p.bars[0].close = NaN, p => p.bars[0].close = 0, p => p.canonical_coverage.end = '2026-09-02', p => p.resolved_contract_segments.push({...p.resolved_contract_segments[0]})]) {
    const p = page(); mutate(p); assert.throws(() => projectNewowDailyQuote(p, 'rb', 'RB2605'))
  }
  assert.throws(() => projectNewowDailyQuote(page(), 'rb', 'RB2610'))
})

test('candidate quote preserves and validates the trusted exclusive cutoff after Decimal wire parsing', () => {
  const p = page()
  p.request.before = '2026-09-03T08:00:00+00:00'
  const wire = { ...p, bars: p.bars.map(value => ({ ...value, open: String(value.open), high: String(value.high), low: String(value.low), close: String(value.close), volume: String(value.volume) })) }
  const normalized = normalizeMarketBarsPageResponse(wire)
  assert.equal(projectNewowDailyQuote(normalized, 'rb', 'RB2605', '2026-09-03T16:00:00.000+08:00').close, 105)
  assert.equal(normalized.request.before, p.request.before)
})

test('candidate quote rejects mismatching, missing or ambiguous echoes and invalid trusted cutoffs', () => {
  const cutoff = '2026-09-03T08:00:00.000Z'
  for (const before of [null, '2026-09-03T08:00:01Z', '2026-09-03T07:59:59Z', '2026-09-03T08:00:00.000001Z', '2026-09-03T08:00:00', 'bad']) {
    const p = page(); p.request.before = before
    assert.throws(() => projectNewowDailyQuote(p, 'rb', 'RB2605', cutoff), /NEWOW_DAILY_QUOTE_INVALID/)
  }
  for (const expected of ['bad', '', '2026-09-03T08:00:00', '2026-02-30T08:00:00Z']) {
    const p = page(); p.request.before = expected
    assert.throws(() => projectNewowDailyQuote(p, 'rb', 'RB2605', expected), /NEWOW_DAILY_QUOTE_INVALID/)
  }
})

test('candidate quote enforces exclusive before even when future bars have valid coverage and owner', () => {
  for (const end of ['2026-09-03T08:00:00Z', '2026-09-03T08:00:00.000001Z', '2026-09-03T08:00:01Z']) {
    const p = page(); p.request.before = '2026-09-03T08:00:00Z'; p.bars[1].bar_end = end
    assert.throws(() => projectNewowDailyQuote(p, 'rb', 'RB2605', p.request.before), /NEWOW_DAILY_QUOTE_INVALID/)
  }
  const p = page(); p.request.before = '2026-09-03T08:00:00Z'; p.bars[1].bar_end = '2026-09-03T07:59:59.999999Z'
  assert.equal(projectNewowDailyQuote(p, 'rb', 'RB2605', p.request.before).close, 105)
})

test('normal quote retains null echo contract and unbounded fetch', async () => {
  const p = page(); p.request.before = '2026-09-03T08:00:00Z'
  assert.throws(() => projectNewowDailyQuote(p, 'rb', 'RB2605'), /NEWOW_DAILY_QUOTE_INVALID/)
  let requested
  const q = useNewowDailyQuote({ symbol: ref('rb'), contract: ref('RB2605'), fetchPage: async request => { requested = request; return page() } })
  await nextTick(); await nextTick()
  assert.equal(requested.before, undefined)
  assert.equal(q.quote.value?.close, 105)
  q.dispose()
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
test('explicit same-product refresh retries an unavailable daily quote', async () => {
  const symbol = ref('rb'); const contract = ref('RB2605'); const pending = []
  const q = useNewowDailyQuote({ symbol, contract, fetchPage: (request, signal) => new Promise((resolve, reject) => pending.push({request, signal, resolve, reject})) })
  pending[0].reject(new Error('fixture unavailable')); await nextTick(); await nextTick()
  assert.equal(q.quote.value, null)
  assert.equal(typeof (q as typeof q & { refresh?: () => void }).refresh, 'function')
  ;(q as typeof q & { refresh: () => void }).refresh()
  assert.equal(pending.length, 2)
  pending[1].resolve(page()); await nextTick(); await nextTick()
  assert.equal(q.quote.value?.close, 105)
  q.dispose()
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
