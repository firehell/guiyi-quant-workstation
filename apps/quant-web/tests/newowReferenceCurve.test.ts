import assert from 'node:assert/strict'
import test from 'node:test'
import { newowReferenceCurve, newowReferenceAnnualized } from '../src/utils/newowReferenceCurve.ts'
import { buildNewowFixtureEnvelopeForTest } from '../e2e/newow-product.helpers.mjs'
import type { NewowReferenceValue } from '../src/types/newowProduct.ts'
function value(): NewowReferenceValue { return buildNewowFixtureEnvelopeForTest('reference').reference.value }
test('closed-only cumulative uses exact decimal sums and chronological stable identities', () => {
  const v = value()
  const trade = v.items.find(t => t.status === 'CLOSED')!
  const items = [
    { ...trade, reference_trade_id: 'b', exit_bar_end: '2026-09-03T07:00:00Z', reference_return_pct: '-0.20' },
    { ...trade, reference_trade_id: 'a', exit_bar_end: '2026-09-02T07:00:00Z', reference_return_pct: '0.30' },
    { ...trade, reference_trade_id: 'open', status: 'OPEN' as const, reference_return_pct: null, mark_change_pct: '20' },
    { ...trade, reference_trade_id: 'roll', status: 'ROLLOVER_INTERRUPTED' as const, reference_return_pct: null, mark_change_pct: '40' },
  ]
  const input = { ...v, next_before: null, items, summary: { ...v.summary, closed_count: 2, sum_return_percentage_points: '0.1' } }
  const result = newowReferenceCurve(input)
  assert.equal(result.message, null)
  assert.deepEqual(result.points.map(p => p.cumulative), ['0.30', '0.10'])
  assert.deepEqual(newowReferenceCurve({ ...input, items: [...items].reverse() }).points, result.points)
  assert.equal(newowReferenceCurve({ ...input, next_before: 'cursor' }).points.length, 0)
  const independent = { ...input, items: [], next_before: 'cursor', curve_trades: items.filter(t => t.status === 'CLOSED') }
  assert.deepEqual(newowReferenceCurve(independent).points, result.points, 'complete curve is independent of list pagination')
  assert.equal(newowReferenceCurve({ ...independent, curve_trades: independent.curve_trades.slice(0, 1) }).points.length, 0)
  assert.equal(newowReferenceCurve({ ...input, summary: { ...input.summary, sum_return_percentage_points: '99' } }).points.length, 0)
  const rounded = { ...input, items: items.filter(t => t.status === 'CLOSED').map(t => ({ ...t, reference_return_pct: '1.123456789012345678901234567' })), summary: { ...input.summary, sum_return_percentage_points: '2.246913578024691357802469134' } }
  assert.equal(newowReferenceCurve(rounded).message, null)
  assert.equal(newowReferenceCurve({ ...rounded, summary: { ...rounded.summary, sum_return_percentage_points: '2.24691357802469135780246914' } }).points.length, 0)
})
test('empty, initial and missing returns never synthesize zero returns', () => {
  const v = value()
  assert.equal(newowReferenceCurve({ ...v, items: [], summary: { ...v.summary, closed_count: 0 } }).points.length, 0)
  const trade = v.items.find(t => t.status === 'CLOSED')!
  assert.equal(newowReferenceCurve({ ...v, next_before: null, items: [{ ...trade, reference_return_pct: null }] }).points.length, 0)
  assert.equal(newowReferenceCurve({ ...v, next_before: null, items: [{ ...trade, statistics_membership: 'initial_before_window' }] }).points.length, 0)
})

test('page reference annualization uses the accepted window and excludes incomplete facts', () => {
  const v = value()
  const trade = v.items.find(t => t.status === 'CLOSED')!
  const input = { ...v, performance_since: '2025-01-01', performance_through: '2026-01-01', actual_available_through: '2026-01-01', history_coverage: 'FULL' as const, next_before: null, curve_trades: [{ ...trade, reference_return_pct: '100' }], summary: { ...v.summary, closed_count: 1, sum_return_percentage_points: '100' } }
  assert.equal(newowReferenceAnnualized(input), 100)
  assert.equal(newowReferenceAnnualized({ ...input, history_coverage: 'PARTIAL' }), null)
  assert.equal(newowReferenceAnnualized({ ...input, performance_since: input.performance_through }), null)
  assert.equal(newowReferenceAnnualized({ ...input, curve_trades: [] }), null)
  const loss = { ...input, curve_trades: [{ ...trade, reference_return_pct: '-100' }], summary: { ...input.summary, sum_return_percentage_points: '-100' } }
  assert.equal(newowReferenceAnnualized(loss), null)
})
