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

test('missing auxiliary value is explicit and never carried from a different Bar', () => {
  const raw = buildNewowFixtureEnvelopeForTest('chart')
  const chart = { meta: raw.meta, section: 'chart', ...raw.chart }
  const model = buildNewowProductChartModel(chart)
  const rawAux = buildNewowFixtureEnvelopeForTest('auxiliary')
  const aux = alignNewowAuxiliaryChartModel(chart, { meta: rawAux.meta, section: 'auxiliary', ...rawAux.auxiliary })!
  const date = model.bars.at(-1)!.tradingDay
  const missing = { ...aux, series: [{ label: 'DIF', points: [] }] } as unknown as Parameters<typeof newowChartReadout>[1]
  assert.ok(newowChartReadout(model, missing, date).some(text => text.includes('该 Bar 缺值')))
  assert.ok(newowChartReadout(model, null, date).includes('副图不可用 / 预热'))
})

test('physical segments with the same legend yield one exact-time reading', () => {
  const raw = buildNewowFixtureEnvelopeForTest('chart')
  const model = buildNewowProductChartModel({ meta: raw.meta, section: 'chart', ...raw.chart })
  const date = model.bars.at(-1)!.tradingDay
  const series = [{ label: 'DIF', points: [{ time: date, value: 12 }] }, { label: 'DIF', points: [{ time: '1900-01-01', value: 99 }] }]
  const aux = { series } as unknown as Parameters<typeof newowChartReadout>[1]
  assert.deepEqual(newowChartReadout(model, aux, date).filter(row => row.startsWith('DIF')), ['DIF 12'])
})
