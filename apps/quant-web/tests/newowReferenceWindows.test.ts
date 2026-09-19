import assert from 'node:assert/strict'
import test from 'node:test'
import { newowReferenceWindow } from '../src/utils/newowReferenceWindows.ts'

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
