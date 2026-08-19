import { ref } from 'vue'
import { resolveWsURL } from '../utils/network.ts'
import { normalizeBarSeries } from '../utils/barSeries.ts'
import type {
  BarData,
  CanonicalBarDto,
  MarketBarsPageRequest,
  MarketBarsPageResponse,
  MarketFrequency,
  MarketOverlaySource,
  MarketReadState,
  MarketWsMessage,
  SeriesKind,
} from '../types/market'

const DEFAULT_PAGE_LIMIT = 1200
const RECONNECT_DELAY_MS = 10_000
const INTRADAY_FREQUENCIES = new Set<MarketFrequency>(['1m', '5m', '15m', '30m', '60m'])

export interface MarketSeriesIdentity {
  seriesKind: SeriesKind
  symbol: string
  contract?: string
  frequency: MarketFrequency
}

export interface MergedMarketPage {
  bars: BarData[]
  hasMoreBefore: boolean
  nextBefore: string | null
}

interface MarketOverlayIdentity {
  source: Exclude<MarketOverlaySource, 'none'>
  tradingDay: string
  contract: string
}

export type MarketSeriesMutation =
  | { kind: 'replace' }
  | { kind: 'prepend'; bars: BarData[] }
  | { kind: 'live'; bars: BarData[] }

export interface MarketWebSocket {
  close(): void
  onopen: (() => void) | null
  onmessage: ((event: { data: string }) => void) | null
  onclose: (() => void) | null
}

export interface MarketSeriesDependencies {
  fetchPage?: (params: MarketBarsPageRequest) => Promise<MarketBarsPageResponse>
  fetchState?: (identity: MarketSeriesIdentity) => Promise<MarketReadState>
  createWebSocket?: (url: string) => MarketWebSocket
  resolveWsURL?: () => string
  scheduleReconnect?: (callback: () => void, delayMs: number) => unknown
  clearReconnect?: (handle: unknown) => void
}

/** Maps the canonical page DTO once at the HTTP boundary. */
function toBarData(item: CanonicalBarDto): BarData {
  return {
    time: item.bar_end,
    trading_day: item.trading_day,
    open: Number(item.open),
    high: Number(item.high),
    low: Number(item.low),
    close: Number(item.close),
    volume: Number(item.volume),
    turnover: item.turnover === null ? undefined : Number(item.turnover),
    openInterest: item.open_interest === null ? undefined : Number(item.open_interest),
  }
}

export function mergeInitialPage(page: MarketBarsPageResponse): MergedMarketPage {
  return {
    bars: normalizeBarSeries(page.bars.map(toBarData)),
    hasMoreBefore: page.page.has_more_before,
    nextBefore: page.page.next_before,
  }
}

export function prependHistoricalPage(
  current: BarData[],
  page: MarketBarsPageResponse,
): MergedMarketPage {
  return {
    bars: normalizeBarSeries([...page.bars.map(toBarData), ...current]),
    hasMoreBefore: page.page.has_more_before,
    nextBefore: page.page.next_before,
  }
}

export function isCurrentGeneration(requestGeneration: number, currentGeneration: number): boolean {
  return requestGeneration === currentGeneration
}

function toPageRequest(identity: MarketSeriesIdentity, before?: string): MarketBarsPageRequest {
  return {
    series_kind: identity.seriesKind,
    symbol: identity.symbol,
    contract: identity.seriesKind === 'contract' ? identity.contract : undefined,
    frequency: identity.frequency,
    before,
    limit: DEFAULT_PAGE_LIMIT,
  }
}

async function defaultFetchPage(params: MarketBarsPageRequest): Promise<MarketBarsPageResponse> {
  const { getMarketBarsPage } = await import('../api/market')
  return getMarketBarsPage(params)
}

async function defaultFetchState(identity: MarketSeriesIdentity): Promise<MarketReadState> {
  const { getMarketState } = await import('../api/market')
  return getMarketState(identity)
}

function defaultCreateWebSocket(url: string): MarketWebSocket {
  // Browser WebSocket handlers include DOM event arguments; the composable only
  // needs JSON message data and close notification, keeping its test seam small.
  return new WebSocket(url) as unknown as MarketWebSocket
}

function defaultScheduleReconnect(callback: () => void, delayMs: number): ReturnType<typeof setTimeout> {
  return setTimeout(callback, delayMs)
}

function defaultClearReconnect(handle: unknown): void {
  clearTimeout(handle as ReturnType<typeof setTimeout>)
}

function latestEnd(items: BarData[]): string | null {
  return items.at(-1)?.time ?? null
}

function loadedCanonicalCoverage(items: BarData[]): MarketBarsPageResponse['canonical_coverage'] {
  if (!items.length) return null
  return { start: items[0].time, end: items.at(-1)!.time }
}

function isLater(left: string | null, right: string | null): boolean {
  return left !== null && (right === null || Date.parse(left) > Date.parse(right))
}

function socketUrl(base: string, identity: MarketSeriesIdentity, after: string | null): string {
  const url = new URL(base, base.includes('://') ? undefined : 'ws://market.local')
  url.searchParams.set('series_kind', identity.seriesKind)
  url.searchParams.set('symbol', identity.symbol)
  url.searchParams.set('frequency', identity.frequency)
  if (identity.seriesKind === 'contract' && identity.contract) url.searchParams.set('contract', identity.contract)
  if (after) url.searchParams.set('after', after)
  return url.toString()
}

function isIdentityLiveCapable(identity: MarketSeriesIdentity, state: MarketReadState): boolean {
  if (!INTRADAY_FREQUENCIES.has(identity.frequency) || !state.live_eligible) return false
  if (identity.seriesKind === 'actual_dominant') return true
  return identity.seriesKind === 'contract'
    && !!identity.contract
    && identity.contract.toUpperCase() === state.live_contract?.toUpperCase()
}

function shouldAwaitAfterMarketSeam(
  identity: MarketSeriesIdentity,
  state: MarketReadState,
): boolean {
  if (
    state.phase !== 'CLOSED'
    || !state.operational
    || state.trading_day === null
    || (identity.seriesKind !== 'actual_dominant'
      && !(identity.seriesKind === 'contract' && !!identity.contract))
    || !INTRADAY_FREQUENCIES.has(identity.frequency)
  ) return false
  return state.after_market.last_successful_trading_day !== state.trading_day
}

function isMarketWsMessage(value: unknown): value is MarketWsMessage {
  if (!value || typeof value !== 'object' || !('type' in value)) return false
  const type = (value as { type?: unknown }).type
  return type === 'state' || type === 'snapshot' || type === 'bar' || type === 'reset'
}

export function useMarketSeries(dependencies: MarketSeriesDependencies = {}) {
  const bars = ref<BarData[]>([])
  const hasMoreBefore = ref(false)
  const nextBefore = ref<string | null>(null)
  const canonicalCoverage = ref<MarketBarsPageResponse['canonical_coverage']>(null)
  const loadingInitial = ref(false)
  const loadingBefore = ref(false)
  const marketState = ref<MarketReadState | null>(null)
  const liveUnavailable = ref(false)
  const overlaySource = ref<MarketOverlaySource>('none')
  const mutation = ref<MarketSeriesMutation>({ kind: 'replace' })
  const fetchPage = dependencies.fetchPage ?? defaultFetchPage
  const fetchState = dependencies.fetchState ?? defaultFetchState
  const createWebSocket = dependencies.createWebSocket ?? defaultCreateWebSocket
  const getWsURL = dependencies.resolveWsURL ?? (() => resolveWsURL(import.meta.env?.VITE_MARKET_WS_URL))
  const scheduleReconnect = dependencies.scheduleReconnect ?? defaultScheduleReconnect
  const clearReconnect = dependencies.clearReconnect ?? defaultClearReconnect
  let generation = 0
  let identity: MarketSeriesIdentity | null = null
  let canonicalBars: BarData[] = []
  let liveBars: BarData[] = []
  let activeSocket: MarketWebSocket | null = null
  let reconnectHandle: unknown = null
  let canonicalRefreshToken = 0
  let overlayIdentity: MarketOverlayIdentity | null = null

  function clearOverlay(): void {
    liveBars = []
    overlaySource.value = 'none'
    overlayIdentity = null
  }

  function publishMerged(nextMutation: MarketSeriesMutation): void {
    const seam = latestEnd(canonicalBars)
    liveBars = liveBars.filter((bar) => seam === null || Date.parse(bar.time) > Date.parse(seam))
    if (!liveBars.length && overlaySource.value === 'post_close') {
      overlaySource.value = 'none'
      overlayIdentity = null
    }
    bars.value = normalizeBarSeries([...canonicalBars, ...liveBars])
    mutation.value = nextMutation
  }

  function clearSocket(): void {
    if (reconnectHandle !== null) {
      clearReconnect(reconnectHandle)
      reconnectHandle = null
    }
    if (activeSocket) {
      const socket = activeSocket
      activeSocket = null
      socket.close()
    }
  }

  function shouldKeepStateSocket(
    nextIdentity: MarketSeriesIdentity,
    nextState: MarketReadState,
  ): boolean {
    return isIdentityLiveCapable(nextIdentity, nextState)
      || shouldAwaitAfterMarketSeam(nextIdentity, nextState)
  }

  async function refreshCanonicalEdge(
    requestGeneration: number,
    nextIdentity: MarketSeriesIdentity,
    refreshToken: number,
    expectedCanonicalEnd: string,
  ): Promise<boolean> {
    try {
      const page = await fetchPage(toPageRequest(nextIdentity))
      if (!isCurrentGeneration(requestGeneration, generation) || refreshToken !== canonicalRefreshToken) return false
      const merged = mergeInitialPage(page)
      const fresh = merged.bars
      const freshEnd = latestEnd(fresh)
      if (freshEnd === null || Date.parse(freshEnd) < Date.parse(expectedCanonicalEnd)) {
        liveUnavailable.value = true
        if (overlaySource.value !== 'post_close') {
          clearOverlay()
          publishMerged({ kind: 'replace' })
        }
        return false
      }
      const freshStart = fresh[0].time
      canonicalBars = normalizeBarSeries([
        ...canonicalBars.filter((bar) => Date.parse(bar.time) < Date.parse(freshStart)),
        ...fresh,
      ])
      canonicalCoverage.value = loadedCanonicalCoverage(canonicalBars)
      publishMerged({ kind: 'replace' })
      return true
    } catch {
      if (isCurrentGeneration(requestGeneration, generation) && refreshToken === canonicalRefreshToken) {
        liveUnavailable.value = true
        if (overlaySource.value !== 'post_close') {
          clearOverlay()
          publishMerged({ kind: 'replace' })
        }
      }
      return false
    }
  }

  function applyLiveBars(incoming: CanonicalBarDto[]): boolean {
    const seam = latestEnd(canonicalBars)
    const accepted = normalizeBarSeries(incoming.map(toBarData).filter((bar) => seam === null || Date.parse(bar.time) > Date.parse(seam)))
    if (!accepted.length) return false
    liveBars = normalizeBarSeries([...liveBars, ...accepted])
    publishMerged({ kind: 'live', bars: accepted })
    return true
  }

  function openSocket(requestGeneration: number, nextIdentity: MarketSeriesIdentity): void {
    if (!isCurrentGeneration(requestGeneration, generation) || !marketState.value || !shouldKeepStateSocket(nextIdentity, marketState.value)) return
    const socket = createWebSocket(socketUrl(getWsURL(), nextIdentity, latestEnd(liveBars)))
    activeSocket = socket
    socket.onmessage = (event) => {
      if (!isCurrentGeneration(requestGeneration, generation) || socket !== activeSocket) return
      let payload: unknown
      try {
        payload = JSON.parse(event.data)
      } catch {
        return
      }
      if (!isMarketWsMessage(payload)) return
      if (payload.type === 'snapshot') {
        liveUnavailable.value = false
        if (payload.source === 'none') {
          clearOverlay()
          publishMerged({ kind: 'replace' })
          return
        }
        if (payload.trading_day === null || payload.contract === null) {
          clearOverlay()
          publishMerged({ kind: 'replace' })
          return
        }
        const samePhysicalIdentity = overlayIdentity === null
          || (overlayIdentity.tradingDay === payload.trading_day
            && overlayIdentity.contract === payload.contract)
        if (!samePhysicalIdentity) {
          clearOverlay()
          publishMerged({ kind: 'replace' })
        }
        overlayIdentity = {
          source: payload.source,
          tradingDay: payload.trading_day,
          contract: payload.contract,
        }
        const accepted = applyLiveBars(payload.bars)
        if (accepted || liveBars.length > 0) {
          overlaySource.value = payload.source
        }
        if (payload.source === 'realtime') {
          return
        }
        return
      }
      if (payload.type === 'bar') {
        liveUnavailable.value = false
        const accepted = applyLiveBars([payload.bar])
        if (accepted || liveBars.length > 0) {
          overlaySource.value = 'realtime'
          if (overlayIdentity) overlayIdentity.source = 'realtime'
        }
        return
      }
      if (payload.type === 'reset') {
        clearOverlay()
        publishMerged({ kind: 'replace' })
        return
      }
      const previousSeam = latestEnd(canonicalBars)
      marketState.value = payload.state
      liveUnavailable.value = !payload.state.live_available
      let canonicalRefresh: Promise<boolean> | null = null
      const announcedCanonicalEnd = payload.state.canonical_end
      if (announcedCanonicalEnd !== null && isLater(announcedCanonicalEnd, previousSeam)) {
        const refreshToken = ++canonicalRefreshToken
        canonicalRefresh = refreshCanonicalEdge(
          requestGeneration,
          nextIdentity,
          refreshToken,
          announcedCanonicalEnd,
        )
      }
      if (payload.state.phase === 'CLOSED' && canonicalRefresh) {
        void canonicalRefresh.then(() => {
          if (isCurrentGeneration(requestGeneration, generation) && socket === activeSocket) clearSocket()
        })
        return
      }
      if (!shouldKeepStateSocket(nextIdentity, payload.state)) {
        if (canonicalRefresh) {
          void canonicalRefresh.then(() => {
            if (isCurrentGeneration(requestGeneration, generation) && socket === activeSocket) clearSocket()
          })
        } else {
          clearSocket()
        }
        return
      }
      if (canonicalRefresh) void canonicalRefresh
    }
    socket.onclose = () => {
      if (!isCurrentGeneration(requestGeneration, generation) || socket !== activeSocket) return
      activeSocket = null
      liveUnavailable.value = true
      if (!identity || !marketState.value || !shouldKeepStateSocket(identity, marketState.value)) return
      reconnectHandle = scheduleReconnect(() => {
        reconnectHandle = null
        openSocket(requestGeneration, nextIdentity)
      }, RECONNECT_DELAY_MS)
    }
  }

  async function replaceSeries(nextIdentity: MarketSeriesIdentity): Promise<void> {
    const requestGeneration = ++generation
    clearSocket()
    identity = { ...nextIdentity }
    canonicalBars = []
    clearOverlay()
    canonicalCoverage.value = null
    canonicalRefreshToken += 1
    marketState.value = null
    liveUnavailable.value = false
    loadingBefore.value = false
    loadingInitial.value = true
    try {
      const page = await fetchPage(toPageRequest(nextIdentity))
      if (!isCurrentGeneration(requestGeneration, generation)) return
      const merged = mergeInitialPage(page)
      canonicalBars = merged.bars
      hasMoreBefore.value = merged.hasMoreBefore
      nextBefore.value = merged.nextBefore
      canonicalCoverage.value = loadedCanonicalCoverage(canonicalBars)
      publishMerged({ kind: 'replace' })
      try {
        const nextState = await fetchState(nextIdentity)
        if (!isCurrentGeneration(requestGeneration, generation)) return
        marketState.value = nextState
        if (shouldKeepStateSocket(nextIdentity, nextState)) openSocket(requestGeneration, nextIdentity)
      } catch {
        if (isCurrentGeneration(requestGeneration, generation)) liveUnavailable.value = true
      }
    } finally {
      if (isCurrentGeneration(requestGeneration, generation)) loadingInitial.value = false
    }
  }

  async function loadMoreBefore(): Promise<void> {
    if (!identity || !hasMoreBefore.value || !nextBefore.value || loadingBefore.value) return
    const requestGeneration = generation
    const before = nextBefore.value
    loadingBefore.value = true
    try {
      const page = await fetchPage(toPageRequest(identity, before))
      if (!isCurrentGeneration(requestGeneration, generation)) return
      const merged = prependHistoricalPage(canonicalBars, page)
      const previous = canonicalBars
      canonicalBars = merged.bars
      hasMoreBefore.value = merged.hasMoreBefore
      nextBefore.value = merged.nextBefore
      canonicalCoverage.value = loadedCanonicalCoverage(canonicalBars)
      const previousTimes = new Set(previous.map((bar) => bar.time))
      publishMerged({ kind: 'prepend', bars: canonicalBars.filter((bar) => !previousTimes.has(bar.time)) })
    } finally {
      if (isCurrentGeneration(requestGeneration, generation)) loadingBefore.value = false
    }
  }

  function dispose(): void {
    generation += 1
    clearSocket()
  }

  return {
    bars,
    hasMoreBefore,
    canonicalCoverage,
    loadingInitial,
    loadingBefore,
    marketState,
    liveUnavailable,
    overlaySource,
    mutation,
    replaceSeries,
    loadMoreBefore,
    dispose,
  }
}
