import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
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

test('a rejected renderer leaves an actionable diagnostic and releases only its own resources', () => {
  const { chart, series } = chartAdapter()
  const host = createChartHost(chart)
  const candles = host.layer('price', 'price', 'main').candles({})
  const stable = host.layer('ema', 'ema_10', 'main').line({})
  assert.equal(host.renderLayer('boll', 'boll', 'main', 'band', layer => {
    layer.band({}, {})
    layer.updateDiagnostics({ status: 'ready', dataCutoff: '2026-11-26', sourceIdentity: 'old-result',
      formulaVersion: 'old-formula', warmup: { available: 12, required: 10 }, frequency: '15m' })
  }), true)
  assert.equal(series.size, 4)
  assert.equal(host.renderLayer('boll', 'boll', 'main', 'band', () => {
    throw new Error('native coordinates and raw payload')
  }), false)
  assert.deepEqual([...series], [candles, stable])
  const failed = host.inspectLayer('boll')
  assert.equal(failed.status, 'renderer_failure')
  assert.equal(failed.lastError, 'CHART_RENDERER_UPDATE_FAILED')
  assert.equal(failed.sourceIdentity, null)
  assert.equal(failed.dataCutoff, null)
  assert.equal(failed.formulaVersion, null)
  assert.equal(failed.warmup, null)
  assert.equal(failed.frequency, null)

  assert.equal(host.renderLayer('unknown', 'unknown-indicator', 'main', 'line', () => assert.fail('unexpected render')), false)
  assert.equal(host.inspectLayer('unknown').status, 'catalog_mismatch')
  assert.equal(host.inspectLayer('unknown').lastError, 'CHART_DISPLAY_NOT_REGISTERED')
  assert.equal(host.renderLayer('ema', 'ema_10', 'main', 'histogram', () => assert.fail('wrong renderer')), false)
  assert.equal(host.inspectLayer('ema').lastError, 'CHART_DISPLAY_RENDERER_MISMATCH')
  assert.deepEqual([...series], [candles])
  host.removeLayer('unknown')
  assert.equal(host.inspectLayer('unknown'), null)
  assert.equal(host.renderLayer('boll', 'boll', 'main', 'band', layer => {
    layer.band({}, {})
    layer.updateDiagnostics({ status: 'ready' })
  }), true)
  assert.equal(host.inspectLayer('boll').status, 'ready')
  assert.equal(host.inspectLayer('boll').lastError, null)
  host.activate('RB:5m:updated')
  assert.equal(host.inspectLayer('ema'), null)
  assert.equal(series.size, 3)
  host.dispose()
  assert.equal(series.size, 0)
})

test('partial native allocation and failed primitive attachment are reclaimed', () => {
  const { chart, series, events } = chartAdapter()
  const add = chart.addSeries.bind(chart)
  const host = createChartHost(chart)
  const candles = host.layer('price', 'price', 'main').candles({})
  let calls = 0
  chart.addSeries = (...args) => {
    if (++calls === 2) throw new Error('second series')
    return add(...args)
  }
  assert.equal(host.renderLayer('boll', 'boll', 'main', 'band', layer => layer.band({}, {})), false)
  assert.deepEqual([...series], [candles])
  candles.attachPrimitive = () => { events.push('partial-attach'); throw new Error('initial paint') }
  assert.equal(host.renderLayer('pattern', 'newow_pattern', 'main', 'primitive',
    layer => layer.primitive(candles, {})), false)
  assert.deepEqual(events.slice(-2), ['partial-attach', 'detach'])
  host.dispose()
})

test('the native marker factory cannot leave an attachment when construction throws', () => {
  const { chart } = chartAdapter()
  const host = createChartHost(chart)
  const candles = host.layer('price', 'price', 'main').candles({})
  const attached = new Set()
  candles.attachPrimitive = primitive => {
    attached.add(primitive)
    throw new Error('attachment callback failed before the marker factory returned')
  }
  candles.detachPrimitive = primitive => { assert.ok(attached.delete(primitive)) }
  for (let attempt = 0; attempt < 3; attempt++) {
    assert.equal(host.renderLayer('actions', 'newow_actions', 'main', 'marker', layer => layer.markers(candles)), false)
    assert.equal(host.inspectLayer('actions').lastError, 'CHART_RENDERER_UPDATE_FAILED')
    assert.equal(attached.size, 0)
  }
  host.dispose()
})

test('a later paint failure quarantines just the primitive, and retry rejects obsolete callbacks', async () => {
  const { chart, series } = chartAdapter()
  const host = createChartHost(chart)
  const candles = host.layer('price', 'price', 'main').candles({})
  const attached = new Set()
  candles.attachPrimitive = primitive => attached.add(primitive)
  candles.detachPrimitive = primitive => { assert.ok(attached.delete(primitive)) }
  const layer = host.layer('overlay', 'newow_pattern', 'main')
  let attempts = 0
  let fail = true
  const view = {
    renderer: () => renderer,
  }
  const renderer = {
    draw() {
      attempts++
      if (fail) throw new Error('private canvas message')
    },
  }
  const views = [view]
  const primitive = { paneViews: () => views }
  layer.primitive(candles, primitive)
  layer.updateDiagnostics({ status: 'ready', sourceIdentity: 'prior', formulaVersion: 'prior', dataCutoff: 'prior' })
  const first = [...attached][0]
  const list = first.paneViews()
  assert.equal(first.paneViews(), list)
  const firstPainter = list[0].renderer()
  assert.equal(list[0].renderer(), firstPainter)
  firstPainter.draw({})
  firstPainter.draw({})
  assert.equal(attempts, 1)
  assert.equal(attached.size, 1, 'never detach while native draw is iterating')
  assert.equal(layer.inspect().lastError, 'CHART_RENDERER_PAINT_FAILED')
  layer.updateDiagnostics({ status: 'ready', sourceIdentity: 'unpainted' })
  assert.equal(layer.inspect().sourceIdentity, null)
  assert.equal(layer.inspect().status, 'renderer_failure')
  await Promise.resolve()
  assert.equal(layer.hasResource(primitive), false)
  assert.equal(attached.size, 0)
  assert.deepEqual([...series], [candles])

  fail = false
  layer.primitive(candles, primitive)
  const second = [...attached][0]
  assert.notEqual(second, first)
  firstPainter.draw({})
  assert.equal(attempts, 1)
  second.paneViews()[0].renderer().draw({})
  assert.equal(attempts, 2)
  assert.equal(layer.inspect().status, 'ready')
  host.dispose()
})

test('a failed native marker paint clears the plugin once even if the view is replaced first', async () => {
  const { chart } = chartAdapter()
  const host = createChartHost(chart)
  const candles = host.layer('price', 'price', 'main').candles({})
  const attached = new Set()
  candles.attachPrimitive = primitive => attached.add(primitive)
  candles.detachPrimitive = primitive => { assert.ok(attached.delete(primitive)) }
  const factory = series => {
    const marker = {
      paneViews: () => [{ renderer: () => ({
        draw() {},
        drawBackground() { throw new Error('background paint failed') },
      }) }],
    }
    series.attachPrimitive(marker)
    return { detach: () => series.detachPrimitive(marker) }
  }
  const original = host.layer('marks', 'newow_actions', 'main')
  original.markers(candles, factory)
  const native = [...attached][0]
  native.paneViews()[0].renderer().drawBackground({})
  assert.equal(original.inspect().renderer, 'marker')
  host.removeLayer('marks')
  const replacement = host.layer('marks', 'newow_actions', 'main')
  replacement.markers(candles, factory)
  await Promise.resolve()
  assert.equal(attached.size, 1)
  assert.equal(replacement.inspect().lastError, null)
  host.dispose()
  assert.equal(attached.size, 0)
})

test('real marker paint failure restores Fancy Canvas state and releases the native subscription', async () => {
  const { CanvasRenderingTarget2D } = createRequire(import.meta.resolve('lightweight-charts'))('fancy-canvas')
  const timeScale = {
    options: () => ({ barSpacing: 10 }), getVisibleLogicalRange: () => ({ from: 0, to: 3 }),
    timeToIndex: () => 1, logicalToCoordinate: () => 20,
  }
  const chart = { timeScale: () => timeScale, options: () => ({ layout: { fontSize: 10, fontFamily: 'sans-serif' } }), remove() {} }
  const bar = { time: 1, value: 4 }
  const listeners = new Set()
  let current
  let released = 0
  const native = {
    attachPrimitive(primitive) {
      current = primitive
      primitive.attached({ chart, series: native, requestUpdate() {} })
    },
    detachPrimitive(primitive) { assert.equal(primitive, current); primitive.detached(); current = undefined },
    subscribeDataChanged(listener) { listeners.add(listener) },
    unsubscribeDataChanged(listener) { assert.ok(listeners.delete(listener)) },
    options: () => ({ visible: true }), data: () => [bar], dataByIndex: () => bar,
    priceScale: () => ({ options: () => ({ invertScale: false }) }), priceToCoordinate: value => value,
  }
  const host = createChartHost(chart)
  let depth = 0
  let crashes = 0
  const context = {
    save() { depth++ }, restore() { depth-- }, setTransform() {}, scale() {},
    measureText: () => ({ width: 4, actualBoundingBoxAscent: 2, actualBoundingBoxDescent: 1 }),
    fillText() { crashes++; throw new Error('injected text paint failure') },
  }
  const save = context.save
  const size = { width: 100, height: 100 }
  const target = new CanvasRenderingTarget2D(context, size, size)
  for (let attempt = 1; attempt <= 3; attempt++) {
    const layer = host.layer('marks', 'newow_actions', 'main')
    const plugin = layer.markers(native, undefined, () => released++)
    assert.equal(listeners.size, 1)
    plugin.setMarkers([{ time: 1, position: 'atPriceMiddle', price: 4, color: 'red', shape: 'circle', text: 'X' }])
    current.updateAllViews()
    current.paneViews()[0].renderer().draw(target)
    assert.equal(crashes, attempt)
    assert.equal(depth, 0)
    assert.equal(context.save, save)
    assert.equal(layer.inspect().lastError, 'CHART_RENDERER_PAINT_FAILED')
    await Promise.resolve()
    assert.equal(released, attempt)
    assert.equal(current, undefined)
    assert.equal(listeners.size, 0)
    host.removeLayer('marks')
  }
  for (let index = 0; index < 100; index++) {
    host.layer('marks', 'newow_actions', 'main').markers(native)
    assert.equal(listeners.size, 1)
    host.removeLayer('marks')
    assert.equal(current, undefined)
    assert.equal(listeners.size, 0)
  }
  host.dispose()
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
