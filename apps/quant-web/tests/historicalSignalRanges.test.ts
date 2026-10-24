import assert from 'node:assert/strict'
import { it } from 'node:test'
import { actualEventsToOwnedMarkers, mergeOwnedSignalMarkers, type OwnedSignalMarker } from '../src/utils/historicalSignalMerge.ts'
import { useHistoricalSignalRanges } from '../src/composables/useHistoricalSignalRanges.ts'
import type { BarData } from '../src/types/market.ts'
const identity = { symbol: 'jm', strategy: 'htdy', frequency: '15m' }
function item(id: string, source: OwnedSignalMarker['source'], contract = 'JM2701', version: string | undefined = 'v1'): OwnedSignalMarker {
  return { ...identity, formulaVersion: version, barEnd: '2026-10-23T07:00:00Z', physicalContract: contract, source, marker: { id, time: '2026-10-23T07:00:00Z', label: id, tone: 'htdy', position: 'aboveBar', shape: 'circle' } }
}
it('actual owns the exact strategy period time and physical slot even when formula version is unknown or differs', () => {
  const historical = item('h', 'historical_replay')
  assert.deepEqual(mergeOwnedSignalMarkers([historical], [item('a', 'actual_observation')], identity).map(x => x.id), ['a'])
  assert.equal(mergeOwnedSignalMarkers([historical], [item('a', 'actual_observation', 'JM2609')], identity).length, 2)
  assert.equal(mergeOwnedSignalMarkers([historical], [item('a', 'actual_observation', 'JM2701', '')], identity).length, 1)
  assert.deepEqual(mergeOwnedSignalMarkers([historical], [item('new-version', 'actual_observation', 'JM2701', 'v2')], identity).map(marker => marker.id), ['new-version'])
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
