import assert from 'node:assert/strict'
import test from 'node:test'
import { referenceIndicatorOverlay } from '../src/utils/referenceIndicatorOverlay.ts'
const bar = { time: '2026-10-23T07:00:00Z', physicalContract: 'JM2701', open: 1, high: 2, low: 1, close: 2, volume: 1 }
const point = { bar_end: bar.time, physical_contract: 'JM2701', dif: '1.2', dea: '0.5', macd: '1.4', ema21: '1410' } as any
test('failed or empty reference read cannot erase the existing chart MACD', () => {
 assert.equal(referenceIndicatorOverlay([bar]), null)
 assert.equal(referenceIndicatorOverlay([bar], []), null)
 assert.equal(referenceIndicatorOverlay([bar], [{...point,physical_contract:'JM2609'}]), null)
})
test('matching reference overrides values and preserves explicit warmup gaps', () => {
 assert.equal(referenceIndicatorOverlay([bar],[point])?.dif[0].value,1.2)
 assert.ok(Number.isNaN(referenceIndicatorOverlay([bar],[{...point,dif:null}])?.dif[0].value))
})
