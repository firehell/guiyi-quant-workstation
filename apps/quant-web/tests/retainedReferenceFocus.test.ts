import test from 'node:test'
import assert from 'node:assert/strict'
import { retainedReferenceFocus } from '../src/utils/retainedReferenceFocus.ts'
import type { BarData } from '../src/types/market.ts'
const bar = (time: string, physicalContract = 'JM2701') => ({ time, physicalContract } as BarData)
test('focus loads earlier pages and binds exact physical contract', async () => {
  let bars = [bar('2026-10-23T01:00:00Z')], calls = 0
  const target = { barEnd: '2026-10-22T01:00:00Z', physicalContract: 'JM2701' }
  const found = await retainedReferenceFocus(target, { bars: () => bars, hasMore: () => true, current: () => true, loadEarlier: async () => { calls++; bars = [bar(target.barEnd), ...bars] } })
  assert.equal(found?.time, target.barEnd); assert.equal(calls, 1)
  assert.equal(await retainedReferenceFocus({ ...target, physicalContract: 'JM2609' }, { bars: () => bars, hasMore: () => true, current: () => true, loadEarlier: async () => { throw Error('must not load') } }), null)
})
test('changed identity cancels focus and no-progress loader cannot loop', async () => {
  const bars = [bar('2026-10-23T01:00:00Z')]
  const target = { barEnd: '2026-10-22T01:00:00Z', physicalContract: 'JM2701' }
  let calls = 0
  assert.equal(await retainedReferenceFocus(target, { bars: () => bars, hasMore: () => true, current: () => true, loadEarlier: async () => { calls++ } }), null)
  assert.equal(calls, 1)
  await retainedReferenceFocus(target, { bars: () => bars, hasMore: () => true, current: () => false, loadEarlier: async () => { throw Error('must not load') } })
})
