import assert from 'node:assert/strict'
import test from 'node:test'
import type {
  AlertEvent,
  BarData,
  SubingHistoricalSignalResponse,
} from '../src/types/market.ts'
import { useHistoricalResearchMarkers } from '../src/composables/useHistoricalResearchMarkers.ts'
import {
  historicalResearchEventToMarker,
} from '../src/utils/historicalResearchMarkers.ts'
import {
  alertEventsToMarkers,
  mergeKlineMarkers,
} from '../src/utils/alertMarkers.ts'
import {
  RESEARCH_OVERLAY_DEFINITIONS,
  researchOverlayCapability,
} from '../src/utils/mainIndicators.ts'


const canonicalBars: BarData[] = [
  {
    time: '2026-08-03T01:05:00Z',
    trading_day: '2026-08-03',
    physicalContract: 'JM2609',
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  },
  {
    time: '2026-08-03T01:10:00Z',
    trading_day: '2026-08-03',
    physicalContract: 'JM2609',
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 10,
  },
]

function response(
  symbol: string,
  frequency: '5m' | '15m',
  barEnd: string,
  direction: 'buy' | 'sell' = 'buy',
): SubingHistoricalSignalResponse {
  return {
    request: {
      series_kind: 'actual_dominant',
      symbol,
      frequency,
      since: '2026-08-03',
      through: '2026-08-03',
    },
    events: [{
      event_id: `subing_entry_signal_v1|${symbol}|JM2609|2026-08-03|${barEnd}|${frequency}|${direction}`,
      bar_end: barEnd,
      trading_day: '2026-08-03',
      contract: 'JM2609',
      segment_start_trading_day: '2026-08-03',
      direction,
      trigger_timeframe: frequency,
      lower_tf_confirmation: false,
    }],
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((accept) => { resolve = accept })
  return { promise, resolve }
}

test('research overlay capability registry stays display-only and adds no N or JDJ placeholder', () => {
  assert.deepEqual(RESEARCH_OVERLAY_DEFINITIONS.map((item) => item.id), ['none', 'subing', 'htdy'])
  assert.deepEqual(researchOverlayCapability('subing', 'actual_dominant', '5m'), {
    supported: true,
    definition: RESEARCH_OVERLAY_DEFINITIONS[1],
  })
  assert.equal(researchOverlayCapability('subing', 'continuous', '5m').supported, false)
  assert.equal(researchOverlayCapability('subing', 'actual_dominant', '1m').supported, false)
  assert.equal(RESEARCH_OVERLAY_DEFINITIONS.some((item) => item.id === ('n_structure' as never)), false)
  assert.equal(RESEARCH_OVERLAY_DEFINITIONS.some((item) => item.id === ('jdj' as never)), false)
})

test('historical loader discards stale response after full overlay identity changes', async () => {
  const first = deferred<SubingHistoricalSignalResponse>()
  const second = deferred<SubingHistoricalSignalResponse>()
  const controller = useHistoricalResearchMarkers({
    fetchSubing: ({ symbol }) => symbol === 'jm' ? first.promise : second.promise,
  })
  const coverage = { start: canonicalBars[0].time, end: canonicalBars[1].time }

  const oldSync = controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '5m' },
    canonicalBars,
    coverage,
    'replace',
  )
  const newSync = controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'ag', frequency: '5m' },
    canonicalBars,
    coverage,
    'replace',
  )
  second.resolve(response('ag', '5m', canonicalBars[1].time))
  await newSync
  first.resolve(response('jm', '5m', canonicalBars[0].time))
  await oldSync

  assert.equal(controller.markers.value.length, 1)
  assert.match(controller.markers.value[0].id, /\|ag\|/)
})

test('historical loader clips requests to canonical coverage and ignores live-only mutations', async () => {
  const requests: Array<Record<string, string>> = []
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async (request) => {
      requests.push(request)
      return response(request.symbol, request.frequency, canonicalBars[1].time)
    },
  })
  const liveTail: BarData = {
    ...canonicalBars[1],
    time: '2026-08-04T01:05:00Z',
    trading_day: '2026-08-04',
  }
  const identity = {
    overlay: 'subing' as const,
    seriesKind: 'actual_dominant' as const,
    symbol: 'jm',
    frequency: '5m' as const,
  }

  await controller.sync(
    identity,
    [...canonicalBars, liveTail],
    { start: canonicalBars[0].time, end: canonicalBars[1].time },
    'replace',
  )
  await controller.sync(
    identity,
    [...canonicalBars, liveTail],
    { start: canonicalBars[0].time, end: canonicalBars[1].time },
    'live',
  )

  assert.deepEqual(requests, [{
    series_kind: 'actual_dominant',
    symbol: 'jm',
    frequency: '5m',
    since: '2026-08-03',
    through: '2026-08-03',
  }])
})

test('unsupported identity clears replay markers without requesting or mutating Kline bars', async () => {
  let requests = 0
  const bars = canonicalBars.map((bar) => ({ ...bar }))
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async (request) => {
      requests += 1
      return response(request.symbol, request.frequency, canonicalBars[1].time)
    },
  })
  await controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '5m' },
    bars,
    { start: bars[0].time, end: bars[1].time },
    'replace',
  )
  assert.equal(controller.markers.value.length, 1)

  await controller.sync(
    { overlay: 'subing', seriesKind: 'continuous', symbol: 'jm', frequency: '5m' },
    bars,
    { start: bars[0].time, end: bars[1].time },
    'replace',
  )

  assert.equal(requests, 1)
  assert.deepEqual(controller.markers.value, [])
  assert.deepEqual(bars, canonicalBars)
})

test('prepend failure keeps confirmed markers and never mutates Kline bars', async () => {
  let fail = false
  const bars = canonicalBars.map((bar) => ({ ...bar }))
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async (request) => {
      if (fail) throw new Error('offline')
      return response(request.symbol, request.frequency, canonicalBars[1].time)
    },
  })
  const identity = {
    overlay: 'subing' as const,
    seriesKind: 'actual_dominant' as const,
    symbol: 'jm',
    frequency: '5m' as const,
  }
  await controller.sync(
    identity,
    bars,
    { start: bars[0].time, end: bars[1].time },
    'replace',
  )
  const previous = [...controller.markers.value]
  fail = true
  const earlier = {
    ...bars[0],
    time: '2026-08-02T01:05:00Z',
    trading_day: '2026-08-02',
  }

  await controller.sync(
    identity,
    [earlier, ...bars],
    { start: earlier.time, end: bars[1].time },
    'prepend',
  )

  assert.deepEqual(controller.markers.value, previous)
  assert.equal(controller.error.value, 'HISTORICAL_RESEARCH_UNAVAILABLE')
  assert.deepEqual(bars, canonicalBars)
})

test('persisted SuBing AlertEvent overrides replay marker with the same dedupe identity', () => {
  const replay = historicalResearchEventToMarker(
    'jm',
    response('jm', '5m', canonicalBars[1].time).events[0],
  )
  const event: AlertEvent = {
    id: 42,
    rule_code: 'subing_entry_signal_v1',
    symbol: 'jm',
    contract: 'JM2609',
    trading_day: '2026-08-03',
    frequency: '5m',
    bar_end: canonicalBars[1].time,
    result_codes: ['buy'],
    lower_tf_confirmation: false,
    detected_at: canonicalBars[1].time,
    notification_attempted_at: null,
  }
  const persisted = alertEventsToMarkers([event])[0]

  assert.equal(replay.dedupeKey, persisted.dedupeKey)
  const merged = mergeKlineMarkers([persisted], [replay])
  assert.equal(merged.length, 1)
  assert.equal(merged[0].id, persisted.id)
  assert.equal(merged[0].label, '买入信号')
})
