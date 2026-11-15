import assert from 'node:assert/strict'
import test from 'node:test'
import { newowFourStepMarks } from '../src/utils/newowFourStepMarks.ts'

const bars = Array.from({ length: 60 }, (_, i) => ({
  barEnd: `bar-${i}`, segmentId: 'owner', physicalContract: 'JM2701', calculationSegmentId: i < 50 ? 'a' : 'b',
}))
function action(id: string, i: number, kind: 'BUILD' | 'CLEAR') {
  return { id, barEnd: bars[i]!.barEnd, segmentId: 'owner', physicalContract: 'JM2701',
    calculationSegmentId: bars[i]!.calculationSegmentId, sequence: 0, kind, tradeEligibility: 'ELIGIBLE' }
}
test('badges preserve same-bar phase, 15-bar evidence, and calculation boundaries', () => {
  const marks = newowFourStepMarks(bars, [
    { source: 'trend', actions: [action('add', 5, 'BUILD'), action('ignored', 6, 'BUILD'),
      action('backstop', 25, 'CLEAR'), action('expired', 46, 'CLEAR'), action('exit', 49, 'CLEAR'),
      action('new-owner', 50, 'CLEAR')] },
    { source: 'oscillation', actions: [action('prefix-clear', 0, 'CLEAR'), action('open', 5, 'BUILD'), action('close', 10, 'CLEAR'),
      action('open-2', 27, 'BUILD'), action('close-2', 30, 'CLEAR'), action('open-3', 48, 'BUILD')] },
  ])
  assert.deepEqual([...marks].map(([id, mark]) => [id, mark.badge]), [
    ['open','①'], ['add','②'], ['close','③'], ['backstop','④'],
    ['open-2','①'], ['close-2','③'], ['open-3','①'], ['exit','④'],
  ])
  assert.match(marks.get('backstop')!.label, /未触发/)
  assert.match(marks.get('exit')!.label, /清仓/)
})
test('a cropped chart starts numbering after a reliable clear', () => {
  const marks = newowFourStepMarks(bars, [
    { source: 'oscillation', actions: [action('unknown', 0, 'BUILD'), action('clear', 8, 'CLEAR'), action('new', 8, 'BUILD')] },
  ])
  assert.deepEqual([...marks.keys()], ['new'])
})
