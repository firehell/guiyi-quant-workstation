import assert from 'node:assert/strict'
import test from 'node:test'
import type {
  AlertEvent,
  BarData,
  JdjHistoricalResponse,
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

function nResponse(
  request: {
    series_kind: 'actual_dominant'
    symbol: string
    frequency: '5m'
    since: string
    through: string
  },
  events: Array<{
    event_id: string
    observed_at: string
    trading_day: string
    contract: string
    segment_start_trading_day: string
    direction: 'up' | 'down'
  }>,
) {
  return { request, events }
}

function jdjResponse(
  request: JdjHistoricalResponse['request'],
  events: JdjHistoricalResponse['events'],
): JdjHistoricalResponse {
  return { request, events }
}

test('research overlay capability registry exposes N and JDJ at their exact identities', () => {
  assert.deepEqual(RESEARCH_OVERLAY_DEFINITIONS.map((item) => item.id), ['none', 'subing', 'n_structure', 'jdj', 'htdy'])
  assert.deepEqual(researchOverlayCapability('subing', 'actual_dominant', '5m'), {
    supported: true,
    definition: RESEARCH_OVERLAY_DEFINITIONS[1],
  })
  assert.equal(researchOverlayCapability('subing', 'continuous', '5m').supported, false)
  assert.equal(researchOverlayCapability('subing', 'actual_dominant', '1m').supported, false)
  assert.equal(researchOverlayCapability('n_structure' as never, 'actual_dominant', '5m').supported, true)
  assert.equal(researchOverlayCapability('n_structure' as never, 'actual_dominant', '15m').supported, false)
  assert.equal(RESEARCH_OVERLAY_DEFINITIONS[2].label, 'N字')
  assert.equal(RESEARCH_OVERLAY_DEFINITIONS[2].historicalSource, 'n_structure')
  assert.deepEqual(RESEARCH_OVERLAY_DEFINITIONS[2].mainIndicators, [])
  assert.equal(researchOverlayCapability('jdj' as never, 'actual_dominant', '1m').supported, true)
  assert.equal(researchOverlayCapability('jdj' as never, 'actual_dominant', '5m').supported, false)
  assert.equal(researchOverlayCapability('jdj' as never, 'continuous', '1m').supported, false)
  assert.equal(RESEARCH_OVERLAY_DEFINITIONS[3].label, '日进斗金')
  assert.equal(RESEARCH_OVERLAY_DEFINITIONS[3].historicalSource, 'jdj')
  assert.deepEqual(RESEARCH_OVERLAY_DEFINITIONS[3].mainIndicators, ['ema_20'])
})

test('JDJ markers keep three candidate identities and use only causal observed_at', async () => {
  const markerModule = await import('../src/utils/historicalResearchMarkers.ts')
  const mapper = (markerModule as unknown as {
    jdjHistoricalEventToMarker?: (event: Record<string, unknown>) => {
      time: string
      label: string
      tooltip: string
      position: string
    }
  }).jdjHistoricalEventToMarker
  assert.equal(typeof mapper, 'function')

  const cases = [
    ['jdj_trend_follow_1m_candidate_v1', 'long', '跟随多', 'belowBar'],
    ['jdj_trend_follow_1m_candidate_v1', 'short', '跟随空', 'aboveBar'],
    ['jdj_trend_reentry_6_1m_candidate_v1', 'long', '再入多', 'belowBar'],
    ['jdj_trend_reentry_6_1m_candidate_v1', 'short', '再入空', 'aboveBar'],
    ['jdj_key_level_breakout_1m_candidate_v1', 'long', '突破多', 'belowBar'],
    ['jdj_key_level_breakout_1m_candidate_v1', 'short', '突破空', 'aboveBar'],
  ] as const
  cases.forEach(([candidateId, direction, label, position]) => {
    const marker = mapper!({
      event_id: `${candidateId}|${direction}|1`,
      candidate_id: candidateId,
      source_event_kind: 'source-kind',
      observed_at: '2026-08-03T02:15:00Z',
      reaction_at: '2026-08-03T01:05:00Z',
      reclaim_at: '2026-08-03T01:10:00Z',
      retest_at: '2026-08-03T01:15:00Z',
      trading_day: '2026-08-03',
      contract: 'JM2609',
      segment_start_trading_day: '2026-08-03',
      direction,
      trigger_level: '101.5',
    })

    assert.equal(marker.time, '2026-08-03T02:15:00Z')
    assert.equal(marker.label, label)
    assert.equal(marker.position, position)
    assert.match(marker.tooltip, new RegExp(candidateId))
    assert.match(marker.tooltip, /事件时间 2026-08-03T02:15:00Z/)
  })
})

test('historical loader discards stale N and JDJ responses after rapid overlay switches', async () => {
  const nStructure = deferred<ReturnType<typeof nResponse>>()
  const jdj = deferred<JdjHistoricalResponse>()
  const subing = deferred<SubingHistoricalSignalResponse>()
  let jdjRequests = 0
  const controller = useHistoricalResearchMarkers({
    fetchSubing: () => subing.promise,
    fetchNStructure: () => nStructure.promise,
    fetchJdj: () => {
      jdjRequests += 1
      return jdj.promise
    },
  } as never)
  const coverage = { start: canonicalBars[0].time, end: canonicalBars[1].time }

  const nSync = controller.sync(
    { overlay: 'n_structure', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '5m' },
    canonicalBars, coverage, 'replace',
  )
  const jdjSync = controller.sync(
    { overlay: 'jdj' as never, seriesKind: 'actual_dominant', symbol: 'jm', frequency: '1m' },
    canonicalBars, coverage, 'replace',
  )
  const subingSync = controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '5m' },
    canonicalBars, coverage, 'replace',
  )
  subing.resolve(response('jm', '5m', canonicalBars[1].time))
  await subingSync
  jdj.resolve({
    request: { series_kind: 'actual_dominant', symbol: 'jm', frequency: '1m', since: '2026-08-03', through: '2026-08-03' },
    events: [],
  })
  nStructure.resolve(nResponse({
    series_kind: 'actual_dominant', symbol: 'jm', frequency: '5m', since: '2026-08-03', through: '2026-08-03',
  }, []))
  await Promise.all([nSync, jdjSync])

  assert.equal(jdjRequests, 1)
  assert.deepEqual(controller.markers.value.map((marker) => marker.label), ['买入信号'])
})

test('JDJ prepend reuses the shared window loader and deduplicates candidate event ids', async () => {
  let call = 0
  const later = {
    event_id: 'jdj-follow-later',
    candidate_id: 'jdj_trend_follow_1m_candidate_v1' as const,
    source_event_kind: 'jdj_trend_follow_triggered',
    observed_at: canonicalBars[1].time,
    trading_day: '2026-08-03',
    contract: 'JM2609',
    segment_start_trading_day: '2026-08-03',
    direction: 'long' as const,
    trigger_level: '101.5',
  }
  const earlierBar = {
    ...canonicalBars[0],
    time: '2026-08-02T01:05:00Z',
    trading_day: '2026-08-02',
  }
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async () => { throw new Error('wrong source') },
    fetchNStructure: async () => { throw new Error('wrong source') },
    fetchJdj: async (request) => {
      call += 1
      return jdjResponse(request, call === 1 ? [later] : [{
        ...later,
        event_id: 'jdj-reentry-earlier',
        candidate_id: 'jdj_trend_reentry_6_1m_candidate_v1',
        source_event_kind: 'jdj_trend_reentry_6_triggered',
        observed_at: earlierBar.time,
        trading_day: '2026-08-02',
        segment_start_trading_day: '2026-08-02',
        direction: 'short',
      }, later])
    },
  })
  const identity = {
    overlay: 'jdj' as const,
    seriesKind: 'actual_dominant' as const,
    symbol: 'jm',
    frequency: '1m' as const,
  }

  await controller.sync(identity, canonicalBars, {
    start: canonicalBars[0].time,
    end: canonicalBars[1].time,
  }, 'replace')
  await controller.sync(identity, [earlierBar, ...canonicalBars], {
    start: earlierBar.time,
    end: canonicalBars[1].time,
  }, 'prepend')

  assert.equal(call, 2)
  assert.deepEqual(controller.markers.value.map((marker) => marker.label), ['再入空', '跟随多'])
  assert.equal(new Set(controller.markers.value.map((marker) => marker.id)).size, 2)
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

test('N marker uses the causal observed_at instead of an earlier pivot timestamp', async () => {
  const markerModule = await import('../src/utils/historicalResearchMarkers.ts')
  const mapper = (markerModule as unknown as {
    nStructureHistoricalEventToMarker?: (event: Record<string, unknown>) => {
      time: string
      label: string
      position: string
    }
  }).nStructureHistoricalEventToMarker
  assert.equal(typeof mapper, 'function')

  const marker = mapper!({
    event_id: 'n-up-1',
    observed_at: '2026-08-03T02:15:00Z',
    pivot_at: '2026-08-03T01:05:00Z',
    trading_day: '2026-08-03',
    contract: 'JM2609',
    segment_start_trading_day: '2026-08-03',
    direction: 'up',
  })

  assert.equal(marker.time, '2026-08-03T02:15:00Z')
  assert.equal(marker.label, 'N↑完成')
  assert.equal(marker.position, 'belowBar')
})

test('historical loader discards stale SuBing response after switching to N', async () => {
  const subing = deferred<SubingHistoricalSignalResponse>()
  const nStructure = deferred<ReturnType<typeof nResponse>>()
  const controller = useHistoricalResearchMarkers({
    fetchSubing: () => subing.promise,
    fetchNStructure: () => nStructure.promise,
  } as never)
  const coverage = { start: canonicalBars[0].time, end: canonicalBars[1].time }

  const oldSync = controller.sync(
    { overlay: 'subing', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '5m' },
    canonicalBars,
    coverage,
    'replace',
  )
  const newSync = controller.sync(
    { overlay: 'n_structure', seriesKind: 'actual_dominant', symbol: 'jm', frequency: '5m' },
    canonicalBars,
    coverage,
    'replace',
  )
  nStructure.resolve(nResponse({
    series_kind: 'actual_dominant', symbol: 'jm', frequency: '5m',
    since: '2026-08-03', through: '2026-08-03',
  }, [{
    event_id: 'n-up-1', observed_at: canonicalBars[1].time,
    trading_day: '2026-08-03', contract: 'JM2609',
    segment_start_trading_day: '2026-08-03', direction: 'up',
  }]))
  await newSync
  subing.resolve(response('jm', '5m', canonicalBars[0].time))
  await oldSync

  assert.deepEqual(controller.markers.value.map((marker) => marker.label), ['N↑完成'])
  assert.equal(controller.markers.value[0].time, canonicalBars[1].time)
})

test('N prepend deduplicates event ids and preserves the confirmed marker window', async () => {
  let call = 0
  const laterEvent = {
    event_id: 'n-up-later', observed_at: canonicalBars[1].time,
    trading_day: '2026-08-03', contract: 'JM2609',
    segment_start_trading_day: '2026-08-03', direction: 'up' as const,
  }
  const earlier = {
    ...canonicalBars[0],
    time: '2026-08-02T01:05:00Z',
    trading_day: '2026-08-02',
  }
  const controller = useHistoricalResearchMarkers({
    fetchSubing: async () => { throw new Error('wrong source') },
    fetchNStructure: async (request: Parameters<typeof nResponse>[0]) => {
      call += 1
      return nResponse(request, call === 1 ? [laterEvent] : [{
        event_id: 'n-down-earlier', observed_at: earlier.time,
        trading_day: '2026-08-02', contract: 'JM2609',
        segment_start_trading_day: '2026-08-02', direction: 'down',
      }, laterEvent])
    },
  } as never)
  const identity = {
    overlay: 'n_structure' as const,
    seriesKind: 'actual_dominant' as const,
    symbol: 'jm',
    frequency: '5m' as const,
  }

  await controller.sync(
    identity,
    canonicalBars,
    { start: canonicalBars[0].time, end: canonicalBars[1].time },
    'replace',
  )
  await controller.sync(
    identity,
    [earlier, ...canonicalBars],
    { start: earlier.time, end: canonicalBars[1].time },
    'prepend',
  )

  assert.equal(call, 2)
  assert.deepEqual(controller.markers.value.map((marker) => marker.label), ['N↓完成', 'N↑完成'])
  assert.equal(new Set(controller.markers.value.map((marker) => marker.id)).size, 2)
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
