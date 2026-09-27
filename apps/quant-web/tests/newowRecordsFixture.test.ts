import assert from 'node:assert/strict'
import test from 'node:test'
import { buildNewowFixtureEnvelopeForTest, installNewowProductFixtures, NEWOW_AS_OF } from '../e2e/newow-product.helpers.mjs'
import { normalizeNewowProductResponse } from '../src/utils/newowProductTypes.ts'
import { newowReferenceCurve } from '../src/utils/newowReferenceCurve.ts'

test('records-history fixture preserves complete closed returns and exact interrupted owners', async () => {
  // Independently fixed expected dates/prices prevent a self-consistent but wrong fixture.
  const raw = buildNewowFixtureEnvelopeForTest('reference', 'trend', '1d', false, null, { recordsHistory: true })
  const response = normalizeNewowProductResponse(raw, {
    identity: { product: 'rb', strategy: 'trend', frequency: '1d', seriesKind: 'actual_dominant' },
    section: 'reference', asOf: NEWOW_AS_OF,
  })
  assert.equal(response.section, 'reference')
  const value = response.value!
  assert.equal(value.summary.closed_count, 2)
  assert.equal(value.summary.sum_return_percentage_points, '10.2040')
  assert.equal(value.next_before, null)
  const curve = newowReferenceCurve(value)
  assert.equal(curve.message, null)
  assert.deepEqual(curve.points.map(p => p.trade.exit_trading_day), ['2026-06-30', '2026-08-02'])
  const interrupted = value.items.find(t => t.status === 'ROLLOVER_INTERRUPTED')!
  assert.equal(interrupted.entry_trading_day, '2026-06-05')
  assert.equal(interrupted.mark_change_pct, '-10.0000')
  const older = buildNewowFixtureEnvelopeForTest('chart', 'trend', '1d', true, null, { recordsHistory: true }).chart.value
  const mark = older.bars.find(b => b.bar_end === interrupted.mark_bar_end)!
  assert.equal(mark.close, '79.2000')
  assert.equal(mark.physical_contract, interrupted.physical_contract)
  assert.equal(mark.segment_id, interrupted.segment_id)
  await installNewowProductFixtures({ on() {}, addInitScript() {}, route() {} }, { recordsHistory: true })
})
