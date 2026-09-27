import assert from 'node:assert/strict'
import test from 'node:test'
import { buildNewowFixtureEnvelopeForTest } from '../e2e/newow-product.helpers.mjs'
import { buildNewowProductChartModel } from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'
import { mergeNewowDualReferences, layoutNewowDualCallouts, newowDualDominance, newowDualVisibleStatistics, type DualPoint } from '../src/utils/newowDualChartDisplay.ts'
import type { NewowReferenceTrade } from '../src/types/newowProduct.ts'

function point(origin: 'trend' | 'oscillation', y: number, id = origin): DualPoint {
  return { origin, x: 160, y, boxWidth: 100, boxHeight: 28,
    callout: { id, title: '清仓', detail: '参考价 101', above: true, time: '2026-08-03T07:00:00Z', price: '101', physicalContract: 'JM2609', tone: 'neutral' },
  }
}
test('dual regions bound boxes, retain actual price anchors and connector endpoints', () => {
  const placed = layoutNewowDualCallouts([point('trend', 320), point('oscillation', 100)], 700, 400)
  assert.equal(placed.length, 2)
  const trend = placed.find(p => p.origin === 'trend')!, osc = placed.find(p => p.origin === 'oscillation')!
  assert.equal(trend.y, 320); assert.equal(osc.y, 100)
  assert.ok(trend.top >= 20 && trend.top + trend.height <= 210)
  assert.ok(osc.top >= 210 && osc.top + osc.height <= 398)
  assert.ok(trend.lineY >= 20 && trend.lineY <= 210)
  assert.ok(osc.lineY >= 210 && osc.lineY <= 398)
  assert.equal(layoutNewowDualCallouts([{ ...point('trend', 100), x: -100 }], 700, 400).length, 0)
})
test('visible statistics accept only exact per-strategy CLOSED references; arithmetic keeps decimal precision', () => {
  const points = [point('trend', 100), point('oscillation', 300)]
  const trade = (origin: 'trend' | 'oscillation', value: string) => ({ status: 'CLOSED', strategy_code: origin,
    exit_signal_id: origin, exit_bar_end: points[0]!.callout.time, physical_contract: 'JM2609', exit_reference_price: '101', reference_return_pct: value,
  } as NewowReferenceTrade)
  const trades = [trade('trend', '12.34567890123456789'), trade('oscillation', '-2.34567890123456789')]
  assert.deepEqual(newowDualVisibleStatistics(points, trades), { count: 2, samples: 2, average: '+5.0%', winRate: '50%', maximum: '+12.3%' })
  assert.equal(newowDualVisibleStatistics(points, [...trades, trades[0]!]).samples, 1)
  assert.equal(newowDualVisibleStatistics(points, trades.map(t => ({ ...t, status: 'OPEN' }))).samples, 0)
  assert.equal(newowDualVisibleStatistics(points, trades.map(t => ({ ...t, physical_contract: 'JM2701' }))).average, '—')
})
test('dominance prefers a sole BUILD, preserves simultaneous BUILD and resets at owner boundaries', () => {
  const raw = buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d', false, null, { dualMarket: true })
  const base = buildNewowProductChartModel({ meta: raw.meta, section: 'chart', ...raw.chart })
  const template = base.bars[0]!
  const bars = Array.from({ length: 20 }, (_, index) => ({ ...template, barEnd: `2026-08-${String(index + 1).padStart(2, '0')}T07:00:00Z` }))
  const action = (index: number, kind: 'BUILD' | 'CLEAR') => ({ id: `${index}:${kind}`, kind, barEnd: bars[index]!.barEnd,
    physicalContract: template.physicalContract, segmentId: template.segmentId, tradingDay: '', value: 100, referencePrice: '100', sequence: 0, tradeEligibility: 'eligible' as const })
  const trend = { ...base, bars, actions: [action(0, 'BUILD'), action(2, 'BUILD'), action(4, 'CLEAR'), action(17, 'BUILD')] }
  const osc = { ...base, identity: { ...base.identity, strategy: 'oscillation' as const }, bars, actions: [action(2, 'BUILD'), action(4, 'BUILD'), action(5, 'CLEAR')] }
  const result = newowDualDominance(trend, [trend, osc])
  assert.equal(result.dominant, 'trend')
  assert.deepEqual(result.switches, [{ index: 4, from: 'trend', to: 'oscillation' }, { index: 17, from: 'oscillation', to: 'trend' }])
  const boundary = { ...trend, bars: bars.map((b, i) => i >= 16 ? { ...b, calculationSegmentId: 'new', physicalContract: 'JM2701' } : b) }
  assert.equal(newowDualDominance(boundary, [trend, osc]).dominant, null)
})

test('curve/page overlap preserves exact records and excludes stable-id conflicts in either order', () => {
  const p = point('trend', 100)
  const trade = { reference_trade_id: 'trade-1', status: 'CLOSED', strategy_code: 'trend',
    exit_signal_id: p.callout.id, exit_bar_end: p.callout.time, physical_contract: 'JM2609',
    exit_reference_price: '101', reference_return_pct: '12.3' } as NewowReferenceTrade
  const equivalent = Object.fromEntries(Object.entries(trade).reverse()) as unknown as NewowReferenceTrade
  assert.equal(mergeNewowDualReferences([trade, equivalent]).length, 1)
  assert.equal(newowDualVisibleStatistics([p], mergeNewowDualReferences([trade, equivalent])).samples, 1)
  for (const conflicting of [{ ...trade, reference_return_pct: '99' }, { ...trade, physical_contract: 'JM2701' }]) {
    for (const records of [[trade, conflicting, trade], [conflicting, trade, conflicting]]) {
      assert.equal(mergeNewowDualReferences(records).length, 0)
      assert.equal(newowDualVisibleStatistics([p], mergeNewowDualReferences(records)).samples, 0)
    }
  }
})
