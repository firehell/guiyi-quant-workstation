import test from 'node:test'
import assert from 'node:assert/strict'
import { newowOscillationBreakout } from '../src/utils/newowBreakoutDisplay.ts'
import type { NewowProductChartModel } from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'

function fixture(count = 12): NewowProductChartModel {
  const bars = Array.from({ length: count }, (_, i) => ({
    barEnd: new Date(Date.UTC(2026, 8, i + 1)).toISOString(), tradingDay: `2026-09-${String(i + 1).padStart(2, '0')}`,
    open: 100, high: 110, low: 90, close: 100, volume: 100,
    physicalContract: 'JM2701', segmentId: 'owner', calculationSegmentId: 'calc', sourceIdentity: 'canonical',
  }))
  bars[9] = { ...bars[9]!, open: 110, close: 95, high: 112, volume: 200 }
  return { identity: { product: 'jm', strategy: 'oscillation', frequency: '1d' }, bars,
    actions: [], hints: [], mainLines: [], bandAreas: [], channelPoints: [], nextBefore: null }
}

test('global scan exposes a scored high-touch even without a CLEAR action', () => {
  const model = fixture()
  const before = JSON.stringify(model)
  const result = newowOscillationBreakout(model)!
  assert.equal(result.price, 95)
  assert.equal(result.score.total, 6)
  assert.equal(result.displayScore, 6)
  assert.equal(result.confirmScore, 0, 'valid OHLC cannot close above its own inclusive HHV10')
  assert.equal(result.origin, 'high_touch')
  assert.equal(JSON.stringify(model), before, 'display selection never creates strategy actions')
})

test('same-date CLEAR takes the server reference price, while a later global candidate wins', () => {
  const model = fixture()
  const bar = model.bars[9]!
  model.actions = [{ id: 'clear', kind: 'CLEAR', barEnd: bar.barEnd, tradingDay: bar.tradingDay,
    physicalContract: bar.physicalContract, segmentId: bar.segmentId, sequence: 0,
    referencePrice: '111.25', value: 111.25, tradeEligibility: 'ELIGIBLE' }]
  assert.equal(newowOscillationBreakout(model)!.price, 111.25)
  assert.equal(newowOscillationBreakout(model)!.origin, 'clear_action')
  model.bars[11] = { ...model.bars[11]!, open: 120, high: 120, close: 95, volume: 250 }
  assert.equal(newowOscillationBreakout(model)!.origin, 'high_touch')
  assert.equal(newowOscillationBreakout(model)!.barEnd, model.bars[11]!.barEnd)
})

test('scan is limited to fifty bars but an older eligible visible CLEAR stays a candidate', () => {
  const model = fixture(61)
  assert.equal(newowOscillationBreakout(model), null)
  const bar = model.bars[9]!
  model.actions = [{ id: 'clear', kind: 'CLEAR', barEnd: bar.barEnd, tradingDay: bar.tradingDay,
    physicalContract: bar.physicalContract, segmentId: bar.segmentId, sequence: 0,
    referencePrice: '112', value: 112, tradeEligibility: 'ELIGIBLE' }]
  assert.equal(newowOscillationBreakout(model)!.price, 112)
})

test('missing warmup, changed physical/quality owner and other strategies revoke the line', () => {
  const model = fixture()
  for (const strategy of ['trend', 'main_rise'] as const) assert.equal(newowOscillationBreakout({ ...model, identity: { ...model.identity, strategy } }), null)
  assert.equal(newowOscillationBreakout({ ...model, bars: model.bars.slice(9) }), null)
  for (const key of ['physicalContract', 'segmentId', 'calculationSegmentId'] as const) {
    const variant = fixture()
    variant.bars[11] = { ...variant.bars[11]!, [key]: 'new-owner' }
    assert.equal(newowOscillationBreakout(variant), null, key)
  }
  const changedSource = fixture()
  changedSource.bars[11] = { ...changedSource.bars[11]!, sourceIdentity: 'new-canonical-partition' }
  assert.equal(newowOscillationBreakout(changedSource)!.price, 95, 'per-Bar source identity is not a calculation reset')
  model.bars[9] = { ...model.bars[9]!, close: 109, open: 109, volume: 100 }
  assert.equal(newowOscillationBreakout(model), null, 'low-scoring touches do not invent a breakout')
})

test('out-of-scale event price is hidden rather than replaced by the same-date close', () => {
  const model = fixture(); const bar = model.bars[9]!
  model.actions = [{ id: 'clear', kind: 'CLEAR', barEnd: bar.barEnd, tradingDay: bar.tradingDay,
    physicalContract: bar.physicalContract, segmentId: bar.segmentId, sequence: 0,
    referencePrice: '10000', value: 10000, tradeEligibility: 'ELIGIBLE' }]
  assert.equal(newowOscillationBreakout(model), null)
})
