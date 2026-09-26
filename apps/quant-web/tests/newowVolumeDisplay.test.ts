import test from 'node:test'
import assert from 'node:assert/strict'
import { newowVolumeColors, newowVolumeScores } from '../src/utils/newowVolumeDisplay.ts'
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

test('explanation shares the exact yellow decision and exposes all three components', () => {
  const model = fixture()
  const [score] = newowVolumeScores(model, 9)
  assert.equal(score!.volumeRatio, 200 / 110)
  assert.equal(score!.bodyRatio, 0.9)
  assert.equal(score!.penetrationRatio, 18 / 90)
  assert.equal(score!.total, 6)
  assert.equal(score!.total, score!.volumeScore + score!.bodyScore + score!.penetrationScore)
  assert.deepEqual(newowVolumeScores(model, 8), [])
  const dual = { ...model, actions: [...model.actions, { ...model.actions[0]!, id: 'clear', kind: 'CLEAR' as const }] }
  const scores = newowVolumeScores(dual, 9)
  assert.equal(scores.length, 2)
  assert.equal(scores[1]!.reference, 110)
  assert.equal(scores[1]!.total, 5)
  assert.equal(newowVolumeColors(model, 'red', 'green')[9], 'rgba(255,215,0,0.7)')
})

test('strict body and penetration boundaries and ordinary bars remain explicit', () => {
  const model = fixture()
  model.bars[9] = { ...model.bars[9]!, open: 102, close: 108, high: 110, low: 100, volume: 100 }
  const score = newowVolumeScores(model, 9)[0]!
  assert.equal(score.volumeScore, 1)
  assert.equal(score.bodyScore, 1, 'exactly 60% does not receive 2 points')
  assert.deepEqual(newowVolumeScores({ ...model, actions: [] }, 9), [])
  assert.deepEqual(newowVolumeScores({ ...model, identity: { ...model.identity, strategy: 'trend' } }, 9), [])
})
