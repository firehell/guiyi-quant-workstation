import { ref } from 'vue'
import type {
  BarData,
  KlineMarker,
  MarketBarsPageResponse,
  MarketFrequency,
  NStructureHistoricalRequest,
  NStructureHistoricalResponse,
  ResearchOverlayId,
  SeriesKind,
  SubingHistoricalSignalRequest,
  SubingHistoricalSignalResponse,
} from '../types/market.ts'
import {
  historicalResearchEventToMarker,
  nStructureHistoricalEventToMarker,
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
  fetchNStructure: (
    request: NStructureHistoricalRequest,
  ) => Promise<NStructureHistoricalResponse>
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
      || (historicalSource !== 'subing' && historicalSource !== 'n_structure')
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
        : await loadNStructure(dependencies, identity, range.since, through)
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
    } catch {
      if (
        requestGeneration === generation
        && identityKey(identity) === identityKey(activeIdentity)
      ) error.value = 'HISTORICAL_RESEARCH_UNAVAILABLE'
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

async function loadNStructure(
  dependencies: Dependencies,
  identity: HistoricalResearchMarkerIdentity,
  since: string,
  through: string,
): Promise<LoadedHistoricalEvent[]> {
  const request: NStructureHistoricalRequest = {
    series_kind: 'actual_dominant',
    symbol: identity.symbol,
    frequency: '5m',
    since,
    through,
  }
  const response = await dependencies.fetchNStructure(request)
  if (!matchesRequest(response, request)) {
    throw new Error('HISTORICAL_RESEARCH_IDENTITY_MISMATCH')
  }
  return response.events.map((event) => ({
    eventId: event.event_id,
    marker: nStructureHistoricalEventToMarker(event),
  }))
}

function identityKey(identity: HistoricalResearchMarkerIdentity | null): string {
  if (!identity) return ''
  return [identity.overlay, identity.seriesKind, identity.symbol, identity.frequency].join('|')
}
