import { ref } from 'vue'
import type {
  BarData,
  KlineMarker,
  MarketBarsPageResponse,
  MarketFrequency,
  ResearchOverlayId,
  SeriesKind,
  SubingStrategyAction,
  SubingStrategyEpisode,
  SubingStrategyHistoricalRequest,
  SubingStrategyHistoricalResponse,
} from '../types/market.ts'
import {
  subingStrategyActionToMarker,
} from '../utils/historicalResearchMarkers.ts'
import {
  researchOverlayCapability,
  subingStrategyHistoricalCapability,
} from '../utils/mainIndicators.ts'


export interface HistoricalResearchMarkerIdentity {
  overlay: ResearchOverlayId
  seriesKind: SeriesKind
  symbol: string
  frequency: MarketFrequency
}

interface Dependencies {
  debounceMs?: number
  fetchSubingStrategy: (
    request: SubingStrategyHistoricalRequest,
    signal?: AbortSignal,
  ) => Promise<SubingStrategyHistoricalResponse>
}

export function useHistoricalResearchMarkers(dependencies: Dependencies) {
  const markers = ref<KlineMarker[]>([])
  const subingStrategyEpisodes = ref<SubingStrategyEpisode[]>([])
  const subingStrategyActions = ref<SubingStrategyAction[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const markersByEventId = new Map<string, KlineMarker>()
  const episodesById = new Map<string, SubingStrategyEpisode>()
  const debounceMs = dependencies.debounceMs ?? 400
  let generation = 0
  let activeIdentity: HistoricalResearchMarkerIdentity | null = null
  let loadedSince: string | null = null
  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  let pendingDebounceResolve: (() => void) | null = null
  let abortController: AbortController | null = null

  function clearDebounce(): void {
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer)
      debounceTimer = null
    }
    if (pendingDebounceResolve !== null) {
      const resolve = pendingDebounceResolve
      pendingDebounceResolve = null
      resolve()
    }
  }

  function abortInFlight(): void {
    if (abortController !== null) {
      abortController.abort()
      abortController = null
    }
  }

  function clearDebounceAndAbort(): void {
    clearDebounce()
    abortInFlight()
  }

  async function sync(
    identity: HistoricalResearchMarkerIdentity,
    bars: BarData[],
    canonicalCoverage: MarketBarsPageResponse['canonical_coverage'],
    mutation: 'replace' | 'prepend' | 'live',
  ): Promise<void> {
    const changed = identityKey(identity) !== identityKey(activeIdentity)
    if (changed || mutation === 'replace') {
      clearDebounceAndAbort()
      reset(identity)
    }
    if (mutation === 'live') return

    const capability = researchOverlayCapability(
      identity.overlay,
      identity.seriesKind,
      identity.frequency,
    )
    const historicalSource = capability.definition.historicalSource
    if (
      !capability.supported
      || historicalSource !== 'subing_strategy'
      || !subingStrategyHistoricalCapability(identity.seriesKind, identity.frequency)
    ) {
      clearDebounceAndAbort()
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

    if (mutation === 'prepend') {
      return schedulePrependFetch(identity, range)
    }

    return executeFetch(identity, range)
  }

  function schedulePrependFetch(
    identity: HistoricalResearchMarkerIdentity,
    range: { since: string; through: string },
  ): Promise<void> {
    clearDebounce()

    loading.value = true
    error.value = null
    const requestGeneration = generation

    return new Promise<void>((resolve) => {
      pendingDebounceResolve = resolve
      debounceTimer = setTimeout(() => {
        debounceTimer = null
        pendingDebounceResolve = null
        void executeFetch(identity, range, requestGeneration).then(resolve)
      }, debounceMs)
    })
  }

  async function executeFetch(
    identity: HistoricalResearchMarkerIdentity,
    range: { since: string; through: string },
    requestGeneration = generation,
  ): Promise<void> {
    loading.value = true
    error.value = null
    abortInFlight()
    const controller = new AbortController()
    abortController = controller
    try {
      const loaded = await loadSubingStrategy(
        dependencies,
        identity,
        range.since,
        range.through,
        controller.signal,
      )
      if (
        requestGeneration !== generation
        || identityKey(identity) !== identityKey(activeIdentity)
      ) return
      mergeStrategyEpisodes(episodesById, loaded.episodes)
      const actionsById = new Map(subingStrategyActions.value.map((action) => [action.action_id, action]))
      for (const action of loaded.actions) actionsById.set(action.action_id, action)
      subingStrategyActions.value = [...actionsById.values()]
      subingStrategyEpisodes.value = [...episodesById.values()]
        .sort((left, right) => Date.parse(left.entry_action.effective_bar_end)
          - Date.parse(right.entry_action.effective_bar_end))
      for (const action of loaded.actions) {
        const marker = subingStrategyActionToMarker(action, episodesById)
        markersByEventId.set(action.action_id, marker)
      }
      markers.value = [...markersByEventId.values()]
        .sort((left, right) => Date.parse(left.time) - Date.parse(right.time))
      if (loadedSince === null || range.since < loadedSince) {
        loadedSince = range.since
      }
    } catch (caught) {
      if (isAbortError(caught)) return
      if (
        requestGeneration === generation
        && identityKey(identity) === identityKey(activeIdentity)
      ) {
        error.value = 'HISTORICAL_RESEARCH_UNAVAILABLE'
      }
    } finally {
      if (abortController === controller) {
        abortController = null
        loading.value = false
      }
    }
  }

  function reset(identity: HistoricalResearchMarkerIdentity) {
    clearDebounceAndAbort()
    generation += 1
    activeIdentity = { ...identity }
    markersByEventId.clear()
    episodesById.clear()
    markers.value = []
    subingStrategyEpisodes.value = []
    subingStrategyActions.value = []
    loading.value = false
    error.value = null
    loadedSince = null
  }

  function dispose() {
    clearDebounceAndAbort()
    generation += 1
    activeIdentity = null
    markersByEventId.clear()
    episodesById.clear()
    markers.value = []
    subingStrategyEpisodes.value = []
    subingStrategyActions.value = []
    loading.value = false
    error.value = null
    loadedSince = null
  }

  return {
    markers,
    subingStrategyActions,
    subingStrategyEpisodes,
    loading,
    error,
    sync,
    dispose,
  }
}

function isAbortError(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  if (error.name === 'AbortError') return true
  return (error as { code?: string }).code === 'ERR_CANCELED'
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

interface LoadedHistoricalResult {
  actions: SubingStrategyAction[]
  episodes: SubingStrategyEpisode[]
}

async function loadSubingStrategy(
  dependencies: Dependencies,
  identity: HistoricalResearchMarkerIdentity,
  since: string,
  through: string,
  signal?: AbortSignal,
): Promise<LoadedHistoricalResult> {
  const request: SubingStrategyHistoricalRequest = {
    series_kind: 'actual_dominant',
    symbol: identity.symbol,
    frequency: '15m',
    since,
    through,
  }
  const response = await dependencies.fetchSubingStrategy(request, signal)
  if (!matchesRequest(response, request)) {
    throw new Error('HISTORICAL_RESEARCH_IDENTITY_MISMATCH')
  }
  return {
    actions: response.actions,
    episodes: response.episodes,
  }
}

function mergeStrategyEpisodes(
  current: Map<string, SubingStrategyEpisode>,
  incoming: SubingStrategyEpisode[],
): void {
  for (const episode of incoming) {
    const existing = current.get(episode.episode_id)
    if (
      existing !== undefined
      && existing.entry_action.action_id !== episode.entry_action.action_id
    ) throw new Error('SUBING_STRATEGY_EPISODE_IDENTITY_MISMATCH')
  }
  for (const episode of incoming) {
    const existing = current.get(episode.episode_id)
    if (
      existing === undefined
      || (existing.state === 'open' && episode.state === 'closed')
      || (existing.state === episode.state
        && episode.holding_bar_count >= existing.holding_bar_count)
    ) current.set(episode.episode_id, episode)
  }
}

function identityKey(identity: HistoricalResearchMarkerIdentity | null): string {
  if (!identity) return ''
  return [identity.overlay, identity.seriesKind, identity.symbol, identity.frequency].join('|')
}
