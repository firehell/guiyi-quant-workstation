import assert from 'node:assert/strict'
import test from 'node:test'
import { createChartHost } from '@guiyi/quant-chart'
import { createDetailChartSession, detailChartVolumeBars, detailChartIndex, detailChartLength, detailChartTimeAt, placeDetailChartViewport } from '../src/utils/detailChartSession.ts'

function fixture() {
  const calls = { creates: 0, removes: 0, candles: 0, updates: 0, overlays: 0, detached: 0 }
  let range: any = { from: 3, to: 7 }
  const surfaceListeners = new Map<string, (event: any) => void>()
  const container = () => ({ style: {}, appendChild() {}, clientWidth: 1000, clientHeight: 700,
    addEventListener(name: string, listener: (event: any) => void) { surfaceListeners.set(name, listener) },
    removeEventListener(name: string, listener: (event: any) => void) {
      if (surfaceListeners.get(name) === listener) surfaceListeners.delete(name)
    },
  }) as any
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
  return { session, calls, raw, container, candle, line, bars, surfaceListeners }
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

for (const reuse of [false, true]) test(`an unsuccessful primary candle ${reuse ? 'configuration' : 'allocation'} leaves the lease eligible for retry`, () => {
  const f = fixture()
  const addSeries = f.raw.addSeries.bind(f.raw)
  let fail = !reuse
  let candles = 0
  f.raw.addSeries = (definition: typeof f.candle) => {
    if (definition.type === 'Candlestick' && fail) throw Error('primary candle failure')
    if (definition.type === 'Candlestick') candles++
    return Object.assign(addSeries(definition), { applyOptions() { if (fail) throw Error('primary candle failure') } })
  }
  if (reuse) {
    const first = f.session.acquire(f.container(), {})
    first.addSeries(f.candle).setData(f.bars)
    first.remove()
    fail = true
  }
  const lease = f.session.acquire(f.container(), {})
  assert.throws(() => lease.addSeries(f.candle), /primary candle failure/)
  fail = false
  lease.addSeries(f.candle).setData([...f.bars, { ...f.bars[0]!, time: 2 }])
  assert.equal(f.session.length(), 2)
  assert.equal(candles, 1)
  f.session.dispose()
})

test('a partial native attachment is removed through the page lease before an indicator retry', () => {
  const f = fixture()
  const original = f.raw.addSeries.bind(f.raw)
  const pattern = { testAttachment: 'pattern' }
  const attached = new Set<unknown>()
  let fail = true
  f.raw.addSeries = (...args: unknown[]) => Object.assign(original(...args), {
    attachPrimitive(primitive: unknown) {
      assert.equal(attached.has(primitive), false)
      attached.add(primitive)
      if ((primitive as typeof pattern).testAttachment === 'pattern' && fail) throw new Error('native attached callback failed')
    },
    detachPrimitive(primitive: unknown) { assert.ok(attached.delete(primitive)) },
  })
  const host = createChartHost(f.session.acquire(f.container(), {}))
  const candles = host.layer('price', 'price', 'main').candles({})
  const render = () => host.renderLayer('pattern', 'newow_pattern', 'main', 'primitive', layer => {
    layer.primitive(candles, pattern)
    layer.updateDiagnostics({ status: 'ready' })
  })
  assert.equal(render(), false)
  assert.equal(host.inspectLayer('pattern')?.lastError, 'CHART_RENDERER_UPDATE_FAILED')
  assert.equal(attached.size, 2, 'the independent execution layers remain attached')
  fail = false
  assert.equal(render(), true)
  assert.equal(host.inspectLayer('pattern')?.status, 'ready')
  assert.equal(attached.size, 3)
  host.dispose()
  assert.equal(attached.size, 2)
  f.session.dispose()
  assert.equal(attached.size, 0)
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

test('execution diagnostics bind each authority to positioned records and clear on identity change', () => {
  const f = fixture()
  f.session.setIdentity('jm:15m')
  const point = { from: 1, to: 1, ratio: 0, price: 2, physicalContract: 'JM2701' } as const
  f.session.setExecutions([
    { ...point, id: 'native-fill', at: '2026-09-03T02:30:00.000001Z', source: '快期原生成交' },
    { ...point, id: 'latest', at: '2026-09-03T10:30:00.000009+08:00', source: '快期原生成交' },
    { ...point, id: 'paper-fill', at: '2026-09-03T02:30:00Z', source: '苏冰模型成交' },
    { ...point, to: 2, id: 'unanchored', at: '2026-09-03T02:45:00Z', source: '快期原生委托' },
  ], '15m')
  assert.deepEqual(f.session.inspectExecutionLayers(), [])
  const lease = f.session.acquire(f.container(), {})
  const candles = lease.addSeries(f.candle)
  const bind = (physicalContract: string) => f.bars.map(bar => ({ ...bar, physicalContract }))
  candles.setData(bind('JM2701'))
  const rows = () => f.session.inspectExecutionLayers().map(row =>
    [row.indicatorId, row.status, row.sourceIdentity, row.dataCutoff, row.frequency],
  )
  assert.deepEqual(rows(), [
    ['reconciliation_executions', 'ready', 'latest', '2026-09-03T10:30:00.000009+08:00', '15m'],
    ['paper_executions', 'ready', 'paper-fill', '2026-09-03T02:30:00Z', '15m'],
  ])
  const preview = lease.addSeries(f.candle)
  preview.setData([{ ...f.bars[0]!, time: 2 }])
  assert.equal(f.session.timeAt(Infinity), 1, 'preview uses a separate native series')
  assert.deepEqual(rows().map(row => row[1]), ['ready', 'ready'])
  candles.setData(bind('JM2705'))
  assert.deepEqual(rows(), [
    ['reconciliation_executions', 'missing_input', null, null, '15m'],
    ['paper_executions', 'missing_input', null, null, '15m'],
  ])
  f.session.setIdentity('rb:15m')
  assert.deepEqual(rows(), [
    ['reconciliation_executions', 'hidden', null, null, null],
    ['paper_executions', 'hidden', null, null, null],
  ])
  f.session.dispose()
})

test('a failed candle update withdraws execution placement until a full repair binds the owners', () => {
  const f = fixture()
  const addSeries = f.raw.addSeries.bind(f.raw)
  f.raw.addSeries = (...args: unknown[]) => Object.assign(addSeries(...args), {
    update() { throw Error('injected native update failure') },
  })
  const lease = f.session.acquire(f.container(), {})
  const candles = lease.addSeries(f.candle)
  const point = { from: 1, to: 1, ratio: 0, price: 2, physicalContract: 'JM2701', at: '2026-09-03T02:30:00Z' } as const
  f.session.setExecutions([
    { ...point, id: 'native-fill', source: '快期原生成交' },
    { ...point, id: 'paper-fill', source: '苏冰模型成交' },
  ], '15m')
  const first = { ...f.bars[0]!, physicalContract: 'JM2701' }
  candles.setData([first])
  const sources = () => f.session.inspectExecutionLayers().map(row => row.sourceIdentity)
  assert.deepEqual(sources(), ['native-fill', 'paper-fill'])
  const next = [first, { ...first, time: 2 }]
  assert.throws(() => candles.setData(next), /injected native update failure/)
  assert.deepEqual(sources(), [null, null])
  assert.equal(f.session.indexOf(1 as any), null)
  candles.setData(next)
  assert.deepEqual(sources(), ['native-fill', 'paper-fill'])
  assert.equal(f.calls.candles, 2)
  f.session.dispose()
})

test('an identity change withdraws both price windows even if one native clear throws', () => {
  const f = fixture()
  const calls: string[] = []
  let rejectClear = false
  const addSeries = f.raw.addSeries.bind(f.raw)
  f.raw.addSeries = (definition: { type: string }, ...args: unknown[]) => Object.assign(addSeries(definition, ...args), {
    setData(points: unknown[]) {
      calls.push(`${definition.type}:${points.length}`)
      if (rejectClear && !points.length && definition.type === 'Candlestick') throw Error('injected clear failure')
    },
    applyOptions(options: { visible: boolean }) { calls.push(`${definition.type}:visible=${options.visible}`) },
  })
  f.session.setIdentity('jm:15m')
  const lease = f.session.acquire(f.container(), {})
  const candles = lease.addSeries(f.candle)
  const volume = lease.addSeries({ type: 'Histogram' } as any, { priceScaleId: 'volume' })
  candles.setData(f.bars)
  volume.setData([{ time: 1 as any, value: 5 }])
  f.session.mergeVolumeBars([{ ...f.bars[0]!, time: '2026-09-03T02:30:00Z', volume: 5 }])

  rejectClear = true
  f.session.setIdentity('rb:15m')
  assert.deepEqual(calls.slice(-3), ['Candlestick:0', 'Candlestick:visible=false', 'Histogram:0'])
  assert.equal(f.session.indexOf(1 as any), null)
  assert.equal(f.session.length(), 0)
  assert.deepEqual(f.session.mergeVolumeBars([]), [])
  candles.setData([{ ...f.bars[0]!, time: 2 }])
  assert.deepEqual(calls.slice(-2), ['Candlestick:1', 'Candlestick:visible=true'])
  assert.equal(f.session.timeAt(0), 2)
  f.session.dispose()
})

test('base provenance follows a shared canvas lease and expires with the market identity', () => {
  const f = fixture()
  f.session.setIdentity('jm:15m')
  const first = f.session.acquire(f.container(), {})
  first.addSeries(f.candle).setData(f.bars)
  const fact = { frequency: '15m', dataCutoff: '2026-09-03T02:30:00Z', sourceIdentity: 'checked-bar',
    formulaVersion: null, cacheState: 'miss' as const, physicalContract: 'JM2701' }
  const diagnostic = { ...fact, renderer: 'candles', indicatorId: 'price' }
  f.session.recordBaseLayer('candles', diagnostic)
  f.session.acquire(f.container(), {}).addSeries(f.candle).setData([])
  assert.deepEqual(f.session.readBaseLayer('candles'), fact)
  f.session.setIdentity('rb:15m')
  assert.equal(f.session.readBaseLayer('candles'), undefined)
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

for (const gesture of ['wheel', 'pointermove']) test(`automatic viewport placement yields to ${gesture} and releases its listener`, () => {
  const f = fixture()
  f.session.setIdentity('jm:1d')
  const first = f.session.acquire(f.container(), {})
  first.addSeries(f.candle).setData(f.bars)
  placeDetailChartViewport(first, { from: 0, to: 1 })
  assert.deepEqual(first.timeScale().getVisibleLogicalRange(), { from: 0, to: 1 })
  assert.equal(f.session.viewport(), null)
  f.surfaceListeners.get('pointermove')?.({ buttons: 0, movementX: 3, movementY: 0 })
  assert.equal(f.session.viewport(), null)
  f.surfaceListeners.get(gesture)?.({ buttons: 1, movementX: 3, movementY: 0 })
  f.raw.timeScale().setVisibleLogicalRange({ from: .1, to: 1.1 })
  assert.deepEqual(f.session.viewport(), { from: .1, to: 1.1 })
  const second = f.session.acquire(f.container(), {})
  placeDetailChartViewport(first, { from: 7, to: 8 })
  assert.deepEqual(second.timeScale().getVisibleLogicalRange(), { from: .1, to: 1.1 })
  f.session.resetWindow()
  assert.equal(f.session.viewport(), null)
  f.session.dispose()
  assert.equal(f.surfaceListeners.size, 0)
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


test('crosshair forwarding unwraps leased series and rejects writes after release',()=>{
 const f=fixture();f.session.setIdentity('rb:60m')
 const original=f.raw.addSeries.bind(f.raw);let nativeSeries:any,received:any[]=[]
 f.raw.addSeries=(...args:any[])=>{nativeSeries=original(...args);return nativeSeries}
 f.raw.setCrosshairPosition=(price:any,time:any,series:any)=>received.push([price,time,series])
 const lease=f.session.acquire(f.container(),{}),wrapped=lease.addSeries(f.candle)
 lease.setCrosshairPosition(105,123 as any,wrapped)
 assert.equal(received.length,1);assert.equal(received[0][2]===nativeSeries,true)
 lease.remove();lease.setCrosshairPosition(110,124 as any,wrapped);assert.equal(received.length,1)
 f.session.dispose()
})


test('retained main-pane volume is shared by Free and Newow without rewriting facts', () => {
  const f = fixture(), histogram = { type: 'Histogram' } as any
  let pane = 1, writes = 0, options: any = {}, creates = 0
  const original = f.raw.addSeries
  f.raw.addSeries = (definition: any, settings: any, index = 0) => {
    if (definition.type !== 'Histogram') return original(definition, settings, index)
    creates++; pane = index; options = settings
    return { setData() { writes++ }, applyOptions(value: any) { options = { ...options, ...value } },
      getPane: () => ({ paneIndex: () => pane }), moveToPane(value: number) { pane = value } }
  }
  f.session.setIdentity('jm:1d')
  const data = [{ time: 1, value: 100 }]
  const free = f.session.acquire(f.container(), {})
  free.addSeries(histogram, { priceScaleId: 'volume' }, 0).setData(data)
  const newow = f.session.acquire(f.container(), {})
  newow.addSeries(histogram, { priceScaleId: 'volume' }, 0).setData(data)
  assert.equal(pane, 0); assert.equal(options.priceScaleId, 'volume')
  const back = f.session.acquire(f.container(), {})
  back.addSeries(histogram, { priceScaleId: 'volume' }, 0).setData(data)
  assert.equal(pane, 0); assert.equal(options.priceScaleId, 'volume')
  assert.equal(creates, 1); assert.equal(writes, 1)
  f.session.dispose()
})

test('volume source suffix retains history for scoring and explanations and resets with identity', () => {
 const f=fixture();f.session.setIdentity('jm:1d')
 const input=Array.from({length:20},(_,i)=>({time:String(i),open:100,high:110,low:90,close:108,volume:100,physicalContract:'JM2701',calculationSegmentId:'c'}))
 const full=f.session.mergeVolumeBars(input)
 assert.equal(full.length,20)
 const tail=f.session.mergeVolumeBars(input.slice(12))
 assert.deepEqual(tail,full)
 assert.equal(tail[0]!.time,'0','retained bars remain addressable by explanation time')
 const corrected=input.slice(12).map(b=>({...b,volume:200}))
 assert.deepEqual(f.session.mergeVolumeBars(corrected),corrected,'changed facts do not silently reuse stale history')
 f.session.setIdentity('rb:1d');assert.deepEqual(f.session.mergeVolumeBars([]),[])
 f.session.dispose()
})

test('MACD in pane one is not retained as volume',()=>{
 const f=fixture(),histogram={type:'Histogram'} as any
 let creates=0
 const original=f.raw.addSeries
 f.raw.addSeries=(...args:any[])=>{creates++;return original(...args)}
 f.session.acquire(f.container(),{}).addSeries(histogram,{base:0},1)
 f.session.acquire(f.container(),{}).addSeries(histogram,{base:0},1)
 assert.equal(creates,2,'strategy auxiliary series are leased, not retained price facts')
 f.session.dispose()
})

test('short preview volume replaces old histogram colors instead of retaining yellow prefix',()=>{
 const f=fixture(),histogram={type:'Histogram'} as any
 let plotted:any[]=[]
 f.raw.addSeries=()=>({setData(data:any[]){plotted=data},update(point:any){plotted.push(point)},applyOptions(){}})
 f.session.setIdentity('jm:1d')
 const lease=f.session.acquire(f.container(),{}),volume=lease.addSeries(histogram,{priceScaleId:'volume'},0)
 volume.setData([{time:1 as any,value:10,color:'#D9A400'},{time:2 as any,value:20,color:'#D9A400'}])
 volume.setData([{time:2 as any,value:20,color:'rgba(255,59,48,0.6)'}])
 assert.equal(plotted.length,1);assert.equal(plotted[0].color,'rgba(255,59,48,0.6)')
 f.session.dispose()
})

test('an expired adapter cannot change the shared volume input window',()=>{
 const f=fixture(),first=f.session.acquire(f.container(),{})
 const input=[{time:'2026-11-01T07:00:00Z',open:1,high:2,low:1,close:2,volume:100,physicalContract:'JM2701',calculationSegmentId:'c'}]
 detailChartVolumeBars(first,input)
 const second=f.session.acquire(f.container(),{})
 detailChartVolumeBars(first,[{...input[0]!,volume:200}])
 assert.deepEqual(detailChartVolumeBars(second,[]),input)
 f.session.dispose()
})
