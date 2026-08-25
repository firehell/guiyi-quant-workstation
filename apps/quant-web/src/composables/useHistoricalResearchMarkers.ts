import { ref } from 'vue'
import type {
  BarData,
  JdjStrategyHistoricalRequest,
  JdjStrategyHistoricalResponse,
  KlineMarker,
  MarketBarsPageResponse,
  MarketFrequency,
  ResearchOverlayId,
  SeriesKind,
  SubingHistoricalSignalRequest,
  SubingHistoricalSignalResponse,
} from '../types/market.ts'
import {
  historicalResearchEventToMarker,
  jdjStrategyActionToMarker,
} from '../utils/historicalResearchMarkers.ts'
import { researchOverlayCapability } from '../utils/mainIndicators.ts'


export interface HistoricalResearchMarkerIdentity {
  overlay: ResearchOverlayId
  seriesKind: SeriesKind
  symbol: string
  frequency: MarketFrequency
}

interface Dependencies {
  fetchSubing: (
    request: SubingHistoricalSignalRequest,
  ) => Promise<SubingHistoricalSignalResponse>
  fetchJdjStrategy: (
    request: JdjStrategyHistoricalRequest,
  ) => Promise<JdjStrategyHistoricalResponse>
}

export function useHistoricalResearchMarkers(dependencies: Dependencies) {
  const markers = ref<KlineMarker[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const markersByEventId = new Map<string, KlineMarker>()
  let generation = 0
  let activeIdentity: HistoricalResearchMarkerIdentity | null = null
  let loadedSince: string | null = null

  async function sync(
    identity: HistoricalResearchMarkerIdentity,
    bars: BarData[],
    canonicalCoverage: MarketBarsPageResponse['canonical_coverage'],
    mutation: 'replace' | 'prepend' | 'live',
  ): Promise<void> {
    const changed = identityKey(identity) !== identityKey(activeIdentity)
    if (changed || mutation === 'replace') reset(identity)
    if (mutation === 'live') return

    const capability = researchOverlayCapability(
      identity.overlay,
      identity.seriesKind,
      identity.frequency,
    )
    const historicalSource = capability.definition.historicalSource
    if (
      !capability.supported
      || !['subing', 'jdj_strategy'].includes(historicalSource)
    ) {
      reset(identity)
      return
    }
    const range = confirmedRange(bars, canonicalCoverage)
    if (range === null) {
      if (mutation === 'replace') {
        markersByEventId.clear()
        markers.value = []
      }
      return
    }
    if (mutation === 'prepend' && loadedSince !== null && range.since >= loadedSince) return
    const through = mutation === 'prepend' && loadedSince !== null
      ? loadedSince
      : range.through
    const requestGeneration = generation
    loading.value = true
    error.value = null
    try {
      const loaded = historicalSource === 'subing'
        ? await loadSubing(dependencies, identity, range.since, through)
        : await loadJdjStrategy(dependencies, identity, range.since, through)
      if (
        requestGeneration !== generation
        || identityKey(identity) !== identityKey(activeIdentity)
      ) return
      for (const event of loaded) markersByEventId.set(event.eventId, event.marker)
      markers.value = [...markersByEventId.values()]
        .sort((left, right) => Date.parse(left.time) - Date.parse(right.time))
      if (loadedSince === null || range.since < loadedSince) {
        loadedSince = range.since
      }
    } catch (caught) {
      if (
        requestGeneration === generation
        && identityKey(identity) === identityKey(activeIdentity)
      ) {
        error.value = identity.overlay === 'jdj_strategy'
          && isJdjStrategyProfileUnavailable(caught)
          ? 'JDJ_STRATEGY_PROFILE_UNAVAILABLE'
          : 'HISTORICAL_RESEARCH_UNAVAILABLE'
      }
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  function reset(identity: HistoricalResearchMarkerIdentity) {
    generation += 1
    activeIdentity = { ...identity }
    markersByEventId.clear()
    markers.value = []
    error.value = null
    loadedSince = null
  }

  function dispose() {
    generation += 1
    activeIdentity = null
    markersByEventId.clear()
    markers.value = []
    loading.value = false
    error.value = null
    loadedSince = null
  }

  return { markers, loading, error, sync, dispose }
}

function isJdjStrategyProfileUnavailable(caught: unknown): boolean {
  if (typeof caught !== 'object' || caught === null) return false
  const response = (caught as {
    response?: { status?: unknown; data?: { detail?: unknown } }
  }).response
  if (response?.status !== 422) return false
  const detail = response.data?.detail
  return typeof detail === 'object'
    && detail !== null
    && (detail as { code?: unknown }).code === 'JDJ_STRATEGY_PROFILE_UNAVAILABLE'
}

function confirmedRange(
  bars: BarData[],
  coverage: MarketBarsPageResponse['canonical_coverage'],
): { since: string; through: string } | null {
  if (!coverage) return null
  const start = Date.parse(coverage.start)
  const end = Date.parse(coverage.end)
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end) return null
  const confirmed = bars.filter((bar) => {
    const time = Date.parse(bar.time)
    return Number.isFinite(time) && start <= time && time <= end
  })
  if (!confirmed.length) return null
  const first = confirmed[0]
  const last = confirmed[confirmed.length - 1]
  return {
    since: first.trading_day ?? first.time.slice(0, 10),
    through: last.trading_day ?? last.time.slice(0, 10),
  }
}

function matchesRequest(
  response: { request: HistoricalRequestIdentity },
  request: HistoricalRequestIdentity,
): boolean {
  return response.request.series_kind === request.series_kind
    && response.request.symbol === request.symbol
    && response.request.frequency === request.frequency
    && response.request.since === request.since
    && response.request.through === request.through
}

interface HistoricalRequestIdentity {
  series_kind: 'actual_dominant'
  symbol: string
  frequency: MarketFrequency
  since: string
  through: string
}

interface LoadedHistoricalEvent {
  eventId: string
  marker: KlineMarker
}

async function loadSubing(
  dependencies: Dependencies,
  identity: HistoricalResearchMarkerIdentity,
  since: string,
  through: string,
): Promise<LoadedHistoricalEvent[]> {
  const request: SubingHistoricalSignalRequest = {
    series_kind: 'actual_dominant',
    symbol: identity.symbol,
    frequency: identity.frequency as '5m' | '15m',
    since,
    through,
  }
  const response = await dependencies.fetchSubing(request)
  if (!matchesRequest(response, request)) {
    throw new Error('HISTORICAL_RESEARCH_IDENTITY_MISMATCH')
  }
  return response.events.map((event) => ({
    eventId: event.event_id,
    marker: historicalResearchEventToMarker(identity.symbol, event),
  }))
}

async function loadJdjStrategy(
  dependencies: Dependencies,
  identity: HistoricalResearchMarkerIdentity,
  since: string,
  through: string,
): Promise<LoadedHistoricalEvent[]> {
  const request: JdjStrategyHistoricalRequest = {
    series_kind: 'actual_dominant',
    symbol: identity.symbol,
    frequency: '1m',
    since,
    through,
  }
  const response = await dependencies.fetchJdjStrategy(request)
  if (!response.reference_execution || !matchesRequest(response, request)) {
    throw new Error('HISTORICAL_RESEARCH_IDENTITY_MISMATCH')
  }
  return response.actions.flatMap((action) => {
    const marker = jdjStrategyActionToMarker(action)
    return marker === null ? [] : [{ eventId: action.event_id, marker }]
  })
}

function identityKey(identity: HistoricalResearchMarkerIdentity | null): string {
  if (!identity) return ''
  return [identity.overlay, identity.seriesKind, identity.symbol, identity.frequency].join('|')
}
