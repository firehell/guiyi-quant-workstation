import { ref } from 'vue'
import type {
  BarData,
  CanonicalBarDto,
  MarketBarsPageRequest,
  MarketBarsPageResponse,
  MarketFrequency,
  SeriesKind,
} from '../types/market'

const DEFAULT_PAGE_LIMIT = 1200

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

function sortAndDedupeBars(items: BarData[]): BarData[] {
  const byEnd = new Map<string, BarData>()
  for (const item of items) byEnd.set(item.time, item)
  return [...byEnd.values()].sort((left, right) => Date.parse(left.time) - Date.parse(right.time))
}

export function mergeInitialPage(page: MarketBarsPageResponse): MergedMarketPage {
  return {
    bars: sortAndDedupeBars(page.bars.map(toBarData)),
    hasMoreBefore: page.page.has_more_before,
    nextBefore: page.page.next_before,
  }
}

export function prependHistoricalPage(
  current: BarData[],
  page: MarketBarsPageResponse,
): MergedMarketPage {
  return {
    bars: sortAndDedupeBars([...page.bars.map(toBarData), ...current]),
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

async function fetchMarketBarsPage(params: MarketBarsPageRequest): Promise<MarketBarsPageResponse> {
  const { getMarketBarsPage } = await import('../api/market')
  return getMarketBarsPage(params)
}

export function useMarketSeries() {
  const bars = ref<BarData[]>([])
  const hasMoreBefore = ref(false)
  const nextBefore = ref<string | null>(null)
  const loadingInitial = ref(false)
  const loadingBefore = ref(false)
  let generation = 0
  let identity: MarketSeriesIdentity | null = null

  async function replaceSeries(nextIdentity: MarketSeriesIdentity): Promise<void> {
    const requestGeneration = ++generation
    identity = { ...nextIdentity }
    loadingBefore.value = false
    loadingInitial.value = true
    try {
      const page = await fetchMarketBarsPage(toPageRequest(nextIdentity))
      if (!isCurrentGeneration(requestGeneration, generation)) return
      const merged = mergeInitialPage(page)
      bars.value = merged.bars
      hasMoreBefore.value = merged.hasMoreBefore
      nextBefore.value = merged.nextBefore
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
      const page = await fetchMarketBarsPage(toPageRequest(identity, before))
      if (!isCurrentGeneration(requestGeneration, generation)) return
      const merged = prependHistoricalPage(bars.value, page)
      bars.value = merged.bars
      hasMoreBefore.value = merged.hasMoreBefore
      nextBefore.value = merged.nextBefore
    } finally {
      if (isCurrentGeneration(requestGeneration, generation)) loadingBefore.value = false
    }
  }

  return {
    bars,
    hasMoreBefore,
    loadingInitial,
    loadingBefore,
    replaceSeries,
    loadMoreBefore,
  }
}
