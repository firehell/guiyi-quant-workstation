import test from 'node:test'
import assert from 'node:assert/strict'
import { newowVolumeColors } from '../src/utils/newowVolumeDisplay.ts'
import type { NewowProductChartModel } from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'
function fixture(): NewowProductChartModel {
  const bars = Array.from({ length: 10 }, (_, i) => ({ barEnd: String(i), tradingDay: String(i), open: 100, high: 110, low: 90, close: 100, volume: 100, physicalContract: 'RB2610', segmentId: 's', calculationSegmentId: 'c', sourceIdentity: 'source' }))
  bars[9] = { ...bars[9]!, open: 90, close: 108, volume: 200 }
  return { identity: { product: 'rb', strategy: 'oscillation', frequency: '1d' }, bars, mainLines: [], bandAreas: [], channelPoints: [], hints: [], nextBefore: null, actions: [{ id: 'build', kind: 'BUILD', barEnd: '9', tradingDay: '9', physicalContract: 'RB2610', segmentId: 's', sequence: 1, referencePrice: '90', value: 90, tradeEligibility: 'ELIGIBLE' }] }
}
test('yellow requires scored oscillation action, not volume alone', () => {
  const model = fixture()
  assert.equal(newowVolumeColors(model, 'red', 'green')[9], 'rgba(255,215,0,0.7)')
  assert.equal(newowVolumeColors({ ...model, actions: [] }, 'red', 'green')[9], 'red')
  assert.equal(newowVolumeColors({ ...model, identity: { ...model.identity, strategy: 'trend' } }, 'red', 'green')[9], 'red')
  model.bars[0] = { ...model.bars[0]!, calculationSegmentId: 'old' }
  assert.equal(newowVolumeColors(model, 'red', 'green')[9], 'red')
})
