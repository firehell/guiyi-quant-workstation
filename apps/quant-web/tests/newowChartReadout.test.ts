import assert from 'node:assert/strict'
import test from 'node:test'
import { newowChartReadout, newowTimeKey } from '../src/utils/newowChartReadout.ts'
import { buildNewowProductChartModel, alignNewowAuxiliaryChartModel } from '../src/components/market/detail/newow/newowProductChartPrimitives.ts'
import { buildNewowFixtureEnvelopeForTest } from '../e2e/newow-product.helpers.mjs'
test('crosshair reads only an exact completed Bar and aligned pane, never a nearby date', () => {
  const raw = buildNewowFixtureEnvelopeForTest('chart')
  const chart = { meta: raw.meta, section: 'chart', ...raw.chart }
  const model = buildNewowProductChartModel(chart)
  const aux = alignNewowAuxiliaryChartModel(chart, (() => { const raw = buildNewowFixtureEnvelopeForTest('auxiliary'); return { meta: raw.meta, section: 'auxiliary', ...raw.auxiliary } })())
  const date = model.bars.at(-1)!.tradingDay
  assert.equal(newowTimeKey({ year: 2026, month: 9, day: 3 }), '2026-09-03')
  assert.ok(newowChartReadout(model, aux, date).some(text => text.includes('收 ')))
  assert.deepEqual(newowChartReadout(model, aux, '1900-01-01'), [])
  assert.deepEqual(newowChartReadout(model, aux, null), [])
})
