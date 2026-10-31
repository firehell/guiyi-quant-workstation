import assert from 'node:assert/strict'
import { it } from 'node:test'
import { actualEventsToOwnedMarkers, canonicalHistoryMarkers, type OwnedSignalMarker } from '../src/utils/historicalSignalMerge.ts'
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
it('actual tooltip exposes unrecorded formula and rejects a different physical owner', () => {
  const event = { id: 1, symbol: 'jm', contract: 'JM2701', frequency: '15m' as const, trading_day: '2026-10-23', bar_end: bar.time, detected_at: bar.time, notification_attempted_at: null, rule_code: 'htdy_original_15m' as const, result_codes: ['buy' as const] }
  const markers = actualEventsToOwnedMarkers([event], [bar], identity)
  assert.equal(markers.length, 1)
  assert.match(markers[0].marker.tooltip ?? '', /公式版本 未记录/)
  assert.equal(markers[0].formulaVersion, undefined)
  assert.equal(actualEventsToOwnedMarkers([{ ...event, contract: 'JM2609' }], [bar], identity).length, 0)
})
