import assert from 'node:assert/strict'
import test from 'node:test'
import { newowReferenceCurve, newowReferenceDrawdown, newowReferenceAnnualized, newowTheoreticalDisplay } from '../src/utils/newowReferenceCurve.ts'
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

 test('theoretical display changes only curve and statistics, with exact closed identities', () => {
  const v = value()
  const closed = (v.curve_trades ?? v.items).filter(t => t.status === 'CLOSED' && t.statistics_membership === v.summary.membership_policy)
  const original = JSON.stringify(v)
  const input = { ...v, summary: { ...v.summary, closed_count: closed.length }, theoretical: {
    model_version: 'newow_hindsight_peak_reference_v1', hindsight: true as const, executable: false as const,
    returns: closed.map(t => ({ reference_trade_id: t.reference_trade_id, return_pct: '10', ideal_exit_price: '110' })),
    sum_return_percentage_points: String(closed.length * 10), win_rate_pct: '100', mean_return_pct: '10',
  } }
  const result = newowTheoreticalDisplay(input)!
  assert.ok(result)
  assert.equal(result.items, input.items)
  assert.equal(result.summary.mean_return_pct, '10')
  assert.ok(result.curve_trades!.every(t => t.reference_return_pct === '10'))
  assert.equal(JSON.stringify(v), original)
  assert.equal(newowTheoreticalDisplay({ ...input, theoretical: { ...input.theoretical, returns: [] } }), null)
  assert.equal(newowTheoreticalDisplay({ ...input, theoretical: { ...input.theoretical, model_version: 'unknown' } }), null)
})

test('drawdown uses normalized additive curve peaks, including the initial baseline', () => {
  const v = value()
  const trade = v.items.find(t => t.status === 'CLOSED')!
  const make = (returns: string[], sum: string) => ({ ...v, history_coverage: 'FULL' as const, curve_trades: returns.map((r, i) => ({ ...trade, reference_trade_id: String(i), exit_bar_end: `2026-09-0${i + 1}T07:00:00Z`, reference_return_pct: r })), summary: { ...v.summary, closed_count: returns.length, sum_return_percentage_points: sum } })
  assert.equal(newowReferenceDrawdown(make(['20', '-30', '5'], '-5')), '25.00')
  assert.equal(newowReferenceDrawdown(make(['-10', '20'], '10')), '10.00')
  assert.equal(newowReferenceDrawdown(make(['1', '2'], '3')), '0.00')
  assert.equal(newowReferenceDrawdown({ ...make(['1'], '1'), history_coverage: 'PARTIAL' }), null)
  assert.equal(newowReferenceDrawdown(make([], '0')), null)
})

test('saved PostgreSQL Decimal zero and scientific notation preserve exact reference curves', () => {
  const v = value()
  const trade = v.items.find(t => t.status === 'CLOSED')!
  const items = [
    { ...trade, reference_trade_id: 'zero', reference_return_pct: '0E-28' },
    { ...trade, reference_trade_id: 'small', reference_return_pct: '1E-2' },
  ]
  const result = newowReferenceCurve({ ...v, items, next_before: null,
    summary: { ...v.summary, closed_count: 2, sum_return_percentage_points: '0.01' } })
  assert.equal(result.message, null)
  assert.equal(Number(result.points.at(-1)!.cumulative), 0.01)
})

test('curve interaction anchors are bounded while the complete curve remains intact', async () => {
  const { referenceCurveAnchors } = await import('../src/utils/newowReferenceCurve.ts')
  const points = Array.from({ length: 33169 }, (_, index) => ({ index }))
  const anchors = referenceCurveAnchors(points)
  assert.ok(anchors.length <= 1000)
  assert.equal(anchors[0], points[0])
  assert.equal(anchors.at(-1), points.at(-1))
  assert.equal(points.length, 33169)
  assert.deepEqual(referenceCurveAnchors(points.slice(0, 20)), points.slice(0, 20))
})

test('click location resolves an unsampled trade from the complete curve', async () => {
  const { closestReferenceCurvePoint } = await import('../src/utils/newowReferenceCurve.ts')
  const points = Array.from({ length: 5000 }, (_, index) => ({ x: index, y: index % 50 }))
  assert.equal(closestReferenceCurvePoint(points, 1234, 34), points[1234])
  assert.equal(closestReferenceCurvePoint([], 1, 1), null)
  assert.equal(closestReferenceCurvePoint(points, NaN, 1), null)
})
