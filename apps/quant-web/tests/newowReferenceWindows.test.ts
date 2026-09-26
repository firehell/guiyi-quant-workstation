import assert from 'node:assert/strict'
import test from 'node:test'
import { acceptedNewowReferencePreset, newowReferenceWindow } from '../src/utils/newowReferenceWindows.ts'

test('reference presets use accepted cutoff and clamp month ends without local-time drift', () => {
  assert.deepEqual(newowReferenceWindow('2026-09-18', 'three_months'), { performanceSince: '2026-06-18', performanceThrough: '2026-09-18' })
  assert.deepEqual(newowReferenceWindow('2026-09-18', 'one_year'), { performanceSince: '2025-09-18', performanceThrough: '2026-09-18' })
  assert.deepEqual(newowReferenceWindow('2026-09-18', 'ytd'), { performanceSince: '2026-01-01', performanceThrough: '2026-09-18' })
  assert.deepEqual(newowReferenceWindow('2024-02-29', 'one_year'), { performanceSince: '2023-02-28', performanceThrough: '2024-02-29' })
  assert.deepEqual(newowReferenceWindow('2026-05-31', 'three_months'), { performanceSince: '2026-02-28', performanceThrough: '2026-05-31' })
})

test('reference presets reject an impossible accepted cutoff', () => {
  assert.throws(() => newowReferenceWindow('2026-02-29', 'ytd'), /ANCHOR_INVALID/)
})

test('preset is highlighted only after the matching request is accepted', () => {
  const pending = { kind: 'one_year' as const, since: '2025-09-18', through: '2026-09-18' }
  assert.equal(acceptedNewowReferencePreset(pending, { performanceSince: '2026-01-01', performanceThrough: '2026-09-18' }), null)
  assert.equal(acceptedNewowReferencePreset(pending, { performanceSince: pending.since, performanceThrough: pending.through }), 'one_year')
  assert.equal(acceptedNewowReferencePreset(null, { performanceSince: pending.since, performanceThrough: pending.through }), null)
})

test('late listing clamps one year, three years and all to the same authoritative start', () => {
  const floor = '2025-11-01'
  const expected = { performanceSince: floor, performanceThrough: '2026-09-24' }
  for (const preset of ['one_year', 'three_years', 'all'] as const) assert.deepEqual(newowReferenceWindow('2026-09-24', preset, floor), expected)
  assert.deepEqual(newowReferenceWindow('2026-09-24', 'three_years', '2023-01-01'), { performanceSince: '2023-09-24', performanceThrough: '2026-09-24' })
  assert.throws(() => newowReferenceWindow('2026-09-24', 'all'), /START_UNAVAILABLE/)
})
