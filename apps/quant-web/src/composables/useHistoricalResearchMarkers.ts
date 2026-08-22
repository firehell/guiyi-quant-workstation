import { ref } from 'vue'
import type {
  BarData,
  KlineMarker,
  MarketBarsPageResponse,
  MarketFrequency,
  ResearchOverlayId,
  SeriesKind,
  SubingHistoricalSignalRequest,
  SubingHistoricalSignalResponse,
} from '../types/market.ts'
import { historicalResearchEventToMarker } from '../utils/historicalResearchMarkers.ts'
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
}

export function useHistoricalResearchMarkers(dependencies: Dependencies) {
  const markers = ref<KlineMarker[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const events = new Map<string, SubingHistoricalSignalResponse['events'][number]>()
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
    if (!capability.supported || capability.definition.historicalSource !== 'subing') {
      reset(identity)
      return
    }
    const range = confirmedRange(bars, canonicalCoverage)
    if (range === null) {
      if (mutation === 'replace') {
        events.clear()
        markers.value = []
      }
      return
    }
    if (mutation === 'prepend' && loadedSince !== null && range.since >= loadedSince) return
    const request: SubingHistoricalSignalRequest = {
      series_kind: 'actual_dominant',
      symbol: identity.symbol,
      frequency: identity.frequency as '5m' | '15m',
      since: range.since,
      through: mutation === 'prepend' && loadedSince !== null ? loadedSince : range.through,
    }
    const requestGeneration = generation
    loading.value = true
    error.value = null
    try {
      const response = await dependencies.fetchSubing(request)
      if (
        requestGeneration !== generation
        || identityKey(identity) !== identityKey(activeIdentity)
      ) return
      if (!matchesRequest(response, request)) throw new Error('HISTORICAL_RESEARCH_IDENTITY_MISMATCH')
      for (const event of response.events) events.set(event.event_id, event)
      markers.value = [...events.values()]
        .sort((left, right) => Date.parse(left.bar_end) - Date.parse(right.bar_end))
        .map((event) => historicalResearchEventToMarker(identity.symbol, event))
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
    events.clear()
    markers.value = []
    error.value = null
    loadedSince = null
  }

  function dispose() {
    generation += 1
    activeIdentity = null
    events.clear()
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
  response: SubingHistoricalSignalResponse,
  request: SubingHistoricalSignalRequest,
): boolean {
  return response.request.series_kind === request.series_kind
    && response.request.symbol === request.symbol
    && response.request.frequency === request.frequency
    && response.request.since === request.since
    && response.request.through === request.through
}

function identityKey(identity: HistoricalResearchMarkerIdentity | null): string {
  if (!identity) return ''
  return [identity.overlay, identity.seriesKind, identity.symbol, identity.frequency].join('|')
}
