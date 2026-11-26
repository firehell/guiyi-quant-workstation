import assert from 'node:assert/strict'
import test from 'node:test'
import { effectScope, nextTick, ref } from 'vue'
import { useDynamicRange, type RangeQuery } from '../src/composables/useDynamicRange.ts'
import type { BarData } from '../src/types/market.ts'
const makeBar=(day:number,contract='JM2701'):BarData=>({time:`2026-01-${String(day).padStart(2,'0')}T07:00:00Z`,physicalContract:contract,open:100,high:102,low:98,close:101,volume:1})
const body=(q:RangeQuery,bs:BarData[])=>({version:'subing_dynamic_range_v2',trend_version:'subing_ema21_ols5_atr14_v2',profile:'bounded_confirmed',symbol:q.symbol,contract:q.contract,frequency:q.frequency,source_proof:{lifecycle_hash:'c'.repeat(64),partitions:{'2026-1':'d'.repeat(64)}},source_hash:'a'.repeat(64),prefix_start:'2025-01-01T00:00:00Z',points:bs.map(b=>({...b,contract:q.contract,phase:'SEARCHING',regime:'RANGE',reason:null,er:.2,chop:60,trend_candidate:false,break_side:null,box:null}))})
async function settle(){await nextTick();await new Promise(r=>setTimeout(r,0));await nextTick()}
test('prepend requests only missing history and never recalculates previously shown points',async()=>{
 const scope=effectScope(),bars=ref([makeBar(3),makeBar(4)]),enabled=ref(true),calls:RangeQuery[]=[]
 const state=scope.run(()=>useDynamicRange({enabled,bars,canonicalEnd:ref(bars.value.at(-1)!.time),identity:ref('jm:30m'),symbol:ref('jm'),frequency:ref('30m'),fetch:async q=>{calls.push(q);return body(q,bars.value.filter(b=>b.time>=q.start&&b.time<=q.end))}}))!
 await settle();assert.equal(state.points.value.length,2)
 const old=state.points.value[0]
 bars.value=[makeBar(1),makeBar(2),...bars.value];await settle()
 assert.equal(state.points.value.length,4);assert.equal(state.points.value[2],old)
 assert.equal(calls[1].end,makeBar(2).time)
 // Live-only append is not admitted to the canonical calculation.
 bars.value=[...bars.value,makeBar(5)];await settle();assert.equal(calls.length,2)
 scope.stop()
})
test('late previous identity result is discarded even if transport ignores abort',async()=>{
 const scope=effectScope(),bars=ref([makeBar(3)]),identity=ref('jm:30m'),symbol=ref('jm')
 const pending:Array<{q:RangeQuery;resolve:(v:unknown)=>void;signal:AbortSignal}>=[]
 const state=scope.run(()=>useDynamicRange({enabled:ref(true),bars,canonicalEnd:ref(bars.value[0].time),identity,symbol,frequency:ref('30m'),fetch:(q,signal)=>new Promise(resolve=>pending.push({q,resolve,signal}))}))!
 await settle();identity.value='ma:30m';symbol.value='ma';bars.value=[makeBar(3,'MA701')];await settle()
 assert.equal(pending[0].signal.aborted,true)
 pending[1].resolve(body(pending[1].q,bars.value));await settle()
 pending[0].resolve(body(pending[0].q,[makeBar(3)]));await settle()
 assert.equal(state.points.value[0].contract,'MA701');scope.stop()
})
test('failed earlier page retains known points; correcting an already shown candle blocks silent rewrite',async()=>{
 const scope=effectScope(),bars=ref([makeBar(3)]),enabled=ref(true)
 let fail=false
 const state=scope.run(()=>useDynamicRange({enabled,bars,canonicalEnd:ref(bars.value[0].time),identity:ref('jm:30m'),symbol:ref('jm'),frequency:ref('30m'),fetch:async q=>{if(fail)throw Error('offline');return body(q,bars.value)}}))!
 await settle();const old=state.points.value[0];fail=true;bars.value=[makeBar(2),...bars.value];await settle()
 assert.equal(state.points.value[0],old);assert.ok(state.error.value)
 bars.value=[{...makeBar(3),close:100}];await settle();assert.equal(state.points.value.length,0);assert.match(state.error.value!,/历史行情已变化/)
 scope.stop()
})

test('hidden prefix revisions block mixing even when displayed OHLC is unchanged',async()=>{
 const scope=effectScope(),bars=ref([makeBar(3)]),enabled=ref(true)
 let changed=false,calls=0
 const state=scope.run(()=>useDynamicRange({enabled,bars,canonicalEnd:ref(bars.value[0].time),identity:ref('jm:30m'),symbol:ref('jm'),frequency:ref('30m'),fetch:async q=>{
   calls++;const r=body(q,bars.value.filter(b=>b.time>=q.start&&b.time<=q.end));if(changed)r.source_proof.partitions['2026-1']='e'.repeat(64);return r
 }}))!
 await settle();assert.equal(state.points.value.length,1)
 changed=true;bars.value=[makeBar(2),...bars.value];await settle()
 assert.equal(state.points.value.length,0);assert.match(state.error.value!,/前缀来源已变化/)
 await state.refresh();assert.equal(calls,2)
 enabled.value=false;await settle();enabled.value=true;await settle()
 assert.equal(state.points.value.length,2);scope.stop()
})

test('60m is supported and stays separate from unsupported periods',async()=>{
 const scope=effectScope(),bars=ref([makeBar(3)]),frequency=ref('60m'),identity=ref('jm:60m'),calls:RangeQuery[]=[]
 const state=scope.run(()=>useDynamicRange({enabled:ref(true),bars,canonicalEnd:ref(bars.value[0].time),identity,symbol:ref('jm'),frequency,fetch:async q=>{calls.push(q);return body(q,bars.value)}}))!
 await settle();assert.equal(state.supported.value,true);assert.equal(state.points.value.length,1);assert.equal(calls[0].frequency,'60m')
 frequency.value='15m';identity.value='jm:15m';await settle();assert.equal(state.supported.value,false);assert.equal(state.points.value.length,0);assert.equal(calls.length,1)
 scope.stop()
})

test('window proof follows the accepted points across prepends and a physical contract change', async () => {
  const scope = effectScope()
  const bars = ref([makeBar(3)])
  const canonicalEnd = ref<string | null>(makeBar(5).time)
  const calls: RangeQuery[] = []
  const state = scope.run(() => useDynamicRange({
    enabled: ref(true), bars, canonicalEnd, identity: ref('jm:30m'), symbol: ref('jm'), frequency: ref('30m'),
    fetch: async query => {
      calls.push(query)
      return { ...body(query, bars.value.filter(bar => bar.time >= query.start && bar.time <= query.end)),
        source_hash: (query.contract === 'JM2705' ? 'e' : query.end === makeBar(3).time ? 'b' : 'f').repeat(64) }
    },
  }))!
  await settle()
  bars.value = [makeBar(2), makeBar(3), makeBar(4, 'JM2705'), { ...makeBar(5, 'JM2705'), confirmed: false }]
  await settle()
  assert.deepEqual(calls.map(query => query.contract), ['JM2701', 'JM2701', 'JM2705'])
  assert.deepEqual(state.display.value?.points.map(point => point.prefixSourceHash), ['f', 'b', 'e'].map(char => char.repeat(64)))
  canonicalEnd.value = makeBar(3).time
  assert.deepEqual(state.display.value?.points, [])
  await settle()
  assert.equal(state.display.value?.points.at(-1)?.prefixSourceHash, 'b'.repeat(64))
  assert.equal(calls.length, 4)
  canonicalEnd.value = null
  await settle()
  assert.deepEqual(state.display.value?.points, [])
  canonicalEnd.value = makeBar(3).time
  await settle()
  assert.equal(calls.length, 5)
  scope.stop()
})

test('a changed sampled Bar hash or a server-side prefix revision invalidates old provenance', async () => {
  const scope = effectScope()
  const bars = ref([{ ...makeBar(3), sourceBarSha256: 'b'.repeat(64) }])
  const enabled = ref(true)
  let changedDuringRead = false
  const state = scope.run(() => useDynamicRange({
    enabled, bars, canonicalEnd: ref(makeBar(3).time), identity: ref('jm:30m'), symbol: ref('jm'), frequency: ref('30m'),
    fetch: async query => {
      if (changedDuringRead) throw { response: { data: { detail: { code: 'DYNAMIC_RANGE_SOURCE_CHANGED' } } } }
      return body(query, bars.value.filter(bar => bar.time >= query.start && bar.time <= query.end))
    },
  }))!
  await settle()
  bars.value = [{ ...bars.value[0]!, sourceBarSha256: 'c'.repeat(64) }]
  await settle()
  assert.deepEqual(state.display.value?.points, [])
  assert.equal(state.display.value?.issue?.code, 'DYNAMIC_RANGE_BAR_CHANGED')
  enabled.value = false; await settle(); enabled.value = true; await settle()
  assert.equal(state.display.value?.points.length, 1)
  changedDuringRead = true
  bars.value = [{ ...makeBar(2), sourceBarSha256: 'd'.repeat(64) }, ...bars.value]
  await settle()
  assert.deepEqual(state.display.value?.points, [])
  assert.equal(state.display.value?.issue?.code, 'DYNAMIC_RANGE_SOURCE_CHANGED')
  scope.stop()
})

test('an aborted window conflict cannot block a newer canonical window in the same scope', async () => {
  const scope = effectScope()
  const bars = ref([makeBar(3)])
  const canonicalEnd = ref(makeBar(3).time)
  const pending: Array<{ query: RangeQuery; reject: (error: Error) => void; resolve: (value: unknown) => void }> = []
  const state = scope.run(() => useDynamicRange({
    enabled: ref(true), bars, canonicalEnd, identity: ref('jm:30m'), symbol: ref('jm'), frequency: ref('30m'),
    fetch: query => new Promise((resolve, reject) => pending.push({ query, resolve, reject })),
  }))!
  pending[0]!.reject(Error('DYNAMIC_RANGE_SOURCE_CHANGED'))
  bars.value = [makeBar(4)]
  canonicalEnd.value = makeBar(4).time
  await settle()
  assert.equal(pending.length, 2)
  pending[1]!.resolve(body(pending[1]!.query, bars.value))
  await settle()
  assert.equal(state.display.value?.issue, null)
  assert.equal(state.display.value?.points[0]?.time, canonicalEnd.value)
  scope.stop()
})
