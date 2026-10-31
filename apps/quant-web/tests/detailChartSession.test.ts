import assert from 'node:assert/strict'
import test from 'node:test'
import { createDetailChartSession, detailChartIndex, detailChartLength, detailChartTimeAt } from '../src/utils/detailChartSession.ts'

function fixture() {
  const calls = { creates: 0, removes: 0, candles: 0, updates: 0, overlays: 0, detached: 0 }
  let range: any = { from: 3, to: 7 }
  const container = () => ({ style: {}, appendChild() {}, clientWidth: 1000, clientHeight: 700 }) as any
  const scale = { getVisibleLogicalRange: () => range, setVisibleLogicalRange: (value: any) => { range = value } }
  const panes = [0, 1, 2].map(() => ({ setStretchFactor() {} }))
  const raw = {
    addPane: () => panes[1], panes: () => panes,
    addSeries(definition: any) { return { setData() { if (definition.type === 'Candlestick') calls.candles++ }, update() { calls.updates++ }, applyOptions() {}, attachPrimitive() {}, detachPrimitive() { calls.detached++ }, createPriceLine() { return {} }, removePriceLine() {} } },
    removeSeries() { calls.overlays++ }, applyOptions() {}, timeScale: () => scale, remove() { calls.removes++ },
  } as any
  const session = createDetailChartSession({ createChart: (() => { calls.creates++; return raw }) as any, createContainer: container })
  const candle = { type: 'Candlestick' } as any, line = { type: 'Line' } as any
  const bars = [{ time: 1, open: 1, high: 2, low: 1, close: 2 }]
  return { session, calls, raw, container, candle, line, bars }
}

test('one price series and canvas survive an adapter change without rewriting unchanged candles', () => {
  const f = fixture(); f.session.setIdentity('jm:1d')
  const first = f.session.acquire(f.container(), {})
  const candles = first.addSeries(f.candle)
  candles.setData(f.bars); first.addSeries(f.line)
  candles.attachPrimitive({} as any)
  first.remove()
  const second = f.session.acquire(f.container(), {})
  second.addSeries(f.candle).setData(f.bars)
  assert.equal(f.calls.creates, 1); assert.equal(f.calls.candles, 1)
  assert.equal(f.calls.overlays, 1); assert.equal(f.calls.detached, 1)
  assert.deepEqual(second.timeScale().getVisibleLogicalRange(), { from: 3, to: 7 })
  assert.equal(f.calls.removes, 0)
  f.session.dispose(); assert.equal(f.calls.removes, 1)
})

test('late writes and disposal from an obsolete adapter cannot alter the active chart', () => {
  const f = fixture(); f.session.setIdentity('jm:1d')
  const first = f.session.acquire(f.container(), {}), old = first.addSeries(f.candle)
  old.setData(f.bars)
  const second = f.session.acquire(f.container(), {})
  old.setData([{ ...f.bars[0]!, close: 8 }]); first.remove()
  second.addSeries(f.candle).setData(f.bars)
  assert.equal(f.calls.candles, 1)
  assert.equal(f.calls.removes, 0)
  f.session.dispose()
})

test('new market identity clears old prices and restores its own saved viewport', () => {
  const f = fixture(); f.session.setIdentity('jm:1d')
  const first = f.session.acquire(f.container(), {}); first.addSeries(f.candle).setData(f.bars)
  first.timeScale().setVisibleLogicalRange({ from: 8, to: 12 } as any)
  f.session.setIdentity('rb:60m')
  assert.equal(f.calls.candles, 2, 'old symbol prices are cleared immediately')
  f.session.setIdentity('jm:1d')
  assert.deepEqual(f.session.viewport(), { from: 8, to: 12 })
  f.session.dispose()
})

test('leases remove anonymous subscriptions and block old time-scale mutations', () => {
  const f = fixture(), listeners = new Set<Function>()
  const scale = f.raw.timeScale()
  scale.subscribeVisibleLogicalRangeChange = (fn: Function) => listeners.add(fn)
  scale.unsubscribeVisibleLogicalRangeChange = (fn: Function) => listeners.delete(fn)
  f.session.setIdentity('jm:1d')
  const first = f.session.acquire(f.container(), {})
  first.timeScale().subscribeVisibleLogicalRangeChange(() => {})
  assert.equal(listeners.size, 1)
  const second = f.session.acquire(f.container(), {})
  assert.equal(listeners.size, 0)
  first.timeScale().setVisibleLogicalRange({ from: 90, to: 100 } as any)
  assert.deepEqual(second.timeScale().getVisibleLogicalRange(), { from: 3, to: 7 })
  f.session.dispose()
})

test('native automatic placement is not a saved user viewport, and a live adapter survives period changes', () => {
  const f = fixture(); f.session.setIdentity('jm:1d')
  const first = f.session.acquire(f.container(), {}), candles = first.addSeries(f.candle)
  candles.setData(f.bars)
  assert.equal(f.session.viewport(), null)
  first.timeScale().setVisibleLogicalRange({ from: 1, to: 3 } as any)
  assert.deepEqual(f.session.viewport(), { from: 1, to: 3 })
  f.session.setIdentity('jm:60m'); candles.setData(f.bars)
  assert.equal(f.calls.candles, 3, 'same component can accept new-period prices after the clear')
  f.session.dispose()
})

test('a shorter identical suffix retains loaded history and the same visible bars', () => {
  const f = fixture(); f.session.setIdentity('jm:1d')
  const bars = Array.from({ length: 500 }, (_, time) => ({ time, open: time, high: time + 2, low: time, close: time + 1 }))
  const first = f.session.acquire(f.container(), {}); first.addSeries(f.candle).setData(bars)
  first.timeScale().setVisibleLogicalRange({ from: 40, to: 100 } as any)
  const second = f.session.acquire(f.container(), {}); second.addSeries(f.candle).setData(bars.slice(-300))
  assert.equal(f.calls.candles, 1, 'identical canonical suffix does not discard previously verified history')
  assert.deepEqual(f.session.viewport(), { from: 40, to: 100 })
  assert.equal(detailChartIndex(second, 499 as any, 299), 499)
  assert.equal(detailChartLength(second, 300), 500)
  assert.equal(detailChartTimeAt(second, 40), 40)
  second.addSeries(f.candle).setData(bars.slice(-400))
  assert.deepEqual(f.session.viewport(), { from: 40, to: 100 }, 'loading a locally missing but already retained prefix does not shift the shared axis')
  f.session.dispose()
})

test('changed history replaces facts and maps the viewport by common bar time', () => {
  const f = fixture(); f.session.setIdentity('jm:1d')
  const bars = Array.from({ length: 500 }, (_, time) => ({ time, open: time, high: time + 2, low: time, close: time + 1 }))
  const first = f.session.acquire(f.container(), {}); first.addSeries(f.candle).setData(bars)
  first.timeScale().setVisibleLogicalRange({ from: 400, to: 499 } as any)
  const corrected = bars.slice(-300).map(bar => ({ ...bar, close: bar.close + .1 }))
  const second = f.session.acquire(f.container(), {}); second.addSeries(f.candle).setData(corrected)
  assert.equal(f.calls.candles, 2)
  assert.deepEqual(f.session.viewport(), { from: 200, to: 299 })
  f.session.dispose()
})
