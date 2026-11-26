import { computed, ref } from 'vue'
import { candidatePreview } from '../utils/candidatePreview.ts'
import { resolveWsURL } from '../utils/network.ts'
import { normalizeBarSeries } from '../utils/barSeries.ts'
import { normalizeMarketBarWire, normalizeMarketTickQuoteWire } from '../api/marketWire.ts'
import type {
  BarData,
  CanonicalBarDto,
  MarketActivityFrame,
  MarketBarsPageRequest,
  MarketBarsPageResponse,
  MarketFrequency,
  MarketOverlaySource,
  MarketReadState,
  MarketTickQuote,
  MarketWsMessage,
  SeriesKind,
} from '../types/market'

/** Keep the initial chart readable and cap first-render indicator work. */
const DEFAULT_PAGE_LIMIT = 300
const MAX_RECONNECT_DELAY_MS = 10_000
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

export class MarketSeriesPhysicalIdentityError extends Error {
  readonly code = 'MARKET_SERIES_SEGMENT_CONFLICT'

  constructor() {
    super('MARKET_SERIES_SEGMENT_CONFLICT')
    this.name = 'MarketSeriesPhysicalIdentityError'
  }
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
  fetchPage?: (params: MarketBarsPageRequest, signal?: AbortSignal) => Promise<MarketBarsPageResponse>
  fetchState?: (identity: MarketSeriesIdentity, signal?: AbortSignal) => Promise<MarketReadState>
  createWebSocket?: (url: string) => MarketWebSocket
  resolveWsURL?: () => string
  scheduleReconnect?: (callback: () => void, delayMs: number) => unknown
  clearReconnect?: (handle: unknown) => void
}

function normalizePhysicalContract(value: string | null | undefined): string | undefined {
  const normalized = value?.trim().toUpperCase()
  return normalized || undefined
}

export function resolveHistoricalPhysicalContract(
  page: MarketBarsPageResponse,
  bar: CanonicalBarDto,
): string | undefined {
  if (page.request.series_kind === 'contract') return normalizePhysicalContract(page.request.contract)
  if (page.request.series_kind === 'continuous') return undefined

  const matches = page.resolved_contract_segments.filter((segment) => (
    segment.start_trading_day <= bar.trading_day && bar.trading_day <= segment.end_trading_day
  ))
  if (matches.length !== 1) throw new MarketSeriesPhysicalIdentityError()
  const contract = normalizePhysicalContract(matches[0].contract)
  if (!contract) throw new MarketSeriesPhysicalIdentityError()
  return contract
}

/** Maps an already-normalized display DTO without repeating wire coercion. */
function toBarData(item: CanonicalBarDto, physicalContract?: string): BarData {
  return {
    time: item.bar_end,
    trading_day: item.trading_day,
    ...(item.source_bar_sha256 ? { sourceBarSha256: item.source_bar_sha256 } : {}),
    physicalContract,
    open: item.open,
    high: item.high,
    low: item.low,
    close: item.close,
    volume: item.volume,
    turnover: item.turnover === null ? undefined : item.turnover,
    openInterest: item.open_interest === null ? undefined : item.open_interest,
  }
}

/** Display segments come from the resolver's mapping intervals and strict page
 * endpoint/quality validation, not a guessed contract or a strategy quality ID. */
function historicalDisplayBar(page: MarketBarsPageResponse, bar: CanonicalBarDto): BarData {
  const physicalContract = resolveHistoricalPhysicalContract(page, bar)
  const segment = page.resolved_contract_segments.find(item => item.contract.toUpperCase() === physicalContract
    && item.start_trading_day <= bar.trading_day && bar.trading_day <= item.end_trading_day)
  const calculationSegmentId = segment ? `${physicalContract}:${segment.start_trading_day}`
    : page.request.series_kind === 'contract' && physicalContract ? `contract:${physicalContract}` : undefined
  return { ...toBarData(bar, physicalContract), calculationSegmentId }
}

export function mergeInitialPage(page: MarketBarsPageResponse): MergedMarketPage {
  return {
    bars: normalizeBarSeries(page.bars.map((bar) => historicalDisplayBar(page, bar))),
    hasMoreBefore: page.page.has_more_before,
    nextBefore: page.page.next_before,
  }
}

export function prependHistoricalPage(
  current: BarData[],
  page: MarketBarsPageResponse,
): MergedMarketPage {
  const earlier = page.bars.map((bar) => historicalDisplayBar(page, bar))
  const last = earlier.at(-1), first = current[0]
  const cursorJoins = page.request.before != null && first != null
    && Date.parse(page.request.before) === Date.parse(first.time)
  const joined = cursorJoins && last?.physicalContract && last.physicalContract === first?.physicalContract
    && last.calculationSegmentId && first.calculationSegmentId
    ? current.map(bar => bar.calculationSegmentId === first.calculationSegmentId
      ? { ...bar, calculationSegmentId: last.calculationSegmentId } : bar) : current
  return {
    bars: normalizeBarSeries([
      ...earlier,
      ...joined,
    ]),
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

async function defaultFetchPage(params: MarketBarsPageRequest, signal?: AbortSignal): Promise<MarketBarsPageResponse> {
  const { getMarketBarsPage } = await import('../api/market')
  return getMarketBarsPage(params, signal)
}

async function defaultFetchState(identity: MarketSeriesIdentity, signal?: AbortSignal): Promise<MarketReadState> {
  const { getMarketState } = await import('../api/market')
  return getMarketState(identity, signal)
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

function canonicalRevision(state: MarketReadState): string | null {
  const revision = state.canonical_revision
  return state.display_preview === true && typeof revision === 'string' && /^[0-9a-f]{64}$/.test(revision)
    ? revision : null
}

function isLater(left: string | null, right: string | null): boolean {
  return left !== null && (right === null || Date.parse(left) > Date.parse(right))
}

function socketUrl(base: string, identity: MarketSeriesIdentity): string {
  const url = new URL(base, base.includes('://') ? undefined : 'ws://market.local')
  url.searchParams.set('series_kind', identity.seriesKind)
  url.searchParams.set('symbol', identity.symbol)
  url.searchParams.set('frequency', identity.frequency)
  if (identity.seriesKind === 'contract' && identity.contract) url.searchParams.set('contract', identity.contract)
  return url.toString()
}

function isIdentityLiveCapable(identity: MarketSeriesIdentity, state: MarketReadState): boolean {
  if (!INTRADAY_FREQUENCIES.has(identity.frequency) || !state.live_eligible) return false
  if (identity.seriesKind === 'actual_dominant') return true
  return identity.seriesKind === 'contract'
    && !!identity.contract
    && identity.contract.toUpperCase() === state.live_contract?.toUpperCase()
}

function physicalOwnerMatches(identity: MarketSeriesIdentity, contract: string): boolean {
  return /^[A-Z]+[0-9]+$/.test(contract) && contract.replace(/[0-9]+$/, '').toLowerCase() === identity.symbol
    && (identity.seriesKind === 'actual_dominant'
      || (identity.seriesKind === 'contract' && normalizePhysicalContract(identity.contract) === contract))
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

function normalizeMarketWsMessage(value: unknown): MarketWsMessage | null {
  if (!value || typeof value !== 'object' || !('type' in value)) return null
  const type = (value as { type?: unknown }).type
  if (type === 'state' || type === 'reset') return value as MarketWsMessage
  if (type === 'bar') {
    const message = value as { type: 'bar'; bar: unknown }
    return { type, bar: normalizeMarketBarWire(message.bar, 'websocket.bar') }
  }
  if (type === 'snapshot' || type === 'retained') {
    const message = value as Extract<MarketWsMessage, { type: 'snapshot' | 'retained' }>
    if (!Array.isArray(message.bars)) return null
    return { ...message, bars: message.bars.map((bar, index) => normalizeMarketBarWire(bar, `websocket.bars[${index}]`)) }
  }
  if (type === 'preview') {
    const message = value as Extract<MarketWsMessage, { type: 'preview' }>
    return {
      type,
      quote: message.quote === null ? null : normalizeMarketTickQuoteWire(message.quote),
      activity: message.activity === null ? null : {
        ...message.activity,
        bar: normalizeMarketBarWire(message.activity?.bar, 'websocket.activity.bar'),
      },
    }
  }
  return null
}

export function useMarketSeries(dependencies: MarketSeriesDependencies = {}) {
  const bars = ref<BarData[]>([])
  const activity = ref<BarData | null>(null)
  const quote = ref<MarketTickQuote | null>(null)
  const activeBar = computed(() => activity.value && isLater(activity.value.time, latestEnd(bars.value))
    ? activity.value : null)
  const hasMoreBefore = ref(false)
  const nextBefore = ref<string | null>(null)
  const canonicalCoverage = ref<MarketBarsPageResponse['canonical_coverage']>(null)
  const loadingInitial = ref(false)
  const loadingBefore = ref(false)
  const historyError = ref<string | null>(null)
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
  let reads = new AbortController()
  let identity: MarketSeriesIdentity | null = null
  let canonicalBars: BarData[] = []
  let liveBars: BarData[] = []
  let retainedBars: BarData[] = []
  let activeSocket: MarketWebSocket | null = null
  let reconnectHandle: unknown = null
  let reconnectAttempts = 0
  let pendingReconnect: (() => void) | null = null
  let canonicalRefreshToken = 0
  let appliedCanonicalRevision: string | null = null
  let revisionRefresh: { revision: string; promise: Promise<boolean> } | null = null
  let overlayIdentity: MarketOverlayIdentity | null = null
  let loadingBeforePromise: Promise<void> | null = null

  function clearPreview(): void {
    quote.value = null
    activity.value = null
  }

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
    retainedBars = retainedBars.filter((bar) => seam === null || Date.parse(bar.time) > Date.parse(seam))
    bars.value = normalizeBarSeries([...canonicalBars, ...retainedBars, ...liveBars])
    mutation.value = nextMutation
  }

  function clearSocket(): void {
    pendingReconnect = null
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

  function resetSeriesState(nextIdentity: MarketSeriesIdentity | null): number {
    const requestGeneration = ++generation
    reads.abort(); reads = new AbortController()
    clearSocket()
    reconnectAttempts = 0
    identity = nextIdentity ? { ...nextIdentity } : null
    canonicalBars = []
    retainedBars = []
    clearPreview()
    clearOverlay()
    hasMoreBefore.value = false
    nextBefore.value = null
    canonicalCoverage.value = null
    canonicalRefreshToken += 1
    appliedCanonicalRevision = null
    revisionRefresh = null
    marketState.value = null
    liveUnavailable.value = false
    loadingBefore.value = false
    historyError.value = null
    loadingBeforePromise = null
    publishMerged({ kind: 'replace' })
    return requestGeneration
  }

  function shouldKeepStateSocket(
    nextIdentity: MarketSeriesIdentity,
    nextState: MarketReadState,
  ): boolean {
    return nextState.display_preview === true || isIdentityLiveCapable(nextIdentity, nextState)
      || shouldAwaitAfterMarketSeam(nextIdentity, nextState)
  }

  async function refreshCanonicalEdge(
    requestGeneration: number,
    nextIdentity: MarketSeriesIdentity,
    refreshToken: number,
    expectedCanonicalEnd: string,
    revision: string | null = null,
  ): Promise<boolean> {
    const signal = reads.signal
    const isCurrent = () => isCurrentGeneration(requestGeneration, generation) && refreshToken === canonicalRefreshToken
    try {
      // Let an already requested older page settle; reread the entire loaded
      // window, including that page, before accepting a revised history.
      if (revision && loadingBeforePromise) await loadingBeforePromise.catch(() => undefined)
      if (!isCurrent()) return false
      const loadedStart = revision ? canonicalBars[0]?.time : undefined
      const page = await fetchPage(toPageRequest(nextIdentity), signal)
      if (!isCurrent()) return false
      let merged = mergeInitialPage(page)
      while (loadedStart && merged.bars.length && Date.parse(merged.bars[0].time) > Date.parse(loadedStart)
        && merged.hasMoreBefore) {
        const cursor = merged.nextBefore
        if (!cursor || Date.parse(cursor) !== Date.parse(merged.bars[0].time)) {
          throw new Error('MARKET_HISTORY_CURSOR_NOT_ADVANCING')
        }
        const older = await fetchPage(toPageRequest(nextIdentity, cursor), signal)
        if (!isCurrent()) return false
        const advanced = prependHistoricalPage(merged.bars, older)
        if (Date.parse(advanced.bars[0].time) >= Date.parse(cursor)) {
          throw new Error('MARKET_HISTORY_CURSOR_NOT_ADVANCING')
        }
        merged = advanced
      }
      if (revision) {
        const verifiedState = await fetchState(nextIdentity, signal)
        if (!isCurrent()) return false
        if (canonicalRevision(verifiedState) !== revision) throw new Error('MARKET_HISTORY_REVISION_CHANGED')
      }
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
      if (revision) {
        appliedCanonicalRevision = revision
        canonicalBars = fresh
        hasMoreBefore.value = merged.hasMoreBefore
        nextBefore.value = merged.nextBefore
      } else {
        const freshStart = fresh[0].time
        canonicalBars = normalizeBarSeries([
          ...canonicalBars.filter((bar) => Date.parse(bar.time) < Date.parse(freshStart)),
          ...fresh,
        ])
      }
      canonicalCoverage.value = loadedCanonicalCoverage(canonicalBars)
      publishMerged({ kind: 'replace' })
      return true
    } catch {
      if (isCurrent()) {
        liveUnavailable.value = true
        if (overlaySource.value !== 'post_close') {
          clearOverlay()
          publishMerged({ kind: 'replace' })
        }
      }
      return false
    }
  }

  function reconcileCanonical(
    requestGeneration: number, nextIdentity: MarketSeriesIdentity, state: MarketReadState,
  ): Promise<boolean> | null {
    const end = state.canonical_end
    if (!end) return null
    const revision = canonicalRevision(state)
    if (revision && revision !== appliedCanonicalRevision) {
      if (revisionRefresh?.revision === revision) return revisionRefresh.promise
      const promise = refreshCanonicalEdge(requestGeneration, nextIdentity, ++canonicalRefreshToken, end, revision)
      const attempt = { revision, promise }
      revisionRefresh = attempt
      void promise.then((ok) => {
        if (revisionRefresh !== attempt) return
        revisionRefresh = null
        if (!ok && isCurrentGeneration(requestGeneration, generation)) {
          clearSocket()
          clearPreview()
          marketState.value = null
          retryLive(requestGeneration, nextIdentity)
        }
      })
      return promise
    }
    if (revisionRefresh) return revisionRefresh.promise
    return isLater(end, latestEnd(canonicalBars))
      ? refreshCanonicalEdge(requestGeneration, nextIdentity, ++canonicalRefreshToken, end) : null
  }

  function applyLiveBars(incoming: CanonicalBarDto[], physicalContract?: string): boolean {
    const seam = latestEnd(canonicalBars)
    const accepted = normalizeBarSeries(incoming
      .map((bar) => ({ ...toBarData(bar, physicalContract), confirmed: false }))
      .filter((bar) => seam === null || Date.parse(bar.time) > Date.parse(seam)))
    if (!accepted.length) return false
    liveBars = normalizeBarSeries([...liveBars, ...accepted])
    publishMerged({ kind: 'live', bars: accepted })
    return true
  }

  function retryLive(requestGeneration: number, nextIdentity: MarketSeriesIdentity): void {
    if (!isCurrentGeneration(requestGeneration, generation)) return
    liveUnavailable.value = true
    if (reconnectHandle !== null) return
    const delay = Math.min(1000 * 2 ** reconnectAttempts, MAX_RECONNECT_DELAY_MS)
    reconnectAttempts += 1
    const reconnect = () => {
      if (pendingReconnect !== reconnect || !isCurrentGeneration(requestGeneration, generation)) return
      pendingReconnect = null
      reconnectHandle = null
      const state = marketState.value
      if (state && shouldKeepStateSocket(nextIdentity, state)) openSocket(requestGeneration, nextIdentity)
      else void connectFromState(requestGeneration, nextIdentity)
    }
    pendingReconnect = reconnect
    reconnectHandle = scheduleReconnect(reconnect, delay)
  }

  async function connectFromState(requestGeneration: number, nextIdentity: MarketSeriesIdentity): Promise<void> {
    if (candidatePreview.enabled) return
    try {
      const state = await fetchState(nextIdentity, reads.signal)
      if (!isCurrentGeneration(requestGeneration, generation)) return
      const recovering = liveUnavailable.value
      marketState.value = state
      const canonicalRefresh = recovering || canonicalRevision(state)
        ? reconcileCanonical(requestGeneration, nextIdentity, state) : null
      if (canonicalRefresh) {
        const refreshed = await canonicalRefresh
        if (!isCurrentGeneration(requestGeneration, generation)) return
        if (!refreshed) {
          marketState.value = null
          retryLive(requestGeneration, nextIdentity)
          return
        }
      }
      if (shouldKeepStateSocket(nextIdentity, state)) {
        openSocket(requestGeneration, nextIdentity)
      } else if (state.operational && INTRADAY_FREQUENCIES.has(nextIdentity.frequency)
          && !state.live_contract && (state.phase === 'TRADING' || state.phase === 'UNKNOWN')) {
        retryLive(requestGeneration, nextIdentity)
      } else {
        liveUnavailable.value = false
      }
    } catch {
      retryLive(requestGeneration, nextIdentity)
    }
  }

  function openSocket(requestGeneration: number, nextIdentity: MarketSeriesIdentity): void {
    if (candidatePreview.enabled) return
    if (!isCurrentGeneration(requestGeneration, generation) || !marketState.value || !shouldKeepStateSocket(nextIdentity, marketState.value)) return
    let socket: MarketWebSocket
    try {
      // A reconnect may have missed a bar older than the latest one rendered.
      // The server's day-scoped snapshot starts at the Canonical seam.
      socket = createWebSocket(socketUrl(getWsURL(), nextIdentity))
    } catch {
      retryLive(requestGeneration, nextIdentity)
      return
    }
    activeSocket = socket
    socket.onmessage = (event) => {
      if (!isCurrentGeneration(requestGeneration, generation) || socket !== activeSocket) return
      let payload: MarketWsMessage | null
      try {
        payload = normalizeMarketWsMessage(JSON.parse(event.data))
      } catch {
        return
      }
      if (payload === null) return
      if (payload.type === 'preview') {
        const state = marketState.value
        const accepts = (item: MarketTickQuote | MarketActivityFrame, day: string): boolean => {
          const contract = normalizePhysicalContract(item.contract)
          return state?.display_preview === true && state.trading_day === day && !!contract
            && physicalOwnerMatches(nextIdentity, contract)
            && (state.live_contract === null || state.live_contract === contract)
            && typeof item.generation === 'string' && !!item.generation
            && Number.isFinite(Date.parse(item.observed_at))
            && Date.parse(item.observed_at) <= Date.parse(item.received_at)
        }
        quote.value = payload.quote && accepts(payload.quote, payload.quote.trading_day) ? payload.quote : null
        activity.value = payload.activity && accepts(payload.activity, payload.activity.bar.trading_day)
          && Date.parse(payload.activity.observed_at) <= Date.parse(payload.activity.bar.bar_end)
          ? { ...toBarData(payload.activity.bar, payload.activity.contract), confirmed: false } : null
        return
      }
      if (payload.type === 'retained') {
        const state = marketState.value
        if (!state?.display_preview) return
        const day = payload.trading_day
        const contract = normalizePhysicalContract(payload.contract)
        if (!day && !contract && retainedBars.length
          && isLater(state.canonical_end, latestEnd(canonicalBars))
          && !isLater(latestEnd(retainedBars), state.canonical_end)) return
        retainedBars = day && state.trading_day && day < state.trading_day && contract
          && physicalOwnerMatches(nextIdentity, contract)
          ? payload.bars.filter(bar => bar.trading_day === day)
            .map(bar => ({ ...toBarData(bar, contract), confirmed: false }))
          : []
        publishMerged({ kind: 'replace' })
        return
      }
      if (payload.type === 'snapshot') {
        if (payload.source === 'none') {
          const state = marketState.value
          if (state?.live_eligible && !state.live_available && state.phase === 'TRADING') {
            liveUnavailable.value = true
            if (overlayIdentity?.tradingDay === state.trading_day
              && overlayIdentity?.contract === normalizePhysicalContract(state.live_contract)) return
          }
          clearOverlay()
          publishMerged({ kind: 'replace' })
          return
        }
        if (payload.trading_day === null || payload.contract === null) {
          clearOverlay()
          publishMerged({ kind: 'replace' })
          return
        }
        const snapshotContract = normalizePhysicalContract(payload.contract)
        if (!snapshotContract || (
          nextIdentity.seriesKind === 'contract'
          && snapshotContract !== normalizePhysicalContract(nextIdentity.contract)
        )) {
          liveUnavailable.value = true
          clearOverlay()
          publishMerged({ kind: 'replace' })
          return
        }
        const samePhysicalIdentity = overlayIdentity === null
          || (overlayIdentity.tradingDay === payload.trading_day
            && overlayIdentity.contract === snapshotContract)
        if (!samePhysicalIdentity) {
          clearOverlay()
          publishMerged({ kind: 'replace' })
        }
        overlayIdentity = {
          source: payload.source,
          tradingDay: payload.trading_day,
          contract: snapshotContract,
        }
        liveUnavailable.value = false
        reconnectAttempts = 0
        const accepted = applyLiveBars(payload.bars.filter(bar => bar.trading_day === payload.trading_day), snapshotContract)
        if (accepted || liveBars.length > 0) {
          overlaySource.value = payload.source
        }
        return
      }
      if (payload.type === 'bar') {
        if (overlayIdentity === null || payload.bar.trading_day !== overlayIdentity.tradingDay) return
        liveUnavailable.value = false
        const accepted = applyLiveBars([payload.bar], overlayIdentity.contract)
        if (accepted || liveBars.length > 0) {
          overlaySource.value = 'realtime'
          overlayIdentity.source = 'realtime'
        }
        return
      }
      if (payload.type === 'reset') {
        clearPreview()
        clearOverlay()
        const resetContract = normalizePhysicalContract(payload.contract)
        if (payload.trading_day !== null && resetContract !== undefined && !(
          nextIdentity.seriesKind === 'contract'
          && resetContract !== normalizePhysicalContract(nextIdentity.contract)
        )) {
          overlayIdentity = {
            source: 'realtime',
            tradingDay: payload.trading_day,
            contract: resetContract,
          }
        }
        publishMerged({ kind: 'replace' })
        return
      }
      if (marketState.value?.trading_day !== payload.state.trading_day
        || marketState.value?.live_contract !== payload.state.live_contract || !payload.state.display_preview) {
        clearPreview()
      }
      marketState.value = payload.state
      if (!payload.state.display_preview && retainedBars.length) {
        retainedBars = []
        publishMerged({ kind: 'replace' })
      }
      liveUnavailable.value = !payload.state.live_available
      const canonicalRefresh = reconcileCanonical(requestGeneration, nextIdentity, payload.state)
      if (payload.state.phase === 'CLOSED' && !payload.state.display_preview && canonicalRefresh) {
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
      clearPreview()
      retryLive(requestGeneration, nextIdentity)
    }
  }

  async function replaceSeries(nextIdentity: MarketSeriesIdentity): Promise<void> {
    const requestGeneration = resetSeriesState(nextIdentity)
    loadingInitial.value = true
    const signal = reads.signal
    try {
      const page = await fetchPage(toPageRequest(nextIdentity), signal)
      if (!isCurrentGeneration(requestGeneration, generation)) return
      const merged = mergeInitialPage(page)
      canonicalBars = merged.bars
      hasMoreBefore.value = merged.hasMoreBefore
      nextBefore.value = merged.nextBefore
      canonicalCoverage.value = loadedCanonicalCoverage(canonicalBars)
      publishMerged({ kind: 'replace' })
      void connectFromState(requestGeneration, nextIdentity)
    } catch (error) {
      if (!signal.aborted && isCurrentGeneration(requestGeneration, generation)) throw error
    } finally {
      if (isCurrentGeneration(requestGeneration, generation)) loadingInitial.value = false
    }
  }

  function clearSeries(): void {
    resetSeriesState(null)
    loadingInitial.value = false
  }

  function loadMoreBefore(): Promise<void> {
    if (loadingBeforePromise) return loadingBeforePromise
    if (revisionRefresh) {
      const requestGeneration = generation
      return revisionRefresh.promise.then((ok) => {
        if (ok && isCurrentGeneration(requestGeneration, generation)) return loadMoreBefore()
      })
    }
    if (!identity || !hasMoreBefore.value || !nextBefore.value) return Promise.resolve()
    const requestIdentity = identity
    const requestGeneration = generation
    const before = nextBefore.value
    const signal = reads.signal
    loadingBefore.value = true
    historyError.value = null
    const request = Promise.resolve().then(async () => {
      try {
        const page = await fetchPage(toPageRequest(requestIdentity, before), signal)
        if (!isCurrentGeneration(requestGeneration, generation)) return
        if (page.page.has_more_before && (!page.page.next_before
          || !Number.isFinite(Date.parse(page.page.next_before))
          || Date.parse(page.page.next_before) >= Date.parse(before))) {
          throw new Error('MARKET_HISTORY_CURSOR_NOT_ADVANCING')
        }
        const merged = prependHistoricalPage(canonicalBars, page)
        const previous = canonicalBars
        canonicalBars = merged.bars
        hasMoreBefore.value = merged.hasMoreBefore
        nextBefore.value = merged.nextBefore
        canonicalCoverage.value = loadedCanonicalCoverage(canonicalBars)
        const previousTimes = new Set(previous.map((bar) => bar.time))
        publishMerged({ kind: 'prepend', bars: canonicalBars.filter((bar) => !previousTimes.has(bar.time)) })
      } catch (error) {
        if (!signal.aborted && isCurrentGeneration(requestGeneration, generation)) {
          historyError.value = '更早行情加载失败，请重试'
          throw error
        }
      } finally {
        if (isCurrentGeneration(requestGeneration, generation)) loadingBefore.value = false
        if (loadingBeforePromise === request) loadingBeforePromise = null
      }
    })
    loadingBeforePromise = request
    return request
  }

  function resumePendingReconnect(): void {
    if (document.visibilityState === 'hidden' || !pendingReconnect) return
    if (reconnectHandle !== null) clearReconnect(reconnectHandle)
    pendingReconnect()
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('online', resumePendingReconnect)
    document.addEventListener('visibilitychange', resumePendingReconnect)
  }

  function dispose(): void {
    if (typeof window !== 'undefined') {
      window.removeEventListener('online', resumePendingReconnect)
      document.removeEventListener('visibilitychange', resumePendingReconnect)
    }
    generation += 1
    reads.abort()
    loadingInitial.value = false; loadingBefore.value = false
    clearSocket()
  }

  return {
    bars,
    activeBar,
    quote,
    hasMoreBefore,
    canonicalCoverage,
    loadingInitial,
    loadingBefore,
    historyError,
    marketState,
    liveUnavailable,
    overlaySource,
    mutation,
    replaceSeries,
    clearSeries,
    loadMoreBefore,
    dispose,
  }
}
