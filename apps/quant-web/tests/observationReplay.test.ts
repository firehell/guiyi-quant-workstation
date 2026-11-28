import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { BarData } from '../src/types/market'
import { validObservationBars, verifiedObservationPoints } from '../src/utils/observationReplay.ts'

const first = '2026-11-26T07:00:00Z'
const last = '2026-11-27T07:00:00Z'
const sha = '0'.repeat(64)
const bar = { time: first, sourceBarSha256: sha, physicalContract: 'RB2701' } as BarData

test('replay requires the original physical owner, digest and complete window', () => {
  const rows: unknown = [
    [first, sha, 0.25, 'RB2701'],
    [last, sha, 0.7, 'RB2701'],
  ]
  assert.ok(validObservationBars(rows))
  const bars = [bar, { ...bar, time: last }]
  assert.deepEqual(
    verifiedObservationPoints(bars, rows)?.map((p) => p.x),
    [0.25, 0.7],
  )
  assert.equal(verifiedObservationPoints([bar], rows), null)
  assert.equal(verifiedObservationPoints([bar, { ...bars[1]!, physicalContract: 'RB2610' }], rows), null)
  assert.equal(verifiedObservationPoints([bar, { ...bars[1]!, sourceBarSha256: '1'.repeat(64) }], rows), null)
})

test('invalid time order or geometry cannot authorize inspection of the original', () => {
  const row = [first, sha, 0.2, 'RB2610']
  for (const proof of [
    [],
    [row, row],
    [row, [last, sha, -1, 'RB2701']],
    [[last, sha, 0, '']],
    [['invalid', sha, 0, 'RB2701']],
  ]) {
    assert.equal(validObservationBars(proof), false)
  }
})
