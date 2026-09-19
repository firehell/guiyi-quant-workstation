import assert from 'node:assert/strict'
import test from 'node:test'
import { projectNewowCupPoints } from '../src/components/market/detail/newow/newowCupFactsPresentation.ts'
import type { NewowCupWitness } from '../src/types/newowProduct.ts'

const witness = (prices: readonly string[]): NewowCupWitness => ({
  witness_id: 'w', candidate_id: 'c', pivot_price: prices[2]!, confirmed_at: '2026-09-03T07:00:00Z', score: 1,
  score_breakdown: [], volume_facts: [], right_leg_median_exact: '1', handle_median_exact: '1', handle_baseline_median_exact: '1', profile_identity: 'p', formula_version: 'f',
  left_rim: pivot(prices[0]!), bottom: pivot(prices[1]!), right_rim: pivot(prices[2]!), handle_extreme: pivot(prices[3]!),
})
const pivot = (price: string) => ({ kind: 'x', price, pivot_at: '2026-09-01T07:00:00Z', confirmed_at: '2026-09-02T07:00:00Z', pivot_index: 1, confirmed_index: 2, atr_at_pivot: 1 })

test('cup geometry preserves price ordering across modulo boundaries and equal prices', () => {
  const ordered = projectNewowCupPoints(witness(['100', '80', '100', '90']))
  assert.ok(ordered[1]!.y > ordered[0]!.y)
  assert.deepEqual(projectNewowCupPoints(witness(['42', '42', '42', '42'])).map(point => point.y), [35, 35, 35, 35])
  assert.equal(projectNewowCupPoints(witness(['x', '80', '100', '90'])).every(point => !point.available), true)
})

test('cup geometry retains order for Decimal values beyond JavaScript Number precision', () => {
  const points = projectNewowCupPoints(witness([
    '100000000000000000000000000000000000000000000000000.2',
    '100000000000000000000000000000000000000000000000000.1',
    '100000000000000000000000000000000000000000000000000.3',
    '100000000000000000000000000000000000000000000000000.15',
  ]))
  assert.equal(points.every(point => point.available), true)
  assert.ok(points[2]!.y < points[0]!.y)
  assert.ok(points[0]!.y < points[3]!.y)
  assert.ok(points[3]!.y < points[1]!.y)
})
