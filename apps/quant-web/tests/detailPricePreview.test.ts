import assert from 'node:assert/strict'
import test from 'node:test'
import { validateDetailPrice } from '../src/utils/detailPricePreview.ts'

const query = { symbol: 'jm', series_kind: 'actual_dominant', frequency: '1d', limit: 500 } as const
const page = () => ({
  request: { ...query, contract: null, before: null },
  bars: [{ bar_end: '2026-10-15T07:00:00Z', trading_day: '2026-10-15', open: 100, high: 110, low: 90, close: 105, volume: 10, turnover: null, open_interest: null }],
  canonical_coverage: { start: '2026-10-15T07:00:00Z', end: '2026-10-15T07:00:00Z' },
  page: { has_more_before: false, next_before: null },
  resolved_contract_segments: [{ contract: 'JM2701', start_trading_day: '2026-10-15', end_trading_day: '2026-10-15' }],
})
test('preview accepts normalized stored prices while rejecting corruption and another owner', () => {
  assert.deepEqual(validateDetailPrice(page(), query), page())
  for (const mutate of [
    value => { value.request.symbol = 'rb' },
    value => { value.request.frequency = '60m' },
    value => { value.request.before = '2026-10-14T07:00:00Z' },
    value => { value.bars[0].close = Infinity },
    value => { value.bars[0].bar_end = 'broken' },
    value => { value.bars.push(value.bars[0]) },
    value => { value.resolved_contract_segments = [] },
  ]) {
    const corrupt = page(); mutate(corrupt)
    assert.throws(() => validateDetailPrice(corrupt, query))
  }
})
