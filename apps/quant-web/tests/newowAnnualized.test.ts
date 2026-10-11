import assert from 'node:assert/strict'
import test from 'node:test'
import { pagePerformanceSegmentAnnualized, pagePerformanceAnnualized } from '../src/utils/newowPagePerformance.ts'

test('page annualization uses selected curve endpoints, not summary or trade returns', () => {
  const mode = { dates: ['2025-01-01', '2026-01-01'], equity: ['20', '32'] }
  assert.ok(Math.abs(pagePerformanceAnnualized(mode)! - 10) < 1e-10)
  assert.ok(Math.abs(pagePerformanceAnnualized({ dates: mode.dates, equity: ['0', '-10'] })! + 10) < 1e-10)
  assert.deepEqual(mode.equity, ['20', '32'])
})

test('page annualization uses Shanghai calendar days for zoned timestamps', () => {
  assert.equal(pagePerformanceAnnualized({ dates: ['2026-01-01T16:00:00Z', '2026-01-02T15:00:00Z'], equity: ['0', '1'] }), null)
  assert.ok(pagePerformanceAnnualized({ dates: ['2025-01-01T16:00:00Z', '2026-01-01T16:00:00Z'], equity: ['0', '10'] })! > 9.99)
})

test('missing, invalid, nonpositive and overflowing curves cannot show fabricated annualization', () => {
  assert.equal(pagePerformanceAnnualized(null), null)
  for (const mode of [
    { dates: ['2026-01-01'], equity: ['0'] },
    { dates: ['2026-01-01', '2026-01-01'], equity: ['0', '1'] },
    { dates: ['2026-02-30', '2026-03-01'], equity: ['0', '1'] },
    { dates: ['2026-01-02', '2026-01-01'], equity: ['0', '1'] },
    { dates: ['2026-01-01', '2026-01-02'], equity: ['0'] },
    { dates: ['2026-01-01', '2026-01-02'], equity: ['-100', '1'] },
    { dates: ['2026-01-01', '2026-01-02'], equity: ['0', '-100'] },
    { dates: ['2026-01-01', '2026-01-02'], equity: ['0', '1e300'] },
    { dates: ['2026-01-01T00:00:00', '2026-01-02T00:00:00'], equity: ['0', '1'] },
  ]) assert.equal(pagePerformanceAnnualized(mode), null)
})


test('annualized page values never bridge physical calculation segments', () => {
  const mode = { dates: ['2024-01-01', '2024-12-31', '2025-01-01', '2026-01-01'], equity: ['0', '10', '10', '32'], segment_ids: ['a', 'a', 'b', 'b'] }
  assert.equal(pagePerformanceAnnualized(mode), null)
  const values = pagePerformanceSegmentAnnualized(mode)
  assert.equal(values.length, 2)
  assert.ok(Math.abs(values[0]!.annualized! - 10) < 1e-10)
  assert.ok(Math.abs(values[1]!.annualized! - 20) < 1e-10)
  assert.equal(pagePerformanceAnnualized({ ...mode, segment_ids: ['a'] }), null)
})
