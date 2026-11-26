import assert from 'node:assert/strict'
import test from 'node:test'
import { CHART_MANIFEST, CHART_PROFILES, DISPLAY_CATALOG, createChartHost, readChartPreferences, setChartLayer, validateDisplayCatalog } from '../dist/index.js'

function chartAdapter() {
  const events = []
  const series = new Set()
  const chart = {
    addSeries(definition, options, pane) {
      const item = {
        type: definition.type, options, pane,
        attachPrimitive() { events.push('attach') },
        detachPrimitive() { events.push('detach') },
        createPriceLine() { return {} },
        removePriceLine() { events.push('remove-level') },
      }
      series.add(item)
      return item
    },
    swapPanes(left, right) { events.push(`swap-panes:${left}:${right}`) },
    removeSeries(item) { assert.ok(series.delete(item)); events.push(`remove:${item.type}`) },
    remove() { events.push('remove-chart') },
  }
  return { chart, series, events }
}

test('layer disposal releases every resource and preserves other layers on a shared chart', () => {
  const { chart, series, events } = chartAdapter()
  const host = createChartHost(chart)
  const candles = host.layer('candles', 'price', 'main').candles({})
  const volume = host.layer('volume', 'generic_volume', 'volume').histogram({ priceScaleId: 'volume' })
  const pane = host.addAuxiliary('macd')
  const macd = host.layer('macd', 'macd', pane)
  const line = macd.line({ color: '#123456' })
  const histogram = macd.histogram({})
  macd.priceLevel(line, { price: 0 })
  macd.primitive(line, {})
  macd.markers(line, () => ({ detach() { events.push('detach-markers') } }))
  macd.own(() => events.push('disconnect-observer'))
  host.own(() => events.push('unsubscribe-range'))
  assert.equal(line.pane, 1)
  assert.equal(histogram.pane, 1)
  assert.equal(volume.pane, candles.pane)
  macd.remove(histogram)
  host.removeAuxiliary('macd')
  assert.deepEqual([...series], [candles, volume])
  assert.deepEqual(events, ['attach', 'remove:Histogram', 'disconnect-observer', 'detach-markers', 'detach', 'remove-level', 'remove:Line'])
  assert.throws(() => macd.line({}), /CHART_RESOURCE_SCOPE_EXPIRED/)
  host.dispose()
  host.dispose()
  assert.deepEqual(events.slice(-4), ['unsubscribe-range', 'remove:Histogram', 'remove:Candlestick', 'remove-chart'])
})

test('three auxiliary panes share one chart and a new identity expires an old generation', () => {
  const { chart, series, events } = chartAdapter()
  const host = createChartHost(chart)
  const before = host.activate('JM:1d:trend')
  const candles = host.layer('price', 'price', 'main').candles({})
  for (const [index, id] of ['macd', 'obv', 'atr'].entries()) {
    const pane = host.addAuxiliary(id)
    const layer = host.layer(id, id, pane, true)
    assert.equal(layer.line({}).pane, index + 1)
    layer.updateDiagnostics({ status: 'warming', warmup: { available: 8, required: 20 } })
    assert.equal(layer.inspect().packageVersion, CHART_MANIFEST.version)
    assert.deepEqual(layer.inspect().warmup, { available: 8, required: 20 })
  }
  assert.throws(() => host.addAuxiliary('stddev'), /CHART_AUXILIARY_PANE_LIMIT/)
  host.orderAuxiliaries(['obv', 'macd', 'atr'])
  assert.deepEqual(events, ['swap-panes:1:2'])
  assert.equal(host.paneIndex({ auxiliary: 'obv' }), 1)
  assert.throws(() => host.orderAuxiliaries(['obv', 'macd', 'macd']), /CHART_AUXILIARY_ORDER_MISMATCH/)
  host.removeAuxiliary('obv')
  assert.equal(host.paneIndex({ auxiliary: 'atr' }), 2)
  const next = host.activate('JM:1d:oscillation')
  assert.equal(host.isCurrent(before), false)
  assert.equal(host.isCurrent(next), true)
  assert.deepEqual([...series], [candles])
  host.dispose()
  assert.equal(host.isCurrent(next), false)
})

test('catalog rejects missing, incompatible and unauthorized compute definitions', () => {
  const features = Object.fromEntries(Object.values(DISPLAY_CATALOG).flatMap(item => {
    if (item.source.type !== 'quant_feature') return []
    return [[item.source.featureId, { output_schema_version: item.source.schema, outputs: item.source.outputs,
      allowed_uses: ['web'], repainting: Boolean(item.retrospective) }]]
  }))
  const manifest = { compute_contract_version: 'guiyi_quant_compute_v1', features }
  assert.doesNotThrow(() => validateDisplayCatalog(manifest))
  assert.throws(() => validateDisplayCatalog({ ...manifest, compute_contract_version: 'future' }), /CHART_COMPUTE_CONTRACT_UNSUPPORTED/)
  assert.throws(() => validateDisplayCatalog({ ...manifest, features: {} }), /CHART_COMPUTE_FEATURE_UNRESOLVED: ema_10/)
  assert.throws(() => validateDisplayCatalog({ ...manifest, features: { ...features, macd: { ...features.macd, outputs: ['dif'] } } }), /CHART_COMPUTE_SCHEMA_MISMATCH: macd/)
  assert.throws(() => validateDisplayCatalog({ ...manifest, features: { ...features, macd: { ...features.macd, allowed_uses: ['research'] } } }), /CHART_COMPUTE_SCHEMA_MISMATCH: macd/)
})

test('preferences preserve legacy selection and isolate hide, configure and removal by profile', () => {
  const profile = 'newow_trend'
  const defaultAux = CHART_PROFILES[profile].auxiliaryDefault
  assert.equal(defaultAux, 'newow.zhaoyao_mirror')
  const preferences = readChartPreferences(null, profile, [defaultAux, 'htdy', defaultAux])
  assert.deepEqual(preferences.layers, [{ id: defaultAux }])
  const hidden = setChartLayer(preferences, profile, defaultAux, { hidden: true, height: 120 })
  assert.deepEqual(hidden.layers, [{ id: defaultAux, hidden: true, height: 120 }])
  assert.deepEqual(setChartLayer(hidden, profile, defaultAux, null).layers, [])
  assert.throws(() => setChartLayer(hidden, 'subing', defaultAux, {}), /CHART_LAYER_NOT_SELECTABLE/)
  assert.throws(() => readChartPreferences({ ...hidden, schemaVersion: 9 }, profile), /CHART_PREFERENCE_SCHEMA_UNSUPPORTED/)
})

test('repeated auxiliary updates and hide/remove leave owned chart resources at the baseline', () => {
  const activeSeries = new Set()
  const activePrimitives = new Set()
  const activeListeners = new Set()
  const chart = {
    addSeries(definition, _options, pane) {
      const series = {
        definition, pane, rows: [],
        setData(rows) { assert.ok(activeSeries.has(series)); series.rows = rows },
        attachPrimitive(primitive) { assert.ok(activeSeries.has(series)); activePrimitives.add(primitive) },
        detachPrimitive(primitive) { assert.ok(activeSeries.has(series)); assert.ok(activePrimitives.delete(primitive)) },
      }
      activeSeries.add(series)
      return series
    },
    removeSeries(series) { assert.ok(activeSeries.delete(series)) },
    remove() { assert.equal(activeSeries.size, 0) },
  }
  const host = createChartHost(chart)
  const candles = host.layer('price', 'price', 'main').candles({})
  const volume = host.layer('volume', 'generic_volume', 'volume').histogram({ priceScaleId: 'volume' })
  const primary = host.addAuxiliary('primary')
  const axis = host.layer('primary-axis', 'auxiliary_axis', primary).line({})
  const baseline = [candles, volume, axis]
  candles.setData([{ time: 1, open: 10, high: 11, low: 9, close: 10 }])
  for (let index = 0; index < 100; index += 1) {
    const pane = host.addAuxiliary('optional')
    const anchor = host.layer('optional-axis', 'auxiliary_axis', pane).line({})
    const optional = host.layer('optional', 'newow.up_down_energy', pane)
    optional.primitive(anchor, {})
    const listener = () => {}
    activeListeners.add(listener)
    optional.own(() => { assert.ok(activeListeners.delete(listener)) })
    anchor.setData([{ time: 1 }, { time: 2 }])
    anchor.setData([{ time: 1 }, { time: 2 }, { time: 3 }])
    assert.equal(anchor.pane, 2)
    assert.equal(activePrimitives.size, 1)
    assert.equal(activeListeners.size, 1)
    host.removeAuxiliary('optional')
    assert.deepEqual([...activeSeries], baseline)
    assert.equal(activePrimitives.size, 0)
    assert.equal(activeListeners.size, 0)
    assert.equal(candles.rows[0].close, 10)
  }
  host.dispose()
  assert.equal(activePrimitives.size, 0)
  assert.equal(activeListeners.size, 0)
})
