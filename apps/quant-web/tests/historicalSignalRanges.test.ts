import assert from 'node:assert/strict'
import { it } from 'node:test'
import { ref } from 'vue'
import { actualEventsToOwnedMarkers, canonicalHistoryMarkers, type OwnedSignalMarker } from '../src/utils/historicalSignalMerge.ts'
import { useHistoricalSignalRanges } from '../src/composables/useHistoricalSignalRanges.ts'
import type { BarData } from '../src/types/market.ts'
const identity = { symbol: 'jm', strategy: 'htdy', frequency: '15m' }
function item(id: string, source: OwnedSignalMarker['source'], contract = 'JM2701', version: string | undefined = 'v1'): OwnedSignalMarker {
  return { ...identity, formulaVersion: version, barEnd: '2026-10-23T07:00:00Z', physicalContract: contract, source, marker: { id, time: '2026-10-23T07:00:00Z', label: id, tone: 'htdy', position: 'aboveBar', shape: 'circle' } }
}
it('formal history admits Canonical signals only and never substitutes first-seen audit facts', () => {
  const historical = item('h', 'historical_replay')
  assert.deepEqual(canonicalHistoryMarkers([historical, item('a', 'actual_observation')], identity).map(x => x.id), ['h'])
  assert.deepEqual(canonicalHistoryMarkers([item('a', 'actual_observation')], identity), [])
  assert.deepEqual(canonicalHistoryMarkers([item('wrong', 'historical_replay', '')], identity), [])
  assert.equal(historical.formulaVersion, 'v1')
})

const bar = { time: '2026-10-23T07:00:00Z', trading_day: '2026-10-23', physicalContract: 'JM2701', open: 1, high: 1, low: 1, close: 1, volume: 1 } satisfies BarData
it('caches completed range and filters wrong physical signals without changing trading windows', async () => {
  let calls = 0
  const state = useHistoricalSignalRanges(async query => { calls++; return { ...query, identity, sourceToken: 'x', signals: [item('h', 'historical_replay'), item('wrong', 'historical_replay', 'JM2609')], nextCursor: null } })
  await state.sync(identity, [bar]); await state.sync(identity, [bar])
  assert.equal(calls, 1); assert.deepEqual(state.signals.value.map(x => x.marker.id), ['h'])
  state.dispose()
})
it('identity switch ignores delayed range response', async () => {
  let finish!: () => void
  const state = useHistoricalSignalRanges(query => new Promise(resolve => { finish = () => resolve({ ...query, identity, sourceToken: 'x', signals: [item('h', 'historical_replay')], nextCursor: null }) }))
  const pending = state.sync(identity, [bar]); await state.sync({ ...identity, symbol: 'rb' }, [])
  finish(); await pending; assert.equal(state.signals.value.length, 0); state.dispose()
})
it('covers more than 48 chunks and only fetches new edge bars', async () => {
  let calls = 0
  const state = useHistoricalSignalRanges(async query => { calls++; return { ...query, identity, sourceToken: 'x', signals: [], nextCursor: null } })
  const bars = Array.from({ length: 21000 }, (_, index) => ({ ...bar, time: new Date(Date.parse(bar.time) + index * 900000).toISOString(), trading_day: new Date(Date.parse(bar.time) + index * 900000).toISOString().slice(0, 10) }))
  await state.sync(identity, bars)
  assert.equal(calls, 70)
  assert.equal(state.error.value, null)
  await state.sync(identity, [...bars, { ...bar, time: new Date(Date.parse(bars.at(-1)!.time) + 900000).toISOString(), trading_day: bars.at(-1)!.trading_day }])
  assert.equal(calls, 71)
  state.dispose()
})
it('keeps confirmed signals but exposes partial canonical coverage', async () => {
  const state = useHistoricalSignalRanges(async query => ({ ...query, identity, sourceToken: 'x', coverage: { status: 'PARTIAL_CANONICAL', completedThrough: bar.time }, signals: [item('h', 'historical_replay')], nextCursor: null }))
  await state.sync(identity, [bar])
  assert.equal(state.signals.value.length, 1)
  assert.match(state.error.value ?? '', /部分历史信号/)
  state.dispose()
})

it('actual tooltip exposes unrecorded formula and rejects a different physical owner', () => {
  const event = { id: 1, symbol: 'jm', contract: 'JM2701', frequency: '15m' as const, trading_day: '2026-10-23', bar_end: bar.time, detected_at: bar.time, notification_attempted_at: null, rule_code: 'htdy_original_15m' as const, result_codes: ['buy' as const] }
  const markers = actualEventsToOwnedMarkers([event], [bar], identity)
  assert.equal(markers.length, 1)
  assert.match(markers[0].marker.tooltip ?? '', /公式版本 未记录/)
  assert.equal(markers[0].formulaVersion, undefined)
  assert.equal(actualEventsToOwnedMarkers([{ ...event, contract: 'JM2609' }], [bar], identity).length, 0)
})

it('retry re-reads an incomplete cached window and only clears warning after complete coverage', async () => {
 let calls=0
 const state=useHistoricalSignalRanges(async query=>({ ...query, identity, sourceToken:'x', signals:[item('h','historical_replay')], nextCursor:null, coverage:{status:++calls<3?'PARTIAL_CANONICAL':'COMPLETE',completedThrough:bar.time} }))
 await state.sync(identity,[bar]); await state.sync(identity,[bar])
 assert.equal(calls,2); assert.match(state.error.value ?? '',/部分历史信号/)
 await state.sync(identity,[bar]); assert.equal(calls,3); assert.equal(state.error.value,null)
 state.dispose()
})


it('changed visible Canonical values invalidate a COMPLETE cached range', async () => {
  let calls = 0
  const state = useHistoricalSignalRanges(async query => ({ ...query, identity, sourceToken: `source-${++calls}`, signals: [item(`h-${calls}`, 'historical_replay')], nextCursor: null, coverage: { status: 'COMPLETE' } }))
  await state.sync(identity, [bar])
  await state.sync(identity, [{ ...bar, close: 2 }])
  assert.equal(calls, 2)
  assert.deepEqual(state.signals.value.map(x => x.marker.id), ['h-2'])
  state.dispose()
})

it('a formal source refresh revalidates identical visible bars after an earlier warmup revision', async () => {
  let calls = 0
  const state = useHistoricalSignalRanges(async query => ({ ...query, identity, sourceToken: `prefix-${++calls}`, signals: [item(`prefix-signal-${calls}`, 'historical_replay')], nextCursor: null, coverage: { status: 'COMPLETE' } }))
  await state.sync(identity, [bar])
  await state.sync(identity, [bar], true)
  assert.equal(calls, 2)
  assert.deepEqual(state.signals.value.map(x => x.marker.id), ['prefix-signal-2'])
  state.dispose()
})

it('a stale saved source fails closed after refresh without retaining old markers', async () => {
  let calls = 0
  const state = useHistoricalSignalRanges(async query => {
    if (++calls > 1) throw new Error('SOURCE_IDENTITY_UNVERIFIED')
    return { ...query, identity, sourceToken: 'old', signals: [item('old', 'historical_replay')], nextCursor: null, coverage: { status: 'COMPLETE' } }
  })
  await state.sync(identity, [bar])
  await state.sync(identity, [bar], true)
  assert.deepEqual(state.signals.value, [])
  assert.match(state.error.value ?? '', /未回退到实时/)
  state.dispose()
})

it('discard an old in-flight generation even when the revised visible window is identical', async () => {
  let finish!: () => void, calls = 0
  const state = useHistoricalSignalRanges(query => {
    if (++calls === 1) return new Promise(resolve => { finish = () => resolve({ ...query, identity, sourceToken: 'old', signals: [item('old', 'historical_replay')], nextCursor: null }) })
    return Promise.resolve({ ...query, identity, sourceToken: 'new', signals: [item('new', 'historical_replay')], nextCursor: null })
  })
  const old = state.sync(identity, [bar])
  await state.sync(identity, [bar], true)
  finish(); await old
  assert.deepEqual(state.signals.value.map(x => x.marker.id), ['new'])
  state.dispose()
})


it('revoking the reference source clears COMPLETE markers before refresh failure without refetching', async () => {
  const source = ref<string | undefined>('verified-prefix'), failure = ref<string | null>(null)
  let calls = 0
  const state = useHistoricalSignalRanges(async query => {
    calls++
    return { ...query, identity, sourceToken: 'verified-prefix', signals: [item('old', 'historical_replay')], nextCursor: null, coverage: { status: 'COMPLETE' } }
  }, { source: () => source.value, error: () => failure.value })
  await state.sync(identity, [bar])
  source.value = undefined
  assert.deepEqual(state.signals.value, [])
  failure.value = 'SOURCE_IDENTITY_UNVERIFIED'
  assert.deepEqual(state.signals.value, [])
  assert.equal(calls, 1)
  assert.match(state.error.value ?? '', /旧信号已撤销/)
  state.dispose()
})

it('HTDY retained reference with a refresh error revokes old in-flight chart markers', async () => {
  const failure = ref<string | null>(null)
  let finish!: () => void
  const state = useHistoricalSignalRanges(query => new Promise(resolve => {
    finish = () => resolve({ ...query, identity, sourceToken: 'old', signals: [item('old', 'historical_replay')], nextCursor: null, coverage: { status: 'COMPLETE' } })
  }), { source: () => 'retained-old-reference', error: () => failure.value })
  const pending = state.sync(identity, [bar])
  failure.value = 'SOURCE_CHANGED'
  assert.deepEqual(state.signals.value, [])
  finish(); await pending
  assert.deepEqual(state.signals.value, [])
  assert.match(state.error.value ?? '', /旧信号已撤销/)
  state.dispose()
})


it('a retained reference failure blocks subsequent unchanged-bar sync until authority succeeds', async () => {
  const failure = ref<string | null>(null)
  let calls = 0
  const state = useHistoricalSignalRanges(async query => {
    calls++
    return { ...query, identity, sourceToken: 'old', signals: [item('old', 'historical_replay')], nextCursor: null, coverage: { status: 'COMPLETE' } }
  }, { source: () => 'retained-reference', error: () => failure.value })
  await state.sync(identity, [bar])
  assert.equal(state.signals.value.length, 1)
  failure.value = 'SOURCE_CHANGED'
  await state.sync(identity, [bar], true)
  assert.deepEqual(state.signals.value, [])
  assert.equal(calls, 1)
  failure.value = null
  await state.sync(identity, [bar], true)
  assert.equal(calls, 2)
  state.dispose()
})
