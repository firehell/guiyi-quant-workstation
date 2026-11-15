import assert from 'node:assert/strict'
import test from 'node:test'
import { buildNewowTrendReversalCommands, buildNewowTrendReversalData, buildNewowTrendReversalMarks, visibleReversalMarks, NEWOW_TREND_REVERSAL_STYLE } from '../src/components/market/detail/newow/newowTrendReversalPrimitive.ts'

test('trend reversal keeps server categories and colors at their exact bars', () => {
  const points = (values: number[]) => values.map((value, index) => ({ barEnd: `2026-09-${String(index + 1).padStart(2, '0')}`, index, value, physicalContract: 'MA701', segmentId: 'owner', time: index + 1 }))
  const rows = buildNewowTrendReversalData([
    { id: 'bias', key: 'bias', label: '偏离', points: points([4, -3, -6, 7]) },
    { id: 'rebound', key: 'rebound', label: '反弹', points: points([0, 0, -6, 0]) },
    { id: 'adjust', key: 'adjust', label: '调整', points: points([0, 0, 0, 7]) },
  ])
  const { items, zeroY, limit } = buildNewowTrendReversalCommands(rows, 400, 240, time => Number(time) * 60, 55)
  assert.deepEqual(items.slice(1).map(item => item.color), [
    NEWOW_TREND_REVERSAL_STYLE.positive, NEWOW_TREND_REVERSAL_STYLE.negative,
    NEWOW_TREND_REVERSAL_STYLE.rebound, NEWOW_TREND_REVERSAL_STYLE.adjust,
  ])
  assert.ok(items[1]!.y < zeroY)
  assert.equal(items[2]!.y, zeroY)
  assert.ok(limit >= 7)
})

test('trend reversal scale uses visible bars and keeps axis within pane', () => {
  const data = [{ index: 0, segmentId: 'a', time: 1, bias: 80, rebound: 0, adjust: 0 },
    { index: 1, segmentId: 'a', time: 2, bias: -2, rebound: 0, adjust: 0 }]
  const result = buildNewowTrendReversalCommands(data, 200, 180, time => Number(time) === 1 ? null : 100, 60)
  assert.equal(result.limit, 3)
  assert.ok(result.zeroY > 60 && result.zeroY < 180)
})

test('confirmation layer requires aligned completed owners and the daily or weekly gate', () => {
  const ends = ['2026-09-01', '2026-09-02', '2026-09-03'].map(d => d + 'T07:00:00Z')
  const segment = { segment_id: 'calculation', physical_contract: 'RB2609', bar_ends: ends,
    data: { wr1: [98, 99, 97], bias: [-4, -3, -1], enough: true } } as any
  const model = { identity: { frequency: '1d' }, bars: ends.map(end => ({
    barEnd: end, tradingDay: end.slice(0, 10), physicalContract: segment.physical_contract,
    calculationSegmentId: segment.segment_id,
  })) } as any
  const marks = buildNewowTrendReversalMarks(model, [segment])
  assert.deepEqual(marks, [{ time: { year: 2026, month: 9, day: 3 }, kind: 'rebound', tentative: true }])
  assert.deepEqual(buildNewowTrendReversalMarks({ ...model, identity: { frequency: '60m' } }, [segment]), [])
  assert.deepEqual(buildNewowTrendReversalMarks(model, [{ ...segment, segment_id: 'other' }]), [])
  assert.deepEqual(buildNewowTrendReversalMarks(model, [{ ...segment, data: { ...segment.data, enough: false } }]), [])
  const older = { time: '2026-09-01', kind: 'adjust' as const, tentative: false }
  assert.deepEqual(visibleReversalMarks([older, ...marks], 200, time => time === older.time ? 75 : 100), [{ ...marks[0], x: 100 }])
})
