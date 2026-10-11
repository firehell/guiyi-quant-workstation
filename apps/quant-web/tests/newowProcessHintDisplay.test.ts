import assert from 'node:assert/strict'
import test from 'node:test'
import { newowProcessHintDisplay } from '../src/utils/newowProcessHintDisplay.ts'
import type { NewowProductChartBar, NewowProductHintMarker } from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'

const bar: NewowProductChartBar = {
  barEnd: '2026-10-09T07:00:00Z', tradingDay: '2026-10-09',
  open: 110, high: 120, low: 100, close: 115, volume: 100,
  physicalContract: 'JM2611', segmentId: 'owner', calculationSegmentId: 'owner', sourceIdentity: 'revision',
}
const hint: NewowProductHintMarker = {
  id: 'stable-id', kind: 'MAGIC11:4低', barEnd: bar.barEnd, tradingDay: bar.tradingDay,
  value: 100, anchorPrice: '100', confirmedAt: bar.barEnd,
  sourceIdentity: bar.sourceIdentity, formulaVersions: ['newow_magic11_page_v1'],
  physicalContract: bar.physicalContract, segmentId: bar.segmentId, sequence: 0, tone: 'cycle',
}

test('cycle labels use source colors and price placement without modifying signal facts', () => {
  assert.deepEqual(newowProcessHintDisplay(hint, bar), {
    text: '4低', color: '#E53935', below: true, cycle: true, displayPrice: 99, padding: 5,
  })
  assert.equal(hint.anchorPrice, '100')
  for (const [kind, text, color, below] of [
    ['MAGIC11:4高', '4高', '#4CAF50', false], ['MAGIC11:7高', '7高', '#4CAF50', false],
    ['MAGIC11:7低', '7低', '#F5A623', true], ['MAGIC11:11变', '11变', '#E91E63', false],
    ['J', 'J', '#00FF00', false], ['D4', '★B', '#E53935', true],
    ['D5', '★B', '#4CAF50', true], ['D6', '★B', '#2979FF', true],
    ['NEWOW_ESCAPE_D1', '★S逃命', '#E53935', false], ['NEWOW_ESCAPE_D2', '★S逃', '#4CAF50', false],
    ['NEWOW_ESCAPE_D3', '★S跑', '#2979FF', false],
  ] as const) {
    const display = newowProcessHintDisplay({ ...hint, kind }, bar)!
    assert.equal(display.text, text); assert.equal(display.color, color); assert.equal(display.below, below)
    assert.equal(display.displayPrice, below ? 99 : 120)
  }
})

test('unknown, missing and conflicting hint owners are never painted onto another candle', () => {
  for (const change of [
    { kind: 'UNKNOWN' }, { anchorPrice: null }, { value: null }, { value: NaN },
    { physicalContract: 'JM2701' }, { barEnd: 'other' }, { segmentId: 'other' }, { sourceIdentity: 'old' },
  ]) assert.equal(newowProcessHintDisplay({ ...hint, ...change }, bar), null)
})
